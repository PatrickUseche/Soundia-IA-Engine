"""Carga de archivos de audio y analisis completo de una pista."""
import logging
from dataclasses import dataclass

import librosa
import numpy as np

from .analysis import compute_energy, detect_bpm, detect_key, find_cue_points
from .beatgrid import MIN_BEAT_STRENGTH, MIN_DOWNBEAT_CONFIDENCE, estimate_grid

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
    # Rejilla de pulsos (ver beatgrid.py); None si la pista no tiene un ritmo claro.
    grid_offset: float | None = None  # segundo del primer pulso
    grid_downbeat: float | None = None  # segundo del primer tiempo del compas
    grid_confidence: float | None = None  # 0-1: seguridad de que ese sea el primer tiempo


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
    grid = estimate_grid(y, sr, bpm)
    has_grid = grid.beat_strength >= MIN_BEAT_STRENGTH
    if has_grid:
        bpm = grid.bpm  # tempo afinado: el de la deteccion normal solo acierta a decimas
    # Los compases se cuentan desde el primer tiempo si se esta seguro de cual es; si no, desde el primer pulso.
    first_beat = None
    if has_grid:
        first_beat = grid.downbeat_offset if grid.downbeat_confidence >= MIN_DOWNBEAT_CONFIDENCE else grid.offset
    key = detect_key(y, sr)
    return TrackAnalysis(
        duration=round(len(y) / sr, 3),
        bpm=round(bpm, 3),
        key=key.name,
        camelot=key.camelot,
        key_confidence=round(key.confidence, 3),
        energy=round(compute_energy(y, sr), 3),
        cue_points=find_cue_points(y, sr, bpm, first_beat=first_beat),
        grid_offset=grid.offset if has_grid else None,
        grid_downbeat=grid.downbeat_offset if has_grid else None,
        grid_confidence=grid.downbeat_confidence if has_grid else None,
    )


def analyze_file(source) -> TrackAnalysis:
    y, sr = load_audio(source)
    return analyze_signal(y, sr)
