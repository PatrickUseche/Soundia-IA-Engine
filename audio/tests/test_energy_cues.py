import numpy as np
from django.test import SimpleTestCase

from audio.analysis import (
    AudioTooShortError,
    SilentAudioError,
    compute_energy,
    find_cue_points,
    rms_to_energy,
)
from audio.tests.signals import SR, click_track, sine


class ComputeEnergyTests(SimpleTestCase):
    def test_el_silencio_lanza_error(self):
        with self.assertRaises(SilentAudioError):
            compute_energy(np.zeros(SR * 5), SR)

    def test_un_audio_corto_lanza_error(self):
        with self.assertRaises(AudioTooShortError):
            compute_energy(sine(440, 0.5), SR)

    def test_mas_volumen_es_mas_energia(self):
        suave = compute_energy(sine(440, 5, amplitude=0.05), SR)
        medio = compute_energy(sine(440, 5, amplitude=0.3), SR)
        fuerte = compute_energy(sine(440, 5, amplitude=0.9), SR)

        self.assertLess(suave, medio)
        self.assertLess(medio, fuerte)

    def test_senal_a_escala_completa_se_acerca_a_1(self):
        # Un seno a escala completa tiene RMS 0.707 (-3 dBFS): energia = 0.925.
        self.assertAlmostEqual(compute_energy(sine(440, 5, amplitude=1.0), SR), 0.925, places=2)

    def test_siempre_esta_entre_0_y_1(self):
        for amplitud in (0.001, 0.01, 0.1, 1.0, 5.0):
            with self.subTest(amplitud=amplitud):
                energia = compute_energy(sine(440, 3, amplitude=amplitud), SR)
                self.assertGreaterEqual(energia, 0.0)
                self.assertLessEqual(energia, 1.0)

    def test_conversion_de_rms_a_energia(self):
        self.assertEqual(rms_to_energy(0), 0.0)
        self.assertEqual(rms_to_energy(1.0), 1.0)
        self.assertEqual(rms_to_energy(0.001), 0.0)        # -60 dBFS, por debajo del piso
        self.assertAlmostEqual(rms_to_energy(0.1), 0.5)    # -20 dBFS, a mitad de escala


class FindCuePointsTests(SimpleTestCase):
    BPM = 120  # un compas de 4 tiempos dura 2 s

    def pista(self, compases_suaves, compases_fuertes):
        suave = click_track(self.BPM, compases_suaves * 2, amplitude=0.1)
        fuerte = click_track(self.BPM, compases_fuertes * 2, amplitude=0.9)
        return np.concatenate([suave, fuerte])

    def test_siempre_incluye_el_inicio_de_la_musica(self):
        cues = find_cue_points(click_track(self.BPM, 20), SR, self.BPM)

        self.assertAlmostEqual(cues[0], 0.0, delta=0.15)

    def test_marca_el_cambio_de_energia_en_el_compas_donde_ocurre(self):
        y = self.pista(compases_suaves=12, compases_fuertes=12)

        cues = find_cue_points(y, SR, self.BPM)

        # El cambio ocurre en el compas 12 = 24 s.
        self.assertTrue(any(abs(c - 24.0) < 0.3 for c in cues), cues)

    def test_marca_tambien_una_caida_de_energia(self):
        y = self.pista(compases_suaves=0, compases_fuertes=12)
        y = np.concatenate([y, click_track(self.BPM, 24, amplitude=0.05)])

        cues = find_cue_points(y, SR, self.BPM)

        self.assertTrue(any(abs(c - 24.0) < 0.3 for c in cues), cues)

    def test_marca_el_punto_de_salida_16_compases_antes_del_final(self):
        y = click_track(self.BPM, 80)  # 40 compases = 80 s

        cues = find_cue_points(y, SR, self.BPM)

        # Salida = compas 24 = 48 s.
        self.assertTrue(any(abs(c - 48.0) < 0.3 for c in cues), cues)

    def test_una_pista_corta_no_tiene_punto_de_salida(self):
        cues = find_cue_points(click_track(self.BPM, 20), SR, self.BPM)  # 10 compases

        self.assertEqual(len(cues), 1)

    def test_los_cues_estan_ordenados_y_separados(self):
        y = np.concatenate([click_track(self.BPM, 24, amplitude=a) for a in (0.1, 0.9, 0.1, 0.9)])

        cues = find_cue_points(y, SR, self.BPM)

        self.assertEqual(cues, sorted(cues))
        self.assertEqual(len(cues), len(set(cues)))
        for anterior, siguiente in zip(cues, cues[1:]):
            self.assertGreaterEqual(siguiente - anterior, 8 * 2 - 0.5)  # >= 8 compases

    def test_los_cues_caen_dentro_de_la_pista(self):
        y = self.pista(12, 12)

        cues = find_cue_points(y, SR, self.BPM)

        self.assertTrue(all(0 <= c < len(y) / SR for c in cues))

    def test_un_audio_corto_lanza_error(self):
        with self.assertRaises(AudioTooShortError):
            find_cue_points(sine(440, 0.5), SR, self.BPM)

    def test_una_senal_casi_inaudible_se_trata_como_silencio(self):
        with self.assertRaises(SilentAudioError):
            compute_energy(sine(440, 3, amplitude=0.00005), SR)
