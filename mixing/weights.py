"""Pesos de la puntuacion vigentes y registro de las valoraciones del DJ."""
from audio.models import Track

from .compatibility import DEFAULT_WEIGHTS, ScoringWeights, TrackInfo, compatibility
from .learning import FeedbackSample, evaluate, has_enough_signal, train_weights
from .models import LearnedWeights, TransitionFeedback

# Solo las valoraciones mas recientes entran al entrenamiento: asi el gusto del DJ puede ir cambiando.
MAX_TRAINING_SAMPLES = 2000


def current_weights() -> ScoringWeights:
    """Los pesos aprendidos si ya hay suficientes valoraciones; si no, los de siempre."""
    learned = LearnedWeights.objects.first()
    if learned is None:
        return DEFAULT_WEIGHTS
    return ScoringWeights(learned.tempo, learned.harmonic, learned.energy)


def record_feedback(from_track: Track, to_track: Track, liked: bool) -> ScoringWeights:
    """Guarda la valoracion de una transicion y reentrena los pesos; devuelve los pesos vigentes.

    Las puntuaciones se guardan tal como eran al valorar, y siempre se reentrena desde los pesos por defecto
    (no desde los ya aprendidos) para que el resultado dependa solo de las valoraciones, no del orden en que llegaron.
    """
    result = compatibility(TrackInfo.from_model(from_track), TrackInfo.from_model(to_track))
    TransitionFeedback.objects.create(
        from_track=from_track, to_track=to_track,
        tempo=result.tempo, harmonic=result.harmonic, energy=result.energy, liked=liked,
    )

    samples = [
        FeedbackSample(f.tempo, f.harmonic, f.energy, f.liked)
        for f in TransitionFeedback.objects.all()[:MAX_TRAINING_SAMPLES]
    ]
    if not has_enough_signal(samples):
        return current_weights()

    weights = train_weights(samples)
    evaluation = evaluate(samples)
    # Si con valoraciones apartadas los pesos nuevos aciertan menos que los de siempre, no se adoptan: mas vale
    # seguir con los vigentes que sustituirlos por algo que, con estos datos, predice peor.
    if evaluation is not None and evaluation.learned < evaluation.default:
        return current_weights()

    previous = LearnedWeights.objects.first()
    LearnedWeights.objects.all().delete()
    LearnedWeights.objects.create(
        tempo=weights.tempo, harmonic=weights.harmonic, energy=weights.energy, samples=len(samples),
        version=previous.version + 1 if previous else 1,
        accuracy=evaluation.learned if evaluation else None,
        default_accuracy=evaluation.default if evaluation else None,
    )
    return weights


def feedback_count() -> int:
    return TransitionFeedback.objects.count()
