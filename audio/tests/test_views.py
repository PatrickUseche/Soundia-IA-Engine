import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from audio.models import Track
from audio.tests.media import TempMediaMixin
from audio.tests.signals import SR, chord, click_track, sine, to_wav_bytes

ANALYZE = '/api/audio/analyze'
TRACKS = '/api/audio/tracks'


def cancion(bpm=120, seconds=30, sr=SR):
    acordes = np.concatenate([
        chord([0, 4, 7], 2, sr=sr), chord([5, 9, 0], 2, sr=sr),
        chord([7, 11, 2], 2, sr=sr), chord([0, 4, 7], 2, sr=sr),
    ])
    armonia = np.tile(acordes, int(seconds / 8) + 1)[: int(seconds * sr)]
    return click_track(bpm, seconds, sr=sr, amplitude=0.5) + armonia


def wav(y, sr=SR, nombre='tema.wav'):
    return SimpleUploadedFile(nombre, to_wav_bytes(y, sr), content_type='audio/wav')


class AnalyzeTrackViewTests(TempMediaMixin, TestCase):
    def subir(self, archivo, **extra):
        return self.client.post(ANALYZE, {'file': archivo, **extra})

    def test_analiza_y_guarda_la_pista(self):
        response = self.subir(wav(cancion(bpm=124)))

        self.assertEqual(response.status_code, 201)
        cuerpo = response.json()
        self.assertAlmostEqual(cuerpo['bpm'], 124, delta=2)
        self.assertEqual(cuerpo['key'], 'C major')
        self.assertEqual(cuerpo['camelot'], '8B')
        self.assertGreater(cuerpo['energy'], 0)
        self.assertGreaterEqual(len(cuerpo['cuePoints']), 1)
        self.assertEqual(Track.objects.count(), 1)
        self.assertEqual(Track.objects.get().camelot, '8B')

    def test_el_titulo_por_defecto_es_el_nombre_del_archivo(self):
        response = self.subir(wav(cancion(), nombre='mi_tema.wav'))

        self.assertEqual(response.json()['title'], 'mi_tema.wav')

    def test_el_titulo_enviado_tiene_prioridad(self):
        response = self.subir(wav(cancion(), nombre='mi_tema.wav'), title='Mi tema (Extended Mix)')

        self.assertEqual(response.json()['title'], 'Mi tema (Extended Mix)')

    def test_un_archivo_grande_que_django_guarda_en_disco_tambien_se_analiza(self):
        # A 44.1 kHz, 40 s pesan ~3.5 MB: supera los 2.5 MB que Django mantiene en memoria.
        archivo = wav(cancion(seconds=40, sr=44100), sr=44100)
        self.assertGreater(archivo.size, 2_621_440)

        response = self.subir(archivo)

        self.assertEqual(response.status_code, 201)
        self.assertAlmostEqual(response.json()['bpm'], 120, delta=2)

    def test_sin_archivo_devuelve_400(self):
        response = self.client.post(ANALYZE, {})

        self.assertEqual(response.status_code, 400)
        self.assertIn("'file'", response.json()['error'])
        self.assertEqual(Track.objects.count(), 0)

    def test_un_archivo_que_no_es_audio_devuelve_400(self):
        basura = SimpleUploadedFile('nota.txt', b'esto no es audio' * 20, content_type='text/plain')

        response = self.subir(basura)

        self.assertEqual(response.status_code, 400)
        self.assertIn('WAV', response.json()['error'])
        self.assertEqual(Track.objects.count(), 0)

    def test_un_audio_demasiado_corto_devuelve_422(self):
        response = self.subir(wav(sine(440, 1.0)))

        self.assertEqual(response.status_code, 422)
        self.assertEqual(Track.objects.count(), 0)

    def test_un_audio_en_silencio_devuelve_422(self):
        response = self.subir(wav(np.zeros(SR * 5)))

        self.assertEqual(response.status_code, 422)
        self.assertEqual(Track.objects.count(), 0)

    @override_settings(AUDIO_MAX_UPLOAD_BYTES=1000)
    def test_un_archivo_que_supera_el_limite_devuelve_413(self):
        response = self.subir(wav(cancion(seconds=10)))

        self.assertEqual(response.status_code, 413)
        self.assertEqual(Track.objects.count(), 0)

    def test_get_devuelve_405(self):
        self.assertEqual(self.client.get(ANALYZE).status_code, 405)

    def test_guarda_el_audio_original_para_poder_reproducirlo(self):
        original = to_wav_bytes(cancion(bpm=124))

        response = self.subir(SimpleUploadedFile('tema.wav', original, content_type='audio/wav'))

        track = Track.objects.get(pk=response.json()['id'])
        self.assertTrue(track.audio_file)
        with track.audio_file.open('rb') as archivo:
            self.assertEqual(archivo.read(), original)
        self.assertTrue(response.json()['hasAudio'])

    def test_un_audio_que_no_se_pudo_analizar_no_deja_archivos_guardados(self):
        import os
        from django.conf import settings
        carpeta = os.path.join(settings.MEDIA_ROOT, 'tracks')
        # La carpeta temporal se comparte entre las pruebas de la clase: se compara antes y despues.
        antes = sorted(os.listdir(carpeta)) if os.path.exists(carpeta) else []

        self.subir(wav(sine(440, 1.0)))

        despues = sorted(os.listdir(carpeta)) if os.path.exists(carpeta) else []
        self.assertEqual(despues, antes)
        self.assertEqual(Track.objects.count(), 0)


class TrackQueryViewTests(TempMediaMixin, TestCase):
    def crear(self, titulo, **cambios):
        datos = dict(title=titulo, duration=200.0, bpm=128.0, key='C major', camelot='8B',
                     energy=0.5, cue_points=[0.0, 30.0])
        datos.update(cambios)
        return Track.objects.create(**datos)

    def test_lista_las_pistas_mas_recientes_primero(self):
        self.crear('primera')
        self.crear('segunda')

        response = self.client.get(TRACKS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([t['title'] for t in response.json()['tracks']], ['segunda', 'primera'])

    def test_la_lista_esta_vacia_sin_pistas(self):
        self.assertEqual(self.client.get(TRACKS).json(), {'tracks': []})

    def test_la_lista_se_limita_a_50(self):
        for i in range(55):
            self.crear(f'pista {i}')

        self.assertEqual(len(self.client.get(TRACKS).json()['tracks']), 50)

    def test_detalle_de_una_pista(self):
        track = self.crear('mi pista', cue_points=[0.0, 16.5])

        response = self.client.get(f'{TRACKS}/{track.id}')

        self.assertEqual(response.status_code, 200)
        cuerpo = response.json()
        self.assertEqual(cuerpo['id'], track.id)
        self.assertEqual(cuerpo['cuePoints'], [0.0, 16.5])
        self.assertEqual(cuerpo['camelot'], '8B')

    def test_detalle_inexistente_devuelve_404(self):
        self.assertEqual(self.client.get(f'{TRACKS}/9999').status_code, 404)

    def test_post_en_el_listado_devuelve_405(self):
        self.assertEqual(self.client.post(TRACKS).status_code, 405)


class TrackFileViewTests(TempMediaMixin, TestCase):
    def crear_con_audio(self, contenido=b'RIFFdatos', nombre='tema.wav'):
        track = Track.objects.create(
            title=nombre, duration=10.0, bpm=128.0, key='C major', camelot='8B', energy=0.5, cue_points=[0.0])
        track.audio_file.save(nombre, SimpleUploadedFile(nombre, contenido))
        return track

    def test_devuelve_el_audio_guardado(self):
        track = self.crear_con_audio(b'RIFFdatos')

        response = self.client.get(f'{TRACKS}/{track.id}/file')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'RIFFdatos')

    def test_el_tipo_de_contenido_depende_de_la_extension(self):
        casos = {'tema.wav': 'audio/', 'tema.mp3': 'audio/mpeg', 'tema.flac': 'audio/'}
        for nombre, esperado in casos.items():
            with self.subTest(nombre=nombre):
                track = self.crear_con_audio(nombre=nombre)

                response = self.client.get(f'{TRACKS}/{track.id}/file')

                self.assertTrue(response['Content-Type'].startswith(esperado), response['Content-Type'])

    def test_indica_la_longitud_para_poder_mostrar_progreso_de_descarga(self):
        track = self.crear_con_audio(b'12345')

        response = self.client.get(f'{TRACKS}/{track.id}/file')

        self.assertEqual(response['Content-Length'], '5')

    def test_pista_inexistente_devuelve_404(self):
        self.assertEqual(self.client.get(f'{TRACKS}/9999/file').status_code, 404)

    def test_pista_sin_audio_devuelve_404_con_mensaje(self):
        track = Track.objects.create(
            title='sin audio', duration=10.0, bpm=128.0, key='C major', camelot='8B', energy=0.5)

        response = self.client.get(f'{TRACKS}/{track.id}/file')

        self.assertEqual(response.status_code, 404)
        self.assertIn('audio', response.json()['error'].lower())

    def test_si_el_archivo_se_borro_del_disco_devuelve_404(self):
        track = self.crear_con_audio()
        track.audio_file.delete(save=False)
        track.audio_file.name = 'tracks/borrado.wav'
        track.save()

        self.assertEqual(self.client.get(f'{TRACKS}/{track.id}/file').status_code, 404)

    def test_post_devuelve_405(self):
        track = self.crear_con_audio()

        self.assertEqual(self.client.post(f'{TRACKS}/{track.id}/file').status_code, 405)

    def test_el_detalle_incluye_el_estado_del_analisis_de_voz(self):
        sin_analizar = Track.objects.create(
            title='x', duration=1.0, bpm=128.0, key='C major', camelot='8B', energy=0.5)
        analizada = Track.objects.create(
            title='y', duration=300.0, bpm=128.0, key='C major', camelot='8B', energy=0.5,
            vocal_status=Track.VOCALS_DONE, vocal_last_end=290.5)

        self.assertEqual(self.client.get(f'{TRACKS}/{sin_analizar.id}').json()['vocals'],
                         {'status': 'none', 'lastEnd': None})
        self.assertEqual(self.client.get(f'{TRACKS}/{analizada.id}').json()['vocals'],
                         {'status': 'done', 'lastEnd': 290.5})

    def test_el_detalle_indica_si_la_pista_tiene_audio(self):
        con_audio = self.crear_con_audio()
        sin_audio = Track.objects.create(
            title='x', duration=1.0, bpm=128.0, key='C major', camelot='8B', energy=0.5)

        self.assertTrue(self.client.get(f'{TRACKS}/{con_audio.id}').json()['hasAudio'])
        self.assertFalse(self.client.get(f'{TRACKS}/{sin_audio.id}').json()['hasAudio'])
