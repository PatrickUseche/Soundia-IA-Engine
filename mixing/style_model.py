"""Modelo del estilo del DJ: cuantos compases suele solapar y donde cambia los graves, aprendido solo de sus mezclas.

Con decenas de grabaciones no hay datos para un modelo complejo, asi que este es deliberadamente pequeno y se puede
explicar. Parte de las reglas del motor y las desplaza hacia lo que hace el DJ *en la misma situacion*, tanto como
permiten los datos:

    estimacion = (K * regla + n * mediana_del_DJ) / (K + n)

donde `n` es cuantas mezclas buenas hay en esa situacion. Con `n = 0` manda la regla; con muchas, manda el DJ. Se aplica
en dos niveles (primero la tonalidad y el tempo, luego ademas el genero), de modo que un genero con pocos casos hereda
lo aprendido de los casos parecidos en vez de quedarse sin estimacion.

El modelo solo se usa si, dejando cada mezcla fuera y prediciendola con las demas, acierta mas que las reglas
(ver `evaluate`).
"""
from collections import defaultdict
from dataclasses import dataclass
from math import log2
from statistics import median

from audio.camelot import harmonic_distance

from .models import MixRecording
from .recordings import derive_features
from .tempo import match_tempo
from .transition import BARS_NORMAL, BARS_QUICK, BARS_SMOOTH, SMOOTH_PITCH_LIMIT

# Cuanto pesa la regla frente a los datos: la regla cuenta como estas mezclas "virtuales". Es alto a proposito: una
# mezcla entra en los dos niveles, y con una o dos no se debe cambiar nada.
PRIOR_WEIGHT = 8.0
# Mezclas buenas necesarias antes de evaluar el modelo: con menos, cualquier acierto seria casualidad.
MIN_RECORDINGS = 20
# Solo cuentan las mas recientes (el estilo cambia) y asi la evaluacion cuesta O(300^2) como mucho.
MAX_RECORDINGS = 300
# El modelo tiene que reducir el error de las reglas al menos en esta fraccion para considerarse mejor.
WIN_MARGIN = 0.05
# Compases entre los que elige una mezcla larga; el solape real se redondea al mas cercano (en escala logaritmica).
BARS_CHOICES = (BARS_QUICK, BARS_NORMAL, BARS_SMOOTH)
# Punto del solape (0-1) en que se cambian los graves segun las reglas, y limites de lo que se acepta aprender.
RULE_BASS_SWAP = 0.5
BASS_SWAP_RANGE = (0.2, 0.8)

KEY_NEAR, KEY_MID, KEY_FAR = 'near', 'mid', 'far'
TEMPO_TIGHT, TEMPO_STRETCH, TEMPO_FREE = 'tight', 'stretch', 'free'


@dataclass(frozen=True)
class Context:
    """La situacion de una transicion: lo unico que el modelo mira para decidir."""

    genre: str
    key: str
    tempo: str

    @property
    def blendable(self) -> bool:
        """Con tempos que no se igualan solo cabe un fundido corto: no hay nada que aprender ni que cambiar."""
        return self.tempo != TEMPO_FREE


def context_of(bpm_a: float, camelot_a: str, bpm_b: float, camelot_b: str, genre: str = '') -> Context:
    steps = harmonic_distance(camelot_a, camelot_b)
    key = KEY_NEAR if steps <= 1 else KEY_MID if steps <= 3 else KEY_FAR
    match = match_tempo(bpm_a, bpm_b)
    if not match.feasible:
        tempo = TEMPO_FREE
    else:
        tempo = TEMPO_TIGHT if match.adjustment <= SMOOTH_PITCH_LIMIT else TEMPO_STRETCH
    return Context(genre=genre or '', key=key, tempo=tempo)


def rule_bars(context: Context) -> int:
    """Los compases que elegiria el motor sin modelo en este contexto (ver `choose_style_and_bars`)."""
    if context.key == KEY_FAR:
        return BARS_QUICK
    if context.key == KEY_NEAR and context.tempo == TEMPO_TIGHT:
        return BARS_SMOOTH
    return BARS_NORMAL


@dataclass(frozen=True)
class Sample:
    """Una mezcla buena del DJ, reducida a lo que el modelo usa."""

    context: Context
    bars_log2: float | None  # log2 de los compases que solapo; None si no se pudo calcular
    bass_swap: float | None  # en que fraccion del solape cambio los graves; None si no los cambio


@dataclass(frozen=True)
class StyleModel:
    """Las medidas del DJ agrupadas por contexto. Guarda los valores y calcula medianas al predecir: con cientos de
    mezclas cuesta menos que mantener estadisticos incrementales y evita errores al sacar una mezcla (evaluacion)."""

    bars: dict  # (key, tempo) y (genero, key, tempo) -> [log2 compases]
    swap: dict  # () y (genero,) -> [fraccion del cambio de graves]

    def _shrunk(self, values: list[float] | None, prior: float) -> float:
        if not values:
            return prior
        n = len(values)
        return (PRIOR_WEIGHT * prior + n * median(values)) / (PRIOR_WEIGHT + n)

    def predict_bars(self, context: Context) -> int:
        """Compases de una mezcla larga en este contexto, redondeados a una de `BARS_CHOICES`."""
        estimate = log2(rule_bars(context))
        estimate = self._shrunk(self.bars.get((context.key, context.tempo)), estimate)
        estimate = self._shrunk(self.bars.get((context.genre, context.key, context.tempo)), estimate)
        return min(BARS_CHOICES, key=lambda choice: abs(log2(choice) - estimate))

    def predict_bass_swap(self, context: Context) -> float:
        estimate = self._shrunk(self.swap.get(()), RULE_BASS_SWAP)
        estimate = self._shrunk(self.swap.get((context.genre,)), estimate)
        return round(min(max(estimate, BASS_SWAP_RANGE[0]), BASS_SWAP_RANGE[1]), 3)


def fit(samples: list[Sample]) -> StyleModel:
    """O(n): reparte cada mezcla en sus grupos."""
    bars: dict = defaultdict(list)
    swap: dict = defaultdict(list)
    for sample in samples:
        context = sample.context
        if sample.bars_log2 is not None and context.blendable:
            bars[(context.key, context.tempo)].append(sample.bars_log2)
            bars[(context.genre, context.key, context.tempo)].append(sample.bars_log2)
        if sample.bass_swap is not None:
            swap[()].append(sample.bass_swap)
            swap[(context.genre,)].append(sample.bass_swap)
    return StyleModel(bars=dict(bars), swap=dict(swap))


def load_samples() -> list[Sample]:
    """Las mezclas buenas mas recientes, de la mas antigua a la mas nueva."""
    recordings = list(MixRecording.objects.filter(quality='good').order_by('-created_at', '-id')[:MAX_RECORDINGS])
    return [_sample_of(recording) for recording in reversed(recordings)]


def count_good() -> int:
    return MixRecording.objects.filter(quality='good').count()


def _sample_of(recording: MixRecording) -> Sample:
    a, b = recording.snapshot_a, recording.snapshot_b
    context = context_of(a['bpm'], a['camelot'], b['bpm'], b['camelot'], recording.genre_a or recording.genre_b)
    features = derive_features({
        'snapshot_a': a, 'snapshot_b': b, 'pitch_a': recording.pitch_a, 'pitch_b': recording.pitch_b,
        'mix_out_at': recording.mix_out_at, 'mix_in_at': recording.mix_in_at,
        'overlap_seconds': recording.overlap_seconds, 'curves': recording.curves,
    })
    overlap_bars = features.get('overlapBars')
    return Sample(
        context=context,
        bars_log2=log2(overlap_bars) if overlap_bars and overlap_bars > 0 else None,
        bass_swap=features.get('bassSwapAt'),
    )


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def evaluate(samples: list[Sample]) -> dict:
    """Dejando cada mezcla fuera, cuanto se equivoca el modelo (entrenado con las demas) frente a las reglas.

    El error de los compases es la distancia en log2 (equivocarse de 8 a 16 pesa igual que de 4 a 8); el del cambio
    de graves, la diferencia de fraccion. Cada objetivo se evalua y se decide por separado: el modelo puede ganar en
    uno y no en el otro. Coste O(n^2) con n <= MAX_RECORDINGS.
    """
    bars_model, bars_rules, swap_model, swap_rules = [], [], [], []
    for index, sample in enumerate(samples):
        if sample.bars_log2 is None and sample.bass_swap is None:
            continue
        model = fit(samples[:index] + samples[index + 1:])
        if sample.bars_log2 is not None and sample.context.blendable:
            bars_model.append(abs(log2(model.predict_bars(sample.context)) - sample.bars_log2))
            bars_rules.append(abs(log2(rule_bars(sample.context)) - sample.bars_log2))
        if sample.bass_swap is not None:
            swap_model.append(abs(model.predict_bass_swap(sample.context) - sample.bass_swap))
            swap_rules.append(abs(RULE_BASS_SWAP - sample.bass_swap))

    def verdict(model_errors: list[float], rule_errors: list[float]) -> dict:
        model_error, rule_error = _mean(model_errors), _mean(rule_errors)
        enough = len(model_errors) >= MIN_RECORDINGS
        return {
            'evaluated': len(model_errors),
            'rulesError': rule_error,
            'modelError': model_error,
            'wins': bool(enough and rule_error is not None and model_error < rule_error * (1 - WIN_MARGIN)),
        }

    return {'bars': verdict(bars_model, bars_rules), 'bassSwap': verdict(swap_model, swap_rules)}


def style_model_status() -> dict:
    """Lo que se muestra al DJ: cuantas mezclas buenas hay, cuantas faltan y como le va al modelo frente a las reglas."""
    good = count_good()
    status = {'goodRecordings': good, 'required': MIN_RECORDINGS, 'ready': good >= MIN_RECORDINGS}
    if status['ready']:
        status['evaluation'] = evaluate(load_samples())
    return status
