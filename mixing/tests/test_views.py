import json

from django.test import TestCase

from audio.models import Track

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
