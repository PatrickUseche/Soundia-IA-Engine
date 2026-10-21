from django.test import SimpleTestCase

from audio.analysis import detect_bpm
from audio.tests.signals import SR, click_track, sine


class DetectBpmTests(SimpleTestCase):
    def assertBpmCerca(self, bpm_real, tolerancia=2.0):
        y = click_track(bpm_real, seconds=20)

        detectado = detect_bpm(y, SR)

        self.assertAlmostEqual(detectado, bpm_real, delta=tolerancia)

    def test_detecta_120_bpm(self):
        self.assertBpmCerca(120)

    def test_detecta_128_bpm(self):
        self.assertBpmCerca(128)

    def test_detecta_100_bpm(self):
        self.assertBpmCerca(100)

    def test_detecta_140_bpm(self):
        self.assertBpmCerca(140)

    def test_devuelve_un_float(self):
        self.assertIsInstance(detect_bpm(click_track(120, 10), SR), float)

    def test_una_senal_sin_pulso_no_inventa_un_tempo_fuera_de_rango(self):
        # Un tono continuo no tiene ritmo; el resultado debe ser al menos un tempo plausible.
        detectado = detect_bpm(sine(440, 10), SR)

        self.assertGreaterEqual(detectado, 70)
        self.assertLessEqual(detectado, 180)

    def test_audio_demasiado_corto_lanza_error(self):
        with self.assertRaises(ValueError):
            detect_bpm(click_track(120, 0.5), SR)

    def test_silencio_lanza_error(self):
        import numpy as np
        with self.assertRaises(ValueError):
            detect_bpm(np.zeros(SR * 10), SR)

    def test_detecta_174_bpm_de_drum_and_bass(self):
        self.assertBpmCerca(174)

    def test_tolera_ruido_de_fondo(self):
        import numpy as np
        rng = np.random.default_rng(seed=7)
        y = click_track(124, seconds=20) + rng.normal(0, 0.02, int(20 * SR))

        self.assertAlmostEqual(detect_bpm(y, SR), 124, delta=2.0)

    def test_precision_de_decimas_en_un_tempo_no_entero(self):
        y = click_track(127.5, seconds=30)

        self.assertAlmostEqual(detect_bpm(y, SR), 127.5, delta=0.5)


