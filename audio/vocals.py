"""Donde hay voz en una pista, para no cortar la letra al mezclar.

Solo se mira el final de la pista (la ventana en la que sale la mezcla): se separa la voz con un modelo de
IA (ver `separator.py`) y aqui se convierte la pista de voz en "hasta donde llega la ultima frase". Estas
funciones trabajan con la senal ya separada, asi se prueban con senales sinteticas.
"""
import numpy as np

# Duracion de cada frame en que se mide la energia de la voz.
FRAME_SECONDS = 0.5
# Segundos del final de la pista que se analizan.
VOCAL_WINDOW_SECONDS = 60.0
# Un frame tiene voz si supera esta fraccion de la energia de la voz en la ventana (percentil 90)...
RELATIVE_THRESHOLD = 0.15
# ...y, en cualquier caso, este minimo absoluto: la separacion deja restos casi nulos donde no hay voz.
ABSOLUTE_FLOOR = 0.003
# Una pausa de hasta estos segundos entre frases (una respiracion) no corta la estrofa.
MAX_GAP_SECONDS = 2.5
# Un sonido de voz mas corto que esto es un resto de la separacion, no una frase.
MIN_SEGMENT_SECONDS = 1.0


def frame_rms(signal: np.ndarray, sr: int) -> np.ndarray:
    """Energia (RMS) de la senal por frames de FRAME_SECONDS; si es estereo se promedian los canales."""
    if signal.ndim > 1:
        signal = signal.mean(axis=0)
    size = int(FRAME_SECONDS * sr)
    count = len(signal) // size
    if count == 0:
        return np.array([])
    frames = signal[:count * size].reshape(count, size)
    return np.sqrt(np.mean(np.square(frames), axis=1))


def vocal_segments(rms: np.ndarray) -> list[tuple[float, float]]:
    """Tramos (inicio, fin) en segundos, relativos al inicio de la ventana, en que suena una voz."""
    if len(rms) == 0:
        return []
    threshold = max(ABSOLUTE_FLOOR, RELATIVE_THRESHOLD * float(np.percentile(rms, 90)))
    active = rms >= threshold

    runs: list[list[float]] = []
    start = None
    for index, is_active in enumerate(active):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            runs.append([start * FRAME_SECONDS, index * FRAME_SECONDS])
            start = None
    if start is not None:
        runs.append([start * FRAME_SECONDS, len(active) * FRAME_SECONDS])

    merged: list[list[float]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= MAX_GAP_SECONDS:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    return [(begin, end) for begin, end in merged if end - begin >= MIN_SEGMENT_SECONDS]


def last_vocal_end(rms: np.ndarray, window_start: float) -> float | None:
    """Segundo de la pista en que acaba la ultima frase cantada, o None si no hay voz en la ventana.

    `window_start` es el segundo de la pista en que empieza la ventana analizada.
    """
    segments = vocal_segments(rms)
    if not segments:
        return None
    return round(window_start + segments[-1][1], 3)
