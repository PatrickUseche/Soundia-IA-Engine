"""Carga de archivos de audio y analisis completo de una pista."""
import logging
from dataclasses import dataclass

import librosa
import numpy as np

from .analysis import compute_energy, detect_bpm, detect_key, find_cue_points

logger = logging.getLogger(__name__)

# Todo el analisis trabaja a esta frecuencia de muestreo: es suficiente para tempo y tonalidad
# y reduce mucho el costo frente a los 44.1 kHz habituales.
TARGET_SAMPLE_RATE = 22050
# Solo se analizan los primeros minutos; en una pista mas larga el resto no cambia el resultado.
MAX_ANALYSIS_SECONDS = 600


class UnsupportedAudioError(ValueError):
    """El archivo no se pudo leer como audio."""


@dataclass(frozen=True)
class TrackAnalysis:
    duration: float  # segundos analizados (maximo MAX_ANALYSIS_SECONDS)
    bpm: float
    key: str
    camelot: str
    key_confidence: float
    energy: float
    cue_points: list[float]


def load_audio(source) -> tuple[np.ndarray, int]:
    """Lee un archivo (ruta o archivo abierto) como senal mono a TARGET_SAMPLE_RATE."""
    try:
        y, sr = librosa.load(source, sr=TARGET_SAMPLE_RATE, mono=True, duration=MAX_ANALYSIS_SECONDS)
    except Exception as error:  # noqa: BLE001 - los decodificadores lanzan muchos tipos de error distintos
        logger.warning("No se pudo leer el audio: %s", error)
        raise UnsupportedAudioError(
            "No se pudo leer el archivo de audio. Formatos soportados: WAV, FLAC, OGG y MP3."
        ) from error
    return y, int(sr)


def analyze_signal(y: np.ndarray, sr: int) -> TrackAnalysis:
    """Calcula tempo, tonalidad, energia y puntos de mezcla de una senal ya cargada."""
    bpm = detect_bpm(y, sr)
    key = detect_key(y, sr)
    return TrackAnalysis(
        duration=round(len(y) / sr, 3),
        bpm=round(bpm, 2),
        key=key.name,
        camelot=key.camelot,
        key_confidence=round(key.confidence, 3),
        energy=round(compute_energy(y, sr), 3),
        cue_points=find_cue_points(y, sr, bpm),
    )


def analyze_file(source) -> TrackAnalysis:
    y, sr = load_audio(source)
    return analyze_signal(y, sr)
