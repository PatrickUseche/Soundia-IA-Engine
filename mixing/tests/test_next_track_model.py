import numpy as np
from django.test import SimpleTestCase, TestCase

from audio.models import Track
from mixing.compatibility import TrackInfo
from mixing.models import AutoDjChoice
from mixing.next_track_model import (
    FEATURES, MAX_BONUS, MIN_CORRECTIONS, bonuses, evaluate, fit, pair_features, record_choice, reset_cache,
)
from mixing.style_model import reset_cache as reset_style_cache, set_enabled, style_model_status


def info(bpm=120.0, camelot='8B', energy=0.5, genre=''):
    return TrackInfo(id=1, title='t', bpm=bpm, camelot=camelot, energy=energy, genre=genre)


def track_obj(titulo, bpm=120.0, camelot='8B', energy=0.5, genre=''):
    return Track.objects.create(title=titulo, duration=300.0, bpm=bpm, key='C major', camelot=camelot,
                                energy=energy, cue_points=[0.0, 60.0, 270.0], genre=genre)


def diferencias(csv_rows):
    return np.array(csv_rows, dtype=float)


class FeaturesTests(SimpleTestCase):
    def test_los_rasgos_siguen_el_orden_y_estan_entre_0_y_1(self):
        rasgos = pair_features(info(), info(bpm=124, camelot='9B', energy=0.8, genre='salsa'))

        self.assertEqual(len(rasgos), len(FEATURES))
        self.assertTrue(all(0.0 <= raw_value <= 1.0 for raw_value in rasgos))

    def test_si_la_energia_sube_se_nota_y_si_baja_no(self):
        sube = pair_features(info(energy=0.4), info(energy=0.7))
        baja = pair_features(info(energy=0.7), info(energy=0.4))

        self.assertAlmostEqual(sube[FEATURES.index('energyUp')], 0.3)
        self.assertEqual(baja[FEATURES.index('energyUp')], 0.0)

    def test_el_mismo_genero_solo_cuenta_si_hay_genero(self):
        igual = pair_features(info(genre='salsa'), info(genre='salsa'))
        sin_genero = pair_features(info(), info())
        distinto = pair_features(info(genre='salsa'), info(genre='bachata'))

        self.assertEqual(igual[FEATURES.index('sameGenre')], 1.0)
        self.assertEqual(sin_genero[FEATURES.index('sameGenre')], 0.0)
        self.assertEqual(distinto[FEATURES.index('sameGenre')], 0.0)


class FitTests(SimpleTestCase):
    def test_sin_correcciones_no_cambia_nada(self):
        self.assertTrue(np.all(fit(np.zeros((0, len(FEATURES)))) == 0.0))

    def test_aprende_la_direccion_en_la_que_el_dj_se_aparta_de_la_propuesta(self):
        # El DJ siempre prefiere la pista que sube la energia (indice 3) a la mas compatible.
        pesos = fit(diferencias([[-0.2, 0.0, -0.3, 0.3, 0.0]] * 20))

        self.assertGreater(pesos[FEATURES.index('energyUp')], 0.2)
        self.assertLess(pesos[FEATURES.index('harmonic')], 0.0)

    def test_con_pocos_casos_los_pesos_son_pequenos(self):
        pocos = fit(diferencias([[0.0, 0.0, 0.0, 0.3, 0.0]]))
        muchos = fit(diferencias([[0.0, 0.0, 0.0, 0.3, 0.0]] * 40))

        self.assertLess(abs(pocos[3]), 1.0)
        self.assertGreaterEqual(abs(muchos[3]), abs(pocos[3]) - 1e-9)

    def test_el_bono_se_centra_en_las_candidatas_y_esta_acotado(self):
        pesos = np.array([5.0, 0.0, 0.0, 0.0, 0.0])

        field_values = bonuses(pesos, [[1.0, 0, 0, 0, 0], [0.0, 0, 0, 0, 0], [0.5, 0, 0, 0, 0]])

        self.assertAlmostEqual(sum(field_values), 0.0, delta=0.4)
        self.assertTrue(all(-MAX_BONUS <= raw_value <= MAX_BONUS for raw_value in field_values))
        self.assertGreater(field_values[0], field_values[2])
        self.assertGreater(field_values[2], field_values[1])

    def test_sin_candidatas_no_hay_bonos(self):
        self.assertEqual(bonuses(np.zeros(len(FEATURES)), []), [])


class EvaluationTests(SimpleTestCase):
    def test_con_pocas_correcciones_nunca_gana(self):
        outcome = evaluate(diferencias([[0.0, 0.0, 0.0, 0.3, 0.0]] * (MIN_CORRECTIONS - 1)))

        self.assertFalse(outcome['wins'])

    def test_un_dj_consistente_hace_ganar_al_modelo(self):
        outcome = evaluate(diferencias([[-0.2, 0.0, -0.3, 0.3, 0.0]] * (MIN_CORRECTIONS + 5)))

        self.assertTrue(outcome['wins'])
        self.assertEqual(outcome['accuracy'], 1.0)
        self.assertEqual(outcome['rulesAccuracy'], 0.0)

    def test_un_dj_que_se_contradice_no_hace_ganar_al_modelo(self):
        a, b = [0.0, 0.0, 0.0, 0.3, 0.0], [0.0, 0.0, 0.0, -0.3, 0.0]
        outcome = evaluate(diferencias([a, b] * (MIN_CORRECTIONS + 5)))

        self.assertFalse(outcome['wins'])

    def test_sin_datos_no_hay_precision(self):
        outcome = evaluate(np.zeros((0, len(FEATURES))))

        self.assertIsNone(outcome['accuracy'])
        self.assertFalse(outcome['wins'])


class RecordChoiceTests(TestCase):
    def setUp(self):
        reset_cache()
        reset_style_cache()
        self.current_value = track_obj('actual')
        self.chosen_item = track_obj('elegida', camelot='9B', energy=0.8)
        self.propuesta = track_obj('propuesta')

    def test_guarda_los_rasgos_de_la_elegida_y_de_la_propuesta(self):
        eleccion = record_choice(self.current_value, self.chosen_item, self.propuesta)

        self.assertEqual(len(eleccion.chosen_features), len(FEATURES))
        self.assertEqual(len(eleccion.rejected_features), len(FEATURES))
        self.assertGreater(eleccion.chosen_features[FEATURES.index('energyUp')], 0.0)

    def test_aceptar_la_propuesta_no_da_un_par_pero_se_cuenta(self):
        eleccion = record_choice(self.current_value, self.propuesta, self.propuesta)

        self.assertIsNone(eleccion.rejected_features)
        self.assertEqual(style_model_status()['nextTrack']['choices'], 1)
        self.assertEqual(style_model_status()['nextTrack']['corrections'], 0)

    def test_sin_propuesta_tampoco_hay_par(self):
        self.assertIsNone(record_choice(self.current_value, self.chosen_item).rejected_features)

    def test_borrar_las_pistas_no_borra_lo_aprendido(self):
        record_choice(self.current_value, self.chosen_item, self.propuesta)

        Track.objects.all().delete()

        eleccion = AutoDjChoice.objects.get()
        self.assertIsNone(eleccion.chosen_track)
        self.assertEqual(len(eleccion.rejected_features), len(FEATURES))


class ChoicesRouteTests(TestCase):
    def setUp(self):
        reset_cache()
        reset_style_cache()
        self.current_value = track_obj('actual')
        self.chosen_item = track_obj('elegida', camelot='9B', energy=0.8)
        self.propuesta = track_obj('propuesta')

    def enviar(self, cuerpo):
        return self.client.post('/api/mix/choices', cuerpo, content_type='application/json')

    def test_guarda_la_eleccion_y_devuelve_las_cuentas(self):
        respuesta = self.enviar({'fromTrackId': self.current_value.id, 'chosenTrackId': self.chosen_item.id,
                                 'recommendedTrackId': self.propuesta.id})

        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.json()['corrections'], 1)
        self.assertEqual(respuesta.json()['required'], MIN_CORRECTIONS)

    def test_la_propuesta_es_opcional(self):
        respuesta = self.enviar({'fromTrackId': self.current_value.id, 'chosenTrackId': self.chosen_item.id})

        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.json()['corrections'], 0)

    def test_rechaza_elegir_la_misma_pista(self):
        self.assertEqual(self.enviar({'fromTrackId': self.current_value.id, 'chosenTrackId': self.current_value.id}).status_code, 400)

    def test_una_pista_que_no_existe_da_404(self):
        self.assertEqual(self.enviar({'fromTrackId': self.current_value.id, 'chosenTrackId': 9999}).status_code, 404)

    def test_faltan_campos_da_400(self):
        self.assertEqual(self.enviar({'fromTrackId': self.current_value.id}).status_code, 400)

    def test_solo_acepta_post(self):
        self.assertEqual(self.client.get('/api/mix/choices').status_code, 405)


class UseInRankingTests(TestCase):
    """Con el modelo encendido y ganando, una pista algo menos compatible pero que el DJ suele preferir sube."""

    def setUp(self):
        reset_cache()
        reset_style_cache()
        self.current_value = track_obj('actual', energy=0.5)
        self.compatible = track_obj('compatible', energy=0.5)  # puntuacion 1.0
        self.subida = track_obj('sube la energia', camelot='9B', energy=0.8)  # puntuacion ~0.875

    def candidatas(self):
        respuesta = self.client.post('/api/mix/next', {'trackId': self.current_value.id, 'limit': 2},
                                     content_type='application/json')
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.json()

    def aprender(self, veces=MIN_CORRECTIONS + 5):
        for _ in range(veces):
            record_choice(self.current_value, self.subida, self.compatible)

    def test_por_defecto_manda_la_regla(self):
        self.aprender()

        cuerpo = self.candidatas()

        self.assertEqual(cuerpo['source'], 'rules')
        self.assertEqual(cuerpo['candidates'][0]['track']['title'], 'compatible')
        self.assertNotIn('learnedBonus', cuerpo['candidates'][0])

    def test_encendido_y_ganando_la_que_prefiere_el_dj_sube(self):
        self.aprender()
        set_enabled(True)

        cuerpo = self.candidatas()

        self.assertEqual(cuerpo['source'], 'model')
        self.assertEqual(cuerpo['candidates'][0]['track']['title'], 'sube la energia')
        self.assertIn('learnedBonus', cuerpo['candidates'][0])

    def test_apagarlo_vuelve_a_la_regla(self):
        self.aprender()
        set_enabled(True)
        set_enabled(False)

        self.assertEqual(self.candidatas()['candidates'][0]['track']['title'], 'compatible')

    def test_con_pocas_correcciones_no_cambia_nada(self):
        self.aprender(veces=MIN_CORRECTIONS - 1)
        set_enabled(True)

        cuerpo = self.candidatas()

        self.assertEqual(cuerpo['source'], 'rules')
        self.assertEqual(cuerpo['candidates'][0]['track']['title'], 'compatible')

    def test_el_estado_dice_si_se_esta_usando(self):
        self.aprender()
        self.assertFalse(style_model_status()['nextTrack']['inUse'])

        set_enabled(True)

        estado = style_model_status()['nextTrack']
        self.assertTrue(estado['inUse'])
        self.assertTrue(estado['evaluation']['wins'])

    def test_el_limite_se_respeta_aunque_se_reordene_todo(self):
        self.aprender()
        set_enabled(True)
        track_obj('otra', camelot='3A')

        respuesta = self.client.post('/api/mix/next', {'trackId': self.current_value.id, 'limit': 1},
                                     content_type='application/json')

        self.assertEqual(len(respuesta.json()['candidates']), 1)
