"""Senales de audio sinteticas con propiedades conocidas, para probar el analisis sin archivos reales."""
import io
import wave

import numpy as np

SR = 22050


def _time(seconds, sr=SR):
    return np.arange(int(seconds * sr)) / sr


def click_track(bpm, seconds, sr=SR, amplitude=0.9, first_beat=0.0):
    """Pulsos percusivos (rafagas de seno con caida exponencial) exactamente a `bpm`."""
    y = np.zeros(int(seconds * sr))
    burst_t = _time(0.05, sr)
    burst = np.sin(2 * np.pi * 1000 * burst_t) * np.exp(-burst_t * 90)
    period = 60.0 / bpm
    beat = first_beat
    while beat < seconds - 0.06:
        start = int(beat * sr)
        y[start:start + len(burst)] += burst * amplitude
        beat += period
    return y


def chord(pitch_classes, seconds, sr=SR, octave=4, amplitude=0.3):
    """Acorde sostenido con las clases de altura dadas (0 = C ... 11 = B), con un armonico suave."""
    t = _time(seconds, sr)
    y = np.zeros_like(t)
    for pc in pitch_classes:
        midi = 12 * (octave + 1) + pc
        freq = 440.0 * 2 ** ((midi - 69) / 12)
        y += np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * 2 * freq * t)
    return amplitude * y / max(len(pitch_classes), 1)


def major_triad(root, seconds, **kwargs):
    return chord([root % 12, (root + 4) % 12, (root + 7) % 12], seconds, **kwargs)


def minor_triad(root, seconds, **kwargs):
    return chord([root % 12, (root + 3) % 12, (root + 7) % 12], seconds, **kwargs)


def sine(freq, seconds, sr=SR, amplitude=1.0):
    return amplitude * np.sin(2 * np.pi * freq * _time(seconds, sr))


def to_wav_bytes(y, sr=SR):
    """Serializa una senal mono a un WAV PCM de 16 bits en memoria (como un archivo subido)."""
    pcm = (np.clip(y, -1, 1) * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue()
