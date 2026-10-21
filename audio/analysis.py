"""Analisis de audio: tempo, tonalidad, energia y puntos de mezcla de una pista.

Todas las funciones reciben la senal ya cargada (`y`, mono, float) y su frecuencia de muestreo (`sr`),
asi se pueden probar con senales sinteticas sin leer archivos.
"""
from dataclasses import dataclass

import librosa
import numpy as np

from .camelot import camelot_code, key_name

# Un audio mas corto no tiene suficientes pulsos para estimar un tempo fiable.
MIN_SECONDS = 2.0
# Rango habitual de la musica de DJ; los errores de octava (mitad/doble) se pliegan dentro de el.
BPM_MIN = 70.0
BPM_MAX = 180.0
# Por debajo de esta amplitud maxima se considera silencio.
SILENCE_THRESHOLD = 1e-4


class AudioTooShortError(ValueError):
    """El audio dura menos de MIN_SECONDS."""


class SilentAudioError(ValueError):
    """El audio no contiene senal."""


def validate_signal(y: np.ndarray, sr: int) -> None:
    if len(y) / sr < MIN_SECONDS:
        raise AudioTooShortError(f"El audio dura menos de {MIN_SECONDS} segundos.")
    if float(np.max(np.abs(y))) < SILENCE_THRESHOLD:
        raise SilentAudioError("El audio es silencio; no hay nada que analizar.")


def fold_bpm(bpm: float) -> float:
    """Lleva un tempo al rango BPM_MIN-BPM_MAX duplicando o dividiendo a la mitad."""
    if bpm <= 0:
        raise ValueError("No se pudo estimar un tempo.")
    while bpm < BPM_MIN:
        bpm *= 2
    while bpm > BPM_MAX:
        bpm /= 2
    return bpm


def refine_bpm(coarse_bpm: float, beat_times: np.ndarray) -> float:
    """Afina un tempo aproximado midiendo el tiempo total entre el primer y el ultimo beat.

    El tempo de librosa tiene una resolucion de ~2.5 BPM; promediar sobre todos los beats la reduce a
    decimas, que es lo que necesita el beatmatching. Si el detector omitio algun beat, cada intervalo
    se cuenta como el numero entero de pulsos que cabe en el.
    """
    if len(beat_times) < 4:
        return coarse_bpm
    intervals = np.diff(beat_times)
    pulses = np.maximum(np.round(intervals / (60.0 / coarse_bpm)), 1)
    return float(60.0 * pulses.sum() / intervals.sum())


def detect_bpm(y: np.ndarray, sr: int) -> float:
    """Tempo estimado en pulsos por minuto, dentro del rango de DJ."""
    validate_signal(y, sr)
    onset_envelope = librosa.onset.onset_strength(y=y, sr=sr)
    coarse = float(np.atleast_1d(librosa.feature.tempo(onset_envelope=onset_envelope, sr=sr))[0])
    if coarse <= 0:
        raise ValueError("No se pudo estimar un tempo.")

    _, beat_times = librosa.beat.beat_track(
        onset_envelope=onset_envelope, sr=sr, start_bpm=coarse, units='time')
    return fold_bpm(refine_bpm(coarse, beat_times))


# Perfiles de Krumhansl-Schmuckler: cuanto "encaja" cada nota en una tonalidad mayor o menor con tonica C.
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


@dataclass(frozen=True)
class KeyEstimate:
    pitch_class: int  # 0 = C ... 11 = B
    mode: str  # 'major' o 'minor'
    confidence: float  # correlacion con el perfil ganador, entre 0 y 1

    @property
    def name(self) -> str:
        return key_name(self.pitch_class, self.mode)

    @property
    def camelot(self) -> str:
        return camelot_code(self.pitch_class, self.mode)


def detect_key(y: np.ndarray, sr: int) -> KeyEstimate:
    """Tonalidad estimada comparando el cromagrama medio con los perfiles de las 24 tonalidades."""
    validate_signal(y, sr)
    mean_chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    if np.std(mean_chroma) == 0:
        raise ValueError("No se pudo estimar la tonalidad: el audio no tiene contenido tonal.")

    best = None
    for pitch_class in range(12):
        for mode, profile in (('major', _MAJOR_PROFILE), ('minor', _MINOR_PROFILE)):
            correlation = float(np.corrcoef(mean_chroma, np.roll(profile, pitch_class))[0, 1])
            if best is None or correlation > best.confidence:
                best = KeyEstimate(pitch_class, mode, correlation)
    return KeyEstimate(best.pitch_class, best.mode, min(max(best.confidence, 0.0), 1.0))
