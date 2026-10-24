from django.test import TestCase, override_settings

URL = '/api/audio/tracks'


class ServiceTokenTests(TestCase):
    @override_settings(SERVICE_TOKEN='')
    def test_sin_clave_configurada_responde_a_todos(self):
        self.assertEqual(self.client.get(URL).status_code, 200)

    @override_settings(SERVICE_TOKEN='clave-larga')
    def test_con_clave_configurada_rechaza_sin_cabecera(self):
        respuesta = self.client.get(URL)
        self.assertEqual(respuesta.status_code, 401)
        self.assertIn('error', respuesta.json())

    @override_settings(SERVICE_TOKEN='clave-larga')
    def test_con_clave_configurada_rechaza_una_clave_incorrecta(self):
        self.assertEqual(self.client.get(URL, headers={'X-Soundia-Key': 'otra'}).status_code, 401)

    @override_settings(SERVICE_TOKEN='clave-larga')
    def test_con_clave_correcta_responde(self):
        self.assertEqual(self.client.get(URL, headers={'X-Soundia-Key': 'clave-larga'}).status_code, 200)

    @override_settings(SERVICE_TOKEN='clave-larga')
    def test_tambien_protege_las_escrituras(self):
        self.assertEqual(self.client.post('/api/audio/analyze').status_code, 401)
