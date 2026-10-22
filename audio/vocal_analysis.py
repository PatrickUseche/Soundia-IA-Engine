"""Analisis de voz de los extremos de una pista: separa la voz y mide donde empieza y hasta donde llega."""
import os
from dataclasses import dataclass
from typing import Callable

import librosa
import numpy as np

from .separator import separate_vocals
from .vocals import VOCAL_START_WINDOW_SECONDS, VOCAL_WINDOW_SECONDS, first_vocal_start, frame_rms, last_vocal_end

# Frecuencia a la que trabaja Demucs.
SEPARATION_SAMPLE_RATE = 44100


@dataclass(frozen=True)
class VocalResult:
    window_start: float  # segundo de la pista en que empieza la ventana analizada
    last_end: float | None  # segundo en que acaba la ultima frase; None si no hay voz en la ventana
    first_start: float | None = None  # segundo en que empieza la primera frase; None si no se analizo o no hay voz


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


def start_analysis_enabled() -> bool:
    """Si ademas del final se analiza el inicio de la pista. Viene APAGADO por defecto: duplica el tiempo del
    analisis y no se pudo medir su pico de memoria en un equipo modesto (3,4 GB de RAM), donde el sistema llego a
    quedarse sin memoria. Se enciende con VOCAL_ANALYSIS_START=on."""
    return os.environ.get('VOCAL_ANALYSIS_START', 'off').strip().lower() == 'on'


def analyze_first_vocals(source, duration: float,
                         separator: Callable[[np.ndarray], np.ndarray] = separate_vocals) -> float | None:
    """Separa la voz de los primeros VOCAL_START_WINDOW_SECONDS de la pista y mide donde empieza (en segundos de
    la pista); None si no hay voz en esa ventana."""
    length = min(VOCAL_START_WINDOW_SECONDS, duration)
    audio, _ = librosa.load(source, sr=SEPARATION_SAMPLE_RATE, mono=False, offset=0.0, duration=length)
    if audio.ndim == 1:
        audio = np.stack([audio, audio])
    vocals = separator(audio)
    return first_vocal_start(frame_rms(vocals, SEPARATION_SAMPLE_RATE))


def analyze_vocals(source, duration: float, with_start: bool | None = None,
                   separator: Callable[[np.ndarray], np.ndarray] = separate_vocals) -> VocalResult:
    """Analiza el final de la pista y, si se pide, tambien el inicio. Las dos ventanas se separan una despues de
    otra (nunca a la vez), asi el pico de memoria deberia ser el de una sola. `with_start` por defecto sigue
    VOCAL_ANALYSIS_START."""
    if with_start is None:
        with_start = start_analysis_enabled()
    last = analyze_last_vocals(source, duration, separator)
    first_start = analyze_first_vocals(source, duration, separator) if with_start else None
    return VocalResult(window_start=last.window_start, last_end=last.last_end, first_start=first_start)
