"""Analisis de voz en segundo plano: separar la voz tarda minutos, asi que no se hace dentro de la peticion.

Un unico hilo va tomando pistas de una cola, de una en una: la separacion consume mucha CPU y memoria y dos a
la vez saturarian un equipo modesto. Cada analisis se ejecuta en un proceso aparte (ver vocal_worker.py): si se
queda sin memoria o se cae, solo falla esa pista y no el servidor. El estado de cada pista (en cola, analizando,
analizada...) se guarda en la propia pista, asi el front puede mostrarlo.
"""
import json
import logging
import os
import queue
import subprocess
import sys
import threading

from django.conf import settings
from django.db import close_old_connections

from .models import Track
from .separator import VocalSeparationUnavailable, is_available
from .vocal_analysis import VocalResult
from .vocal_worker import UNAVAILABLE_EXIT_CODE

logger = logging.getLogger(__name__)

# Segundos que se le dan a un analisis antes de darlo por colgado (por defecto 30 min: ~3 min en un equipo modesto).
ANALYSIS_TIMEOUT_SECONDS = int(os.environ.get('VOCAL_ANALYSIS_TIMEOUT', '1800'))

_queue: 'queue.Queue[int]' = queue.Queue()
_worker_lock = threading.Lock()
_worker: threading.Thread | None = None
# Pistas que estan en la cola o analizandose ahora mismo en este proceso. Si una pista figura como "en cola" o
# "analizando" pero no esta aqui, el estado es de antes de un fallo o reinicio del servidor y no hay nadie
# trabajando en ella.
_active: set[int] = set()


def analyze_in_subprocess(source: str, duration: float) -> VocalResult:
    """Analiza la voz del final de la pista en un proceso aparte; lanza RuntimeError si falla."""
    command = [sys.executable, '-m', 'audio.vocal_worker', str(source), str(duration)]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=ANALYSIS_TIMEOUT_SECONDS, cwd=settings.BASE_DIR,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f'El analisis de voz tardo mas de {ANALYSIS_TIMEOUT_SECONDS} s') from error

    if completed.returncode == UNAVAILABLE_EXIT_CODE:
        raise VocalSeparationUnavailable('El modelo de separacion no esta instalado.')
    if completed.returncode != 0:
        detail = (completed.stderr or '').strip().splitlines()[-1:] or ['sin detalles']
        raise RuntimeError(f'El analisis de voz termino con el codigo {completed.returncode}: {detail[0]}')

    for line in reversed((completed.stdout or '').strip().splitlines()):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        return VocalResult(window_start=data['window_start'], last_end=data['last_end'])
    raise RuntimeError('El analisis de voz no devolvio ningun resultado')


def run_vocal_analysis(track_id: int, analyzer=None) -> None:
    """Analiza la voz de una pista y guarda el resultado. Nunca lanza: un fallo deja la pista como 'failed'."""
    analyzer = analyzer or analyze_in_subprocess
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
    'no disponible' y con VOCAL_ANALYSIS=off no se toca. Una pista que figura en cola pero que nadie esta
    analizando (quedo asi tras un fallo del servidor) se vuelve a encolar."""
    if settings.VOCAL_ANALYSIS == 'off':
        return track.vocal_status
    if not track.audio_file:
        return track.vocal_status
    if track.vocal_status in (Track.VOCALS_PENDING, Track.VOCALS_RUNNING) and track.id in _active:
        return track.vocal_status
    if not is_available():
        _save(track, Track.VOCALS_UNAVAILABLE, None)
        return track.vocal_status

    _save(track, Track.VOCALS_PENDING, track.vocal_last_end)
    _submit(track.id)
    return track.vocal_status


def _submit(track_id: int) -> None:
    with _worker_lock:
        _active.add(track_id)
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
            with _worker_lock:
                _active.discard(track_id)
            close_old_connections()
            _queue.task_done()
