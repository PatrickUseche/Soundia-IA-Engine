"""Cuando mezclar: el Auto-DJ aprende de las veces que el DJ pidio mezclar antes de lo planeado."""
from statistics import median

from audio.models import Track

from .models import MixTimingFeedback

# Casos necesarios antes de fiarse de ellos: con uno o dos, el DJ pudo tener un motivo puntual.
MIN_TIMING_SAMPLES = 3
# Solo cuentan los casos mas recientes, para que el motor siga los gustos actuales del DJ.
RECENT_TIMING_SAMPLES = 20
# Tope del adelanto: no tiene sentido mezclar dos minutos antes por una racha de impaciencia.
MAX_ADVANCE_SECONDS = 120.0


def advance_from(advances: list[float]) -> float:
    """Segundos que se adelanta la salida: la mediana de lo que el DJ adelanto en cada caso (0 si pidio mezclar
    despues). La mediana evita que un caso extremo mueva el resultado."""
    if len(advances) < MIN_TIMING_SAMPLES:
        return 0.0
    return round(min(median(max(value, 0.0) for value in advances), MAX_ADVANCE_SECONDS), 3)


def learned_advance() -> float:
    recent = MixTimingFeedback.objects.all()[:RECENT_TIMING_SAMPLES]
    return advance_from([row.planned_mix_out - row.actual_mix_out for row in recent])


def timing_count() -> int:
    return MixTimingFeedback.objects.count()


def reset_timing() -> int:
    """Olvida todo lo aprendido sobre cuando mezclar (el Auto-DJ vuelve a mezclar en el punto planeado)."""
    deleted, _ = MixTimingFeedback.objects.all().delete()
    return deleted


def record_mix_timing(origin: Track, destination: Track, planned: float, actual: float) -> float:
    """Guarda el caso y devuelve el adelanto vigente con el."""
    MixTimingFeedback.objects.create(
        from_track=origin, to_track=destination, planned_mix_out=planned, actual_mix_out=actual,
    )
    return learned_advance()
