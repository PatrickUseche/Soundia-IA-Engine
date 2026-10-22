import os

from django.conf import settings
from django.http import FileResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .analysis import AudioTooShortError, SilentAudioError
from .models import Track
from .separator import is_available
from .services import UnsupportedAudioError, analyze_file
from .vocal_jobs import request_vocal_analysis

# Maximo de pistas que devuelve el listado.
LIST_LIMIT = 50

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
    return {'offset': track.grid_offset, 'downbeat': track.grid_downbeat, 'confidence': track.grid_confidence}


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
        analysis = analyze_file(upload)
    except UnsupportedAudioError as error:
        return JsonResponse({'error': str(error)}, status=400)
    except (AudioTooShortError, SilentAudioError) as error:
        # El archivo es valido pero no se puede analizar (muy corto o sin senal).
        return JsonResponse({'error': str(error)}, status=422)

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
    tracks = Track.objects.all()[:LIST_LIMIT]
    return JsonResponse({'tracks': [track_to_dict(track) for track in tracks]})


def track_detail(request, pk):
    if request.method != 'GET':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    try:
        track = Track.objects.get(pk=pk)
    except Track.DoesNotExist:
        return JsonResponse({'error': 'Pista no encontrada'}, status=404)
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
