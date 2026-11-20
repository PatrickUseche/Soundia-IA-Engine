from unittest import mock

import librosa
from django.test import SimpleTestCase

from audio.analysis import detect_bpm, tempo_prior
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


class TempoPriorTests(SimpleTestCase):
    """La prior de librosa por defecto (centrada en 120 BPM) mandaba a ~120 la salsa a ~90 (4/3 del tempo real). Una
    prior plana tampoco sirve: no resuelve la octava y un pulso limpio a 140 salia a 70. Esta no prefiere ningun tempo
    dentro del rango musical (78-180) y solo desfavorece lo que queda fuera. Medido con el conjunto Salsa (124
    fragmentos): acierto exacto del 19 % con la prior por defecto y del 37 % con esta, sin empeorar los pulsos
    sinteticos de 70 a 180 BPM."""

    def test_no_prefiere_ningun_tempo_dentro_del_rango_musical(self):
        prior = tempo_prior()

        for bpm in (80, 90, 100, 120, 140, 160, 175):
            with self.subTest(bpm=bpm):
                self.assertEqual(float(prior.logpdf(bpm)), 0.0)

    def test_desfavorece_los_tempos_fuera_del_rango_y_cada_vez_mas_lejos(self):
        prior = tempo_prior()

        self.assertLess(float(prior.logpdf(70)), 0.0)
        self.assertLess(float(prior.logpdf(60)), float(prior.logpdf(70)))
        self.assertLess(float(prior.logpdf(190)), 0.0)
        self.assertLess(float(prior.logpdf(220)), float(prior.logpdf(190)))

    def test_la_mitad_de_un_tempo_rapido_pierde_frente_al_tempo_rapido(self):
        prior = tempo_prior()

        # Es lo que evita que un pulso limpio a 140 BPM salga a 70.
        self.assertGreater(float(prior.logpdf(140)) - float(prior.logpdf(70)), 0.15)

    def test_acepta_varios_tempos_a_la_vez(self):
        import numpy as np

        resultado = tempo_prior().logpdf(np.array([60.0, 100.0, 220.0]))

        self.assertEqual(resultado.shape, (3,))
        self.assertEqual(float(resultado[1]), 0.0)

    def test_detect_bpm_estima_el_tempo_con_esa_prior_y_sin_tempo_de_partida(self):
        y = click_track(90, seconds=20)

        with mock.patch('audio.analysis.librosa.feature.tempo', wraps=librosa.feature.tempo) as espia:
            detect_bpm(y, SR)

        llamada = espia.call_args.kwargs
        self.assertNotIn('start_bpm', llamada)
        self.assertEqual(float(llamada['prior'].logpdf(90)), float(llamada['prior'].logpdf(120)))

    def test_detecta_90_bpm_el_tempo_tipico_de_la_salsa(self):
        self.assertAlmostEqual(detect_bpm(click_track(90, seconds=20), SR), 90, delta=2.0)

    def test_detecta_75_bpm_de_una_salsa_lenta(self):
        self.assertAlmostEqual(detect_bpm(click_track(75, seconds=20), SR), 75, delta=2.0)
