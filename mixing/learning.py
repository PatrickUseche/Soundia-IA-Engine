"""Aprendizaje de los pesos de la puntuacion a partir de las valoraciones del DJ.

Cada vez que el DJ valora una transicion (me gusto / no me gusto) se guardan las tres puntuaciones que tenia
(tempo, armonia, energia). Con esos ejemplos se ajusta una regresion logistica pequena que dice cuanto
importa cada criterio *para este DJ*; los pesos aprendidos reemplazan a los fijos (45/40/15).

Es una regresion logistica de tres variables entrenada con descenso de gradiente, sin librerias externas:
para tan pocas variables y ejemplos no hace falta mas, y el resultado se puede explicar (los pesos).
"""
import math
from dataclasses import dataclass

from .compatibility import DEFAULT_WEIGHTS, ScoringWeights

# Con menos valoraciones que estas no se aprende nada: se mantienen los pesos actuales.
MIN_SAMPLES = 10
# Un criterio nunca baja de este peso: aunque no haya aportado nada hasta ahora, no se ignora del todo.
MIN_WEIGHT = 0.02

EPOCHS = 800
LEARNING_RATE = 1.0
# Los pesos actuales cuentan como estos ejemplos "virtuales": con pocas valoraciones reales pesan mucho
# (el DJ aun no ha dicho nada concluyente) y, a medida que se acumulan, lo aprendido va mandando.
PRIOR_SAMPLES = 30
REGULARIZATION = 1.0
# Los pesos viven en [0, 1] y suman 1; el modelo logistico necesita una escala mayor para separar likes de dislikes.
_SCALE = 6.0


@dataclass(frozen=True)
class FeedbackSample:
    """Una valoracion: las puntuaciones de la transicion (0-1) y si le gusto al DJ."""

    tempo: float
    harmonic: float
    energy: float
    liked: bool


def _sigmoid(x: float) -> float:
    # Dos ramas para no desbordar exp() con valores muy negativos o muy positivos.
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def predict_like_probability(weights: ScoringWeights, sample: FeedbackSample, bias: float = 0.0) -> float:
    """Probabilidad estimada de que la transicion le guste al DJ con estos pesos."""
    z = _SCALE * (weights.tempo * sample.tempo + weights.harmonic * sample.harmonic + weights.energy * sample.energy)
    return _sigmoid(z + bias)


def has_enough_signal(samples: list[FeedbackSample]) -> bool:
    """Hay suficientes valoraciones y de las dos clases (si todas son iguales no se aprende nada util)."""
    if len(samples) < MIN_SAMPLES:
        return False
    liked = sum(1 for s in samples if s.liked)
    return 0 < liked < len(samples)


def train_weights(samples: list[FeedbackSample], prior: ScoringWeights = DEFAULT_WEIGHTS) -> ScoringWeights:
    """Pesos ajustados a las valoraciones; los de `prior` si no hay datos suficientes.

    Descenso de gradiente por lotes sobre la perdida logistica mas una penalizacion que tira de los pesos hacia
    `prior` con la fuerza de PRIOR_SAMPLES ejemplos virtuales. Al final se recortan a un minimo y se normalizan
    para que sumen 1. Es determinista.
    """
    if not has_enough_signal(samples):
        return prior

    prior_vector = [prior.tempo, prior.harmonic, prior.energy]
    w = prior_vector[:]
    bias = 0.0
    n = len(samples)

    for _ in range(EPOCHS):
        gradient = [0.0, 0.0, 0.0]
        gradient_bias = 0.0
        for sample in samples:
            x = (sample.tempo, sample.harmonic, sample.energy)
            z = _SCALE * sum(wi * xi for wi, xi in zip(w, x)) + bias
            error = _sigmoid(z) - (1.0 if sample.liked else 0.0)
            for i in range(3):
                gradient[i] += error * _SCALE * x[i]
            gradient_bias += error
        for i in range(3):
            gradient[i] = (gradient[i] + PRIOR_SAMPLES * REGULARIZATION * (w[i] - prior_vector[i])) / n
            w[i] -= LEARNING_RATE * gradient[i]
        bias -= LEARNING_RATE * gradient_bias / n

    clipped = [max(MIN_WEIGHT, value) for value in w]
    total = sum(clipped)
    tempo, harmonic, energy = (value / total for value in clipped)
    # Se corrige el ultimo para que la suma sea exactamente 1 pese al redondeo de coma flotante.
    return ScoringWeights(tempo, harmonic, 1.0 - tempo - harmonic)
