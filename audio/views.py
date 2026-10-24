import json
import logging
import math
import os

from django.conf import settings
from django.http import FileResponse, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .analysis import AudioTooShortError, SilentAudioError
from .beatgrid import downbeat_from_choice
from .memory import release_memory
from .models import Track
from .separator import is_available
from .services import UnsupportedAudioError, analyze_file
from .vocal_jobs import request_vocal_analysis

logger = logging.getLogger(__name__)

MAX_GENRE_LENGTH = 40


def normalize_genre(value) -> str:
    """El genero como se guarda: sin espacios de mas y en minusculas, para que "Salsa" y "salsa " cuenten como uno.
    Lanza ValueError si no es texto o es demasiado largo."""
    if not isinstance(value, str):
        raise ValueError("'genre' debe ser texto.")
    genre = ' '.join(value.split()).lower()
    if len(genre) > MAX_GENRE_LENGTH:
        raise ValueError(f"'genre' no puede pasar de {MAX_GENRE_LENGTH} caracteres.")
    return genre


# Tipos MIME de los formatos soportados; se fijan a mano para no depender del registro del sistema operativo.
AUDIO_CONTENT_TYPES = {
    '.wav': 'audio/wav',
    '.mp3': 'audio/mpeg',
    '.flac': 'audio/flac',
    '.ogg': 'audio/ogg',
}


def _grid_to_dict(track: Track) -> dict | None:
    if track.grid_offset is None:
        return None
    return {
        'offset': track.grid_offset, 'downbeat': track.grid_downbeat, 'confidence': track.grid_confidence,
        'manual': track.grid_manual,
    }


def track_to_dict(track: Track) -> dict:
    return {
        'id': track.id,
        'title': track.title,
        'duration': track.duration,
        'bpm': track.bpm,
        'key': track.key,
        'camelot': track.camelot,
        'energy': track.energy,
        'cuePoints': track.cue_points,
        'hasAudio': bool(track.audio_file),
        'genre': track.genre,
        'vocals': {
            'status': track.vocal_status, 'lastEnd': track.vocal_last_end, 'firstStart': track.vocal_first_start,
        },
        'grid': _grid_to_dict(track),
        'createdAt': track.created_at.isoformat(),
    }


@csrf_exempt
def analyze_track(request):
    """POST multipart con el campo `file` (y `title` opcional): analiza la pista y la guarda."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)

    upload = request.FILES.get('file')
    if upload is None:
        return JsonResponse({'error': "Falta el archivo de audio en el campo 'file'."}, status=400)
    if upload.size > settings.AUDIO_MAX_UPLOAD_BYTES:
        limite_mb = settings.AUDIO_MAX_UPLOAD_BYTES // (1024 * 1024)
        return JsonResponse({'error': f'El archivo supera el maximo de {limite_mb} MB.'}, status=413)

    try:
        genre = normalize_genre(request.POST.get('genre', ''))
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)

    try:
        analysis = analyze_file(upload)
    except UnsupportedAudioError as error:
        return JsonResponse({'error': str(error)}, status=400)
    except (AudioTooShortError, SilentAudioError) as error:
        # El archivo es valido pero no se puede analizar (muy corto o sin senal).
        return JsonResponse({'error': str(error)}, status=422)
    finally:
        # Con haya salido bien o mal, la memoria del analisis vuelve al sistema antes de la siguiente pista.
        release_memory()

    track = Track.objects.create(
        title=(request.POST.get('title') or upload.name)[:255],
        duration=analysis.duration,
        bpm=analysis.bpm,
        key=analysis.key,
        camelot=analysis.camelot,
        energy=analysis.energy,
        cue_points=analysis.cue_points,
        grid_offset=analysis.grid_offset,
        grid_downbeat=analysis.grid_downbeat,
        grid_confidence=analysis.grid_confidence,
        genre=genre,
    )
    # El analisis ya leyo el archivo hasta el final: se rebobina para guardarlo completo.
    upload.seek(0)
    track.audio_file.save(upload.name, upload, save=True)
    # La voz del final se analiza aparte, en segundo plano: tarda minutos.
    request_vocal_analysis(track)
    return JsonResponse(track_to_dict(track), status=201)


def list_tracks(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    tracks = Track.objects.all()[:settings.TRACK_LIST_LIMIT]
    return JsonResponse({'tracks': [track_to_dict(track) for track in tracks]})


@csrf_exempt
def track_detail(request, pk):
    """GET: los datos de la pista. PUT `{genre}`: le pone el genero (vacio lo quita). DELETE: la borra junto con su
    audio (las grabaciones de mezclas que la usaron se conservan: guardan una foto de sus datos)."""
    if request.method not in ('GET', 'PUT', 'DELETE'):
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    try:
        track = Track.objects.get(pk=pk)
    except Track.DoesNotExist:
        return JsonResponse({'error': 'Pista no encontrada'}, status=404)
    if request.method == 'GET':
        return JsonResponse(track_to_dict(track))

    if request.method == 'PUT':
        try:
            data = json.loads(request.body or b'null')
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'error': 'El cuerpo debe ser un JSON valido'}, status=400)
        if not isinstance(data, dict) or 'genre' not in data:
            return JsonResponse({'error': "Falta 'genre' en el cuerpo."}, status=400)
        try:
            track.genre = normalize_genre(data['genre'])
        except ValueError as error:
            return JsonResponse({'error': str(error)}, status=400)
        track.save(update_fields=['genre'])
        return JsonResponse(track_to_dict(track))

    # El audio se borra primero: si el almacenamiento falla, la pista sigue y se puede reintentar sin dejar un
    # archivo huerfano ocupando espacio.
    try:
        if track.audio_file:
            track.audio_file.delete(save=False)
    except Exception:  # noqa: BLE001 - un almacenamiento externo puede fallar de muchas formas
        logger.exception('No se pudo borrar el audio de la pista %s', pk)
        return JsonResponse({'error': 'No se pudo borrar el audio de la pista. Intentalo de nuevo.'}, status=502)
    track.delete()
    return HttpResponse(status=204)


@csrf_exempt
def track_grid(request, pk):
    """PUT `{downbeat}`: el DJ senala un instante (segundos) que es un "1" del compas. Se ajusta al pulso mas cercano
    de la rejilla de la pista y se guarda como primer tiempo, con confianza 1 y marcado como manual."""
    if request.method != 'PUT':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    try:
        track = Track.objects.get(pk=pk)
    except Track.DoesNotExist:
        return JsonResponse({'error': 'Pista no encontrada'}, status=404)

    try:
        data = json.loads(request.body or b'null')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'El cuerpo debe ser un JSON valido'}, status=400)
    chosen = data.get('downbeat') if isinstance(data, dict) else None
    # bool es un int en Python: true/false no son segundos validos.
    if isinstance(chosen, bool) or not isinstance(chosen, (int, float)) or not math.isfinite(chosen):
        return JsonResponse({'error': "Falta 'downbeat': el segundo de la pista que es un primer tiempo"}, status=400)
    if not 0 <= chosen <= track.duration:
        return JsonResponse({'error': 'downbeat debe estar dentro de la duracion de la pista'}, status=400)
    if track.grid_offset is None:
        return JsonResponse({'error': 'La pista no tiene una rejilla de pulsos (no tiene un ritmo claro)'}, status=409)

    track.grid_downbeat = downbeat_from_choice(track.grid_offset, track.bpm, float(chosen))
    track.grid_confidence = 1.0
    track.grid_manual = True
    track.save(update_fields=['grid_downbeat', 'grid_confidence', 'grid_manual'])
    return JsonResponse(track_to_dict(track))


@csrf_exempt
def request_vocals(request, pk):
    """POST: pide analizar la voz del final de una pista ya guardada (se hace en segundo plano; responde 202)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    try:
        track = Track.objects.get(pk=pk)
    except Track.DoesNotExist:
        return JsonResponse({'error': 'Pista no encontrada'}, status=404)
    if not is_available():
        return JsonResponse(
            {'error': 'El analisis de voz no esta disponible: instala requirements-vocals.txt.'}, status=503)
    request_vocal_analysis(track)
    return JsonResponse(track_to_dict(track), status=202)


def track_file(request, pk):
    """GET: el audio original de la pista, para reproducirlo en los decks."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    try:
        track = Track.objects.get(pk=pk)
    except Track.DoesNotExist:
        return JsonResponse({'error': 'Pista no encontrada'}, status=404)
    if not track.audio_file:
        return JsonResponse({'error': 'La pista no tiene audio guardado.'}, status=404)

    try:
        handle = track.audio_file.open('rb')
    except FileNotFoundError:
        # El registro existe pero el archivo ya no esta en el disco.
        return JsonResponse({'error': 'El archivo de audio de la pista ya no esta disponible.'}, status=404)

    extension = os.path.splitext(track.audio_file.name)[1].lower()
    return FileResponse(handle, content_type=AUDIO_CONTENT_TYPES.get(extension, 'application/octet-stream'))
