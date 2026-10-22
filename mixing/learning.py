"""Aprendizaje de los pesos de la puntuacion a partir de las valoraciones del DJ.

Cada vez que el DJ valora una transicion (me gusto / no me gusto) se guardan las tres puntuaciones que tenia
(tempo, armonia, energia). Con esos ejemplos se ajusta una regresion logistica pequena que dice cuanto
importa cada criterio *para este DJ*; los pesos aprendidos reemplazan a los fijos (45/40/15).

Es una regresion logistica de tres variables entrenada con descenso de gradiente: para tan pocas variables y
ejemplos no hace falta mas, y el resultado se puede explicar (los pesos).
"""
from dataclasses import dataclass

import numpy as np

from .compatibility import DEFAULT_WEIGHTS, ScoringWeights

# Con menos valoraciones que estas no se aprende nada: se mantienen los pesos actuales.
MIN_SAMPLES = 10
# Un criterio nunca baja de este peso: aunque no haya aportado nada hasta ahora, no se ignora del todo.
MIN_WEIGHT = 0.02

EPOCHS = 1500
BASE_LEARNING_RATE = 0.4
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


def _sigmoid(x):
    """Sigmoide estable: no desborda exp() con valores muy negativos ni muy positivos (admite escalares y arreglos)."""
    return 0.5 * (1.0 + np.tanh(0.5 * x))


def predict_like_probability(weights: ScoringWeights, sample: FeedbackSample, bias: float = 0.0) -> float:
    """Probabilidad estimada de que la transicion le guste al DJ con estos pesos."""
    z = _SCALE * (weights.tempo * sample.tempo + weights.harmonic * sample.harmonic + weights.energy * sample.energy)
    return float(_sigmoid(z + bias))


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

    x = np.array([[s.tempo, s.harmonic, s.energy] for s in samples], dtype=float)
    y = np.array([1.0 if s.liked else 0.0 for s in samples])
    n = len(samples)

    # Se centra cada criterio (se le resta su media). Un criterio que vale casi lo mismo en todas las
    # valoraciones no distingue los "me gusta" de los "no me gusta"; sin centrar actuaria como un sesgo
    # extra y le quitaria peso a los criterios que si importan. El sesgo absorbe la tasa base de "me gusta".
    x = x - x.mean(axis=0)

    prior_vector = np.array([prior.tempo, prior.harmonic, prior.energy])
    w = prior_vector.copy()
    bias = 0.0

    # La penalizacion hacia `prior` es mas fuerte cuanto menos datos hay; el paso se acorta en la misma
    # proporcion para que el descenso converja en lugar de oscilar o divergir con pocos ejemplos.
    prior_strength = PRIOR_SAMPLES * REGULARIZATION / n
    learning_rate = BASE_LEARNING_RATE / (1.0 + prior_strength)

    for _ in range(EPOCHS):
        error = _sigmoid(_SCALE * (x @ w) + bias) - y
        gradient_w = _SCALE * (x.T @ error) / n + prior_strength * (w - prior_vector)
        w = w - learning_rate * gradient_w
        bias -= learning_rate * float(error.mean())

    clipped = np.maximum(MIN_WEIGHT, w)
    clipped = clipped / clipped.sum()
    tempo, harmonic = float(clipped[0]), float(clipped[1])
    # Se corrige el ultimo para que la suma sea exactamente 1 pese al redondeo de coma flotante.
    return ScoringWeights(tempo, harmonic, max(0.0, 1.0 - tempo - harmonic))


# --- Evaluacion ---------------------------------------------------------------------------------------------

EVALUATION_FOLDS = 5


@dataclass(frozen=True)
class Evaluation:
    """Cuanto acierta el modelo con valoraciones que no vio al entrenar (validacion cruzada).

    Cada acierto se mide prediciendo "me gusto" / "no me gusto" de transiciones apartadas del entrenamiento.
    `majority` es lo que acertaria quien dijera siempre la respuesta mas frecuente: si el modelo no la supera,
    no ha aprendido nada util.
    """

    learned: float
    default: float
    majority: float
    folds: int
    samples: int

    @property
    def improves_on_default(self) -> bool:
        return self.learned > self.default

    @property
    def beats_majority(self) -> bool:
        return self.learned > self.majority


def _score(weights: ScoringWeights, sample: FeedbackSample) -> float:
    return weights.tempo * sample.tempo + weights.harmonic * sample.harmonic + weights.energy * sample.energy


def _decision_threshold(weights: ScoringWeights, train: list[FeedbackSample]) -> float:
    """Puntuacion a partir de la cual se predice "me gusto": el punto medio entre las medias de cada clase."""
    liked = [_score(weights, s) for s in train if s.liked]
    disliked = [_score(weights, s) for s in train if not s.liked]
    return (sum(liked) / len(liked) + sum(disliked) / len(disliked)) / 2


def _accuracy(weights: ScoringWeights, train: list[FeedbackSample], test: list[FeedbackSample]) -> float:
    threshold = _decision_threshold(weights, train)
    hits = sum(1 for s in test if (_score(weights, s) > threshold) == s.liked)
    return hits / len(test)


def evaluate(samples: list[FeedbackSample], folds: int = EVALUATION_FOLDS) -> Evaluation | None:
    """Validacion cruzada de `train_weights` frente a los pesos por defecto; None si no hay datos suficientes.

    Las valoraciones se reparten por turnos entre `folds` grupos (la i-esima va al grupo i % folds); cada grupo se
    aparta una vez como prueba mientras se entrena con los demas. Es determinista. Los grupos cuyo entrenamiento
    no tenga las dos clases se saltan.
    """
    if folds < 2 or not has_enough_signal(samples):
        return None

    learned_hits = default_hits = majority_hits = tested = used = 0
    for fold in range(folds):
        test = [s for i, s in enumerate(samples) if i % folds == fold]
        train = [s for i, s in enumerate(samples) if i % folds != fold]
        if not test or not any(s.liked for s in train) or all(s.liked for s in train):
            continue

        learned = train_weights(train)
        learned_hits += _accuracy(learned, train, test) * len(test)
        default_hits += _accuracy(DEFAULT_WEIGHTS, train, test) * len(test)
        likes_in_train = sum(1 for s in train if s.liked)
        majority_liked = likes_in_train * 2 >= len(train)
        majority_hits += sum(1 for s in test if s.liked == majority_liked)
        tested += len(test)
        used += 1

    if tested == 0:
        return None
    return Evaluation(
        learned=learned_hits / tested, default=default_hits / tested, majority=majority_hits / tested,
        folds=used, samples=len(samples),
    )
