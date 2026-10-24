import json

import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest import mock

from django.test import TestCase, override_settings

from audio.models import Track
from audio.tests.media import TempMediaMixin
from audio.tests.signals import SR, chord, click_track, sine, to_wav_bytes
from audio.tests.test_beatgrid import circular_error

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

    def test_una_pista_nueva_no_tiene_genero(self):
        self.assertEqual(self.subir(wav(cancion())).json()['genre'], '')

    def test_se_puede_poner_el_genero_al_subir_la_pista(self):
        response = self.subir(wav(cancion()), genre='  Salsa  Brava ')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['genre'], 'salsa brava')
        self.assertEqual(Track.objects.get().genre, 'salsa brava')

    def test_un_genero_demasiado_largo_se_rechaza_antes_de_analizar(self):
        response = self.subir(wav(cancion()), genre='x' * 41)

        self.assertEqual(response.status_code, 400)
        self.assertIn('genre', response.json()['error'])
        self.assertEqual(Track.objects.count(), 0)

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


class VocalAnalysisViewTests(TempMediaMixin, TestCase):
    def crear(self, **cambios):
        datos = dict(title='x', duration=200.0, bpm=128.0, key='C major', camelot='8B', energy=0.5)
        datos.update(cambios)
        return Track.objects.create(**datos)

    def test_subir_una_pista_pide_analizar_su_voz_y_responde_con_el_estado(self):
        def pedir(track):
            track.vocal_status = Track.VOCALS_PENDING
            track.save(update_fields=['vocal_status'])
            return track.vocal_status

        with mock.patch('audio.views.request_vocal_analysis', side_effect=pedir) as pedido:
            response = self.client.post(ANALYZE, {'file': wav(cancion(bpm=124))})

        self.assertEqual(response.status_code, 201)
        pedido.assert_called_once()
        self.assertEqual(response.json()['vocals']['status'], 'pending')

    def test_pedir_el_analisis_de_voz_de_una_pista_existente(self):
        pista = self.crear()

        with mock.patch('audio.views.request_vocal_analysis', return_value='pending') as pedido,                 mock.patch('audio.views.is_available', return_value=True):
            response = self.client.post(f'{TRACKS}/{pista.id}/vocals')

        self.assertEqual(response.status_code, 202)
        pedido.assert_called_once_with(pista)

    def test_sin_el_modelo_instalado_responde_503_y_lo_explica(self):
        pista = self.crear()

        with mock.patch('audio.views.is_available', return_value=False):
            response = self.client.post(f'{TRACKS}/{pista.id}/vocals')

        self.assertEqual(response.status_code, 503)
        self.assertIn('requirements-vocals.txt', response.json()['error'])

    def test_pista_inexistente_devuelve_404(self):
        self.assertEqual(self.client.post(f'{TRACKS}/9999/vocals').status_code, 404)

    def test_solo_acepta_post(self):
        pista = self.crear()

        self.assertEqual(self.client.get(f'{TRACKS}/{pista.id}/vocals').status_code, 405)


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

    @override_settings(TRACK_LIST_LIMIT=50)
    def test_la_lista_se_limita_al_maximo_configurado(self):
        for i in range(55):
            self.crear(f'pista {i}')

        self.assertEqual(len(self.client.get(TRACKS).json()['tracks']), 50)

    def test_por_defecto_la_lista_llega_a_200_pistas(self):
        from django.conf import settings
        self.assertEqual(settings.TRACK_LIST_LIMIT, 200)

    @override_settings(TRACK_LIST_LIMIT=200)
    def test_con_mas_de_50_pistas_las_devuelve_todas_hasta_el_maximo(self):
        for i in range(60):
            self.crear(f'pista {i}')

        self.assertEqual(len(self.client.get(TRACKS).json()['tracks']), 60)

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


class GeneroDeLaPistaViewTests(TestCase):
    def setUp(self):
        self.track = Track.objects.create(
            title='tema', duration=200.0, bpm=128.0, key='C major', camelot='8B', energy=0.5, cue_points=[0.0])

    def poner(self, cuerpo, pk=None):
        return self.client.put(
            f'{TRACKS}/{pk or self.track.id}', data=json.dumps(cuerpo) if not isinstance(cuerpo, str) else cuerpo,
            content_type='application/json')

    def test_pone_el_genero_y_devuelve_la_pista(self):
        response = self.poner({'genre': 'Bachata'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['genre'], 'bachata')
        self.track.refresh_from_db()
        self.assertEqual(self.track.genre, 'bachata')

    def test_normaliza_espacios_y_mayusculas(self):
        self.assertEqual(self.poner({'genre': '  DISCO   Bar '}).json()['genre'], 'disco bar')

    def test_un_genero_vacio_lo_quita(self):
        self.poner({'genre': 'salsa'})

        self.assertEqual(self.poner({'genre': ''}).json()['genre'], '')

    def test_el_detalle_y_el_listado_incluyen_el_genero(self):
        self.poner({'genre': 'merengue'})

        self.assertEqual(self.client.get(f'{TRACKS}/{self.track.id}').json()['genre'], 'merengue')
        self.assertEqual(self.client.get(TRACKS).json()['tracks'][0]['genre'], 'merengue')

    def test_rechaza_lo_que_no_es_un_genero_valido(self):
        for cuerpo in ({'genre': 5}, {'genre': None}, {'genre': 'x' * 41}, {}, [], 'no-json', ''):
            with self.subTest(cuerpo=cuerpo):
                self.assertEqual(self.poner(cuerpo).status_code, 400)
        self.track.refresh_from_db()
        self.assertEqual(self.track.genre, '')

    def test_pista_inexistente_devuelve_404(self):
        self.assertEqual(self.poner({'genre': 'salsa'}, pk=9999).status_code, 404)

    def test_no_exige_token_csrf(self):
        from django.test import Client

        response = Client(enforce_csrf_checks=True).put(
            f'{TRACKS}/{self.track.id}', data='{"genre": "salsa"}', content_type='application/json')

        self.assertEqual(response.status_code, 200)


class BorrarPistaViewTests(TempMediaMixin, TestCase):
    def crear_con_audio(self, nombre='tema.wav'):
        track = Track.objects.create(
            title=nombre, duration=10.0, bpm=128.0, key='C major', camelot='8B', energy=0.5, cue_points=[0.0])
        track.audio_file.save(nombre, SimpleUploadedFile(nombre, b'RIFFdatos'))
        return track

    def test_borra_la_pista_y_su_audio(self):
        track = self.crear_con_audio()
        storage, nombre = track.audio_file.storage, track.audio_file.name
        self.assertTrue(storage.exists(nombre))

        response = self.client.delete(f'{TRACKS}/{track.id}')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Track.objects.filter(pk=track.id).exists())
        self.assertFalse(storage.exists(nombre))

    def test_borra_una_pista_sin_audio(self):
        track = Track.objects.create(
            title='sin audio', duration=10.0, bpm=128.0, key='C major', camelot='8B', energy=0.5)

        self.assertEqual(self.client.delete(f'{TRACKS}/{track.id}').status_code, 204)
        self.assertFalse(Track.objects.filter(pk=track.id).exists())

    def test_pista_inexistente_devuelve_404(self):
        self.assertEqual(self.client.delete(f'{TRACKS}/9999').status_code, 404)

    def test_no_borra_las_demas_pistas(self):
        borrada = self.crear_con_audio('a.wav')
        otra = self.crear_con_audio('b.wav')

        self.client.delete(f'{TRACKS}/{borrada.id}')

        self.assertTrue(Track.objects.filter(pk=otra.id).exists())
        self.assertTrue(otra.audio_file.storage.exists(otra.audio_file.name))

    def test_si_falla_el_almacenamiento_conserva_la_pista_y_avisa(self):
        track = self.crear_con_audio()

        with mock.patch('django.db.models.fields.files.FieldFile.delete', side_effect=OSError('sin red')):
            response = self.client.delete(f'{TRACKS}/{track.id}')

        self.assertEqual(response.status_code, 502)
        self.assertIn('error', response.json())
        self.assertTrue(Track.objects.filter(pk=track.id).exists())

    def test_no_exige_token_csrf(self):
        from django.test import Client
        track = self.crear_con_audio()

        response = Client(enforce_csrf_checks=True).delete(f'{TRACKS}/{track.id}')

        self.assertEqual(response.status_code, 204)

    def test_otros_metodos_siguen_dando_405(self):
        track = self.crear_con_audio()

        self.assertEqual(self.client.post(f'{TRACKS}/{track.id}').status_code, 405)
        self.assertEqual(self.client.patch(f'{TRACKS}/{track.id}').status_code, 405)


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

    def test_el_detalle_incluye_la_rejilla_de_pulsos(self):
        sin_rejilla = Track.objects.create(
            title='x', duration=1.0, bpm=128.0, key='C major', camelot='8B', energy=0.5)
        con_rejilla = Track.objects.create(
            title='y', duration=300.0, bpm=110.0, key='C major', camelot='8B', energy=0.5,
            grid_offset=0.0239, grid_downbeat=0.5844, grid_confidence=0.585)

        self.assertIsNone(self.client.get(f'{TRACKS}/{sin_rejilla.id}').json()['grid'])
        self.assertEqual(self.client.get(f'{TRACKS}/{con_rejilla.id}').json()['grid'],
                         {'offset': 0.0239, 'downbeat': 0.5844, 'confidence': 0.585, 'manual': False})

    def test_subir_una_pista_con_ritmo_guarda_su_rejilla(self):
        response = self.client.post(ANALYZE, {'file': wav(click_track(110.0, 30, first_beat=0.2))})

        cuerpo = response.json()
        self.assertEqual(response.status_code, 201)
        # Con solo 30 s de audio el tempo se afina a unas centesimas: en una cancion entera, a menos.
        self.assertAlmostEqual(cuerpo['bpm'], 110.0, delta=0.06)
        self.assertIsNotNone(cuerpo['grid'])
        self.assertLess(abs(circular_error(cuerpo['grid']['offset'], 0.2, 60 / 110)), 0.006)

    def test_el_detalle_incluye_el_estado_del_analisis_de_voz(self):
        sin_analizar = Track.objects.create(
            title='x', duration=1.0, bpm=128.0, key='C major', camelot='8B', energy=0.5)
        analizada = Track.objects.create(
            title='y', duration=300.0, bpm=128.0, key='C major', camelot='8B', energy=0.5,
            vocal_status=Track.VOCALS_DONE, vocal_last_end=290.5, vocal_first_start=14.0)

        self.assertEqual(self.client.get(f'{TRACKS}/{sin_analizar.id}').json()['vocals'],
                         {'status': 'none', 'lastEnd': None, 'firstStart': None})
        self.assertEqual(self.client.get(f'{TRACKS}/{analizada.id}').json()['vocals'],
                         {'status': 'done', 'lastEnd': 290.5, 'firstStart': 14.0})

    def test_el_detalle_indica_si_la_pista_tiene_audio(self):
        con_audio = self.crear_con_audio()
        sin_audio = Track.objects.create(
            title='x', duration=1.0, bpm=128.0, key='C major', camelot='8B', energy=0.5)

        self.assertTrue(self.client.get(f'{TRACKS}/{con_audio.id}').json()['hasAudio'])
        self.assertFalse(self.client.get(f'{TRACKS}/{sin_audio.id}').json()['hasAudio'])


class FijarPrimerTiempoViewTests(TestCase):
    """PUT /api/audio/tracks/<id>/grid: el DJ senala un "1" y se guarda como primer tiempo."""

    def setUp(self):
        # 120 BPM: pulso de 0.5 s y compas de 2 s; primer pulso en 0.1; primer tiempo dudoso (confianza 0.03).
        self.pista = Track.objects.create(
            title='tema', duration=60.0, bpm=120.0, key='C major', camelot='8B', energy=0.5, cue_points=[0.0],
            grid_offset=0.1, grid_downbeat=0.1, grid_confidence=0.03)
        self.url = f'{TRACKS}/{self.pista.id}/grid'

    def fijar(self, cuerpo, pk=None):
        url = self.url if pk is None else f'{TRACKS}/{pk}/grid'
        datos = cuerpo if isinstance(cuerpo, (str, bytes)) else json.dumps(cuerpo)
        return self.client.put(url, data=datos, content_type='application/json')

    def test_guarda_el_primer_tiempo_con_confianza_total_y_marca_la_rejilla_como_manual(self):
        respuesta = self.fijar({'downbeat': 4.6})

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta.json()['grid'], {'offset': 0.1, 'downbeat': 0.6, 'confidence': 1.0, 'manual': True})
        self.pista.refresh_from_db()
        self.assertEqual((self.pista.grid_downbeat, self.pista.grid_confidence, self.pista.grid_manual), (0.6, 1.0, True))

    def test_no_toca_la_fase_de_los_pulsos_ni_el_tempo(self):
        self.fijar({'downbeat': 12.34})

        self.pista.refresh_from_db()
        self.assertEqual((self.pista.grid_offset, self.pista.bpm), (0.1, 120.0))

    def test_ajusta_el_instante_al_pulso_mas_cercano(self):
        self.fijar({'downbeat': 4.62})

        self.pista.refresh_from_db()
        self.assertEqual(self.pista.grid_downbeat, 0.6)

    def test_acepta_un_entero_y_los_limites_de_la_pista(self):
        self.assertEqual(self.fijar({'downbeat': 4}).status_code, 200)
        self.assertEqual(self.fijar({'downbeat': 0}).status_code, 200)
        self.assertEqual(self.fijar({'downbeat': 60.0}).status_code, 200)

    def test_la_consulta_posterior_devuelve_la_rejilla_manual(self):
        self.fijar({'downbeat': 4.6})

        self.assertEqual(self.client.get(f'{TRACKS}/{self.pista.id}').json()['grid']['manual'], True)

    def test_una_pista_sin_fijar_a_mano_dice_manual_false(self):
        self.assertFalse(self.client.get(f'{TRACKS}/{self.pista.id}').json()['grid']['manual'])

    def test_rechaza_un_cuerpo_que_no_es_un_objeto_json(self):
        for cuerpo in ('no es json', '[1, 2]', '"texto"', 'null', ''):
            respuesta = self.fijar(cuerpo)
            self.assertEqual(respuesta.status_code, 400, cuerpo)

    def test_rechaza_un_downbeat_que_falta_o_no_es_un_numero_valido(self):
        for cuerpo in ({}, {'downbeat': None}, {'downbeat': '4.6'}, {'downbeat': True}, {'downbeat': [4.6]},
                       '{"downbeat": NaN}', '{"downbeat": Infinity}'):
            respuesta = self.fijar(cuerpo)
            self.assertEqual(respuesta.status_code, 400, cuerpo)

    def test_rechaza_un_instante_fuera_de_la_pista(self):
        self.assertEqual(self.fijar({'downbeat': -0.1}).status_code, 400)
        self.assertEqual(self.fijar({'downbeat': 60.1}).status_code, 400)

    def test_una_peticion_rechazada_no_cambia_nada(self):
        self.fijar({'downbeat': 999})

        self.pista.refresh_from_db()
        self.assertEqual((self.pista.grid_downbeat, self.pista.grid_confidence, self.pista.grid_manual), (0.1, 0.03, False))

    def test_una_pista_sin_rejilla_responde_409(self):
        sin_ritmo = Track.objects.create(
            title='sin ritmo', duration=60.0, bpm=120.0, key='C major', camelot='8B', energy=0.5, cue_points=[0.0])

        respuesta = self.fijar({'downbeat': 4.6}, pk=sin_ritmo.id)

        self.assertEqual(respuesta.status_code, 409)
        sin_ritmo.refresh_from_db()
        self.assertFalse(sin_ritmo.grid_manual)

    def test_una_pista_que_no_existe_responde_404(self):
        self.assertEqual(self.fijar({'downbeat': 4.6}, pk=99999).status_code, 404)

    def test_solo_acepta_put(self):
        for metodo in ('get', 'post', 'patch', 'delete'):
            respuesta = getattr(self.client, metodo)(self.url)
            self.assertEqual(respuesta.status_code, 405, metodo)
