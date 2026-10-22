import numpy as np
from django.test import SimpleTestCase

from audio.beatgrid import MIN_BEAT_STRENGTH, estimate_grid
from audio.tests.signals import SR, click_track, sine


def circular_error(estimado, real, periodo):
    """Diferencia entre dos fases de una rejilla periodica, en segundos, en el rango +-periodo/2."""
    return ((estimado - real + periodo / 2) % periodo) - periodo / 2


def kick_pattern(bpm, seconds, first_beat, strong_beat, sr=SR):
    """Bombos graves en cada pulso; el de la posicion `strong_beat` (0-3) de cada compas es mas fuerte."""
    y = np.zeros(int(seconds * sr))
    t = np.arange(int(0.12 * sr)) / sr
    period = 60.0 / bpm
    beat = 0
    while first_beat + beat * period < seconds - 0.2:
        amplitude = 0.9 if beat % 4 == strong_beat else 0.45
        start = int((first_beat + beat * period) * sr)
        # Seno grave con caida de frecuencia y de amplitud, como un bombo.
        kick = np.sin(2 * np.pi * (50 * t + 60 * (1 - np.exp(-t * 30)) / 30)) * np.exp(-t * 25)
        y[start:start + len(kick)] += kick * amplitude
        beat += 1
    return y


class EstimateGridTests(SimpleTestCase):
    def assertRejilla(self, bpm, primer_pulso, segundos=60):
        y = click_track(bpm, segundos, first_beat=primer_pulso)

        rejilla = estimate_grid(y, SR, bpm_hint=round(bpm))

        periodo = 60.0 / bpm
        self.assertAlmostEqual(rejilla.bpm, bpm, delta=0.03)
        self.assertLess(abs(circular_error(rejilla.offset, primer_pulso, periodo)), 0.004)

    def test_encuentra_el_tempo_y_la_fase_de_un_pulso_regular(self):
        self.assertRejilla(127.3, 0.37)

    def test_funciona_con_varios_tempos_y_desfases(self):
        for bpm, primer_pulso in ((96.0, 0.12), (110.2, 0.5), (140.0, 0.0), (75.5, 0.31)):
            with self.subTest(bpm=bpm, primer_pulso=primer_pulso):
                self.assertRejilla(bpm, primer_pulso)

    def test_afina_un_tempo_que_la_pista_tiene_con_decimales(self):
        # El BPM de partida tiene 0.2 de error: es lo que arrastraria una mezcla larga fuera de compas.
        y = click_track(110.0, 60, first_beat=0.2)

        rejilla = estimate_grid(y, SR, bpm_hint=110.2)

        self.assertAlmostEqual(rejilla.bpm, 110.0, delta=0.02)

    def test_el_primer_pulso_siempre_cae_dentro_del_primer_periodo(self):
        rejilla = estimate_grid(click_track(120, 30, first_beat=0.7), SR, bpm_hint=120)

        self.assertGreaterEqual(rejilla.offset, 0.0)
        self.assertLess(rejilla.offset, 60 / 120)

    def test_un_pulso_regular_tiene_mucha_fuerza(self):
        rejilla = estimate_grid(click_track(124, 40, first_beat=0.1), SR, bpm_hint=124)

        self.assertGreater(rejilla.beat_strength, MIN_BEAT_STRENGTH * 3)

    def test_sin_ritmo_la_fuerza_es_baja(self):
        ruido = np.random.default_rng(1).normal(0, 0.1, SR * 30)

        self.assertLess(estimate_grid(ruido, SR, bpm_hint=120).beat_strength, MIN_BEAT_STRENGTH)
        self.assertLess(estimate_grid(sine(440, 30), SR, bpm_hint=120).beat_strength, MIN_BEAT_STRENGTH)


class DownbeatTests(SimpleTestCase):
    def test_el_primer_tiempo_del_compas_es_el_bombo_mas_fuerte(self):
        for fuerte in range(4):
            with self.subTest(pulso_fuerte=fuerte):
                bpm, primer_pulso = 100.0, 0.3
                y = kick_pattern(bpm, 60, primer_pulso, strong_beat=fuerte)

                rejilla = estimate_grid(y, SR, bpm_hint=100)

                periodo = 60.0 / bpm
                esperado = primer_pulso + fuerte * periodo
                compas = 4 * periodo
                self.assertLess(abs(circular_error(rejilla.downbeat_offset, esperado, compas)), 0.006)
                self.assertGreater(rejilla.downbeat_confidence, 0.3)

    def test_el_primer_tiempo_cae_dentro_del_primer_compas(self):
        rejilla = estimate_grid(kick_pattern(100, 40, 0.3, strong_beat=2), SR, bpm_hint=100)

        self.assertGreaterEqual(rejilla.downbeat_offset, 0.0)
        self.assertLess(rejilla.downbeat_offset, 4 * 60 / 100)

    def test_con_todos_los_pulsos_iguales_la_confianza_es_baja(self):
        # No hay forma de saber cual es el primer tiempo: se tiene que notar.
        rejilla = estimate_grid(click_track(100, 60, first_beat=0.3), SR, bpm_hint=100)

        self.assertLess(rejilla.downbeat_confidence, 0.15)
