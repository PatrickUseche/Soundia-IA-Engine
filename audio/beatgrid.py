"""Rejilla de pulsos de una pista: tempo preciso, donde cae cada golpe y cual es el primer tiempo del compas.

Es lo que hace falta para mezclar "a compas": para que los golpes de dos pistas coincidan no basta con igualar el
tempo, hay que saber en que instante exacto suena cada golpe. Se asume tempo constante (lo habitual en musica
de baile: la deriva medida en canciones reales es de unos pocos milisegundos por minuto).

El metodo, en tres pasos:
1. Tempo y fase: la envolvente de ataques se "pliega" sobre el periodo de cada tempo candidato; con el tempo
   correcto todos los golpes caen en la misma fase y el histograma queda muy afilado.
2. Afinado: el detector de ataques va unos milisegundos retrasado, asi que se corrige la fase con la posicion
   real de la subida de energia en la senal (dominio del tiempo).
3. Primer tiempo del compas: de los 4 pulsos de un compas, el del bombo mas fuerte.
"""
from dataclasses import dataclass

import librosa
import numpy as np
from scipy import signal as scipy_signal

BEATS_PER_BAR = 4

# Resolucion temporal de la envolvente de ataques (5.8 ms a 22 kHz) y tamano de su ventana de analisis.
HOP_LENGTH = 128
N_FFT = 1024
# La envolvente se calcula por tramos para no pedir cientos de MB en pistas largas (el STFT con este paso es
# muy denso). Cada tramo lleva un margen a cada lado para que el borde no distorsione.
CHUNK_FRAMES = 10240
MARGIN_FRAMES = 172

# Busqueda del tempo alrededor del BPM de partida.
BPM_SEARCH_SPAN = 0.6
BPM_SEARCH_STEP = 0.01
COARSE_BINS = 64
FINE_BINS = 400
# Suavizado (en bins) del histograma de fase para localizar su pico.
PHASE_SMOOTHING_BINS = 3.0

# Afinado de la fase con la subida real de energia.
ATTACK_WINDOW_SECONDS = 0.06
ATTACK_ENVELOPE_CUTOFF_HZ = 60
MAX_ATTACK_CORRECTION_SECONDS = 0.04

# Deteccion del primer tiempo del compas por la energia de graves (bombo) de cada pulso.
KICK_CUTOFF_HZ = 150
KICK_PRE_SECONDS = 0.01
KICK_WINDOW_SECONDS = 0.08

# Fuerza minima del pulso para fiarse de la rejilla (fraccion de la energia de ataques que cae en los golpes).
# Medido: ruido y tonos puros dan < 0.01; la musica real, 0.13-0.16; un pulso sintetico limpio, 0.87.
MIN_BEAT_STRENGTH = 0.05
# Ancho de la franja alrededor del pico que se considera "en el golpe", para medir su fuerza.
BEAT_STRENGTH_WINDOW_SECONDS = 0.05


@dataclass(frozen=True)
class BeatGrid:
    bpm: float
    offset: float  # segundo del primer pulso (siempre dentro del primer periodo)
    downbeat_offset: float  # segundo del primer "primer tiempo" de compas (dentro del primer compas)
    beat_strength: float  # 0-1: cuanto se concentran los ataques en los pulsos; bajo = sin ritmo claro
    downbeat_confidence: float  # 0-1: cuanto destaca el primer tiempo sobre los otros tres pulsos


def _onset_envelope(y: np.ndarray, sr: int) -> np.ndarray:
    """Fuerza de ataques por frames de HOP_LENGTH muestras; el frame i esta centrado en la muestra i * HOP_LENGTH."""
    chunk = CHUNK_FRAMES * HOP_LENGTH
    margin = MARGIN_FRAMES * HOP_LENGTH
    parts = []
    for start in range(0, len(y), chunk):
        a = max(start - margin, 0)
        b = min(start + chunk + margin, len(y))
        envelope = librosa.onset.onset_strength(y=y[a:b], sr=sr, hop_length=HOP_LENGTH, n_fft=N_FFT)
        first = (start - a) // HOP_LENGTH
        parts.append(envelope[first:first + CHUNK_FRAMES])
    return np.concatenate(parts)


def _fold(envelope: np.ndarray, frame_seconds: float, bpm: float, bins: int) -> tuple[np.ndarray, float]:
    """Histograma de la envolvente plegada sobre el periodo de `bpm`: energia de ataques por fase."""
    period = 60.0 / bpm
    times = np.arange(len(envelope)) * frame_seconds
    index = ((times % period) / period * bins).astype(int) % bins
    return np.bincount(index, weights=envelope, minlength=bins), period


def _refine_bpm(envelope: np.ndarray, frame_seconds: float, bpm_hint: float) -> float:
    """El tempo candidato cuyo histograma de fase queda mas afilado (mayor varianza)."""
    candidates = np.arange(bpm_hint - BPM_SEARCH_SPAN, bpm_hint + BPM_SEARCH_SPAN + 1e-9, BPM_SEARCH_STEP)
    scores = [float(np.var(_fold(envelope, frame_seconds, bpm, COARSE_BINS)[0])) for bpm in candidates]
    return float(candidates[int(np.argmax(scores))])


def _smooth_circular(histogram: np.ndarray) -> np.ndarray:
    radius = int(PHASE_SMOOTHING_BINS * 3)
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / PHASE_SMOOTHING_BINS) ** 2)
    padded = np.zeros(len(histogram))
    padded[:len(kernel)] = kernel
    smoothed = np.real(np.fft.ifft(np.fft.fft(histogram) * np.fft.fft(padded)))
    return np.roll(smoothed, -radius)


def _attack_correction(y: np.ndarray, sr: int, beat_times: np.ndarray) -> float:
    """Segundos que hay que mover la rejilla para que caiga sobre el inicio real de los golpes (mediana)."""
    sos = scipy_signal.butter(2, ATTACK_ENVELOPE_CUTOFF_HZ, 'low', fs=sr, output='sos')
    envelope = scipy_signal.sosfiltfilt(sos, np.abs(y))
    slope = np.diff(envelope, prepend=envelope[0])
    half = int(ATTACK_WINDOW_SECONDS * sr)
    centers = (beat_times * sr).astype(int)
    centers = centers[(centers - half >= 0) & (centers + half < len(slope))]
    if len(centers) == 0:
        return 0.0
    windows = slope[centers[:, None] + np.arange(-half, half)[None, :]]
    offsets = (np.argmax(windows, axis=1) - half) / sr
    return float(np.clip(np.median(offsets), -MAX_ATTACK_CORRECTION_SECONDS, MAX_ATTACK_CORRECTION_SECONDS))


def _downbeat(y: np.ndarray, sr: int, first_beat: float, period: float) -> tuple[int, float]:
    """(posicion 0-3 del primer tiempo entre los pulsos del compas, confianza 0-1) segun la energia de graves."""
    sos = scipy_signal.butter(2, KICK_CUTOFF_HZ, 'low', fs=sr, output='sos')
    low = scipy_signal.sosfilt(sos, y)
    pre = int(KICK_PRE_SECONDS * sr)
    length = int((KICK_PRE_SECONDS + KICK_WINDOW_SECONDS) * sr)
    count = int((len(y) / sr - first_beat) / period)
    starts = ((first_beat + np.arange(count) * period) * sr).astype(int) - pre
    valid = (starts >= 0) & (starts + length <= len(low))
    if valid.sum() < 2 * BEATS_PER_BAR:
        return 0, 0.0
    beat_index = np.arange(count)[valid]
    windows = low[starts[valid][:, None] + np.arange(length)[None, :]]
    accent = np.sqrt(np.mean(np.square(windows), axis=1))

    by_position = np.array([
        accent[beat_index % BEATS_PER_BAR == position].mean() if np.any(beat_index % BEATS_PER_BAR == position) else 0.0
        for position in range(BEATS_PER_BAR)
    ])
    best = int(np.argmax(by_position))
    others = np.delete(by_position, best).mean()
    if by_position[best] <= 0:
        return 0, 0.0
    return best, float(np.clip((by_position[best] - others) / by_position[best], 0.0, 1.0))


def estimate_grid(y: np.ndarray, sr: int, bpm_hint: float) -> BeatGrid:
    """Rejilla de pulsos de una senal mono. `bpm_hint` es un tempo aproximado (el de la deteccion normal)."""
    envelope = np.maximum(_onset_envelope(y, sr), 0.0)
    peak = float(envelope.max()) if len(envelope) else 0.0
    if peak <= 0:
        return BeatGrid(bpm=bpm_hint, offset=0.0, downbeat_offset=0.0, beat_strength=0.0, downbeat_confidence=0.0)
    envelope = envelope / peak
    frame_seconds = HOP_LENGTH / sr

    bpm = _refine_bpm(envelope, frame_seconds, bpm_hint)
    histogram, period = _fold(envelope, frame_seconds, bpm, FINE_BINS)
    smoothed = _smooth_circular(histogram)
    phase = (int(np.argmax(smoothed)) + 0.5) / FINE_BINS * period

    # Fuerza: fraccion de la energia de ataques dentro de la franja del golpe, descontando lo que cabria por azar.
    window_bins = max(int(BEAT_STRENGTH_WINDOW_SECONDS / period * FINE_BINS), 1)
    peak_bin = int(np.argmax(smoothed))
    in_window = np.take(histogram, np.arange(peak_bin - window_bins // 2, peak_bin + window_bins // 2 + 1), mode='wrap')
    chance = (window_bins + 1) / FINE_BINS
    strength = float(np.clip((in_window.sum() / max(histogram.sum(), 1e-9) - chance) / (1 - chance), 0.0, 1.0))

    beat_times = phase + np.arange(int((len(y) / sr - phase) / period)) * period
    corrected = phase + _attack_correction(y, sr, beat_times)

    position, confidence = _downbeat(y, sr, corrected, period)
    downbeat = (corrected + position * period) % (BEATS_PER_BAR * period)
    return BeatGrid(
        bpm=round(bpm, 3),
        offset=round(downbeat % period, 4),
        downbeat_offset=round(downbeat, 4),
        beat_strength=round(strength, 3),
        downbeat_confidence=round(confidence, 3),
    )
