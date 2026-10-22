import os
import tempfile
from unittest import mock

import numpy as np
from django.test import SimpleTestCase

from audio.tests.signals import SR, sine, to_wav_bytes
from audio.vocal_analysis import (
    SEPARATION_SAMPLE_RATE, analyze_first_vocals, analyze_last_vocals, analyze_vocals, start_analysis_enabled,
)
from audio.vocals import VOCAL_START_WINDOW_SECONDS, VOCAL_WINDOW_SECONDS


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


class AnalyzeFirstVocalsTests(SimpleTestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.wav')
        with os.fdopen(fd, 'wb') as archivo:
            archivo.write(to_wav_bytes(sine(220, 100.0, amplitude=0.3)))
        self.addCleanup(os.remove, self.path)

    def separador_con_voz_desde(self, segundos):
        recibido = {}

        def separador(audio):
            recibido['forma'] = audio.shape
            voz = np.zeros_like(audio)
            voz[:, int(segundos * SEPARATION_SAMPLE_RATE):] = 0.1
            return voz

        return separador, recibido

    def test_devuelve_donde_empieza_la_voz_en_segundos_de_la_pista(self):
        separador, _ = self.separador_con_voz_desde(15)

        self.assertEqual(analyze_first_vocals(self.path, 100.0, separator=separador), 15.0)

    def test_solo_separa_los_primeros_segundos_en_estereo_a_la_frecuencia_del_modelo(self):
        separador, recibido = self.separador_con_voz_desde(5)

        analyze_first_vocals(self.path, 100.0, separator=separador)

        canales, muestras = recibido['forma']
        self.assertEqual(canales, 2)
        self.assertAlmostEqual(muestras / SEPARATION_SAMPLE_RATE, VOCAL_START_WINDOW_SECONDS, delta=0.1)

    def test_sin_voz_en_la_ventana_es_none(self):
        self.assertIsNone(analyze_first_vocals(self.path, 100.0, separator=lambda audio: np.zeros_like(audio)))

    def test_una_pista_mas_corta_que_la_ventana_se_analiza_entera(self):
        separador, recibido = self.separador_con_voz_desde(4)

        resultado = analyze_first_vocals(self.path, 30.0, separator=separador)

        self.assertEqual(resultado, 4.0)
        self.assertAlmostEqual(recibido['forma'][1] / SEPARATION_SAMPLE_RATE, 30.0, delta=0.1)


class AnalyzeVocalsTests(SimpleTestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.wav')
        with os.fdopen(fd, 'wb') as archivo:
            archivo.write(to_wav_bytes(sine(220, 100.0, amplitude=0.3)))
        self.addCleanup(os.remove, self.path)

    @staticmethod
    def separador_con_voz_en(desde, hasta):
        def separador(audio):
            voz = np.zeros_like(audio)
            voz[:, int(desde * SEPARATION_SAMPLE_RATE):int(hasta * SEPARATION_SAMPLE_RATE)] = 0.1
            return voz

        return separador

    def test_analiza_el_final_y_el_inicio(self):
        # La misma voz de 8 a 25 s en las dos ventanas: en la del final (desde el s 40) acaba en 40 + 25.
        resultado = analyze_vocals(self.path, 100.0, with_start=True, separator=self.separador_con_voz_en(8, 25))

        self.assertEqual(resultado.first_start, 8.0)
        self.assertEqual(resultado.last_end, 65.0)
        self.assertEqual(resultado.window_start, 40.0)

    def test_sin_analizar_el_inicio_solo_hay_final(self):
        llamadas = []

        def separador(audio):
            llamadas.append(audio.shape)
            return np.zeros_like(audio)

        resultado = analyze_vocals(self.path, 100.0, with_start=False, separator=separador)

        self.assertIsNone(resultado.first_start)
        self.assertEqual(len(llamadas), 1)

    def test_las_dos_ventanas_se_separan_una_despues_de_otra(self):
        en_curso, maximo = [0], [0]

        def separador(audio):
            en_curso[0] += 1
            maximo[0] = max(maximo[0], en_curso[0])
            try:
                return np.zeros_like(audio)
            finally:
                en_curso[0] -= 1

        analyze_vocals(self.path, 100.0, with_start=True, separator=separador)

        self.assertEqual(maximo[0], 1)

    def test_el_inicio_se_enciende_con_una_variable_de_entorno(self):
        with mock.patch.dict(os.environ, {'VOCAL_ANALYSIS_START': 'on'}):
            self.assertTrue(start_analysis_enabled())
            resultado = analyze_vocals(self.path, 100.0, separator=self.separador_con_voz_en(8, 25))
        self.assertEqual(resultado.first_start, 8.0)

    def test_por_defecto_el_inicio_no_se_analiza(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('VOCAL_ANALYSIS_START', None)
            self.assertFalse(start_analysis_enabled())
            resultado = analyze_vocals(self.path, 100.0, separator=self.separador_con_voz_en(8, 25))
        self.assertIsNone(resultado.first_start)

    def test_off_o_cualquier_otro_valor_lo_deja_apagado(self):
        for valor in ('off', 'OFF', '', 'si', '0'):
            with mock.patch.dict(os.environ, {'VOCAL_ANALYSIS_START': valor}):
                self.assertFalse(start_analysis_enabled(), valor)
