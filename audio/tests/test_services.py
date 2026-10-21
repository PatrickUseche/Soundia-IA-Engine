import io
import wave

import numpy as np
from django.test import SimpleTestCase

from audio.analysis import AudioTooShortError, SilentAudioError
from audio.services import (
    TARGET_SAMPLE_RATE,
    UnsupportedAudioError,
    analyze_file,
    analyze_signal,
    load_audio,
)
from audio.tests.signals import SR, chord, click_track, sine, to_wav_bytes


def cancion_de_prueba(bpm=120, seconds=40):
    """Pista sintetica: pulso a `bpm` sobre una progresion I-IV-V-I en C mayor."""
    acordes = np.concatenate([
        chord([0, 4, 7], 2), chord([5, 9, 0], 2), chord([7, 11, 2], 2), chord([0, 4, 7], 2),
    ])
    armonia = np.tile(acordes, int(seconds / 8) + 1)[: int(seconds * SR)]
    return click_track(bpm, seconds, amplitude=0.5) + armonia


def wav_estereo(y, sr):
    pcm = (np.clip(np.column_stack([y, y * 0.5]), -1, 1) * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue()


class LoadAudioTests(SimpleTestCase):
    def test_carga_un_wav_a_la_frecuencia_objetivo(self):
        y, sr = load_audio(io.BytesIO(to_wav_bytes(sine(440, 3))))

        self.assertEqual(sr, TARGET_SAMPLE_RATE)
        self.assertAlmostEqual(len(y) / sr, 3.0, delta=0.05)

    def test_remuestrea_un_audio_de_44100_hz(self):
        y, sr = load_audio(io.BytesIO(to_wav_bytes(sine(440, 3, sr=44100), sr=44100)))

        self.assertEqual(sr, TARGET_SAMPLE_RATE)
        self.assertAlmostEqual(len(y) / sr, 3.0, delta=0.05)

    def test_convierte_estereo_a_mono(self):
        y, _ = load_audio(io.BytesIO(wav_estereo(sine(440, 3), SR)))

        self.assertEqual(y.ndim, 1)

    def test_un_archivo_corrupto_lanza_unsupported_audio_error(self):
        with self.assertRaises(UnsupportedAudioError):
            load_audio(io.BytesIO(b'esto no es audio, son solo bytes cualquiera' * 10))

    def test_un_archivo_vacio_lanza_unsupported_audio_error(self):
        with self.assertRaises(UnsupportedAudioError):
            load_audio(io.BytesIO(b''))


class AnalyzeSignalTests(SimpleTestCase):
    def test_analiza_tempo_tonalidad_energia_y_cues(self):
        analisis = analyze_signal(cancion_de_prueba(bpm=120), SR)

        self.assertAlmostEqual(analisis.bpm, 120, delta=2)
        self.assertEqual(analisis.key, 'C major')
        self.assertEqual(analisis.camelot, '8B')
        self.assertGreater(analisis.energy, 0)
        self.assertLessEqual(analisis.energy, 1)
        self.assertAlmostEqual(analisis.duration, 40, delta=0.1)
        self.assertGreaterEqual(len(analisis.cue_points), 1)
        self.assertAlmostEqual(analisis.cue_points[0], 0, delta=0.2)

    def test_los_cues_vienen_ordenados(self):
        analisis = analyze_signal(cancion_de_prueba(bpm=128, seconds=60), SR)

        self.assertEqual(analisis.cue_points, sorted(analisis.cue_points))

    def test_un_audio_silencioso_lanza_error(self):
        with self.assertRaises(SilentAudioError):
            analyze_signal(np.zeros(SR * 10), SR)

    def test_un_audio_demasiado_corto_lanza_error(self):
        with self.assertRaises(AudioTooShortError):
            analyze_signal(sine(440, 1.0), SR)


class AnalyzeFileTests(SimpleTestCase):
    def test_analiza_un_wav_en_memoria_de_punta_a_punta(self):
        archivo = io.BytesIO(to_wav_bytes(cancion_de_prueba(bpm=124)))

        analisis = analyze_file(archivo)

        self.assertAlmostEqual(analisis.bpm, 124, delta=2)
        self.assertEqual(analisis.camelot, '8B')
