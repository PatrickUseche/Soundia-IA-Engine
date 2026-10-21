"""Plan de transicion entre dos pistas: cuando entra la siguiente, cuanto dura la mezcla y como se
automatizan el crossfader y los ecualizadores."""
import math
from dataclasses import dataclass

from audio.camelot import harmonic_distance

from .compatibility import Compatibility, TrackInfo, compatibility
from .tempo import TempoMatch

BEATS_PER_BAR = 4

STYLE_BLEND = 'blend'  # las dos pistas suenan a la vez mientras se hace la transicion
STYLE_CUT = 'cut'  # corte directo en el compas: los tempos no se pueden igualar

# Compases de mezcla segun lo bien que encajan las pistas.
BARS_SMOOTH = 16  # tempo casi igual y tonalidades vecinas
BARS_NORMAL = 8  # algo de ajuste de tempo o tonalidades a dos o tres pasos
BARS_QUICK = 4  # tonalidades que chocan: se solapan lo minimo

# Hasta este ajuste de pitch (4 %) la mezcla larga suena natural.
SMOOTH_PITCH_LIMIT = 0.04
# Margen para dar por valido un punto de salida que se pasa unos milisegundos del final.
END_TOLERANCE_SECONDS = 0.5


@dataclass(frozen=True)
class AutomationPoint:
    position: float  # 0.0 (solo suena A) a 1.0 (solo suena B)
    gain_a: float  # crossfader
    gain_b: float
    low_a: float  # graves (1.0 = abiertos, 0.0 = cortados)
    low_b: float
    mid_a: float
    mid_b: float
    high_a: float
    high_b: float


@dataclass(frozen=True)
class TransitionPlan:
    style: str
    bars: int
    seconds: float
    mix_out_at: float  # segundo de la pista A en que empieza la mezcla
    mix_in_at: float  # segundo de la pista B desde el que se reproduce
    tempo_match: TempoMatch
    compatibility: Compatibility
    automation: list[AutomationPoint]


def eq_automation(steps: int) -> list[AutomationPoint]:
    """Curvas de una mezcla clasica con `steps` + 1 puntos entre 0.0 y 1.0.

    - Crossfader de potencia constante (la suma de potencias es siempre 1: el volumen percibido no baja).
    - Intercambio de graves (bass swap) a mitad: nunca suenan los graves de las dos pistas a la vez,
      que es lo que embarra una mezcla.
    - Medios y agudos se cruzan de forma lineal.
    """
    if steps < 1:
        raise ValueError("steps debe ser al menos 1.")

    points = []
    for i in range(steps + 1):
        p = i / steps
        bass_swapped = p >= 0.5
        points.append(AutomationPoint(
            position=round(p, 4),
            gain_a=round(math.cos(p * math.pi / 2), 4),
            gain_b=round(math.sin(p * math.pi / 2), 4),
            low_a=0.0 if bass_swapped else 1.0,
            low_b=1.0 if bass_swapped else 0.0,
            mid_a=round(1.0 - p, 4),
            mid_b=round(p, 4),
            high_a=round(1.0 - p, 4),
            high_b=round(p, 4),
        ))
    return points


def choose_style_and_bars(match: TempoMatch, harmonic_steps: int) -> tuple[str, int]:
    if not match.feasible:
        return STYLE_CUT, 0
    if harmonic_steps >= 4:
        return STYLE_BLEND, BARS_QUICK
    if harmonic_steps <= 1 and match.adjustment <= SMOOTH_PITCH_LIMIT:
        return STYLE_BLEND, BARS_SMOOTH
    return STYLE_BLEND, BARS_NORMAL


def choose_mix_out(track: TrackInfo, transition_seconds: float) -> float:
    """Ultimo punto de mezcla de la pista en el que la transicion todavia cabe antes del final."""
    latest = max(track.duration - transition_seconds, 0.0)
    fitting = [cue for cue in track.cue_points if cue <= latest + END_TOLERANCE_SECONDS]
    return round(max(fitting), 3) if fitting else round(latest, 3)


def plan_transition(a: TrackInfo, b: TrackInfo) -> TransitionPlan:
    """Como pasar de la pista A a la pista B."""
    result = compatibility(a, b)
    match = result.tempo_match
    style, bars = choose_style_and_bars(match, harmonic_distance(a.camelot, b.camelot))

    bar_seconds = BEATS_PER_BAR * 60.0 / a.bpm
    seconds = round(bars * bar_seconds, 3)
    return TransitionPlan(
        style=style,
        bars=bars,
        seconds=seconds,
        mix_out_at=choose_mix_out(a, seconds),
        mix_in_at=b.cue_points[0] if b.cue_points else 0.0,
        tempo_match=match,
        compatibility=result,
        # Una automatizacion por pulso; el corte no tiene automatizacion.
        automation=eq_automation(max(bars * BEATS_PER_BAR, 1)) if style == STYLE_BLEND else [],
    )
