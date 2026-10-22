from io import StringIO
from unittest import mock

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from audio import vocal_jobs
from audio.models import Track
from audio.separator import VocalSeparationUnavailable
from audio.tests.media import TempMediaMixin
from audio.vocal_analysis import VocalResult


def crear_pista(con_audio=True, **cambios):
    datos = dict(title='tema.wav', duration=200.0, bpm=128.0, key='C major', camelot='8B', energy=0.6)
    datos.update(cambios)
    pista = Track.objects.create(**datos)
    if con_audio:
        pista.audio_file.save('tema.wav', ContentFile(b'RIFF'), save=True)
    return pista


class RunVocalAnalysisTests(TempMediaMixin, TestCase):
    def test_guarda_hasta_donde_llega_la_voz_y_marca_la_pista_como_analizada(self):
        pista = crear_pista()
        analizador = mock.Mock(return_value=VocalResult(window_start=140.0, last_end=188.5))

        vocal_jobs.run_vocal_analysis(pista.id, analyzer=analizador)

        pista.refresh_from_db()
        self.assertEqual((pista.vocal_status, pista.vocal_last_end), ('done', 188.5))
        analizador.assert_called_once_with(pista.audio_file.path, 200.0)

    def test_sin_voz_al_final_queda_analizada_con_el_final_vacio(self):
        pista = crear_pista(vocal_last_end=150.0)

        vocal_jobs.run_vocal_analysis(pista.id, analyzer=lambda *args: VocalResult(140.0, None))

        pista.refresh_from_db()
        self.assertEqual((pista.vocal_status, pista.vocal_last_end), ('done', None))

    def test_mientras_analiza_la_pista_figura_como_analizando(self):
        pista = crear_pista()
        estados = []

        def analizador(*args):
            estados.append(Track.objects.get(pk=pista.id).vocal_status)
            return VocalResult(140.0, 180.0)

        vocal_jobs.run_vocal_analysis(pista.id, analyzer=analizador)

        self.assertEqual(estados, ['running'])

    def test_si_el_modelo_no_esta_instalado_la_pista_queda_como_no_disponible(self):
        pista = crear_pista()

        vocal_jobs.run_vocal_analysis(pista.id, analyzer=mock.Mock(side_effect=VocalSeparationUnavailable('x')))

        pista.refresh_from_db()
        self.assertEqual(pista.vocal_status, 'unavailable')

    def test_si_el_analisis_falla_queda_como_fallido_sin_romper_nada(self):
        pista = crear_pista()

        vocal_jobs.run_vocal_analysis(pista.id, analyzer=mock.Mock(side_effect=RuntimeError('memoria')))

        pista.refresh_from_db()
        self.assertEqual(pista.vocal_status, 'failed')

    def test_una_pista_sin_audio_guardado_falla(self):
        pista = crear_pista(con_audio=False)
        analizador = mock.Mock()

        vocal_jobs.run_vocal_analysis(pista.id, analyzer=analizador)

        pista.refresh_from_db()
        self.assertEqual(pista.vocal_status, 'failed')
        analizador.assert_not_called()

    def test_una_pista_borrada_se_ignora(self):
        vocal_jobs.run_vocal_analysis(9999, analyzer=mock.Mock())


@override_settings(VOCAL_ANALYSIS='auto')
class RequestVocalAnalysisTests(TempMediaMixin, TestCase):
    def test_con_el_modelo_disponible_la_pista_pasa_a_la_cola(self):
        pista = crear_pista()

        with mock.patch.object(vocal_jobs, 'is_available', return_value=True), \
                mock.patch.object(vocal_jobs, '_submit') as enviar:
            estado = vocal_jobs.request_vocal_analysis(pista)

        pista.refresh_from_db()
        self.assertEqual((estado, pista.vocal_status), ('pending', 'pending'))
        enviar.assert_called_once_with(pista.id)

    def test_sin_el_modelo_la_pista_queda_como_no_disponible_y_no_se_encola(self):
        pista = crear_pista()

        with mock.patch.object(vocal_jobs, 'is_available', return_value=False), \
                mock.patch.object(vocal_jobs, '_submit') as enviar:
            estado = vocal_jobs.request_vocal_analysis(pista)

        pista.refresh_from_db()
        self.assertEqual((estado, pista.vocal_status), ('unavailable', 'unavailable'))
        enviar.assert_not_called()

    @override_settings(VOCAL_ANALYSIS='off')
    def test_desactivado_por_configuracion_no_toca_la_pista(self):
        pista = crear_pista()

        with mock.patch.object(vocal_jobs, '_submit') as enviar:
            estado = vocal_jobs.request_vocal_analysis(pista)

        pista.refresh_from_db()
        self.assertEqual((estado, pista.vocal_status), ('none', 'none'))
        enviar.assert_not_called()

    def test_una_pista_ya_en_cola_o_analizando_no_se_encola_otra_vez(self):
        for estado in ('pending', 'running'):
            pista = crear_pista(vocal_status=estado)
            with mock.patch.object(vocal_jobs, 'is_available', return_value=True), \
                    mock.patch.object(vocal_jobs, '_submit') as enviar:
                self.assertEqual(vocal_jobs.request_vocal_analysis(pista), estado)
            enviar.assert_not_called()

    def test_una_pista_sin_audio_no_se_encola(self):
        pista = crear_pista(con_audio=False)

        with mock.patch.object(vocal_jobs, 'is_available', return_value=True), \
                mock.patch.object(vocal_jobs, '_submit') as enviar:
            vocal_jobs.request_vocal_analysis(pista)

        enviar.assert_not_called()


class AnalyzeVocalsCommandTests(TempMediaMixin, TestCase):
    def ejecutar(self, *args):
        salida = StringIO()
        with mock.patch.object(vocal_jobs, 'is_available', return_value=True):
            call_command('analyze_vocals', *args, stdout=salida)
        return salida.getvalue()

    def test_analiza_las_pistas_pendientes_de_analizar_con_su_audio(self):
        sin_analizar = crear_pista(title='a')
        ya_analizada = crear_pista(title='b', vocal_status='done', vocal_last_end=100.0)
        sin_audio = crear_pista(title='c', con_audio=False)
        analizador = mock.Mock(return_value=VocalResult(140.0, 180.0))

        with mock.patch.object(vocal_jobs, 'analyze_last_vocals', analizador):
            salida = self.ejecutar()

        sin_analizar.refresh_from_db()
        ya_analizada.refresh_from_db()
        sin_audio.refresh_from_db()
        self.assertEqual((sin_analizar.vocal_status, sin_analizar.vocal_last_end), ('done', 180.0))
        self.assertEqual(ya_analizada.vocal_last_end, 100.0)
        self.assertEqual(sin_audio.vocal_status, 'none')
        self.assertEqual(analizador.call_count, 1)
        self.assertIn('1 pista', salida)

    def test_con_all_reanaliza_tambien_las_ya_analizadas(self):
        crear_pista(title='a', vocal_status='done', vocal_last_end=100.0)
        analizador = mock.Mock(return_value=VocalResult(140.0, 180.0))

        with mock.patch.object(vocal_jobs, 'analyze_last_vocals', analizador):
            self.ejecutar('--all')

        self.assertEqual(analizador.call_count, 1)

    def test_sin_el_modelo_instalado_avisa_y_no_analiza_nada(self):
        crear_pista()
        salida = StringIO()

        with mock.patch.object(vocal_jobs, 'is_available', return_value=False):
            call_command('analyze_vocals', stdout=salida)

        self.assertIn('requirements-vocals.txt', salida.getvalue())
        self.assertEqual(Track.objects.get().vocal_status, 'none')
