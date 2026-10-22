import numpy as np
from django.test import SimpleTestCase

from audio.vocals import FRAME_SECONDS, frame_rms, last_vocal_end, vocal_segments


def curva(*tramos):
    """Curva de energia de voz por frames de 0.5 s: cada tramo es (segundos, nivel)."""
    return np.concatenate([np.full(int(segundos / FRAME_SECONDS), nivel) for segundos, nivel in tramos])


class FrameRmsTests(SimpleTestCase):
    def test_mide_la_energia_por_frames_de_medio_segundo(self):
        sr = 1000
        senal = np.concatenate([np.full(500, 0.5), np.zeros(500), np.full(500, 0.2)])

        rms = frame_rms(senal, sr)

        np.testing.assert_allclose(rms, [0.5, 0.0, 0.2])

    def test_promedia_los_canales_si_la_senal_es_estereo(self):
        sr = 1000
        estereo = np.stack([np.full(500, 0.4), np.full(500, 0.2)])

        np.testing.assert_allclose(frame_rms(estereo, sr), [0.3])

    def test_descarta_el_resto_que_no_llena_un_frame(self):
        self.assertEqual(len(frame_rms(np.ones(1250), 1000)), 2)


class VocalSegmentsTests(SimpleTestCase):
    def test_sin_voz_no_hay_segmentos(self):
        self.assertEqual(vocal_segments(curva((20, 0.0))), [])
        self.assertEqual(vocal_segments(np.array([])), [])

    def test_ruido_de_fondo_muy_bajo_no_cuenta_como_voz(self):
        self.assertEqual(vocal_segments(curva((20, 0.001))), [])

    def test_encuentra_un_tramo_con_voz(self):
        self.assertEqual(vocal_segments(curva((10, 0.0), (10, 0.1), (10, 0.0))), [(10.0, 20.0)])

    def test_une_las_frases_separadas_por_una_pausa_corta(self):
        # 2 s de silencio entre frases (una respiracion): sigue siendo la misma estrofa.
        self.assertEqual(vocal_segments(curva((8, 0.1), (2, 0.0), (8, 0.1))), [(0.0, 18.0)])

    def test_no_une_las_frases_separadas_por_una_pausa_larga(self):
        self.assertEqual(vocal_segments(curva((8, 0.1), (5, 0.0), (8, 0.1))), [(0.0, 8.0), (13.0, 21.0)])

    def test_descarta_un_sonido_suelto_demasiado_corto(self):
        self.assertEqual(vocal_segments(curva((10, 0.0), (0.5, 0.1), (10, 0.0))), [])

    def test_el_umbral_es_relativo_a_lo_fuerte_que_es_la_voz(self):
        # Una voz suave (0.02) y otra fuerte (0.2) se detectan igual; lo flojo dentro de ellas, no.
        suave = curva((10, 0.02), (6, 0.001), (10, 0.02))
        fuerte = curva((10, 0.2), (6, 0.01), (10, 0.2))

        self.assertEqual(vocal_segments(suave), [(0.0, 10.0), (16.0, 26.0)])
        self.assertEqual(vocal_segments(fuerte), [(0.0, 10.0), (16.0, 26.0)])


class LastVocalEndTests(SimpleTestCase):
    def test_es_el_final_de_la_ultima_frase_en_segundos_de_la_pista(self):
        # La ventana empieza en el segundo 270 de la pista; la voz acaba 20 s despues.
        rms = curva((20, 0.1), (20, 0.0))

        self.assertEqual(last_vocal_end(rms, window_start=270.0), 290.0)

    def test_si_la_voz_llega_hasta_el_final_de_la_ventana_devuelve_el_final(self):
        self.assertEqual(last_vocal_end(curva((30, 0.1)), window_start=100.0), 130.0)

    def test_sin_voz_en_la_ventana_devuelve_none(self):
        self.assertIsNone(last_vocal_end(curva((30, 0.0)), window_start=100.0))
