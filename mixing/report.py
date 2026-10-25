"""Resumen de las mezclas grabadas de un DJ: que hace normalmente en cada genero.

Es el primer paso antes de entrenar ningun modelo: con pocas decenas de grabaciones ya se ve cuantos compases suele
solapar, como mueve el crossfader, si hace cambio de graves y donde sale de la pista. Solo cuenta (medianas y
frecuencias); no aprende ni cambia nada.
"""
from collections import Counter, defaultdict
from statistics import median

from .models import MixRecording
from .recordings import QUALITIES, derive_features

NO_GENRE = 'sin genero'


def _features(recording: MixRecording) -> dict:
    return derive_features({
        'snapshot_a': recording.snapshot_a, 'snapshot_b': recording.snapshot_b,
        'pitch_a': recording.pitch_a, 'pitch_b': recording.pitch_b, 'mix_out_at': recording.mix_out_at,
        'mix_in_at': recording.mix_in_at, 'overlap_seconds': recording.overlap_seconds, 'curves': recording.curves,
    })


def _spread(values: list[float], digits: int = 2) -> dict | None:
    """Mediana, minimo y maximo; None si no hay ningun valor."""
    if not values:
        return None
    return {
        'median': round(median(values), digits), 'min': round(min(values), digits), 'max': round(max(values), digits),
        'count': len(values),
    }


def _group_key(recording: MixRecording) -> str:
    """El genero de la mezcla: el de la pista que sale; si no lo tiene, el de la que entra; si ninguna, sin genero."""
    return recording.genre_a or recording.genre_b or NO_GENRE


def _summarize_group(genre: str, recordings: list[MixRecording]) -> dict:
    features = [_features(r) for r in recordings]

    def values(key: str, transform=lambda v: v) -> list[float]:
        return [transform(f[key]) for f in features if f.get(key) is not None]

    shapes = Counter(f['crossfaderShape'] for f in features if f.get('crossfaderShape'))
    distances = Counter(f['keyDistance'] for f in features if f.get('keyDistance') is not None)
    bass_swaps = values('bassSwapAt')
    return {
        'genre': genre,
        'count': len(recordings),
        'overlapBars': _spread(values('overlapBars')),
        'exitFraction': _spread(values('exitFraction'), 3),
        'crossfaderShapes': dict(shapes),
        'bassSwap': {'count': len(bass_swaps), 'ofTotal': len(recordings), 'medianAt': _spread(bass_swaps, 3)},
        'phaseErrorMs': _spread(values('phaseErrorMs', abs), 1),
        'bpmDifference': _spread(values('bpmDifference', abs), 1),
        'keyDistance': {str(k): v for k, v in sorted(distances.items())},
    }


def summarize(quality: str | None = 'good', genre: str | None = None) -> dict:
    """Resume las grabaciones por genero.

    `quality`: 'good' (por defecto, lo que deberia usarse para entrenar), 'unreviewed', 'discard' o None para todas.
    `genre`: si se indica, solo ese genero (en minusculas, o 'sin genero').
    """
    if quality is not None and quality not in QUALITIES:
        raise ValueError(f"'quality' debe ser uno de {list(QUALITIES)} o None.")
    queryset = MixRecording.objects.order_by('created_at', 'id')
    if quality is not None:
        queryset = queryset.filter(quality=quality)

    groups: dict[str, list[MixRecording]] = defaultdict(list)
    for recording in queryset:
        groups[_group_key(recording)].append(recording)
    if genre is not None:
        groups = {g: r for g, r in groups.items() if g == genre}

    summaries = [_summarize_group(g, r) for g, r in groups.items()]
    summaries.sort(key=lambda s: (-s['count'], s['genre']))
    return {'quality': quality, 'total': sum(s['count'] for s in summaries), 'groups': summaries}
