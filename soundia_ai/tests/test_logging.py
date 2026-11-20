import logging
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase


class RegistroDeErroresTests(TestCase):
    """Con DJANGO_DEBUG=False (Render) Django no imprime la traza de un 500 en la consola: solo la manda por correo a
    unos administradores que no existen. El log mostraba `POST /api/audio/analyze 500` sin ningun motivo y no habia
    forma de saber que fallo. Los errores 500 deben quedar en la consola (el log de Render) con su traza."""

    def test_los_errores_de_las_peticiones_van_a_un_manejador_de_consola_sin_filtros(self):
        manejadores = logging.getLogger('django.request').handlers

        consolas = [m for m in manejadores if isinstance(m, logging.StreamHandler)]

        self.assertTrue(consolas, 'django.request no tiene un manejador de consola')
        for consola in consolas:
            # Sin el filtro `require_debug_true` de Django, que lo apaga justo en produccion.
            self.assertEqual(consola.filters, [])

    def test_la_consola_deja_pasar_los_errores(self):
        consolas = [m for m in logging.getLogger('django.request').handlers if isinstance(m, logging.StreamHandler)]

        for consola in consolas:
            self.assertLessEqual(consola.level, logging.ERROR)

    def test_un_fallo_dentro_de_analyze_deja_la_traza_en_el_registro(self):
        self.client.raise_request_exception = False
        archivo = SimpleUploadedFile('tema.wav', b'no importa', content_type='audio/wav')

        with mock.patch('audio.views.analyze_file', side_effect=RuntimeError('fallo de prueba')):
            with self.assertLogs('django.request', level='ERROR') as registro:
                respuesta = self.client.post('/api/audio/analyze', {'file': archivo})

        self.assertEqual(respuesta.status_code, 500)
        texto = '\n'.join(registro.output)
        self.assertIn('/api/audio/analyze', texto)
        self.assertIn('RuntimeError', texto)
        self.assertIn('fallo de prueba', texto)
