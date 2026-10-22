"""Que tan bien mezclan dos pistas y cual conviene poner despues de la actual."""
from dataclasses import dataclass, field

from audio.camelot import harmonic_distance

from .tempo import TempoMatch, match_tempo, tempo_score

# Pesos de cada criterio en la puntuacion total (suman 1.0).
TEMPO_WEIGHT = 0.45
HARMONIC_WEIGHT = 0.40
ENERGY_WEIGHT = 0.15


@dataclass(frozen=True)
class ScoringWeights:
    """Cuanto pesa cada criterio en la puntuacion total. No pueden ser negativos y suman 1."""

    tempo: float
    harmonic: float
    energy: float

    def __post_init__(self):
        if min(self.tempo, self.harmonic, self.energy) < 0:
            raise ValueError("Los pesos no pueden ser negativos.")
        total = self.tempo + self.harmonic + self.energy
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Los pesos deben sumar 1 (suman {total}).")


DEFAULT_WEIGHTS = ScoringWeights(TEMPO_WEIGHT, HARMONIC_WEIGHT, ENERGY_WEIGHT)

# Puntuacion armonica segun los pasos de distancia en la rueda de Camelot.
_HARMONIC_SCORES = {0: 1.0, 1: 0.8, 2: 0.5, 3: 0.25}


@dataclass(frozen=True)
class TrackInfo:
    """Lo que el motor de mezcla necesita saber de una pista."""

    id: int
    title: str
    bpm: float
    camelot: str
    energy: float
    duration: float = 0.0
    cue_points: list[float] = field(default_factory=list)
    vocal_last_end: float | None = None  # segundo en que acaba la ultima frase cantada; None si no se sabe

    @classmethod
    def from_model(cls, track) -> 'TrackInfo':
        return cls(
            id=track.id, title=track.title, bpm=track.bpm, camelot=track.camelot,
            energy=track.energy, duration=track.duration, cue_points=list(track.cue_points),
            vocal_last_end=track.vocal_last_end,
        )


@dataclass(frozen=True)
class Compatibility:
    score: float  # 0.0 - 1.0
    tempo: float
    harmonic: float
    energy: float
    tempo_match: TempoMatch


def harmonic_score(camelot_a: str, camelot_b: str) -> float:
    """1.0 en la misma tonalidad, 0.8 en las vecinas, y bajando hasta 0.0 a partir de 4 pasos."""
    return _HARMONIC_SCORES.get(harmonic_distance(camelot_a, camelot_b), 0.0)


def energy_score(energy_a: float, energy_b: float) -> float:
    """1.0 si la energia es igual; cae linealmente con la diferencia (0.0 si difieren en todo el rango)."""
    return max(0.0, 1.0 - abs(energy_a - energy_b))


def compatibility(a: TrackInfo, b: TrackInfo, weights: ScoringWeights = DEFAULT_WEIGHTS) -> Compatibility:
    """Puntuacion de mezclar B despues de A, combinando tempo, armonia y energia."""
    tempo_match = match_tempo(a.bpm, b.bpm)
    tempo = tempo_score(tempo_match)
    harmonic = harmonic_score(a.camelot, b.camelot)
    energy = energy_score(a.energy, b.energy)
    total = weights.tempo * tempo + weights.harmonic * harmonic + weights.energy * energy
    return Compatibility(
        score=round(total, 4), tempo=round(tempo, 4), harmonic=harmonic,
        energy=round(energy, 4), tempo_match=tempo_match,
    )


def rank_next_tracks(
    current: TrackInfo,
    candidates: list[TrackInfo],
    limit: int = 5,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
) -> list[tuple[TrackInfo, Compatibility]]:
    """Las mejores pistas para seguir a `current`, de mayor a menor puntuacion.

    La propia pista actual se excluye. A igual puntuacion gana la de menor id, para que el orden sea estable.
    """
    if limit < 1:
        raise ValueError("limit debe ser al menos 1.")
    scored = [(track, compatibility(current, track, weights)) for track in candidates if track.id != current.id]
    scored.sort(key=lambda item: (-item[1].score, item[0].id))
    return scored[:limit]
