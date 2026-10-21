from django.test import SimpleTestCase

from mixing.tempo import MAX_PITCH_ADJUSTMENT, TempoMatch, match_tempo, tempo_score


class MatchTempoTests(SimpleTestCase):
    def test_mismo_tempo_no_requiere_ajuste(self):
        match = match_tempo(128, 128)

        self.assertEqual(match.ratio, 1.0)
        self.assertEqual(match.multiplier, 1.0)
        self.assertTrue(match.feasible)
        self.assertEqual(match.adjustment, 0.0)

    def test_tempos_cercanos_son_factibles(self):
        match = match_tempo(128, 126)

        self.assertAlmostEqual(match.ratio, 128 / 126)
        self.assertTrue(match.feasible)

    def test_el_ratio_lleva_la_pista_b_al_tempo_de_a(self):
        match = match_tempo(128, 124)

        self.assertAlmostEqual(124 * match.ratio, 128)

    def test_el_limite_del_pitch_fader_es_factible(self):
        # 8 % exacto: 100 -> 108.
        self.assertTrue(match_tempo(108, 100).feasible)

    def test_mas_alla_del_limite_no_es_factible(self):
        self.assertFalse(match_tempo(128, 140).feasible)   # -8.6 %
        self.assertFalse(match_tempo(128, 115).feasible)   # +11 %

    def test_una_pista_al_doble_de_tempo_se_mezcla_contando_la_mitad_de_sus_pulsos(self):
        match = match_tempo(70, 140)

        self.assertEqual(match.multiplier, 0.5)
        self.assertAlmostEqual(match.ratio, 1.0)
        self.assertTrue(match.feasible)

    def test_una_pista_a_la_mitad_de_tempo_se_mezcla_contando_el_doble_de_pulsos(self):
        match = match_tempo(140, 70)

        self.assertEqual(match.multiplier, 2.0)
        self.assertAlmostEqual(match.ratio, 1.0)
        self.assertTrue(match.feasible)

    def test_drum_and_bass_a_174_con_house_a_87_se_mezcla_a_medio_tiempo(self):
        match = match_tempo(174, 87)

        self.assertEqual(match.multiplier, 2.0)
        self.assertTrue(match.feasible)

    def test_tempos_sin_relacion_no_son_factibles_por_ningun_camino(self):
        match = match_tempo(128, 174)

        self.assertFalse(match.feasible)

    def test_elige_la_opcion_que_menos_pitch_pide(self):
        match = match_tempo(128, 66)  # 66 * 2 = 132: pide -3 %, frente a +94 % sin multiplicar

        self.assertEqual(match.multiplier, 2.0)
        self.assertAlmostEqual(match.adjustment, abs(128 / 132 - 1), places=6)

    def test_bpm_no_positivo_lanza_error(self):
        for a, b in [(0, 128), (128, 0), (-5, 128), (128, -1)]:
            with self.subTest(a=a, b=b):
                with self.assertRaises(ValueError):
                    match_tempo(a, b)


class TempoScoreTests(SimpleTestCase):
    def test_sin_ajuste_la_puntuacion_es_maxima(self):
        self.assertEqual(tempo_score(match_tempo(128, 128)), 1.0)

    def test_en_el_limite_del_fader_la_puntuacion_es_cero(self):
        self.assertAlmostEqual(tempo_score(match_tempo(108, 100)), 0.0, places=6)

    def test_a_mitad_del_limite_la_puntuacion_es_media(self):
        match = TempoMatch(ratio=1 + MAX_PITCH_ADJUSTMENT / 2, multiplier=1.0, feasible=True)

        self.assertAlmostEqual(tempo_score(match), 0.5)

    def test_fuera_de_rango_no_baja_de_cero(self):
        self.assertEqual(tempo_score(match_tempo(128, 174)), 0.0)

    def test_mas_cercano_puntua_mas(self):
        self.assertGreater(tempo_score(match_tempo(128, 127)), tempo_score(match_tempo(128, 123)))
