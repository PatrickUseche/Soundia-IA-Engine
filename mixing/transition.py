"""Plan de transicion entre dos pistas: cuando entra la siguiente, cuanto dura la mezcla y como se
automatizan el crossfader y los ecualizadores."""
import math
from dataclasses import dataclass

from audio.camelot import harmonic_distance

from .compatibility import DEFAULT_WEIGHTS, Compatibility, ScoringWeights, TrackInfo, compatibility
from .tempo import TempoMatch

BEATS_PER_BAR = 4

STYLE_BLEND = 'blend'  # las dos pistas suenan a la vez mientras se hace la transicion
# Fundido corto: los tempos no se pueden igualar, asi que no se fuerza el pitch; la pista entrante
# suena a su ritmo y se cruza con la saliente solo unos compases para que no sea un corte seco.
STYLE_FADE = 'fade'

# Compases de mezcla segun lo bien que encajan las pistas.
BARS_SMOOTH = 16  # tempo casi igual y tonalidades vecinas
BARS_NORMAL = 8  # algo de ajuste de tempo o tonalidades a dos o tres pasos
BARS_QUICK = 4  # tonalidades que chocan: se solapan lo minimo
BARS_FADE = 2  # tempos que no se igualan: el solape mas corto posible

# Hasta este ajuste de pitch (4 %) la mezcla larga suena natural.
SMOOTH_PITCH_LIMIT = 0.04
# Margen para dar por valido un punto de salida que se pasa unos milisegundos del final.
END_TOLERANCE_SECONDS = 0.5
# Holgura entre el final del fundido y el final de la pista: el Auto-DJ revisa el punto de salida cada medio
# segundo y la pista saliente no debe acabarse antes de que termine el cruce.
FADE_END_MARGIN_SECONDS = 2.0
# Segundos entre la ultima frase cantada y el inicio del fundido: que no se solape con el eco de la voz.
VOCAL_TAIL_GAP_SECONDS = 1.0


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
    mix_out_advance: float = 0.0  # segundos que se adelanta la salida por lo aprendido de los DJ


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
        return STYLE_FADE, BARS_FADE
    if harmonic_steps >= 4:
        return STYLE_BLEND, BARS_QUICK
    if harmonic_steps <= 1 and match.adjustment <= SMOOTH_PITCH_LIMIT:
        return STYLE_BLEND, BARS_SMOOTH
    return STYLE_BLEND, BARS_NORMAL


def fit_bars_to_intro(track: TrackInfo, bars: int, bar_seconds: float, mix_in_at: float) -> int:
    """Compases de una mezcla larga que caben en la intro instrumental de la pista que entra.

    Si se sabe donde empieza su voz, el solape no debe llegar hasta ella: dos voces a la vez ensucian la mezcla. Se
    elige la mas larga de las mezclas habituales (sin alargar la pedida) cuyo solape acaba antes de esa voz; si ni la
    mas corta cabe, se queda con la mas corta, porque menos de eso ya no es una mezcla.
    """
    first_start = track.vocal_first_start
    if first_start is None:
        return bars
    room = first_start - mix_in_at
    for candidate in (BARS_SMOOTH, BARS_NORMAL, BARS_QUICK):
        if candidate <= bars and candidate * bar_seconds <= room:
            return candidate
    return min(bars, BARS_QUICK)


def choose_fade_out(track: TrackInfo, transition_seconds: float, advance: float = 0.0) -> float:
    """Punto de salida de un fundido, sin cortar la letra de la pista que sale.

    Los cues marcan cambios de energia (a veces en mitad de un estribillo) y el de salida cae unos compases
    antes del final: empezar ahi apagaria la pista saliente y se perderia el resto de la cancion y su letra.
    Sin beatmatch no hay una rejilla que respetar, asi que no hace falta alinear el fundido a un cue:
    - si se sabe donde acaba la ultima frase y queda cola instrumental para el fundido, empieza justo despues;
    - si no, tan tarde como cabe, para que la cancion suene casi hasta el final.
    `advance` son los segundos que el DJ suele querer mezclar antes y se restan al final.
    """
    latest = max(track.duration - transition_seconds - FADE_END_MARGIN_SECONDS, 0.0)
    start = latest
    if track.vocal_last_end is not None:
        after_vocals = track.vocal_last_end + VOCAL_TAIL_GAP_SECONDS
        if after_vocals <= latest:
            start = after_vocals
    return round(max(start - advance, 0.0), 3)


def choose_mix_out(track: TrackInfo, transition_seconds: float) -> float:
    """Ultimo punto de mezcla de la pista en el que la transicion todavia cabe antes del final."""
    latest = max(track.duration - transition_seconds, 0.0)
    fitting = [cue for cue in track.cue_points if cue <= latest + END_TOLERANCE_SECONDS]
    return round(max(fitting), 3) if fitting else round(latest, 3)


def plan_transition(a: TrackInfo, b: TrackInfo, weights: ScoringWeights = DEFAULT_WEIGHTS,
                    advance: float = 0.0) -> TransitionPlan:
    """Como pasar de la pista A a la pista B. Los pesos solo afectan a la puntuacion de compatibilidad.

    `advance` son los segundos que la mezcla sale antes de lo normal, aprendidos de cuando el DJ pidio mezclar antes.
    """
    result = compatibility(a, b, weights)
    match = result.tempo_match
    style, bars = choose_style_and_bars(match, harmonic_distance(a.camelot, b.camelot))

    bar_seconds = BEATS_PER_BAR * 60.0 / a.bpm
    mix_in_at = b.cue_points[0] if b.cue_points else 0.0
    if style == STYLE_BLEND:
        bars = fit_bars_to_intro(b, bars, bar_seconds, mix_in_at)
    seconds = round(bars * bar_seconds, 3)
    return TransitionPlan(
        style=style,
        bars=bars,
        seconds=seconds,
        mix_out_at=(choose_fade_out(a, seconds, advance) if style == STYLE_FADE
                    else choose_mix_out(a, seconds + advance)),
        mix_in_at=mix_in_at,
        tempo_match=match,
        compatibility=result,
        # Una automatizacion por pulso.
        automation=eq_automation(bars * BEATS_PER_BAR),
        mix_out_advance=advance,
    )
