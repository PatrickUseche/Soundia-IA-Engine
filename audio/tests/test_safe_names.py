import re
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from audio.models import Track
from audio.storage import MAX_AUDIO_NAME_LENGTH, safe_audio_name
from audio.tests.media import TempMediaMixin
from audio.tests.signals import SR, click_track, to_wav_bytes

SEGURO = re.compile(r'^[A-Za-z0-9._-]+$')


class SafeAudioNameTests(SimpleTestCase):
    """Supabase Storage solo acepta nombres de objeto con caracteres 'seguros' de S3: una cancion con tildes
    (`Por_Qué_Sigues_con_Él.mp3`) fallaba al guardarse y el usuario veia un 500. El audio se guarda con un nombre ASCII."""

    def test_quita_las_tildes_y_las_enes(self):
        self.assertEqual(safe_audio_name('Por Qué Sigues con Él.mp3'), 'Por_Que_Sigues_con_El.mp3')
        self.assertEqual(safe_audio_name('Ñengo Flow - Cuando Me Dirá.mp3'), 'Nengo_Flow_-_Cuando_Me_Dira.mp3')

    def test_quita_parentesis_comas_y_otros_simbolos(self):
        self.assertEqual(safe_audio_name('Bryant, Kevin (Remix) [Video Oficial] #1.mp3'), 'Bryant_Kevin_Remix_Video_Oficial_1.mp3')

    def test_quita_los_caracteres_invisibles(self):
        self.assertEqual(safe_audio_name('﻿Anuel AA - ﻿Bugatti.mp3'), 'Anuel_AA_-_Bugatti.mp3')

    def test_conserva_la_extension_en_minusculas(self):
        self.assertTrue(safe_audio_name('Tema.MP3').endswith('.mp3'))

    def test_junta_los_espacios_y_guiones_bajos_repetidos(self):
        self.assertEqual(safe_audio_name('a    b___c.wav'), 'a_b_c.wav')

    def test_un_nombre_ya_seguro_no_cambia(self):
        self.assertEqual(safe_audio_name('cancion-1_final.wav'), 'cancion-1_final.wav')

    def test_el_resultado_solo_tiene_caracteres_seguros(self):
        for file_name in ('ÁÉÍÓÚ áéíóú ñÑ üÜ.mp3', '日本語の曲.mp3', 'a/b\\c:d*e?f"g<h>i|j.mp3', '../../etc/passwd', 'canción 😀.ogg'):
            with self.subTest(file_name=file_name):
                self.assertRegex(safe_audio_name(file_name), SEGURO)

    def test_no_deja_pasar_rutas_ni_puntos_al_principio(self):
        outcome = safe_audio_name('../../etc/passwd.mp3')

        self.assertNotIn('/', outcome)
        self.assertFalse(outcome.startswith('.'))

    def test_un_nombre_largo_se_acorta_sin_perder_la_extension(self):
        outcome = safe_audio_name('a' * 500 + '.flac')

        self.assertLessEqual(len(outcome), MAX_AUDIO_NAME_LENGTH)
        self.assertTrue(outcome.endswith('.flac'))

    def test_si_no_queda_nada_usa_un_nombre_por_defecto(self):
        self.assertEqual(safe_audio_name('日本語.mp3'), 'audio.mp3')
        self.assertEqual(safe_audio_name(''), 'audio')


def _wav(file_name):
    return SimpleUploadedFile(file_name, to_wav_bytes(click_track(120, 10, sr=SR, amplitude=0.5)), content_type='audio/wav')


class AnalyzeStoresSafeNameTests(TempMediaMixin, TestCase):
    def test_el_audio_se_guarda_con_un_nombre_seguro_y_el_titulo_conserva_el_original(self):
        respuesta = self.client.post('/api/audio/analyze', {'file': _wav('Por Qué Sigues con Él (Remix).wav')})

        self.assertEqual(respuesta.status_code, 201)
        track_obj = Track.objects.get()
        self.assertEqual(track_obj.title, 'Por Qué Sigues con Él (Remix).wav')
        self.assertRegex(track_obj.audio_file.name.split('/')[-1], SEGURO)
        self.assertIn('Por_Que_Sigues_con_El_Remix', track_obj.audio_file.name)

    def test_la_pista_se_puede_volver_a_descargar_con_su_nombre_seguro(self):
        self.client.post('/api/audio/analyze', {'file': _wav('Qué tal.wav')})
        track_obj = Track.objects.get()

        respuesta = self.client.get(f'/api/audio/tracks/{track_obj.id}/file')

        self.assertEqual(respuesta.status_code, 200)


class AnalyzeStorageFailureTests(TempMediaMixin, TestCase):
    """Si el audio no se puede guardar (Supabase caido, nombre rechazado, sin espacio), el usuario debe ver un motivo
    y no debe quedar una pista a medias (con datos pero sin audio) en la biblioteca."""

    def test_si_falla_al_guardar_el_audio_responde_un_error_claro_y_no_deja_la_pista(self):
        with mock.patch('django.core.files.storage.FileSystemStorage.save', side_effect=OSError('almacenamiento caido')):
            with self.assertLogs('audio.views', level='ERROR') as registro:
                respuesta = self.client.post('/api/audio/analyze', {'file': _wav('tema.wav')})

        self.assertEqual(respuesta.status_code, 502)
        self.assertIn('No se pudo guardar el audio', respuesta.json()['error'])
        self.assertEqual(Track.objects.count(), 0)
        self.assertIn('almacenamiento caido', '\n'.join(registro.output))
