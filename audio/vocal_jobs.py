"""Analisis de voz en segundo plano: separar la voz tarda minutos, asi que no se hace dentro de la peticion.

Un unico hilo va tomando pistas de una cola, de una en una: la separacion consume mucha CPU y memoria y dos a
la vez saturarian un equipo modesto. El estado de cada pista (en cola, analizando, analizada...) se guarda en
la propia pista, asi el front puede mostrarlo.
"""
import logging
import queue
import threading

from django.conf import settings
from django.db import close_old_connections

from .models import Track
from .separator import VocalSeparationUnavailable, is_available
from .vocal_analysis import analyze_last_vocals

logger = logging.getLogger(__name__)

_queue: 'queue.Queue[int]' = queue.Queue()
_worker_lock = threading.Lock()
_worker: threading.Thread | None = None


def run_vocal_analysis(track_id: int, analyzer=None) -> None:
    """Analiza la voz de una pista y guarda el resultado. Nunca lanza: un fallo deja la pista como 'failed'."""
    analyzer = analyzer or analyze_last_vocals
    try:
        track = Track.objects.get(pk=track_id)
    except Track.DoesNotExist:
        return
    if not track.audio_file:
        _save(track, Track.VOCALS_FAILED, None)
        return

    _save(track, Track.VOCALS_RUNNING, track.vocal_last_end)
    try:
        result = analyzer(track.audio_file.path, track.duration)
    except VocalSeparationUnavailable:
        _save(track, Track.VOCALS_UNAVAILABLE, None)
    except Exception:  # noqa: BLE001 - un fallo del modelo o del audio no debe tumbar el hilo
        logger.exception('Fallo el analisis de voz de la pista %s', track_id)
        _save(track, Track.VOCALS_FAILED, None)
    else:
        _save(track, Track.VOCALS_DONE, result.last_end)


def _save(track: Track, status: str, last_end: float | None) -> None:
    track.vocal_status = status
    track.vocal_last_end = last_end
    track.save(update_fields=['vocal_status', 'vocal_last_end'])


def request_vocal_analysis(track: Track) -> str:
    """Pide analizar la voz de una pista; devuelve su estado. Sin el modelo instalado la pista queda como
    'no disponible' y con VOCAL_ANALYSIS=off no se toca."""
    if settings.VOCAL_ANALYSIS == 'off':
        return track.vocal_status
    if track.vocal_status in (Track.VOCALS_PENDING, Track.VOCALS_RUNNING) or not track.audio_file:
        return track.vocal_status
    if not is_available():
        _save(track, Track.VOCALS_UNAVAILABLE, None)
        return track.vocal_status

    _save(track, Track.VOCALS_PENDING, track.vocal_last_end)
    _submit(track.id)
    return track.vocal_status


def _submit(track_id: int) -> None:
    _queue.put(track_id)
    _ensure_worker()


def _ensure_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name='vocal-analysis', daemon=True)
            _worker.start()


def _work() -> None:
    while True:
        track_id = _queue.get()
        try:
            run_vocal_analysis(track_id)
        finally:
            close_old_connections()
            _queue.task_done()
