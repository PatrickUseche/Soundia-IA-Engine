"""Analisis de voz del final de una pista: separa la voz y mide hasta donde llega."""
from dataclasses import dataclass
from typing import Callable

import librosa
import numpy as np

from .separator import separate_vocals
from .vocals import VOCAL_WINDOW_SECONDS, frame_rms, last_vocal_end

# Frecuencia a la que trabaja Demucs.
SEPARATION_SAMPLE_RATE = 44100


@dataclass(frozen=True)
class VocalResult:
    window_start: float  # segundo de la pista en que empieza la ventana analizada
    last_end: float | None  # segundo en que acaba la ultima frase; None si no hay voz en la ventana


def analyze_last_vocals(source, duration: float,
                        separator: Callable[[np.ndarray], np.ndarray] = separate_vocals) -> VocalResult:
    """Separa la voz de los ultimos VOCAL_WINDOW_SECONDS de la pista (hasta `duration`) y mide donde acaba.

    `duration` es la de la pista guardada, para que los segundos coincidan con los del plan de mezcla.
    """
    window_start = max(duration - VOCAL_WINDOW_SECONDS, 0.0)
    audio, _ = librosa.load(
        source, sr=SEPARATION_SAMPLE_RATE, mono=False, offset=window_start, duration=duration - window_start,
    )
    if audio.ndim == 1:
        audio = np.stack([audio, audio])
    vocals = separator(audio)
    return VocalResult(
        window_start=window_start,
        last_end=last_vocal_end(frame_rms(vocals, SEPARATION_SAMPLE_RATE), window_start),
    )
