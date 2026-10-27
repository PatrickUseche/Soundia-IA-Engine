"""Modelo de que pista sigue: aprende de las veces que el DJ eligio una pista distinta de la que proponia la IA.

Cada vez que el Auto-DJ saca una pista de la cola del DJ en vez de la que habria propuesto, hay una comparacion real:
el DJ prefirio la *elegida* a la *propuesta*. Con esos pares se ajusta una regresion logistica sobre la diferencia de
rasgos entre las dos (como compatibles son en armonia, tempo y energia, si la energia sube, si son del mismo genero):

    P(el DJ prefiere A a B) = sigmoide(w . (rasgos(A) - rasgos(B)))

Los pesos `w` arrancan en 0 (la IA no cambia nada) y la regularizacion los mantiene cerca de 0 mientras haya pocos
casos. El resultado es un bono pequeno y acotado sobre la puntuacion de compatibilidad: solo desempata pistas parecidas.

Solo cuenta lo que el DJ elige; las veces que acepta la propuesta no dan un par (no hay nada que comparar) y solo se
cuentan. Por eso la evaluacion mide una cosa concreta: dejando cada correccion fuera, si el modelo habria puesto la
elegida por encima de la propuesta. Las reglas, por construccion, fallan todas esas (la propuesta *era* su mejor).
"""
from dataclasses import dataclass

import numpy as np
from django.db.models import Count, Max, Sum

from .compatibility import TrackInfo, energy_score, harmonic_score
from .models import AutoDjChoice
from .tempo import match_tempo, tempo_score

FEATURES = ('harmonic', 'tempo', 'energy', 'energyUp', 'sameGenre')

# Correcciones necesarias antes de evaluar: con menos, acertar mas de la mitad puede ser casualidad.
MIN_CORRECTIONS = 15
# Solo las mas recientes (el gusto cambia) y la evaluacion cuesta O(300^2 * EPOCHS) como mucho.
MAX_CORRECTIONS = 300
# Para usar el modelo debe acertar al menos esta fraccion de las correcciones dejadas fuera (0.5 = azar).
MIN_ACCURACY = 0.6
# Mas de esto sobre una puntuacion de 0-1 haria que el modelo mande sobre las reglas en vez de desempatar.
MAX_BONUS = 0.15

EPOCHS = 300
LEARNING_RATE = 1.0
REGULARIZATION = 0.5


def pair_features(a: TrackInfo, b: TrackInfo) -> list[float]:
    """Como es la transicion de A a B, en el orden de FEATURES. Todos los rasgos estan en [0, 1]."""
    return [
        harmonic_score(a.camelot, b.camelot),
        tempo_score(match_tempo(a.bpm, b.bpm)),
        energy_score(a.energy, b.energy),
        max(b.energy - a.energy, 0.0),
        1.0 if a.genre and a.genre == b.genre else 0.0,
    ]


def _sigmoid(x):
    return 0.5 * (1.0 + np.tanh(0.5 * x))


def fit(differences: np.ndarray) -> np.ndarray:
    """Pesos a partir de las diferencias (elegida - propuesta), una fila por correccion. O(n * EPOCHS).

    Sin correcciones (o con pocas) los pesos se quedan cerca de 0 por la regularizacion.
    """
    weights = np.zeros(len(FEATURES))
    if len(differences) == 0:
        return weights
    for _ in range(EPOCHS):
        probability_wrong = _sigmoid(-(differences @ weights))
        gradient = -(differences.T @ probability_wrong) / len(differences) + REGULARIZATION * weights
        weights -= LEARNING_RATE * gradient
    return weights


def bonuses(weights: np.ndarray, rows: list[list[float]]) -> list[float]:
    """Cuanto sube o baja la puntuacion de cada candidata segun lo aprendido, acotado a +-MAX_BONUS.

    El modelo solo sabe comparar (A mejor que B), asi que el bono se centra en la media de las candidatas: lo que importa
    es cuanto se aparta cada una de las demas, no el valor absoluto, que un tope haria igual para todas.
    """
    raw = np.array([float(np.dot(weights, row)) for row in rows])
    return [float(value) for value in np.clip(raw - raw.mean(), -MAX_BONUS, MAX_BONUS)] if len(raw) else []


def evaluate(differences: np.ndarray) -> dict:
    """Dejando cada correccion fuera, en cuantas habria puesto el modelo la pista elegida por encima de la propuesta.

    Las reglas aciertan 0 de ellas por construccion. Coste O(n^2 * EPOCHS) con n <= MAX_CORRECTIONS.
    """
    hits = 0
    for index in range(len(differences)):
        others = np.delete(differences, index, axis=0)
        if float(differences[index] @ fit(others)) > 0:
            hits += 1
    accuracy = hits / len(differences) if len(differences) else None
    return {
        'evaluated': len(differences),
        'accuracy': round(accuracy, 3) if accuracy is not None else None,
        'rulesAccuracy': 0.0 if len(differences) else None,
        'wins': bool(len(differences) >= MIN_CORRECTIONS and accuracy is not None and accuracy >= MIN_ACCURACY),
    }


def record_choice(origin, chosen, recommended=None) -> AutoDjChoice:
    """Guarda lo que el DJ eligio tras `origin` y lo que la IA habria propuesto (modelos `Track`).

    Los rasgos se calculan aqui, nunca vienen del cliente, y se guardan junto a la eleccion: el DJ borra pistas al
    terminar una sesion y las elecciones no deben perderse con ellas.
    """
    a = TrackInfo.from_model(origin)
    rejected = None
    if recommended is not None and recommended.pk != chosen.pk:
        rejected = pair_features(a, TrackInfo.from_model(recommended))
    return AutoDjChoice.objects.create(
        from_track=origin, chosen_track=chosen, recommended_track=recommended,
        chosen_features=pair_features(a, TrackInfo.from_model(chosen)), rejected_features=rejected,
    )


@dataclass(frozen=True)
class _Trained:
    signature: tuple
    choices: int
    corrections: int
    weights: np.ndarray | None
    evaluation: dict | None


_cache: _Trained | None = None


def reset_cache() -> None:
    global _cache
    _cache = None


def _trained() -> _Trained:
    """Pesos y evaluacion, recalculados solo cuando cambian las elecciones guardadas (cache por proceso)."""
    global _cache
    stats = AutoDjChoice.objects.aggregate(
        n=Count('id'), last=Max('id'), total=Sum('id'), newest=Max('created_at'))
    signature = (stats['n'], stats['last'], stats['total'], stats['newest'])
    if _cache is not None and _cache.signature == signature:
        return _cache
    rows = list(AutoDjChoice.objects.exclude(rejected_features=None).order_by('-id')[:MAX_CORRECTIONS])
    differences = np.array([np.array(r.chosen_features) - np.array(r.rejected_features) for r in rows])
    corrections = len(rows)
    if corrections < MIN_CORRECTIONS:
        _cache = _Trained(signature, stats['n'], corrections, None, None)
    else:
        _cache = _Trained(signature, stats['n'], corrections, fit(differences), evaluate(differences))
    return _cache


def learned_weights(enabled: bool) -> np.ndarray | None:
    """Los pesos a aplicar al ordenar, o None si el modelo esta apagado o todavia no gana."""
    if not enabled:
        return None
    trained = _trained()
    if trained.weights is None or trained.evaluation is None or not trained.evaluation['wins']:
        return None
    return trained.weights


def status(enabled: bool) -> dict:
    trained = _trained()
    result = {
        'choices': trained.choices, 'corrections': trained.corrections, 'required': MIN_CORRECTIONS,
        'ready': trained.evaluation is not None,
    }
    if trained.evaluation is not None:
        result['evaluation'] = trained.evaluation
        result['inUse'] = bool(enabled and trained.evaluation['wins'])
    return result
