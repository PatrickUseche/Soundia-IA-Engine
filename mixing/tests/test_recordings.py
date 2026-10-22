import json

from django.test import SimpleTestCase, TestCase

from audio.models import Track
from mixing.models import MixRecording
from mixing.recordings import (
    InvalidRecording,
    bass_swap_fraction,
    beat_phase_error_ms,
    crossfader_shape,
    derive_features,
    parse_recording,
    parse_review,
)

RECORDINGS = '/api/mix/recordings'


def snap(bpm=120.0, camelot='8B', energy=0.6, duration=300.0, offset=0.0, downbeat=0.0, confidence=0.9,
         vocal_last_end=None, vocal_first_start=None, grid=True):
    return {
        'bpm': bpm, 'camelot': camelot, 'energy': energy, 'duration': duration,
        'grid': {'offset': offset, 'downbeat': downbeat, 'confidence': confidence, 'manual': False} if grid else None,
        'vocalLastEnd': vocal_last_end, 'vocalFirstStart': vocal_first_start,
    }


def lineal(inicio, fin, v0=0.0, v1=1.0, pasos=20):
    """Curva que va de v0 a v1 entre los segundos `inicio` y `fin`."""
    return [[inicio + (fin - inicio) * i / pasos, v0 + (v1 - v0) * i / pasos] for i in range(pasos + 1)]


class BeatPhaseErrorTests(SimpleTestCase):
    def error(self, pos_a, pos_b, pitch_a=1.0, pitch_b=1.0, a=None, b=None):
        return beat_phase_error_ms(a or snap(), b or snap(), pos_a, pos_b, pitch_a, pitch_b)

    def test_pulsos_en_fase_dan_cero(self):
        self.assertEqual(self.error(10.0, 20.0), 0.0)

    def test_b_adelantada_es_negativa_y_atrasada_es_positiva(self):
        # A esta justo en un pulso; el ultimo pulso de B fue hace 0.1 s: B se adelanto.
        self.assertEqual(self.error(10.0, 20.1), -100.0)
        # El ultimo pulso de B fue hace 0.4 s: le faltan 0.1 s para el siguiente, va atrasada.
        self.assertEqual(self.error(10.0, 19.9), 100.0)

    def test_nunca_pasa_de_medio_pulso(self):
        for centesimas in range(0, 200, 3):
            valor = self.error(10.0, 20.0 + centesimas / 100)
            self.assertLessEqual(abs(valor), 250.0 + 1e-6)

    def test_tiene_en_cuenta_el_offset_de_cada_rejilla(self):
        b = snap(offset=0.1, downbeat=0.1)
        self.assertEqual(self.error(10.0, 20.1, b=b), 0.0)

    def test_tiene_en_cuenta_el_pitch(self):
        # B va un 5 % mas rapida: 0.105 s de pista son 0.1 s de reloj.
        valor = self.error(10.0, 20.105, pitch_b=1.05)
        self.assertAlmostEqual(valor, -100.0, places=1)

    def test_sin_rejilla_en_alguna_no_hay_valor(self):
        self.assertIsNone(self.error(10.0, 20.0, a=snap(grid=False)))
        self.assertIsNone(self.error(10.0, 20.0, b=snap(grid=False)))


class BassSwapTests(SimpleTestCase):
    def test_es_la_fraccion_del_solape_en_que_los_graves_de_a_bajan_de_la_mitad(self):
        curvas = {'a': {'low': [[0, 1.0], [4, 1.0], [8, 0.0]]}}

        self.assertEqual(bass_swap_fraction(curvas, 8.0), 0.75)  # cruza 0.5 en el segundo 6

    def test_si_los_graves_nunca_bajan_no_hay_cambio(self):
        self.assertIsNone(bass_swap_fraction({'a': {'low': [[0, 1.0], [8, 0.8]]}}, 8.0))

    def test_sin_curva_de_graves_no_hay_valor(self):
        self.assertIsNone(bass_swap_fraction({}, 8.0))
        self.assertIsNone(bass_swap_fraction({'a': {'low': [[0, 1.0]]}}, 8.0))
        self.assertIsNone(bass_swap_fraction({'a': {'mid': [[0, 1.0], [8, 0.0]]}}, 8.0))

    def test_el_resultado_se_limita_a_0_y_1(self):
        curvas = {'a': {'low': [[0, 1.0], [1, 0.0]]}}

        self.assertEqual(bass_swap_fraction(curvas, 0.5), 1.0)


class CrossfaderShapeTests(SimpleTestCase):
    BEAT = 0.5

    def forma(self, curva, overlap=32.0):
        return crossfader_shape({'crossfader': curva}, overlap, self.BEAT)

    def test_un_cambio_brusco_es_un_corte(self):
        self.assertEqual(self.forma(lineal(15.0, 16.0)), 'corte')

    def test_un_cruce_que_ocupa_una_parte_del_solape_es_gradual(self):
        self.assertEqual(self.forma(lineal(12.0, 20.0)), 'gradual')

    def test_un_cruce_que_ocupa_casi_todo_el_solape_es_lento(self):
        self.assertEqual(self.forma(lineal(0.0, 32.0)), 'lento')

    def test_tambien_se_reconoce_cuando_el_crossfader_va_de_1_a_0(self):
        self.assertEqual(self.forma(lineal(0.0, 32.0, 1.0, 0.0)), 'lento')
        self.assertEqual(self.forma(lineal(15.0, 16.0, 1.0, 0.0)), 'corte')

    def test_sin_curva_o_sin_cruce_completo_no_hay_forma(self):
        self.assertIsNone(crossfader_shape({}, 32.0, self.BEAT))
        self.assertIsNone(self.forma([[0.0, 0.5]]))
        self.assertIsNone(self.forma(lineal(0.0, 32.0, 0.0, 0.5)))


class DeriveFeaturesTests(SimpleTestCase):
    def grabacion(self, **cambios):
        datos = {
            'snapshot_a': snap(bpm=120.0, camelot='8B', energy=0.5, duration=300.0, vocal_last_end=230.0),
            'snapshot_b': snap(bpm=120.0, camelot='9B', energy=0.8, duration=240.0, offset=0.1, downbeat=0.1,
                               vocal_first_start=20.0),
            'pitch_a': 1.0, 'pitch_b': 1.0, 'mix_out_at': 240.0, 'mix_in_at': 0.1, 'overlap_seconds': 32.0,
            'curves': {},
        }
        datos.update(cambios)
        return datos

    def test_calcula_los_rasgos_principales(self):
        rasgos = derive_features(self.grabacion())

        self.assertEqual(rasgos['overlapBars'], 16.0)            # 32 s a 120 BPM = 16 compases de 2 s
        self.assertEqual(rasgos['exitFromEnd'], 60.0)
        self.assertEqual(rasgos['exitFraction'], 0.8)
        self.assertEqual(rasgos['exitAfterLastVocal'], 10.0)
        self.assertEqual(rasgos['entryBarsFromDownbeat'], 0.0)   # entra justo en su primer tiempo
        self.assertEqual(rasgos['entryBeforeFirstVocal'], 19.9)
        self.assertEqual(rasgos['phaseErrorMs'], 0.0)
        self.assertEqual(rasgos['tempoRatio'], 1.0)
        self.assertEqual(rasgos['bpmDifference'], 0.0)
        self.assertEqual(rasgos['keyDistance'], 1)
        self.assertAlmostEqual(rasgos['energyDelta'], 0.3)

    def test_los_compases_de_solape_usan_el_tempo_al_que_suena_a(self):
        rasgos = derive_features(self.grabacion(pitch_a=1.05))

        self.assertAlmostEqual(rasgos['overlapBars'], 16.8, places=2)  # va mas rapida: el compas dura menos

    def test_entrar_dos_compases_despues_del_primer_tiempo(self):
        rasgos = derive_features(self.grabacion(mix_in_at=4.1))

        self.assertEqual(rasgos['entryBarsFromDownbeat'], 2.0)

    def test_sin_voz_ni_rejilla_esos_rasgos_quedan_vacios(self):
        rasgos = derive_features(self.grabacion(
            snapshot_a=snap(grid=False), snapshot_b=snap(grid=False, camelot='8B')))

        self.assertIsNone(rasgos['exitAfterLastVocal'])
        self.assertIsNone(rasgos['entryBeforeFirstVocal'])
        self.assertIsNone(rasgos['entryBarsFromDownbeat'])
        self.assertIsNone(rasgos['phaseErrorMs'])
        self.assertEqual(rasgos['keyDistance'], 0)

    def test_incluye_el_cambio_de_graves_y_la_forma_del_crossfader_si_hay_curvas(self):
        curvas = {'crossfader': lineal(12.0, 20.0), 'a': {'low': [[0, 1.0], [16, 1.0], [17, 0.0], [32, 0.0]]}}

        rasgos = derive_features(self.grabacion(curves=curvas))

        self.assertEqual(rasgos['crossfaderShape'], 'gradual')
        self.assertAlmostEqual(rasgos['bassSwapAt'], 16.5 / 32, places=3)


class ParseRecordingTests(TestCase):
    def setUp(self):
        self.a = Track.objects.create(
            title='A', duration=300.0, bpm=120.0, key='C major', camelot='8B', energy=0.5, cue_points=[0.0],
            grid_offset=0.0, grid_downbeat=0.0, grid_confidence=0.9, vocal_last_end=230.0)
        self.b = Track.objects.create(
            title='B', duration=240.0, bpm=124.0, key='G major', camelot='9B', energy=0.7, cue_points=[0.0])

    def cuerpo(self, **cambios):
        datos = {
            'fromTrackId': self.a.id, 'toTrackId': self.b.id, 'mixOutAt': 240.0, 'mixInAt': 0.5,
            'overlapSeconds': 32.0, 'pitchA': 1.0, 'pitchB': 0.968,
        }
        datos.update(cambios)
        return datos

    def test_un_cuerpo_valido_devuelve_los_campos_con_la_foto_de_las_pistas(self):
        campos = parse_recording(self.cuerpo(dj='  Alias  ', genreA='salsa', genreB='bachata', notes='ok'))

        self.assertEqual(campos['from_track'], self.a)
        self.assertEqual(campos['source'], 'manual')
        self.assertEqual(campos['dj'], 'Alias')
        self.assertEqual((campos['genre_a'], campos['genre_b'], campos['notes']), ('salsa', 'bachata', 'ok'))
        self.assertEqual(campos['snapshot_a']['bpm'], 120.0)
        self.assertEqual(campos['snapshot_a']['grid']['downbeat'], 0.0)
        self.assertEqual(campos['snapshot_a']['vocalLastEnd'], 230.0)
        self.assertIsNone(campos['snapshot_b']['grid'])

    def test_la_foto_la_toma_el_servidor_y_no_el_cliente(self):
        campos = parse_recording(self.cuerpo(snapshotA={'bpm': 999}))

        self.assertEqual(campos['snapshot_a']['bpm'], 120.0)

    def test_valores_por_defecto(self):
        campos = parse_recording(self.cuerpo())

        self.assertEqual((campos['dj'], campos['genre_a'], campos['notes'], campos['curves']), ('dj', '', '', {}))

    def test_ordena_los_puntos_de_las_curvas_por_tiempo(self):
        campos = parse_recording(self.cuerpo(curves={'crossfader': [[2, 1.0], [0, 0.0], [1, 0.5]]}))

        self.assertEqual(campos['curves']['crossfader'], [[0.0, 0.0], [1.0, 0.5], [2.0, 1.0]])

    def test_acepta_las_curvas_de_cada_deck(self):
        curvas = {'a': {'volume': [[0, 1.0]], 'low': [[0, 1.0], [8, 0.0]]}, 'b': {'high': [[0, 0.0], [8, 1.0]]}}

        self.assertEqual(parse_recording(self.cuerpo(curves=curvas))['curves']['a']['low'], [[0.0, 1.0], [8.0, 0.0]])

    def assertInvalida(self, cuerpo, texto=None):
        with self.assertRaises(InvalidRecording) as contexto:
            parse_recording(cuerpo)
        if texto:
            self.assertIn(texto, str(contexto.exception))

    def test_rechaza_lo_que_no_es_un_objeto(self):
        for cuerpo in (None, [], 'texto', 5):
            self.assertInvalida(cuerpo)

    def test_rechaza_ids_que_faltan_o_no_son_enteros(self):
        for cambio in ({'fromTrackId': None}, {'fromTrackId': '1'}, {'toTrackId': True}, {'toTrackId': 1.5}):
            self.assertInvalida(self.cuerpo(**cambio))

    def test_rechaza_la_misma_pista_de_salida_y_de_entrada(self):
        self.assertInvalida(self.cuerpo(toTrackId=self.a.id), 'la misma')

    def test_una_pista_que_no_existe_lanza_does_not_exist(self):
        with self.assertRaises(Track.DoesNotExist):
            parse_recording(self.cuerpo(toTrackId=99999))

    def test_rechaza_un_origen_desconocido(self):
        self.assertInvalida(self.cuerpo(source='robot'), 'source')

    def test_rechaza_segundos_invalidos(self):
        for cambio in (
            {'mixOutAt': -1}, {'mixOutAt': 302}, {'mixOutAt': 'x'}, {'mixOutAt': float('nan')},
            {'mixInAt': -0.1}, {'mixInAt': 241.5}, {'overlapSeconds': 0}, {'overlapSeconds': -5},
            {'overlapSeconds': 601}, {'overlapSeconds': True}, {'overlapSeconds': float('inf')},
        ):
            self.assertInvalida(self.cuerpo(**cambio))

    def test_rechaza_un_pitch_fuera_de_rango(self):
        for cambio in ({'pitchA': 0.4}, {'pitchB': 2.5}, {'pitchA': None}, {'pitchB': 'rapido'}):
            self.assertInvalida(self.cuerpo(**cambio))

    def test_rechaza_textos_demasiado_largos_o_que_no_son_texto(self):
        for cambio in ({'dj': 'x' * 61}, {'genreA': 'x' * 41}, {'notes': 'x' * 501}, {'dj': 5}, {'notes': ['a']}):
            self.assertInvalida(self.cuerpo(**cambio))

    def test_rechaza_curvas_mal_formadas(self):
        malas = [
            [[0, 1.0]],                                  # 'curves' debe ser un objeto
            {'volumen': []},                             # clave desconocida
            {'crossfader': 'no'},                        # no es lista
            {'crossfader': [[0]]},                       # punto de un solo numero
            {'crossfader': [[0, 1, 2]]},                 # punto de tres
            {'crossfader': [['a', 1]]},                  # texto
            {'crossfader': [[0, 1.5]]},                  # valor fuera de 0-1
            {'crossfader': [[0, -0.1]]},
            {'crossfader': [[40, 0.5]]},                 # fuera del solape (32 s + 1 s de margen)
            {'crossfader': [[-2, 0.5]]},
            {'crossfader': [[0, float('nan')]]},
            {'crossfader': [[i / 10, 0.5] for i in range(201)]},   # demasiados puntos
            {'a': 'no'},                                 # un deck debe ser un objeto
            {'a': {'reverb': []}},                       # curva desconocida
            {'c': {'low': []}},                          # deck desconocido
        ]
        for curvas in malas:
            self.assertInvalida(self.cuerpo(curves=curvas))

    def test_acepta_hasta_el_maximo_de_puntos(self):
        curva = [[i / 10, 0.5] for i in range(200)]

        self.assertEqual(len(parse_recording(self.cuerpo(curves={'crossfader': curva}))['curves']['crossfader']), 200)


class ParseReviewTests(SimpleTestCase):
    def test_acepta_calidad_y_notas(self):
        self.assertEqual(parse_review({'quality': 'good', 'notes': ' bien '}), {'quality': 'good', 'notes': 'bien'})

    def test_acepta_solo_uno(self):
        self.assertEqual(parse_review({'quality': 'discard'}), {'quality': 'discard'})
        self.assertEqual(parse_review({'notes': ''}), {'notes': ''})

    def test_rechaza_calidad_desconocida_o_cuerpo_sin_cambios(self):
        for cuerpo in ({'quality': 'regular'}, {}, {'otra': 1}, [], None, 'x'):
            with self.assertRaises(InvalidRecording):
                parse_review(cuerpo)

    def test_rechaza_notas_demasiado_largas(self):
        with self.assertRaises(InvalidRecording):
            parse_review({'notes': 'x' * 501})


class RecordingViewTests(TestCase):
    def setUp(self):
        self.a = Track.objects.create(
            title='A', duration=300.0, bpm=120.0, key='C major', camelot='8B', energy=0.5, cue_points=[0.0],
            grid_offset=0.0, grid_downbeat=0.0, grid_confidence=0.9)
        self.b = Track.objects.create(
            title='B', duration=240.0, bpm=120.0, key='G major', camelot='9B', energy=0.7, cue_points=[0.0],
            grid_offset=0.1, grid_downbeat=0.1, grid_confidence=0.9)

    def cuerpo(self, **cambios):
        datos = {
            'fromTrackId': self.a.id, 'toTrackId': self.b.id, 'mixOutAt': 240.0, 'mixInAt': 0.1,
            'overlapSeconds': 32.0, 'pitchA': 1.0, 'pitchB': 1.0,
            'curves': {'crossfader': lineal(12.0, 20.0), 'a': {'low': [[0, 1.0], [16, 1.0], [17, 0.0], [32, 0.0]]}},
        }
        datos.update(cambios)
        return datos

    def post(self, cuerpo=None, raw=None):
        datos = raw if raw is not None else json.dumps(cuerpo if cuerpo is not None else self.cuerpo())
        return self.client.post(RECORDINGS, data=datos, content_type='application/json')

    def put(self, pk, cuerpo):
        return self.client.put(f'{RECORDINGS}/{pk}', data=json.dumps(cuerpo), content_type='application/json')

    def test_guardar_devuelve_201_con_la_grabacion_y_sus_rasgos(self):
        respuesta = self.post()

        self.assertEqual(respuesta.status_code, 201)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['quality'], 'unreviewed')
        self.assertEqual(cuerpo['features']['overlapBars'], 16.0)
        self.assertEqual(cuerpo['features']['crossfaderShape'], 'gradual')
        self.assertIn('curves', cuerpo)
        self.assertEqual(MixRecording.objects.count(), 1)

    def test_guardar_con_datos_invalidos_devuelve_400_y_no_guarda_nada(self):
        for cuerpo in (self.cuerpo(overlapSeconds=0), self.cuerpo(source='robot'), {}):
            self.assertEqual(self.post(cuerpo).status_code, 400)
        for raw in ('', 'no-json', '[]'):
            self.assertEqual(self.post(raw=raw).status_code, 400)
        self.assertEqual(MixRecording.objects.count(), 0)

    def test_guardar_con_una_pista_inexistente_devuelve_404(self):
        self.assertEqual(self.post(self.cuerpo(toTrackId=99999)).status_code, 404)

    def test_listar_devuelve_las_mas_recientes_sin_curvas_y_un_resumen(self):
        self.post()
        segunda = self.post(self.cuerpo(mixOutAt=100.0)).json()['id']
        self.put(segunda, {'quality': 'good'})

        cuerpo = self.client.get(RECORDINGS).json()

        self.assertEqual(cuerpo['counts'], {'unreviewed': 1, 'good': 1, 'discard': 0, 'total': 2})
        self.assertEqual(cuerpo['recordings'][0]['id'], segunda)
        self.assertNotIn('curves', cuerpo['recordings'][0])
        self.assertIn('features', cuerpo['recordings'][0])

    def test_listar_se_puede_filtrar_por_calidad(self):
        self.post()
        buena = self.post().json()['id']
        self.put(buena, {'quality': 'good'})

        ids = [r['id'] for r in self.client.get(f'{RECORDINGS}?quality=good').json()['recordings']]

        self.assertEqual(ids, [buena])
        self.assertEqual(self.client.get(f'{RECORDINGS}?quality=regular').status_code, 400)

    def test_el_detalle_incluye_las_curvas_y_la_foto_de_las_pistas(self):
        identificador = self.post().json()['id']

        cuerpo = self.client.get(f'{RECORDINGS}/{identificador}').json()

        self.assertEqual(cuerpo['curves']['a']['low'][2], [17.0, 0.0])
        self.assertEqual(cuerpo['snapshotA']['bpm'], 120.0)
        self.assertEqual(cuerpo['snapshotB']['grid']['offset'], 0.1)

    def test_revisar_cambia_la_calidad_y_las_notas(self):
        identificador = self.post().json()['id']

        respuesta = self.put(identificador, {'quality': 'discard', 'notes': 'me equivoque de pista'})

        self.assertEqual(respuesta.status_code, 200)
        grabacion = MixRecording.objects.get(pk=identificador)
        self.assertEqual((grabacion.quality, grabacion.notes), ('discard', 'me equivoque de pista'))

    def test_revisar_con_datos_invalidos_devuelve_400(self):
        identificador = self.post().json()['id']

        self.assertEqual(self.put(identificador, {'quality': 'regular'}).status_code, 400)
        self.assertEqual(self.put(identificador, {}).status_code, 400)
        self.assertEqual(MixRecording.objects.get(pk=identificador).quality, 'unreviewed')

    def test_borrar_devuelve_204_y_la_elimina(self):
        identificador = self.post().json()['id']

        self.assertEqual(self.client.delete(f'{RECORDINGS}/{identificador}').status_code, 204)
        self.assertEqual(MixRecording.objects.count(), 0)

    def test_una_grabacion_que_no_existe_devuelve_404(self):
        self.assertEqual(self.client.get(f'{RECORDINGS}/99999').status_code, 404)
        self.assertEqual(self.put(99999, {'quality': 'good'}).status_code, 404)
        self.assertEqual(self.client.delete(f'{RECORDINGS}/99999').status_code, 404)

    def test_metodos_no_permitidos(self):
        identificador = self.post().json()['id']

        self.assertEqual(self.client.put(RECORDINGS).status_code, 405)
        self.assertEqual(self.client.delete(RECORDINGS).status_code, 405)
        self.assertEqual(self.client.post(f'{RECORDINGS}/{identificador}').status_code, 405)

    def test_si_se_borra_una_pista_la_grabacion_se_conserva_con_su_foto(self):
        identificador = self.post().json()['id']

        self.b.delete()

        grabacion = MixRecording.objects.get(pk=identificador)
        self.assertIsNone(grabacion.to_track)
        self.assertEqual(grabacion.snapshot_b['bpm'], 120.0)
        self.assertEqual(self.client.get(f'{RECORDINGS}/{identificador}').status_code, 200)

    def test_corregir_la_rejilla_de_una_pista_no_cambia_lo_ya_grabado(self):
        identificador = self.post().json()['id']

        self.a.grid_downbeat = 1.5
        self.a.save()

        grabacion = MixRecording.objects.get(pk=identificador)
        self.assertEqual(grabacion.snapshot_a['grid']['downbeat'], 0.0)
