from types import SimpleNamespace

from django.test import SimpleTestCase

from mixing.compatibility import (
    DEFAULT_WEIGHTS,
    ENERGY_WEIGHT,
    HARMONIC_WEIGHT,
    TEMPO_WEIGHT,
    ScoringWeights,
    TrackInfo,
    compatibility,
    energy_score,
    harmonic_score,
    rank_next_tracks,
)


def track(id, bpm=128.0, camelot='8B', energy=0.6, **extra):
    return TrackInfo(id=id, title=f'pista {id}', bpm=bpm, camelot=camelot, energy=energy, **extra)


class WeightsTests(SimpleTestCase):
    def test_los_pesos_suman_uno(self):
        self.assertAlmostEqual(TEMPO_WEIGHT + HARMONIC_WEIGHT + ENERGY_WEIGHT, 1.0)


class HarmonicScoreTests(SimpleTestCase):
    def test_misma_tonalidad(self):
        self.assertEqual(harmonic_score('8B', '8B'), 1.0)

    def test_vecinas_y_relativas(self):
        self.assertEqual(harmonic_score('8B', '9B'), 0.8)
        self.assertEqual(harmonic_score('8B', '7B'), 0.8)
        self.assertEqual(harmonic_score('8B', '8A'), 0.8)

    def test_distancia_dos_y_tres(self):
        self.assertEqual(harmonic_score('8B', '10B'), 0.5)
        self.assertEqual(harmonic_score('8B', '9A'), 0.5)  # un paso de numero y uno de letra
        self.assertEqual(harmonic_score('8B', '11B'), 0.25)

    def test_tonalidades_lejanas_no_puntuan(self):
        self.assertEqual(harmonic_score('8B', '2B'), 0.0)
        self.assertEqual(harmonic_score('1A', '7B'), 0.0)

    def test_la_rueda_es_circular(self):
        self.assertEqual(harmonic_score('12A', '1A'), 0.8)

    def test_es_simetrica(self):
        self.assertEqual(harmonic_score('3A', '5B'), harmonic_score('5B', '3A'))


class EnergyScoreTests(SimpleTestCase):
    def test_misma_energia(self):
        self.assertEqual(energy_score(0.5, 0.5), 1.0)

    def test_cae_con_la_diferencia(self):
        self.assertAlmostEqual(energy_score(0.5, 0.8), 0.7)

    def test_extremos_opuestos(self):
        self.assertEqual(energy_score(0.0, 1.0), 0.0)


class CompatibilityTests(SimpleTestCase):
    def test_pistas_identicas_puntuan_el_maximo(self):
        resultado = compatibility(track(1), track(2))

        self.assertEqual(resultado.score, 1.0)

    def test_expone_cada_criterio_y_el_ajuste_de_tempo(self):
        resultado = compatibility(track(1, bpm=128), track(2, bpm=126, camelot='9B', energy=0.5))

        self.assertTrue(resultado.tempo_match.feasible)
        self.assertEqual(resultado.harmonic, 0.8)
        self.assertAlmostEqual(resultado.energy, 0.9)
        self.assertGreater(resultado.tempo, 0.0)
        self.assertLess(resultado.score, 1.0)

    def test_la_puntuacion_combina_los_tres_criterios_con_sus_pesos(self):
        a, b = track(1, bpm=128), track(2, bpm=128, camelot='9B', energy=0.4)

        resultado = compatibility(a, b)

        esperado = TEMPO_WEIGHT * 1.0 + HARMONIC_WEIGHT * 0.8 + ENERGY_WEIGHT * 0.8
        self.assertAlmostEqual(resultado.score, esperado, places=3)

    def test_tempos_imposibles_de_igualar_restan_todo_el_peso_del_tempo(self):
        resultado = compatibility(track(1, bpm=128), track(2, bpm=174))

        self.assertEqual(resultado.tempo, 0.0)
        self.assertFalse(resultado.tempo_match.feasible)
        self.assertAlmostEqual(resultado.score, HARMONIC_WEIGHT + ENERGY_WEIGHT, places=3)

    def test_el_orden_de_los_argumentos_no_cambia_la_puntuacion_armonica_ni_de_energia(self):
        a, b = track(1, camelot='3A', energy=0.2), track(2, camelot='4A', energy=0.9)

        self.assertEqual(compatibility(a, b).harmonic, compatibility(b, a).harmonic)
        self.assertEqual(compatibility(a, b).energy, compatibility(b, a).energy)

    def test_from_model_copia_los_datos_de_un_track(self):
        modelo = SimpleNamespace(
            id=7, title='tema', bpm=126.5, camelot='5A', energy=0.7, duration=240.0, cue_points=[0.0, 32.0],
            vocal_last_end=228.5, vocal_first_start=12.5,
        )

        info = TrackInfo.from_model(modelo)

        self.assertEqual((info.id, info.title, info.bpm, info.camelot), (7, 'tema', 126.5, '5A'))
        self.assertEqual(info.cue_points, [0.0, 32.0])
        self.assertEqual(info.vocal_last_end, 228.5)
        self.assertEqual(info.vocal_first_start, 12.5)


class RankNextTracksTests(SimpleTestCase):
    def test_ordena_de_mejor_a_peor(self):
        actual = track(1, bpm=128, camelot='8B')
        perfecta = track(2, bpm=128, camelot='8B')
        buena = track(3, bpm=126, camelot='9B')
        mala = track(4, bpm=170, camelot='2A')

        ranking = rank_next_tracks(actual, [mala, buena, perfecta])

        self.assertEqual([t.id for t, _ in ranking], [2, 3, 4])

    def test_excluye_la_pista_actual(self):
        actual = track(1)

        ranking = rank_next_tracks(actual, [actual, track(2)])

        self.assertEqual([t.id for t, _ in ranking], [2])

    def test_respeta_el_limite(self):
        ranking = rank_next_tracks(track(1), [track(i) for i in range(2, 12)], limit=3)

        self.assertEqual(len(ranking), 3)

    def test_sin_candidatas_devuelve_lista_vacia(self):
        self.assertEqual(rank_next_tracks(track(1), []), [])

    def test_a_igual_puntuacion_gana_el_menor_id(self):
        ranking = rank_next_tracks(track(1), [track(9), track(5), track(7)])

        self.assertEqual([t.id for t, _ in ranking], [5, 7, 9])

    def test_un_limite_invalido_lanza_error(self):
        with self.assertRaises(ValueError):
            rank_next_tracks(track(1), [track(2)], limit=0)

    def test_prefiere_una_pista_armonica_aunque_tenga_un_poco_menos_de_tempo(self):
        actual = track(1, bpm=128, camelot='8B')
        misma_tonalidad = track(2, bpm=124, camelot='8B')      # tempo flojo, armonia perfecta
        tonalidad_lejana = track(3, bpm=128, camelot='3A')     # tempo perfecto, armonia nula

        ranking = rank_next_tracks(actual, [tonalidad_lejana, misma_tonalidad])

        self.assertEqual(ranking[0][0].id, 2)


class ScoringWeightsTests(SimpleTestCase):
    def test_los_pesos_por_defecto_son_los_de_siempre(self):
        self.assertEqual(
            (DEFAULT_WEIGHTS.tempo, DEFAULT_WEIGHTS.harmonic, DEFAULT_WEIGHTS.energy),
            (TEMPO_WEIGHT, HARMONIC_WEIGHT, ENERGY_WEIGHT),
        )

    def test_unos_pesos_validos_se_crean(self):
        pesos = ScoringWeights(0.2, 0.5, 0.3)

        self.assertEqual((pesos.tempo, pesos.harmonic, pesos.energy), (0.2, 0.5, 0.3))

    def test_los_pesos_deben_sumar_uno(self):
        for invalido in [(0.5, 0.5, 0.5), (0.1, 0.1, 0.1), (1.0, 0.0, 0.5)]:
            with self.subTest(pesos=invalido):
                with self.assertRaises(ValueError):
                    ScoringWeights(*invalido)

    def test_no_se_admiten_pesos_negativos(self):
        with self.assertRaises(ValueError):
            ScoringWeights(1.2, -0.1, -0.1)

    def test_se_pueden_usar_pesos_que_ignoran_un_criterio(self):
        ScoringWeights(0.0, 1.0, 0.0)

    def test_la_puntuacion_usa_los_pesos_indicados(self):
        a = track(1, bpm=128, camelot='8B', energy=0.6)
        b = track(2, bpm=128, camelot='3A', energy=0.6)   # tempo y energia perfectos, armonia nula

        solo_tempo = compatibility(a, b, ScoringWeights(1.0, 0.0, 0.0))
        solo_armonia = compatibility(a, b, ScoringWeights(0.0, 1.0, 0.0))

        self.assertEqual(solo_tempo.score, 1.0)
        self.assertEqual(solo_armonia.score, 0.0)

    def test_los_pesos_cambian_el_orden_del_ranking(self):
        actual = track(1, bpm=128, camelot='8B')
        buen_tempo = track(2, bpm=128, camelot='3A')        # tempo perfecto, armonia nula
        buena_armonia = track(3, bpm=122, camelot='8B')     # armonia perfecta, tempo regular

        con_tempo = rank_next_tracks(actual, [buen_tempo, buena_armonia], weights=ScoringWeights(0.9, 0.05, 0.05))
        con_armonia = rank_next_tracks(actual, [buen_tempo, buena_armonia], weights=ScoringWeights(0.05, 0.9, 0.05))

        self.assertEqual(con_tempo[0][0].id, 2)
        self.assertEqual(con_armonia[0][0].id, 3)

    def test_sin_indicar_pesos_se_usan_los_por_defecto(self):
        a, b = track(1, bpm=128, camelot='8B'), track(2, bpm=126, camelot='9B')

        self.assertEqual(compatibility(a, b), compatibility(a, b, DEFAULT_WEIGHTS))
