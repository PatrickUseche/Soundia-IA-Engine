"""Grabaciones de transiciones: lo que un DJ hace de verdad al pasar de una pista a otra.

El front (en el modo aprendizaje) registra, en cada mezcla, cuando entra la pista B, cuanto solapa con la A y como
mueve el crossfader, el EQ y el volumen. Aqui se valida lo que llega, se guarda una foto de los datos de las dos
pistas en ese momento (el servidor la toma de la base: no se fia del cliente) y se calculan los rasgos con los que
despues se entrenan modelos: compases de solape, donde sale y entra, desfase de pulsos, cambio de graves...

Es un modulo sin dependencias de Django salvo `parse_recording`, que consulta las pistas: las demas funciones
trabajan con diccionarios y se prueban sin base de datos.
"""
import math
from dataclasses import dataclass

from audio.camelot import harmonic_distance
from audio.models import Track

SOURCES = ('manual', 'autodj')
QUALITIES = ('unreviewed', 'good', 'discard')

BEATS_PER_BAR = 4
MAX_OVERLAP_SECONDS = 600.0
# El pitch real de un reproductor es +-8 %; se acepta un margen amplio por si se usa un rango mayor.
MIN_PITCH, MAX_PITCH = 0.5, 2.0
MAX_CURVE_POINTS = 200
MAX_TEXT = 500
MAX_LABEL = 60
MAX_GENRE = 40

DECK_CURVES = ('volume', 'low', 'mid', 'high')
CURVE_TOLERANCE_SECONDS = 1.0

# Un cambio de graves (bass swap): la curva de graves de A baja de este nivel.
BASS_SWAP_LEVEL = 0.5
# El crossfader "corta" si pasa de 10 % a 90 % en menos de esta fraccion del solape (o de 2 s); "lento" si tarda mas de la mitad.
CUT_SPAN_FRACTION = 0.1
CUT_SPAN_SECONDS = 2.0
SLOW_SPAN_FRACTION = 0.5


class InvalidRecording(ValueError):
    """La grabacion no es valida; el mensaje se devuelve al cliente con un 400."""


@dataclass(frozen=True)
class Snapshot:
    """Datos de una pista tal como eran cuando se grabo la mezcla."""

    bpm: float
    camelot: str
    energy: float
    duration: float
    grid: dict | None
    vocal_last_end: float | None
    vocal_first_start: float | None

    def to_dict(self) -> dict:
        return {
            'bpm': self.bpm, 'camelot': self.camelot, 'energy': self.energy, 'duration': self.duration,
            'grid': self.grid, 'vocalLastEnd': self.vocal_last_end, 'vocalFirstStart': self.vocal_first_start,
        }


def snapshot_of(track: Track) -> Snapshot:
    grid = None
    if track.grid_offset is not None:
        grid = {
            'offset': track.grid_offset, 'downbeat': track.grid_downbeat, 'confidence': track.grid_confidence,
            'manual': track.grid_manual,
        }
    return Snapshot(
        bpm=track.bpm, camelot=track.camelot, energy=track.energy, duration=track.duration, grid=grid,
        vocal_last_end=track.vocal_last_end, vocal_first_start=track.vocal_first_start,
    )


# --- validacion -------------------------------------------------------------------------------------------------


def _number(data: dict, key: str, low: float, high: float) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InvalidRecording(f"Falta '{key}' o no es un numero.")
    if not low <= value <= high:
        raise InvalidRecording(f"'{key}' debe estar entre {low:g} y {high:g}.")
    return float(value)


def _track_id(data: dict, key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRecording(f"Falta '{key}' o no es un entero.")
    return value


def _text(data: dict, key: str, limit: int, default: str = '') -> str:
    value = data.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise InvalidRecording(f"'{key}' debe ser texto.")
    value = value.strip()
    if len(value) > limit:
        raise InvalidRecording(f"'{key}' no puede pasar de {limit} caracteres.")
    return value


def _curve(raw, name: str, overlap: float) -> list[list[float]]:
    """Una curva de [segundo, valor 0-1] en orden de tiempo, con segundos relativos a la entrada de B."""
    if not isinstance(raw, list):
        raise InvalidRecording(f"La curva '{name}' debe ser una lista de pares [segundo, valor].")
    if len(raw) > MAX_CURVE_POINTS:
        raise InvalidRecording(f"La curva '{name}' no puede tener mas de {MAX_CURVE_POINTS} puntos.")
    points = []
    for point in raw:
        if (not isinstance(point, (list, tuple)) or len(point) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point)):
            raise InvalidRecording(f"La curva '{name}' tiene un punto que no es un par de numeros.")
        second, value = float(point[0]), float(point[1])
        if not -CURVE_TOLERANCE_SECONDS <= second <= overlap + CURVE_TOLERANCE_SECONDS:
            raise InvalidRecording(f"La curva '{name}' tiene un punto fuera de la duracion del solape.")
        if not 0.0 <= value <= 1.0:
            raise InvalidRecording(f"La curva '{name}' tiene un valor fuera de 0 a 1.")
        points.append([round(second, 3), round(value, 4)])
    points.sort(key=lambda p: p[0])
    return points


def _curves(raw, overlap: float) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise InvalidRecording("'curves' debe ser un objeto.")
    allowed = {'crossfader', 'a', 'b'}
    unknown = set(raw) - allowed
    if unknown:
        raise InvalidRecording(f"'curves' solo admite {sorted(allowed)}; sobra {sorted(unknown)}.")
    curves = {}
    if 'crossfader' in raw:
        curves['crossfader'] = _curve(raw['crossfader'], 'crossfader', overlap)
    for deck in ('a', 'b'):
        if deck not in raw:
            continue
        if not isinstance(raw[deck], dict):
            raise InvalidRecording(f"'curves.{deck}' debe ser un objeto.")
        unknown = set(raw[deck]) - set(DECK_CURVES)
        if unknown:
            raise InvalidRecording(f"'curves.{deck}' solo admite {list(DECK_CURVES)}; sobra {sorted(unknown)}.")
        curves[deck] = {name: _curve(values, f'{deck}.{name}', overlap) for name, values in raw[deck].items()}
    return curves


def parse_recording(data: dict) -> dict:
    """Valida el cuerpo de una grabacion y devuelve los campos del modelo (con la foto de las pistas incluida).

    Lanza InvalidRecording si algo no es valido y Track.DoesNotExist si falta una pista.
    """
    if not isinstance(data, dict):
        raise InvalidRecording('El cuerpo debe ser un objeto.')
    from_id = _track_id(data, 'fromTrackId')
    to_id = _track_id(data, 'toTrackId')
    if from_id == to_id:
        raise InvalidRecording('La pista de salida y la de entrada no pueden ser la misma.')
    source = data.get('source', 'manual')
    if source not in SOURCES:
        raise InvalidRecording(f"'source' debe ser uno de {list(SOURCES)}.")

    origin = Track.objects.get(pk=from_id)
    destination = Track.objects.get(pk=to_id)
    mix_out_at = _number(data, 'mixOutAt', 0.0, origin.duration + CURVE_TOLERANCE_SECONDS)
    mix_in_at = _number(data, 'mixInAt', 0.0, destination.duration + CURVE_TOLERANCE_SECONDS)
    overlap = _number(data, 'overlapSeconds', 0.0, MAX_OVERLAP_SECONDS)
    if overlap <= 0:
        raise InvalidRecording("'overlapSeconds' debe ser mayor que 0.")

    return {
        'from_track': origin,
        'to_track': destination,
        'source': source,
        'dj': _text(data, 'dj', MAX_LABEL, 'dj') or 'dj',
        'mix_out_at': mix_out_at,
        'mix_in_at': mix_in_at,
        'overlap_seconds': overlap,
        'pitch_a': _number(data, 'pitchA', MIN_PITCH, MAX_PITCH),
        'pitch_b': _number(data, 'pitchB', MIN_PITCH, MAX_PITCH),
        'curves': _curves(data.get('curves'), overlap),
        # Si el cliente no manda el genero, se toma el que el DJ le puso a cada pista.
        'genre_a': _text(data, 'genreA', MAX_GENRE) or origin.genre,
        'genre_b': _text(data, 'genreB', MAX_GENRE) or destination.genre,
        'snapshot_a': snapshot_of(origin).to_dict(),
        'snapshot_b': snapshot_of(destination).to_dict(),
        'notes': _text(data, 'notes', MAX_TEXT),
    }


def parse_review(data) -> dict:
    """Valida los cambios de la revision de una grabacion (`quality` y `notes`); al menos uno."""
    if not isinstance(data, dict):
        raise InvalidRecording('El cuerpo debe ser un objeto.')
    changes = {}
    if 'quality' in data:
        if data['quality'] not in QUALITIES:
            raise InvalidRecording(f"'quality' debe ser uno de {list(QUALITIES)}.")
        changes['quality'] = data['quality']
    if 'notes' in data:
        changes['notes'] = _text(data, 'notes', MAX_TEXT)
    if not changes:
        raise InvalidRecording("Indica 'quality' o 'notes'.")
    return changes


# --- rasgos derivados -------------------------------------------------------------------------------------------


def _wrap(value: float, period: float) -> float:
    """`value` llevado al rango (-period/2, period/2]."""
    wrapped = ((value + period / 2) % period) - period / 2
    return period / 2 if math.isclose(wrapped, -period / 2) else wrapped


def beat_phase_error_ms(snapshot_a: dict, snapshot_b: dict, mix_out_at: float, mix_in_at: float,
                        pitch_a: float, pitch_b: float) -> float | None:
    """Cuanto se adelanta o atrasa (en ms) un pulso de B respecto al de A en el momento en que B entra.

    Positivo = B va por detras. None si alguna de las dos pistas no tiene rejilla de pulsos.
    """
    grid_a, grid_b = snapshot_a.get('grid'), snapshot_b.get('grid')
    if not grid_a or not grid_b:
        return None
    beat_a = 60.0 / snapshot_a['bpm']
    beat_b = 60.0 / snapshot_b['bpm']
    # Tiempo de reloj desde el ultimo pulso de cada pista (la posicion avanza `pitch` veces mas rapido).
    since_a = ((mix_out_at - grid_a['offset']) % beat_a) / pitch_a
    since_b = ((mix_in_at - grid_b['offset']) % beat_b) / pitch_b
    period = beat_a / pitch_a
    return round(_wrap(since_a - since_b, period) * 1000, 1)


def _crossings(curve: list[list[float]], level: float, rising: bool) -> float | None:
    """Primer segundo en que la curva cruza `level` hacia arriba (rising) o hacia abajo; interpolado."""
    for (t0, v0), (t1, v1) in zip(curve, curve[1:]):
        crosses = v0 < level <= v1 if rising else v0 > level >= v1
        if crosses:
            return t0 if v1 == v0 else t0 + (level - v0) / (v1 - v0) * (t1 - t0)
    return None


def bass_swap_fraction(curves: dict, overlap: float) -> float | None:
    """En que fraccion (0-1) del solape el DJ quita los graves de A; None si no hay curva de graves de A."""
    low = curves.get('a', {}).get('low')
    if not low or len(low) < 2 or overlap <= 0:
        return None
    second = _crossings(low, BASS_SWAP_LEVEL, rising=False)
    if second is None:
        return None
    return round(min(max(second / overlap, 0.0), 1.0), 3)


def crossfader_shape(curves: dict, overlap: float, beat_seconds: float) -> str | None:
    """'corte', 'gradual' o 'lento' segun cuanto tarda el crossfader en ir del 10 % al 90 %; None si no hay curva."""
    fader = curves.get('crossfader')
    if not fader or len(fader) < 2 or overlap <= 0:
        return None
    start = _crossings(fader, 0.1, rising=True)
    end = _crossings(fader, 0.9, rising=True)
    if start is None or end is None:
        # Tambien puede ir de B hacia A (de 1 a 0), segun el deck que salga.
        start = _crossings(fader, 0.9, rising=False)
        end = _crossings(fader, 0.1, rising=False)
    if start is None or end is None:
        return None
    span = end - start
    if span <= max(CUT_SPAN_FRACTION * overlap, min(CUT_SPAN_SECONDS, beat_seconds * 2)):
        return 'corte'
    return 'lento' if span >= SLOW_SPAN_FRACTION * overlap else 'gradual'


def derive_features(recording: dict) -> dict:
    """Rasgos de una grabacion, listos para entrenar o para mostrar. `recording` trae los campos del modelo en
    claves de Python (`mix_out_at`, `snapshot_a`...); lo que no se puede calcular queda en None."""
    a, b = recording['snapshot_a'], recording['snapshot_b']
    pitch_a, pitch_b = recording['pitch_a'], recording['pitch_b']
    mix_out_at, mix_in_at = recording['mix_out_at'], recording['mix_in_at']
    overlap = recording['overlap_seconds']
    curves = recording.get('curves') or {}

    beat_clock = 60.0 / (a['bpm'] * pitch_a)  # segundos de reloj por pulso de A, al ritmo al que suena
    bar_clock = BEATS_PER_BAR * beat_clock

    grid_b = b.get('grid')
    entry_bars = None
    if grid_b:
        entry_bars = round((mix_in_at - grid_b['downbeat']) / (BEATS_PER_BAR * 60.0 / b['bpm']), 3)

    vocal_last_end = a.get('vocalLastEnd')
    vocal_first_start = b.get('vocalFirstStart')
    return {
        'overlapBars': round(overlap / bar_clock, 3),
        'exitFromEnd': round(a['duration'] - mix_out_at, 3),
        'exitFraction': round(mix_out_at / a['duration'], 4) if a['duration'] > 0 else None,
        'exitAfterLastVocal': round(mix_out_at - vocal_last_end, 3) if vocal_last_end is not None else None,
        'entryBarsFromDownbeat': entry_bars,
        'entryBeforeFirstVocal': round(vocal_first_start - mix_in_at, 3) if vocal_first_start is not None else None,
        'phaseErrorMs': beat_phase_error_ms(a, b, mix_out_at, mix_in_at, pitch_a, pitch_b),
        'tempoRatio': round((b['bpm'] * pitch_b) / (a['bpm'] * pitch_a), 4),
        'bpmDifference': round(b['bpm'] - a['bpm'], 3),
        'keyDistance': harmonic_distance(a['camelot'], b['camelot']),
        'energyDelta': round(b['energy'] - a['energy'], 3),
        'bassSwapAt': bass_swap_fraction(curves, overlap),
        'crossfaderShape': crossfader_shape(curves, overlap, beat_clock),
    }
