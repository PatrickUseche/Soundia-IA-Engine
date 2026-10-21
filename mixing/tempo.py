"""Beatmatching: cuanto hay que acelerar o frenar una pista para que su tempo coincida con otra."""
from dataclasses import dataclass

# Rango tipico del pitch fader de un reproductor de DJ: +-8 %.
MAX_PITCH_ADJUSTMENT = 0.08

# Una pista a la mitad o al doble de tempo tambien se puede mezclar (los golpes coinciden cada dos pulsos).
_MULTIPLIERS = (1.0, 2.0, 0.5)


@dataclass(frozen=True)
class TempoMatch:
    ratio: float  # factor a aplicar a la segunda pista para igualar el tempo de la primera
    # Factor con el que se reinterpreta el tempo de B antes de igualarlo: 1.0 = tal cual; 0.5 = B va al
    # doble de rapido y se mezcla contando la mitad de sus pulsos; 2.0 = B es lento y se cuentan el doble.
    multiplier: float
    feasible: bool  # el ajuste cabe en el rango del pitch fader

    @property
    def adjustment(self) -> float:
        """Desviacion respecto a no tocar el pitch (0.03 = +3 %)."""
        return abs(self.ratio - 1.0)


def match_tempo(bpm_a: float, bpm_b: float) -> TempoMatch:
    """Ajuste que necesita la pista B para sonar al tempo de la pista A.

    Prueba tambien B al doble y a la mitad de su tempo y se queda con la opcion que menos pitch pide.
    """
    if bpm_a <= 0 or bpm_b <= 0:
        raise ValueError("El BPM debe ser positivo.")

    best_multiplier = min(_MULTIPLIERS, key=lambda m: abs(bpm_a / (bpm_b * m) - 1.0))
    ratio = bpm_a / (bpm_b * best_multiplier)
    return TempoMatch(
        ratio=ratio,
        multiplier=best_multiplier,
        feasible=abs(ratio - 1.0) <= MAX_PITCH_ADJUSTMENT + 1e-9,
    )


def tempo_score(match: TempoMatch) -> float:
    """1.0 si no hace falta tocar el pitch, bajando linealmente hasta 0.0 en el limite del fader."""
    return max(0.0, 1.0 - match.adjustment / MAX_PITCH_ADJUSTMENT)
