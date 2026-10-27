import json
import math
from json.decoder import JSONDecodeError

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from audio.models import Track

from .compatibility import ScoringWeights, TrackInfo, rank_next_tracks
from .backup import export_recordings, import_recordings
from .models import MixRecording
from .report import summarize
from .style_model import style_model_status
from .recordings import QUALITIES, InvalidRecording, derive_features, parse_recording, parse_review
from .timing import learned_advance, record_mix_timing, timing_count
from .transition import plan_transition
from .weights import active_weights, current_weights, feedback_count, record_feedback, weight_history

DEFAULT_LIMIT = 5
MAX_LIMIT = 20


class BadRequest(Exception):
    """La peticion no es valida; el mensaje se devuelve al cliente con un 400."""


class NotFound(Exception):
    """No existe la pista pedida; el mensaje se devuelve al cliente con un 404."""


def _read_json_object(request) -> dict:
    if not request.body:
        raise BadRequest('Cuerpo de la peticion vacio.')
    try:
        data = json.loads(request.body)
    except JSONDecodeError:
        raise BadRequest('Sintaxis JSON invalida.')
    if not isinstance(data, dict):
        raise BadRequest('El cuerpo JSON debe ser un objeto.')
    return data


def _read_id(data: dict, key: str) -> int:
    value = data.get(key)
    # bool es subclase de int en Python: se rechaza explicitamente.
    if isinstance(value, bool) or not isinstance(value, int):
        raise BadRequest(f"Falta '{key}' o no es un entero.")
    return value


def _read_seconds(data: dict, key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise BadRequest(f"Falta '{key}' o no es un numero de segundos (0 o mas).")
    return float(value)


def _get_track(track_id: int) -> Track:
    try:
        return Track.objects.get(pk=track_id)
    except Track.DoesNotExist:
        raise NotFound(f'No existe la pista {track_id}.')


def _tempo_match_to_dict(match) -> dict:
    return {'ratio': round(match.ratio, 4), 'multiplier': match.multiplier, 'feasible': match.feasible}


def _compatibility_to_dict(result) -> dict:
    return {
        'score': result.score,
        'tempo': result.tempo,
        'harmonic': result.harmonic,
        'energy': result.energy,
        'tempoMatch': _tempo_match_to_dict(result.tempo_match),
    }


def _weights_to_dict(weights: ScoringWeights) -> dict:
    return {'tempo': weights.tempo, 'harmonic': weights.harmonic, 'energy': weights.energy}


def _track_info_to_dict(info: TrackInfo) -> dict:
    return {
        'id': info.id, 'title': info.title, 'bpm': info.bpm, 'camelot': info.camelot,
        'energy': info.energy, 'duration': info.duration, 'cuePoints': info.cue_points,
    }


def _automation_point_to_dict(point) -> dict:
    return {
        'position': point.position,
        'gainA': point.gain_a, 'gainB': point.gain_b,
        'lowA': point.low_a, 'lowB': point.low_b,
        'midA': point.mid_a, 'midB': point.mid_b,
        'highA': point.high_a, 'highB': point.high_b,
    }


@csrf_exempt
def next_tracks(request):
    """POST {trackId, limit?}: las pistas que mejor siguen a la indicada, de mayor a menor compatibilidad."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    try:
        data = _read_json_object(request)
        track_id = _read_id(data, 'trackId')
        limit = data.get('limit', DEFAULT_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
            raise BadRequest(f"'limit' debe ser un entero entre 1 y {MAX_LIMIT}.")
        current = TrackInfo.from_model(_get_track(track_id))
    except BadRequest as error:
        return JsonResponse({'error': str(error)}, status=400)
    except NotFound as error:
        return JsonResponse({'error': str(error)}, status=404)

    candidates = [TrackInfo.from_model(track) for track in Track.objects.exclude(pk=track_id)]
    ranking = rank_next_tracks(current, candidates, limit, current_weights())
    return JsonResponse({
        'current': _track_info_to_dict(current),
        'candidates': [
            {'track': _track_info_to_dict(info), 'compatibility': _compatibility_to_dict(result)}
            for info, result in ranking
        ],
    })


@csrf_exempt
def transition(request):
    """POST {fromTrackId, toTrackId}: plan para pasar de una pista a la otra."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    try:
        data = _read_json_object(request)
        from_id = _read_id(data, 'fromTrackId')
        to_id = _read_id(data, 'toTrackId')
        if from_id == to_id:
            raise BadRequest('No se puede hacer una transicion de una pista a si misma.')
        origin = TrackInfo.from_model(_get_track(from_id))
        destination = TrackInfo.from_model(_get_track(to_id))
    except BadRequest as error:
        return JsonResponse({'error': str(error)}, status=400)
    except NotFound as error:
        return JsonResponse({'error': str(error)}, status=404)

    plan = plan_transition(origin, destination, current_weights(), advance=learned_advance())
    return JsonResponse({
        'fromTrackId': from_id,
        'toTrackId': to_id,
        'style': plan.style,
        'bars': plan.bars,
        'seconds': plan.seconds,
        'mixOutAt': plan.mix_out_at,
        'mixInAt': plan.mix_in_at,
        'tempoMatch': _tempo_match_to_dict(plan.tempo_match),
        'compatibility': _compatibility_to_dict(plan.compatibility),
        'automation': [_automation_point_to_dict(point) for point in plan.automation],
        'mixOutAdvance': plan.mix_out_advance,
    })


@csrf_exempt
def feedback(request):
    """POST {fromTrackId, toTrackId, liked}: valora una transicion; el motor reentrena sus pesos con ella."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    try:
        data = _read_json_object(request)
        from_id = _read_id(data, 'fromTrackId')
        to_id = _read_id(data, 'toTrackId')
        liked = data.get('liked')
        # Se exige un booleano de verdad: en Python 1 == True y "si" es truthy, y no deben pasar por valoraciones.
        if not isinstance(liked, bool):
            raise BadRequest("Falta 'liked' o no es verdadero/falso.")
        if from_id == to_id:
            raise BadRequest('No se puede valorar una transicion de una pista a si misma.')
        origin = _get_track(from_id)
        destination = _get_track(to_id)
    except BadRequest as error:
        return JsonResponse({'error': str(error)}, status=400)
    except NotFound as error:
        return JsonResponse({'error': str(error)}, status=404)

    weights = record_feedback(origin, destination, liked)
    return JsonResponse({
        'weights': _weights_to_dict(weights),
        'samples': feedback_count(),
        'learned': active_weights() is not None,
    }, status=201)


@csrf_exempt
def mix_timing(request):
    """POST {fromTrackId, toTrackId, plannedMixOutAt, actualMixOutAt}: el DJ pidio mezclar antes de lo planeado.

    El motor guarda el caso y, con suficientes, adelanta sus siguientes mezclas.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    try:
        data = _read_json_object(request)
        from_id = _read_id(data, 'fromTrackId')
        to_id = _read_id(data, 'toTrackId')
        planned = _read_seconds(data, 'plannedMixOutAt')
        actual = _read_seconds(data, 'actualMixOutAt')
        if from_id == to_id:
            raise BadRequest('No se puede mezclar una pista consigo misma.')
        origin = _get_track(from_id)
        destination = _get_track(to_id)
    except BadRequest as error:
        return JsonResponse({'error': str(error)}, status=400)
    except NotFound as error:
        return JsonResponse({'error': str(error)}, status=404)

    advance = record_mix_timing(origin, destination, planned, actual)
    return JsonResponse({'samples': timing_count(), 'advanceSeconds': advance, 'learned': advance > 0}, status=201)


def weights(request):
    """GET: los pesos vigentes, si son aprendidos, con cuantas valoraciones, su version y su acierto medido."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    learned = active_weights()
    return JsonResponse({
        'weights': _weights_to_dict(current_weights()),
        'learned': learned is not None,
        'samples': max(feedback_count(), learned.samples if learned else 0),
        'version': learned.version if learned else 0,
        # Acierto con valoraciones apartadas del entrenamiento; null si no se pudo medir (o no hay pesos aprendidos).
        'accuracy': learned.accuracy if learned else None,
        'defaultAccuracy': learned.default_accuracy if learned else None,
        # Versiones guardadas (las 10 mas nuevas): se puede volver a una con `manage.py learning --restore-version N`.
        'history': [
            {
                'version': row.version, 'active': row.active, 'weights': _weights_to_dict(
                    ScoringWeights(row.tempo, row.harmonic, row.energy)),
                'samples': row.samples, 'accuracy': row.accuracy,
            }
            for row in weight_history(limit=10)
        ],
    })


def _recording_to_dict(recording: MixRecording, full: bool = True) -> dict:
    data = {
        'id': recording.id,
        'fromTrackId': recording.from_track_id,
        'toTrackId': recording.to_track_id,
        'source': recording.source,
        'dj': recording.dj,
        'mixOutAt': recording.mix_out_at,
        'mixInAt': recording.mix_in_at,
        'overlapSeconds': recording.overlap_seconds,
        'pitchA': recording.pitch_a,
        'pitchB': recording.pitch_b,
        'genreA': recording.genre_a,
        'genreB': recording.genre_b,
        'quality': recording.quality,
        'notes': recording.notes,
        'createdAt': recording.created_at.isoformat(),
        'features': derive_features({
            'snapshot_a': recording.snapshot_a, 'snapshot_b': recording.snapshot_b,
            'pitch_a': recording.pitch_a, 'pitch_b': recording.pitch_b, 'mix_out_at': recording.mix_out_at,
            'mix_in_at': recording.mix_in_at, 'overlap_seconds': recording.overlap_seconds,
            'curves': recording.curves,
        }),
    }
    if full:
        data['curves'] = recording.curves
        data['snapshotA'] = recording.snapshot_a
        data['snapshotB'] = recording.snapshot_b
    return data


MAX_RECORDINGS_LISTED = 200


@csrf_exempt
def recordings(request):
    """POST: guarda una transicion tal como la hizo un DJ. GET: las mas recientes (sin las curvas), con un resumen."""
    if request.method == 'POST':
        try:
            fields = parse_recording(_read_json_object(request))
        except (BadRequest, InvalidRecording) as error:
            return JsonResponse({'error': str(error)}, status=400)
        except Track.DoesNotExist:
            return JsonResponse({'error': 'No existe una de las pistas de la mezcla.'}, status=404)
        return JsonResponse(_recording_to_dict(MixRecording.objects.create(**fields)), status=201)

    if request.method == 'GET':
        queryset = MixRecording.objects.all()
        quality = request.GET.get('quality')
        if quality:
            if quality not in QUALITIES:
                return JsonResponse({'error': f"'quality' debe ser uno de {list(QUALITIES)}."}, status=400)
            queryset = queryset.filter(quality=quality)
        counts = {q: MixRecording.objects.filter(quality=q).count() for q in QUALITIES}
        return JsonResponse({
            'recordings': [_recording_to_dict(r, full=False) for r in queryset[:MAX_RECORDINGS_LISTED]],
            'counts': {**counts, 'total': sum(counts.values())},
        })

    return JsonResponse({'error': 'Metodo no permitido'}, status=405)


def style_model(request):
    """GET: cuantas mezclas buenas hay para aprender el estilo del DJ y si el modelo ya acierta mas que las reglas."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    return JsonResponse(style_model_status())


def recordings_summary(request):
    """GET: resumen por genero de las mezclas grabadas (medianas y frecuencias). `?quality=good|unreviewed|discard|all`
    (por defecto good) y `?genre=salsa` para quedarse con un genero."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    quality = request.GET.get('quality', 'good')
    if quality != 'all' and quality not in QUALITIES:
        return JsonResponse({'error': f"'quality' debe ser uno de {list(QUALITIES)} o 'all'."}, status=400)
    return JsonResponse(summarize(quality=None if quality == 'all' else quality, genre=request.GET.get('genre') or None))


def recordings_export(request):
    """GET: todas las grabaciones en un archivo JSON descargable (copia de seguridad)."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    response = JsonResponse(export_recordings(), json_dumps_params={'ensure_ascii': False})
    response['Content-Disposition'] = 'attachment; filename="soundia-grabaciones.json"'
    return response


@csrf_exempt
def recordings_import(request):
    """POST: restaura las grabaciones de una copia exportada. Todo o nada; las que ya estan no se duplican."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Metodo no permitido'}, status=405)
    try:
        created, skipped = import_recordings(_read_json_object(request))
    except (BadRequest, InvalidRecording) as error:
        return JsonResponse({'error': str(error)}, status=400)
    return JsonResponse({'created': created, 'skipped': skipped}, status=201 if created else 200)


@csrf_exempt
def recording_detail(request, pk):
    """GET: una grabacion con sus curvas. PUT {quality?, notes?}: la revisa. DELETE: la borra."""
    try:
        recording = MixRecording.objects.get(pk=pk)
    except MixRecording.DoesNotExist:
        return JsonResponse({'error': 'Grabacion no encontrada'}, status=404)

    if request.method == 'GET':
        return JsonResponse(_recording_to_dict(recording))
    if request.method == 'PUT':
        try:
            changes = parse_review(_read_json_object(request))
        except (BadRequest, InvalidRecording) as error:
            return JsonResponse({'error': str(error)}, status=400)
        for field, value in changes.items():
            setattr(recording, field, value)
        recording.save(update_fields=list(changes))
        return JsonResponse(_recording_to_dict(recording))
    if request.method == 'DELETE':
        recording.delete()
        return HttpResponse(status=204)
    return JsonResponse({'error': 'Metodo no permitido'}, status=405)
