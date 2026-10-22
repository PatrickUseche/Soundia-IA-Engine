import os
import tempfile

import numpy as np
from django.test import SimpleTestCase

from audio.tests.signals import SR, sine, to_wav_bytes
from audio.vocal_analysis import SEPARATION_SAMPLE_RATE, analyze_last_vocals
from audio.vocals import VOCAL_WINDOW_SECONDS


class AnalyzeLastVocalsTests(SimpleTestCase):
    def setUp(self):
        # Una pista de 100 s; su ventana de analisis son los ultimos 60 s (desde el segundo 40).
        fd, self.path = tempfile.mkstemp(suffix='.wav')
        with os.fdopen(fd, 'wb') as archivo:
            archivo.write(to_wav_bytes(sine(220, 100.0, amplitude=0.3)))
        self.addCleanup(os.remove, self.path)

    def separador_con_voz_hasta(self, segundos):
        recibido = {}

        def separador(audio):
            recibido['forma'] = audio.shape
            voz = np.zeros_like(audio)
            voz[:, :int(segundos * SEPARATION_SAMPLE_RATE)] = 0.1
            return voz

        return separador, recibido

    def test_devuelve_hasta_donde_llega_la_voz_en_segundos_de_la_pista(self):
        separador, _ = self.separador_con_voz_hasta(20)

        resultado = analyze_last_vocals(self.path, duration=100.0, separator=separador)

        self.assertEqual(resultado.window_start, 100.0 - VOCAL_WINDOW_SECONDS)
        self.assertEqual(resultado.last_end, 60.0)  # 40 + 20

    def test_solo_separa_la_ventana_final_en_estereo_a_la_frecuencia_del_modelo(self):
        separador, recibido = self.separador_con_voz_hasta(5)

        analyze_last_vocals(self.path, duration=100.0, separator=separador)

        canales, muestras = recibido['forma']
        self.assertEqual(canales, 2)
        self.assertAlmostEqual(muestras / SEPARATION_SAMPLE_RATE, VOCAL_WINDOW_SECONDS, delta=0.1)

    def test_si_no_hay_voz_en_la_ventana_el_final_es_none(self):
        resultado = analyze_last_vocals(self.path, duration=100.0, separator=lambda audio: np.zeros_like(audio))

        self.assertIsNone(resultado.last_end)

    def test_una_pista_mas_corta_que_la_ventana_se_analiza_entera(self):
        separador, recibido = self.separador_con_voz_hasta(10)

        resultado = analyze_last_vocals(self.path, duration=30.0, separator=separador)

        self.assertEqual(resultado.window_start, 0.0)
        self.assertEqual(resultado.last_end, 10.0)
        self.assertAlmostEqual(recibido['forma'][1] / SEPARATION_SAMPLE_RATE, 30.0, delta=0.1)
