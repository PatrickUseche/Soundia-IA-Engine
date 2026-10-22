"""Pesos de la puntuacion vigentes y registro de las valoraciones del DJ."""
from audio.models import Track

from .compatibility import DEFAULT_WEIGHTS, ScoringWeights, TrackInfo, compatibility
from .learning import FeedbackSample, evaluate, has_enough_signal, train_weights
from .models import LearnedWeights, TransitionFeedback

# Solo las valoraciones mas recientes entran al entrenamiento: asi el gusto del DJ puede ir cambiando.
MAX_TRAINING_SAMPLES = 2000
# Cuantas versiones de los pesos se guardan para poder volver a una anterior.
MAX_WEIGHT_VERSIONS = 50


def active_weights() -> LearnedWeights | None:
    """La version vigente de los pesos aprendidos, o None si no hay ninguna (se usan los de siempre)."""
    return LearnedWeights.objects.filter(active=True).order_by('-version', '-id').first()


def current_weights() -> ScoringWeights:
    """Los pesos aprendidos si ya hay suficientes valoraciones; si no, los de siempre."""
    learned = active_weights()
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

    latest = LearnedWeights.objects.order_by('-version').first()
    LearnedWeights.objects.filter(active=True).update(active=False)
    LearnedWeights.objects.create(
        tempo=weights.tempo, harmonic=weights.harmonic, energy=weights.energy, samples=len(samples),
        version=latest.version + 1 if latest else 1, active=True,
        accuracy=evaluation.learned if evaluation else None,
        default_accuracy=evaluation.default if evaluation else None,
    )
    _trim_history()
    return weights


def _trim_history() -> None:
    """Conserva solo las ultimas MAX_WEIGHT_VERSIONS versiones (nunca borra la vigente)."""
    keep = list(LearnedWeights.objects.order_by('-version').values_list('id', flat=True)[:MAX_WEIGHT_VERSIONS])
    LearnedWeights.objects.exclude(id__in=keep).exclude(active=True).delete()


def weight_history(limit: int = MAX_WEIGHT_VERSIONS) -> list[LearnedWeights]:
    """Las versiones guardadas de los pesos, de la mas nueva a la mas vieja."""
    return list(LearnedWeights.objects.order_by('-version')[:limit])


def restore_weights(version: int) -> LearnedWeights:
    """Vuelve a usar una version guardada de los pesos. Lanza LookupError si esa version ya no existe.

    Solo dura hasta la proxima valoracion: al reentrenar se parte siempre de las valoraciones, no de los pesos
    vigentes, y el resultado nuevo pasa a ser la version vigente.
    """
    chosen = LearnedWeights.objects.filter(version=version).first()
    if chosen is None:
        raise LookupError(f'No hay una version {version} de los pesos.')
    LearnedWeights.objects.filter(active=True).update(active=False)
    chosen.active = True
    chosen.save(update_fields=['active', 'updated_at'])
    return chosen


def rollback_weights() -> LearnedWeights:
    """Vuelve a la version anterior a la vigente. Lanza LookupError si no hay vigente o no hay una anterior."""
    current = active_weights()
    if current is None:
        raise LookupError('No hay pesos aprendidos vigentes.')
    previous = LearnedWeights.objects.filter(version__lt=current.version).order_by('-version').first()
    if previous is None:
        raise LookupError('No hay una version anterior a la vigente.')
    return restore_weights(previous.version)


def reset_weights(forget_ratings: bool = False) -> int:
    """Deja de usar los pesos aprendidos (vuelven los de siempre). Con `forget_ratings` ademas borra las
    valoraciones y las versiones guardadas, para empezar de cero; si no, la proxima valoracion volvera a
    entrenar con todas las que hay. Devuelve cuantas valoraciones se borraron."""
    LearnedWeights.objects.filter(active=True).update(active=False)
    if not forget_ratings:
        return 0
    deleted, _ = TransitionFeedback.objects.all().delete()
    LearnedWeights.objects.all().delete()
    return deleted


def feedback_count() -> int:
    return TransitionFeedback.objects.count()
