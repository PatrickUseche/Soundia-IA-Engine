import json

from django.test import TestCase

from audio.models import Track
from mixing.learning import MIN_SAMPLES
from mixing.models import LearnedWeights, TransitionFeedback

NEXT = '/api/mix/next'
TRANSITION = '/api/mix/transition'


def crear_track(titulo, bpm=128.0, camelot='8B', energy=0.6, duration=300.0, cues=None):
    return Track.objects.create(
        title=titulo, duration=duration, bpm=bpm, key='C major', camelot=camelot, energy=energy,
        cue_points=[0.0, 60.0, 270.0] if cues is None else cues,
    )


class ViewTestCase(TestCase):
    def post(self, url, payload=None, raw=None):
        cuerpo = raw if raw is not None else json.dumps(payload)
        return self.client.post(url, data=cuerpo, content_type='application/json')


class NextTracksViewTests(ViewTestCase):
    def setUp(self):
        self.actual = crear_track('actual', bpm=128, camelot='8B')
        self.perfecta = crear_track('perfecta', bpm=128, camelot='8B')
        self.buena = crear_track('buena', bpm=126, camelot='9B')
        self.mala = crear_track('mala', bpm=170, camelot='2A')

    def test_devuelve_las_candidatas_ordenadas_por_compatibilidad(self):
        response = self.post(NEXT, {'trackId': self.actual.id})

        self.assertEqual(response.status_code, 200)
        ids = [c['track']['id'] for c in response.json()['candidates']]
        self.assertEqual(ids, [self.perfecta.id, self.buena.id, self.mala.id])

    def test_no_incluye_la_pista_actual_y_la_devuelve_aparte(self):
        cuerpo = self.post(NEXT, {'trackId': self.actual.id}).json()

        self.assertEqual(cuerpo['current']['id'], self.actual.id)
        self.assertNotIn(self.actual.id, [c['track']['id'] for c in cuerpo['candidates']])

    def test_cada_candidata_trae_el_detalle_de_la_compatibilidad(self):
        primera = self.post(NEXT, {'trackId': self.actual.id}).json()['candidates'][0]

        self.assertEqual(primera['compatibility']['score'], 1.0)
        self.assertEqual(primera['compatibility']['harmonic'], 1.0)
        self.assertTrue(primera['compatibility']['tempoMatch']['feasible'])
        self.assertEqual(primera['track']['cuePoints'], [0.0, 60.0, 270.0])

    def test_respeta_el_limite(self):
        cuerpo = self.post(NEXT, {'trackId': self.actual.id, 'limit': 2}).json()

        self.assertEqual(len(cuerpo['candidates']), 2)

    def test_el_limite_por_defecto_es_5(self):
        for i in range(10):
            crear_track(f'extra {i}')

        cuerpo = self.post(NEXT, {'trackId': self.actual.id}).json()

        self.assertEqual(len(cuerpo['candidates']), 5)

    def test_sin_otras_pistas_la_lista_esta_vacia(self):
        Track.objects.exclude(pk=self.actual.id).delete()

        cuerpo = self.post(NEXT, {'trackId': self.actual.id}).json()

        self.assertEqual(cuerpo['candidates'], [])

    def test_pista_inexistente_devuelve_404(self):
        self.assertEqual(self.post(NEXT, {'trackId': 99999}).status_code, 404)

    def test_peticiones_invalidas_devuelven_400(self):
        casos = [
            {},                                  # falta trackId
            {'trackId': 'uno'},                  # no es entero
            {'trackId': True},                   # bool disfrazado de entero
            {'trackId': self.actual.id, 'limit': 0},
            {'trackId': self.actual.id, 'limit': 21},
            {'trackId': self.actual.id, 'limit': 'cinco'},
        ]
        for payload in casos:
            with self.subTest(payload=payload):
                self.assertEqual(self.post(NEXT, payload).status_code, 400)

    def test_cuerpo_vacio_json_invalido_o_no_objeto_devuelven_400(self):
        self.assertEqual(self.post(NEXT, raw='').status_code, 400)
        self.assertEqual(self.post(NEXT, raw='{no es json').status_code, 400)
        self.assertEqual(self.post(NEXT, raw='[1, 2]').status_code, 400)

    def test_get_devuelve_405(self):
        self.assertEqual(self.client.get(NEXT).status_code, 405)


class TransitionViewTests(ViewTestCase):
    def setUp(self):
        self.a = crear_track('a', bpm=128, camelot='8B', duration=300, cues=[0.0, 60.0, 270.0])
        self.b = crear_track('b', bpm=128, camelot='8B', cues=[4.0, 40.0])

    def test_devuelve_el_plan_de_la_transicion(self):
        response = self.post(TRANSITION, {'fromTrackId': self.a.id, 'toTrackId': self.b.id})

        self.assertEqual(response.status_code, 200)
        plan = response.json()
        self.assertEqual(plan['style'], 'blend')
        self.assertEqual(plan['bars'], 16)
        self.assertEqual(plan['seconds'], 30.0)
        self.assertEqual(plan['mixOutAt'], 270.0)
        self.assertEqual(plan['mixInAt'], 4.0)
        self.assertEqual(plan['fromTrackId'], self.a.id)
        self.assertEqual(plan['toTrackId'], self.b.id)

    def test_incluye_ajuste_de_tempo_y_compatibilidad(self):
        plan = self.post(TRANSITION, {'fromTrackId': self.a.id, 'toTrackId': self.b.id}).json()

        self.assertEqual(plan['tempoMatch'], {'ratio': 1.0, 'multiplier': 1.0, 'feasible': True})
        self.assertEqual(plan['compatibility']['score'], 1.0)

    def test_incluye_las_curvas_de_automatizacion(self):
        plan = self.post(TRANSITION, {'fromTrackId': self.a.id, 'toTrackId': self.b.id}).json()

        puntos = plan['automation']
        self.assertEqual(len(puntos), 65)
        self.assertEqual(puntos[0]['gainA'], 1.0)
        self.assertEqual(puntos[-1]['gainB'], 1.0)
        self.assertEqual(set(puntos[0]), {'position', 'gainA', 'gainB', 'lowA', 'lowB', 'midA', 'midB', 'highA', 'highB'})

    def test_tempos_imposibles_devuelven_un_corte_sin_automatizacion(self):
        rapida = crear_track('dnb', bpm=174)

        plan = self.post(TRANSITION, {'fromTrackId': self.a.id, 'toTrackId': rapida.id}).json()

        self.assertEqual(plan['style'], 'cut')
        self.assertEqual(plan['automation'], [])

    def test_pista_inexistente_devuelve_404(self):
        self.assertEqual(self.post(TRANSITION, {'fromTrackId': self.a.id, 'toTrackId': 9999}).status_code, 404)
        self.assertEqual(self.post(TRANSITION, {'fromTrackId': 9999, 'toTrackId': self.b.id}).status_code, 404)

    def test_una_pista_consigo_misma_devuelve_400(self):
        self.assertEqual(self.post(TRANSITION, {'fromTrackId': self.a.id, 'toTrackId': self.a.id}).status_code, 400)

    def test_peticiones_invalidas_devuelven_400(self):
        casos = [{}, {'fromTrackId': self.a.id}, {'toTrackId': self.b.id}, {'fromTrackId': 'x', 'toTrackId': 'y'}]
        for payload in casos:
            with self.subTest(payload=payload):
                self.assertEqual(self.post(TRANSITION, payload).status_code, 400)

    def test_get_devuelve_405(self):
        self.assertEqual(self.client.get(TRANSITION).status_code, 405)


class ExistingEndpointStillWorksTests(ViewTestCase):
    def test_mix_calculate_de_telemetry_sigue_funcionando(self):
        response = self.post('/api/mix/calculate', {'controlId': 14, 'value': 100})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')


FEEDBACK = '/api/mix/feedback'
WEIGHTS = '/api/mix/weights'


class WeightsInRecommendationsTests(ViewTestCase):
    def setUp(self):
        self.actual = crear_track('actual', bpm=128, camelot='8B')
        self.buen_tempo = crear_track('buen tempo', bpm=128, camelot='3A')        # armonia nula
        self.buena_armonia = crear_track('buena armonia', bpm=122, camelot='8B')  # tempo regular

    def ids(self, payload):
        return [c['track']['id'] for c in self.post(NEXT, payload).json()['candidates']]

    def test_sin_valoraciones_usa_los_pesos_por_defecto(self):
        # Con los pesos por defecto (45/40/15) la pista de buena armonia (tempo algo ajustado) supera a la de buen tempo.
        ids = self.ids({'trackId': self.actual.id})

        self.assertEqual(ids[0], self.buena_armonia.id)

    def test_con_pesos_aprendidos_que_priorizan_el_tempo_cambia_el_orden(self):
        LearnedWeights.objects.create(tempo=0.9, harmonic=0.05, energy=0.05, samples=50)

        ids = self.ids({'trackId': self.actual.id})

        self.assertEqual(ids[0], self.buen_tempo.id)

    def test_con_pesos_aprendidos_que_priorizan_la_armonia_gana_la_armonica(self):
        LearnedWeights.objects.create(tempo=0.05, harmonic=0.9, energy=0.05, samples=50)

        ids = self.ids({'trackId': self.actual.id})

        self.assertEqual(ids[0], self.buena_armonia.id)

    def test_el_plan_de_transicion_usa_los_pesos_aprendidos_en_su_puntuacion(self):
        LearnedWeights.objects.create(tempo=0.0, harmonic=1.0, energy=0.0, samples=50)

        plan = self.post(TRANSITION, {'fromTrackId': self.actual.id, 'toTrackId': self.buen_tempo.id}).json()

        self.assertEqual(plan['compatibility']['score'], 0.0)  # armonia nula y solo importa la armonia


class FeedbackViewTests(ViewTestCase):
    def setUp(self):
        self.a = crear_track('a', camelot='8B')
        self.b = crear_track('b', camelot='9B')

    def valorar(self, **extra):
        payload = {'fromTrackId': self.a.id, 'toTrackId': self.b.id, 'liked': True}
        payload.update(extra)
        return self.post(FEEDBACK, payload)

    def test_registra_la_valoracion_y_devuelve_los_pesos_vigentes(self):
        response = self.valorar()

        self.assertEqual(response.status_code, 201)
        cuerpo = response.json()
        self.assertEqual(set(cuerpo['weights']), {'tempo', 'harmonic', 'energy'})
        self.assertAlmostEqual(sum(cuerpo['weights'].values()), 1.0, places=6)
        self.assertEqual(cuerpo['samples'], 1)
        self.assertFalse(cuerpo['learned'])
        self.assertEqual(TransitionFeedback.objects.count(), 1)

    def test_guarda_si_gusto_o_no(self):
        self.valorar(liked=False)

        self.assertFalse(TransitionFeedback.objects.get().liked)

    def test_tras_suficientes_valoraciones_los_pesos_pasan_a_ser_aprendidos(self):
        mala = crear_track('mala', camelot='3A')
        for _ in range(MIN_SAMPLES):
            self.valorar(liked=True)
            self.post(FEEDBACK, {'fromTrackId': self.a.id, 'toTrackId': mala.id, 'liked': False})

        cuerpo = self.valorar(liked=True).json()

        self.assertTrue(cuerpo['learned'])
        self.assertEqual(cuerpo['samples'], MIN_SAMPLES * 2 + 1)

    def test_peticiones_invalidas_devuelven_400(self):
        casos = [
            {},
            {'fromTrackId': self.a.id, 'toTrackId': self.b.id},                   # falta liked
            {'fromTrackId': self.a.id, 'toTrackId': self.b.id, 'liked': 'si'},    # liked no es booleano
            {'fromTrackId': self.a.id, 'toTrackId': self.b.id, 'liked': 1},       # un entero no es un booleano
            {'fromTrackId': self.a.id, 'liked': True},                            # falta toTrackId
            {'fromTrackId': 'x', 'toTrackId': 'y', 'liked': True},
        ]
        for payload in casos:
            with self.subTest(payload=payload):
                self.assertEqual(self.post(FEEDBACK, payload).status_code, 400)
        self.assertEqual(TransitionFeedback.objects.count(), 0)

    def test_una_pista_consigo_misma_devuelve_400(self):
        self.assertEqual(self.valorar(toTrackId=self.a.id).status_code, 400)

    def test_pista_inexistente_devuelve_404(self):
        self.assertEqual(self.valorar(toTrackId=99999).status_code, 404)
        self.assertEqual(self.valorar(fromTrackId=99999).status_code, 404)
        self.assertEqual(TransitionFeedback.objects.count(), 0)

    def test_cuerpo_invalido_devuelve_400(self):
        self.assertEqual(self.post(FEEDBACK, raw='').status_code, 400)
        self.assertEqual(self.post(FEEDBACK, raw='{no es json').status_code, 400)

    def test_get_devuelve_405(self):
        self.assertEqual(self.client.get(FEEDBACK).status_code, 405)


class WeightsViewTests(ViewTestCase):
    def test_sin_aprendizaje_devuelve_los_pesos_por_defecto(self):
        response = self.client.get(WEIGHTS)

        self.assertEqual(response.status_code, 200)
        cuerpo = response.json()
        self.assertEqual(cuerpo['weights'], {'tempo': 0.45, 'harmonic': 0.4, 'energy': 0.15})
        self.assertFalse(cuerpo['learned'])
        self.assertEqual(cuerpo['samples'], 0)
        self.assertEqual(cuerpo['version'], 0)
        self.assertIsNone(cuerpo['accuracy'])
        self.assertIsNone(cuerpo['defaultAccuracy'])

    def test_con_pesos_aprendidos_devuelve_su_version_y_su_acierto(self):
        LearnedWeights.objects.create(
            tempo=0.2, harmonic=0.6, energy=0.2, samples=42, version=3, accuracy=0.85, default_accuracy=0.7)

        cuerpo = self.client.get(WEIGHTS).json()

        self.assertEqual(cuerpo['version'], 3)
        self.assertEqual(cuerpo['accuracy'], 0.85)
        self.assertEqual(cuerpo['defaultAccuracy'], 0.7)

    def test_si_el_acierto_no_se_pudo_medir_es_null(self):
        LearnedWeights.objects.create(tempo=0.2, harmonic=0.6, energy=0.2, samples=42)

        cuerpo = self.client.get(WEIGHTS).json()

        self.assertIsNone(cuerpo['accuracy'])
        self.assertEqual(cuerpo['version'], 1)

    def test_con_pesos_aprendidos_los_devuelve_con_el_numero_de_valoraciones(self):
        LearnedWeights.objects.create(tempo=0.2, harmonic=0.6, energy=0.2, samples=42)

        cuerpo = self.client.get(WEIGHTS).json()

        self.assertEqual(cuerpo['weights'], {'tempo': 0.2, 'harmonic': 0.6, 'energy': 0.2})
        self.assertTrue(cuerpo['learned'])
        self.assertEqual(cuerpo['samples'], 42)

    def test_el_conteo_incluye_las_valoraciones_aunque_aun_no_se_haya_aprendido(self):
        a, b = crear_track('a'), crear_track('b')
        TransitionFeedback.objects.create(from_track=a, to_track=b, tempo=1, harmonic=1, energy=1, liked=True)

        cuerpo = self.client.get(WEIGHTS).json()

        self.assertEqual(cuerpo['samples'], 1)
        self.assertFalse(cuerpo['learned'])

    def test_post_devuelve_405(self):
        self.assertEqual(self.client.post(WEIGHTS).status_code, 405)


class LearningLoopTests(ViewTestCase):
    """El bucle completo: el DJ valora transiciones y las recomendaciones se adaptan a su gusto."""

    def setUp(self):
        self.actual = crear_track('actual', bpm=128, camelot='8B')
        # Con los pesos por defecto gana la de tempo perfecto y armonia vecina...
        self.tempo_perfecto = crear_track('tempo perfecto', bpm=128, camelot='9B')
        # ...pero a este DJ le gustan las que mantienen la tonalidad aunque haya que ajustar el tempo.
        self.misma_tonalidad = crear_track('misma tonalidad', bpm=122, camelot='8B')

    def primera_recomendada(self):
        return self.post(NEXT, {'trackId': self.actual.id}).json()['candidates'][0]['track']['id']

    def valorar(self, destino, liked):
        return self.post(FEEDBACK, {'fromTrackId': self.actual.id, 'toTrackId': destino.id, 'liked': liked})

    def test_antes_de_valorar_gana_la_de_tempo_perfecto(self):
        self.assertEqual(self.primera_recomendada(), self.tempo_perfecto.id)

    def test_tras_valorar_el_orden_se_adapta_al_gusto_del_dj(self):
        for _ in range(MIN_SAMPLES + 2):
            self.valorar(self.misma_tonalidad, liked=True)
            self.valorar(self.tempo_perfecto, liked=False)

        self.assertEqual(self.primera_recomendada(), self.misma_tonalidad.id)

    def test_los_pesos_aprendidos_se_pueden_consultar_y_priorizan_la_armonia(self):
        for _ in range(MIN_SAMPLES + 2):
            self.valorar(self.misma_tonalidad, liked=True)
            self.valorar(self.tempo_perfecto, liked=False)

        cuerpo = self.client.get(WEIGHTS).json()

        self.assertTrue(cuerpo['learned'])
        self.assertGreater(cuerpo['weights']['harmonic'], 0.4)
        self.assertGreater(cuerpo['weights']['harmonic'], cuerpo['weights']['tempo'])

    def test_con_valoraciones_contrarias_el_orden_vuelve_a_favorecer_el_tempo(self):
        for _ in range(MIN_SAMPLES + 2):
            self.valorar(self.tempo_perfecto, liked=True)
            self.valorar(self.misma_tonalidad, liked=False)

        self.assertEqual(self.primera_recomendada(), self.tempo_perfecto.id)
