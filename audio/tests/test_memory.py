from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from audio import memory
from audio.analysis import SilentAudioError
from audio.services import UnsupportedAudioError


class ReleaseMemoryTests(SimpleTestCase):
    def test_recoge_la_basura(self):
        with mock.patch('audio.memory.gc.collect') as recoger:
            memory.release_memory()

        recoger.assert_called_once()

    def test_en_linux_le_pide_a_glibc_que_devuelva_la_memoria(self):
        libc = mock.Mock()
        with mock.patch('audio.memory.sys.platform', 'linux'), mock.patch('audio.memory.ctypes.CDLL', return_value=libc):
            memory.release_memory()

        libc.malloc_trim.assert_called_once_with(0)

    def test_fuera_de_linux_no_toca_la_libc(self):
        with mock.patch('audio.memory.sys.platform', 'win32'), mock.patch('audio.memory.ctypes.CDLL') as cdll:
            memory.release_memory()

        cdll.assert_not_called()

    def test_con_una_libc_sin_malloc_trim_no_falla(self):
        with mock.patch('audio.memory.sys.platform', 'linux'), \
                mock.patch('audio.memory.ctypes.CDLL', side_effect=OSError('sin libc.so.6')):
            memory.release_memory()  # no lanza

    def test_si_la_libc_no_tiene_la_funcion_no_falla(self):
        libc = mock.Mock(spec=[])  # sin malloc_trim
        with mock.patch('audio.memory.sys.platform', 'linux'), mock.patch('audio.memory.ctypes.CDLL', return_value=libc):
            memory.release_memory()  # no lanza


class AnalizarLiberaMemoriaTests(TestCase):
    def subir(self):
        return self.client.post('/api/audio/analyze', {'file': SimpleUploadedFile('a.wav', b'RIFF')})

    def test_libera_la_memoria_despues_de_un_analisis_correcto(self):
        analisis = mock.Mock(
            duration=10.0, bpm=120.0, key='C major', camelot='8B', energy=0.5, cue_points=[0.0], grid_offset=None,
            grid_downbeat=None, grid_confidence=None, tempo_wobble_ms=None)
        with mock.patch('audio.views.analyze_file', return_value=analisis), \
                mock.patch('audio.views.release_memory') as liberar:
            self.subir()

        liberar.assert_called_once()

    def test_tambien_la_libera_si_el_analisis_falla(self):
        for error, codigo in ((UnsupportedAudioError('mal'), 400), (SilentAudioError('silencio'), 422)):
            with self.subTest(error=type(error).__name__):
                with mock.patch('audio.views.analyze_file', side_effect=error), \
                        mock.patch('audio.views.release_memory') as liberar:
                    respuesta = self.subir()

                self.assertEqual(respuesta.status_code, codigo)
                liberar.assert_called_once()
