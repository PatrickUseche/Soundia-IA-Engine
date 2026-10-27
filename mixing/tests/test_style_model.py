from math import log2

from django.test import TestCase

from audio.camelot import harmonic_distance

from mixing.models import MixRecording
from audio.models import Track
from mixing.style_model import (
    BARS_CHOICES, MIN_RECORDINGS, PRIOR_WEIGHT, Context, Sample, choose_for, context_of, evaluate, fit, is_enabled,
    load_samples, reset_cache, rule_bars, set_enabled, style_model_status,
)
from mixing.tempo import match_tempo
from mixing.transition import choose_style_and_bars

# A 120 BPM un compas dura 2 s: 16 s de solape son 8 compases y 32 s son 16.
SNAP_A = {'title': 'A', 'bpm': 120.0, 'camelot': '8B', 'energy': 0.5, 'duration': 300.0, 'grid': None}
SNAP_B = {'title': 'B', 'bpm': 124.0, 'camelot': '9B', 'energy': 0.7, 'duration': 240.0, 'grid': None}

CERCA = Context(genre='salsa', key='near', tempo='tight')  # la regla da 16 compases


def muestra(bars, contexto=CERCA, swap=None):
    return Sample(context=contexto, bars_log2=log2(bars), bass_swap=swap)


def guardar(overlap=16.0, quality='good', genre_a='salsa', low=None):
    return MixRecording.objects.create(
        source='manual', dj='dj', mix_out_at=240.0, mix_in_at=0.5, overlap_seconds=overlap, pitch_a=1.0, pitch_b=1.0,
        curves={'a': {'low': low}} if low else {}, snapshot_a=SNAP_A, snapshot_b=SNAP_B, genre_a=genre_a, genre_b='',
        quality=quality)


class ContextTests(TestCase):
    def test_agrupa_la_distancia_de_tonalidad_y_el_ajuste_de_tempo(self):
        self.assertEqual(context_of(120, '8B', 122, '8B').key, 'near')
        self.assertEqual(context_of(120, '8B', 122, '10B').key, 'mid')
        self.assertEqual(context_of(120, '8B', 122, '2B').key, 'far')
        self.assertEqual(context_of(120, '8B', 122, '8B').tempo, 'tight')  # 1.6 %
        self.assertEqual(context_of(120, '8B', 126, '8B').tempo, 'stretch')  # 5 %
        self.assertEqual(context_of(120, '8B', 150, '8B').tempo, 'free')  # no cabe en el pitch

    def test_sin_genero_queda_vacio_y_el_fundido_no_se_puede_aprender(self):
        contexto = context_of(120, '8B', 150, '8B')

        self.assertEqual(contexto.genre, '')
        self.assertFalse(contexto.blendable)

    def test_la_regla_coincide_con_la_del_planificador(self):
        for bpm_b, camelot_b in [(122, '8B'), (126, '8B'), (122, '10B'), (122, '2B'), (126, '3A')]:
            contexto = context_of(120, '8B', bpm_b, camelot_b)
            _, esperados = choose_style_and_bars(match_tempo(120, bpm_b), harmonic_distance('8B', camelot_b))
            self.assertEqual(rule_bars(contexto), esperados, (bpm_b, camelot_b))


class PredictionTests(TestCase):
    def test_sin_datos_manda_la_regla(self):
        modelo = fit([])

        self.assertEqual(modelo.predict_bars(CERCA), 16)
        self.assertEqual(modelo.predict_bass_swap(CERCA), 0.5)

    def test_una_sola_mezcla_no_basta_para_cambiar_la_regla(self):
        self.assertEqual(fit([muestra(4)]).predict_bars(CERCA), 16)

    def test_con_suficientes_mezclas_manda_el_dj(self):
        modelo = fit([muestra(4) for _ in range(int(PRIOR_WEIGHT) * 4)])

        self.assertEqual(modelo.predict_bars(CERCA), 4)

    def test_el_resultado_siempre_es_una_de_las_mezclas_habituales(self):
        modelo = fit([muestra(6) for _ in range(30)])

        self.assertIn(modelo.predict_bars(CERCA), BARS_CHOICES)

    def test_un_genero_con_pocos_casos_hereda_lo_aprendido_de_los_parecidos(self):
        otro_genero = Context(genre='merengue', key='near', tempo='tight')
        modelo = fit([muestra(4, contexto=otro_genero) for _ in range(30)])

        # Nunca vio 'salsa', pero en esa tonalidad y tempo el DJ siempre mezcla corto.
        self.assertEqual(modelo.predict_bars(CERCA), 4)

    def test_el_genero_propio_puede_distinguirse_del_resto(self):
        merengue = Context(genre='merengue', key='near', tempo='tight')
        modelo = fit([muestra(16, contexto=CERCA) for _ in range(40)] + [muestra(4, contexto=merengue) for _ in range(40)])

        self.assertEqual(modelo.predict_bars(CERCA), 16)
        self.assertEqual(modelo.predict_bars(merengue), 4)

    def test_un_fundido_no_se_aprende(self):
        libre = Context(genre='salsa', key='near', tempo='free')
        modelo = fit([muestra(4, contexto=libre) for _ in range(30)])

        self.assertEqual(modelo.bars, {})

    def test_el_cambio_de_graves_se_acerca_al_del_dj_sin_salirse_de_los_limites(self):
        moderado = fit([muestra(8, swap=0.3) for _ in range(40)]).predict_bass_swap(CERCA)
        extremo = fit([muestra(8, swap=0.0) for _ in range(500)]).predict_bass_swap(CERCA)

        self.assertLess(moderado, 0.5)
        self.assertGreater(moderado, 0.3)  # la regla todavia pesa un poco
        self.assertEqual(extremo, 0.2)  # nunca se pasa del limite


class EvaluationTests(TestCase):
    def test_con_pocas_mezclas_nunca_gana(self):
        resultado = evaluate([muestra(4) for _ in range(MIN_RECORDINGS - 1)])

        self.assertFalse(resultado['bars']['wins'])

    def test_un_dj_que_siempre_se_aparta_de_la_regla_hace_ganar_al_modelo(self):
        resultado = evaluate([muestra(4) for _ in range(MIN_RECORDINGS + 10)])

        self.assertTrue(resultado['bars']['wins'])
        self.assertLess(resultado['bars']['modelError'], resultado['bars']['rulesError'])

    def test_un_dj_que_ya_sigue_la_regla_no_hace_ganar_al_modelo(self):
        resultado = evaluate([muestra(16) for _ in range(MIN_RECORDINGS + 10)])

        self.assertFalse(resultado['bars']['wins'])
        self.assertEqual(resultado['bars']['rulesError'], 0.0)

    def test_cada_objetivo_se_decide_por_separado(self):
        # Los compases siguen la regla, pero el cambio de graves es siempre a 0.3 en vez de a 0.5.
        resultado = evaluate([muestra(16, swap=0.3) for _ in range(MIN_RECORDINGS + 10)])

        self.assertFalse(resultado['bars']['wins'])
        self.assertTrue(resultado['bassSwap']['wins'])

    def test_una_mezcla_sin_datos_utiles_no_cuenta(self):
        vacia = Sample(context=CERCA, bars_log2=None, bass_swap=None)

        resultado = evaluate([vacia] * 50)

        self.assertEqual(resultado['bars']['evaluated'], 0)
        self.assertFalse(resultado['bars']['wins'])


class PersistenceTests(TestCase):
    def setUp(self):
        reset_cache()

    def test_solo_aprende_de_las_mezclas_buenas(self):
        guardar(quality='good')
        guardar(quality='unreviewed')
        guardar(quality='discard')

        self.assertEqual(len(load_samples()), 1)

    def test_lee_los_compases_y_el_genero_de_la_grabacion(self):
        guardar(overlap=16.0, genre_a='salsa')

        muestra_guardada = load_samples()[0]

        self.assertAlmostEqual(muestra_guardada.bars_log2, 3.0)  # 8 compases
        self.assertEqual(muestra_guardada.context, CERCA)

    def test_el_estado_sin_suficientes_mezclas_dice_cuantas_faltan(self):
        guardar()

        estado = style_model_status()

        self.assertEqual(
            {clave: valor for clave, valor in estado.items() if clave != 'nextTrack'},
            {'goodRecordings': 1, 'required': MIN_RECORDINGS, 'ready': False, 'enabled': False})

    def test_el_estado_con_suficientes_mezclas_incluye_la_evaluacion(self):
        for _ in range(MIN_RECORDINGS):
            guardar(overlap=16.0)

        estado = style_model_status()

        self.assertTrue(estado['ready'])
        self.assertTrue(estado['evaluation']['bars']['wins'])  # la regla da 16 y el DJ hace 8

    def test_la_ruta_devuelve_el_estado(self):
        guardar()

        respuesta = self.client.get('/api/mix/style-model')

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['goodRecordings'], 1)

    def test_la_ruta_no_acepta_otros_metodos(self):
        self.assertEqual(self.client.put('/api/mix/style-model').status_code, 405)



def pistas():
    a = Track.objects.create(title='A', duration=300.0, bpm=120.0, key='C major', camelot='8B', energy=0.5,
                             cue_points=[0.0, 60.0, 270.0], genre='salsa')
    b = Track.objects.create(title='B', duration=240.0, bpm=124.0, key='G major', camelot='9B', energy=0.7,
                             cue_points=[0.0, 60.0, 200.0], genre='')
    return a, b


class UseInPlanTests(TestCase):
    """8.9: el modelo solo cambia el plan si esta encendido y gana a las reglas."""

    def setUp(self):
        reset_cache()
        self.a, self.b = pistas()

    def aprender(self, mezclas=MIN_RECORDINGS, overlap=16.0):
        # La regla para A -> B (tonalidad vecina, ajuste del 3 %) son 16 compases; estas mezclas son de 8.
        for _ in range(mezclas):
            guardar(overlap=overlap)

    def plan(self):
        respuesta = self.client.post('/api/mix/transition', {'fromTrackId': self.a.id, 'toTrackId': self.b.id},
                                     content_type='application/json')
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.json()

    def test_por_defecto_esta_apagado_y_manda_la_regla(self):
        self.aprender()

        plan = self.plan()

        self.assertFalse(is_enabled())
        self.assertEqual(plan['source'], 'rules')
        self.assertEqual(plan['bars'], 16)

    def test_encendido_y_ganando_usa_los_compases_del_dj(self):
        self.aprender()
        set_enabled(True)

        plan = self.plan()

        self.assertEqual(plan['source'], 'model')
        self.assertTrue(plan['learnedBars'])
        self.assertEqual(plan['bars'], 8)

    def test_apagarlo_devuelve_las_reglas(self):
        self.aprender()
        set_enabled(True)
        self.assertEqual(self.plan()['bars'], 8)

        set_enabled(False)

        plan = self.plan()
        self.assertEqual(plan['source'], 'rules')
        self.assertEqual(plan['bars'], 16)

    def test_encendido_pero_con_pocas_mezclas_no_cambia_nada(self):
        self.aprender(mezclas=MIN_RECORDINGS - 1)
        set_enabled(True)

        self.assertEqual(self.plan()['source'], 'rules')
        self.assertFalse(choose_for(self.a, self.b).used)

    def test_si_el_dj_ya_sigue_la_regla_el_modelo_no_cambia_los_compases(self):
        self.aprender(overlap=32.0)  # 16 compases: lo mismo que la regla
        set_enabled(True)

        plan = self.plan()

        self.assertFalse(plan['learnedBars'])
        self.assertEqual(plan['bars'], 16)

    def test_un_dj_que_cambia_los_graves_antes_mueve_el_punto_del_cambio(self):
        for _ in range(MIN_RECORDINGS + 5):
            guardar(overlap=32.0, low=[[0.0, 1.0], [9.6, 1.0], [11.2, 0.0], [32.0, 0.0]])
        set_enabled(True)

        plan = self.plan()

        self.assertTrue(plan['learnedBassSwap'])
        graves = [p['lowA'] for p in plan['automation']]
        primer_corte = next(i for i, valor in enumerate(graves) if valor == 0.0)
        self.assertLess(primer_corte / (len(graves) - 1), 0.5)

    def test_la_huella_detecta_mezclas_nuevas(self):
        self.aprender(mezclas=MIN_RECORDINGS)
        self.assertEqual(style_model_status()['goodRecordings'], MIN_RECORDINGS)

        guardar()

        self.assertEqual(style_model_status()['goodRecordings'], MIN_RECORDINGS + 1)

    def test_el_estado_dice_que_parametros_se_estan_usando(self):
        self.aprender()
        self.assertEqual(style_model_status()['inUse'], {'bars': False, 'bassSwap': False})

        set_enabled(True)

        self.assertTrue(style_model_status()['inUse']['bars'])

    def test_la_ruta_enciende_y_apaga(self):
        self.aprender()

        encendido = self.client.post('/api/mix/style-model', {'enabled': True}, content_type='application/json')
        apagado = self.client.post('/api/mix/style-model', {'enabled': False}, content_type='application/json')

        self.assertTrue(encendido.json()['enabled'])
        self.assertFalse(apagado.json()['enabled'])

    def test_la_ruta_rechaza_un_valor_que_no_es_booleano(self):
        respuesta = self.client.post('/api/mix/style-model', {'enabled': 'si'}, content_type='application/json')

        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(is_enabled())
