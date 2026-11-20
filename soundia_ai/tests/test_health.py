from unittest import mock

from django.db import OperationalError
from django.test import TestCase, override_settings

URL = '/health/'


class HealthTests(TestCase):
    def test_responde_ok_cuando_la_base_de_datos_contesta(self):
        respuesta = self.client.get(URL)

        self.assertEqual(respuesta.status_code, 200)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['status'], 'ok')
        self.assertEqual(cuerpo['database'], 'ok')
        self.assertIn('database_ms', cuerpo)

    @override_settings(SERVICE_TOKEN='clave-larga')
    def test_no_pide_la_clave_de_servicio(self):
        # Lo consultan el comprobador de salud y el que mantiene despierto el servicio, que no llevan la clave.
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_responde_503_si_la_base_de_datos_falla(self):
        with mock.patch('soundia_ai.health.connection') as conexion:
            conexion.cursor.side_effect = OperationalError('no hay conexion')

            respuesta = self.client.get(URL)

        self.assertEqual(respuesta.status_code, 503)
        self.assertEqual(respuesta.json()['status'], 'error')
        self.assertEqual(respuesta.json()['database'], 'error')

    def test_no_filtra_el_detalle_del_error(self):
        with mock.patch('soundia_ai.health.connection') as conexion:
            conexion.cursor.side_effect = OperationalError('password authentication failed for user x')

            respuesta = self.client.get(URL)

        self.assertNotIn('password', respuesta.content.decode())

    @override_settings(SERVICE_TOKEN='clave-larga')
    def test_el_resto_de_rutas_siguen_protegidas(self):
        self.assertEqual(self.client.get('/api/audio/tracks').status_code, 401)
