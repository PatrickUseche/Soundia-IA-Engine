import json
from io import StringIO
from unittest import mock

from django.test import SimpleTestCase

from audio import vocal_worker
from audio.separator import VocalSeparationUnavailable
from audio.vocal_analysis import VocalResult


class VocalWorkerTests(SimpleTestCase):
    def ejecutar(self, resultado=None, error=None):
        salida = StringIO()
        with mock.patch.object(vocal_worker, 'analyze_last_vocals', return_value=resultado, side_effect=error), \
                mock.patch.object(vocal_worker.sys, 'stdout', salida):
            codigo = vocal_worker.main(['vocal_worker', '/audio/tema.mp3', '200.0'])
        return codigo, salida.getvalue()

    def test_imprime_el_resultado_como_json_y_sale_bien(self):
        codigo, salida = self.ejecutar(resultado=VocalResult(window_start=140.0, last_end=188.5))

        self.assertEqual(codigo, 0)
        self.assertEqual(json.loads(salida.strip().splitlines()[-1]), {'window_start': 140.0, 'last_end': 188.5})

    def test_pasa_la_ruta_y_la_duracion_al_analisis(self):
        with mock.patch.object(vocal_worker, 'analyze_last_vocals', return_value=VocalResult(0.0, None)) as analisis, \
                mock.patch.object(vocal_worker.sys, 'stdout', StringIO()):
            vocal_worker.main(['vocal_worker', '/audio/tema.mp3', '200.0'])

        analisis.assert_called_once_with('/audio/tema.mp3', 200.0)

    def test_sin_el_modelo_instalado_sale_con_el_codigo_de_no_disponible(self):
        codigo, _ = self.ejecutar(error=VocalSeparationUnavailable('x'))

        self.assertEqual(codigo, vocal_worker.UNAVAILABLE_EXIT_CODE)

    def test_con_argumentos_incorrectos_sale_con_error(self):
        with mock.patch.object(vocal_worker.sys, 'stderr', StringIO()):
            self.assertEqual(vocal_worker.main(['vocal_worker']), 2)
