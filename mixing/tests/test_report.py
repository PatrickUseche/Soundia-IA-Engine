from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from mixing.models import MixRecording
from mixing.report import NO_GENRE, summarize

# A 120 BPM un compas dura 2 s: 32 s de solape son 16 compases.
SNAP_A = {'title': 'A', 'bpm': 120.0, 'camelot': '8B', 'energy': 0.5, 'duration': 300.0, 'grid': None}
SNAP_B = {'title': 'B', 'bpm': 124.0, 'camelot': '9B', 'energy': 0.7, 'duration': 240.0, 'grid': None}


def guardar(overlap=32.0, quality='good', genre_a='salsa', genre_b='', mix_out_at=240.0, crossfader=None, low=None,
            snap_b=None):
    curves = {}
    if crossfader is not None:
        curves['crossfader'] = crossfader
    if low is not None:
        curves['a'] = {'low': low}
    return MixRecording.objects.create(
        source='manual', dj='dj', mix_out_at=mix_out_at, mix_in_at=0.5, overlap_seconds=overlap, pitch_a=1.0,
        pitch_b=1.0, curves=curves, snapshot_a=SNAP_A, snapshot_b=snap_b or SNAP_B, genre_a=genre_a, genre_b=genre_b,
        quality=quality)


class SummarizeTests(TestCase):
    def test_sin_grabaciones_no_hay_grupos(self):
        resumen = summarize()

        self.assertEqual(resumen['total'], 0)
        self.assertEqual(resumen['groups'], [])

    def test_por_defecto_solo_cuenta_las_buenas(self):
        guardar(quality='good')
        guardar(quality='unreviewed')
        guardar(quality='discard')

        self.assertEqual(summarize()['total'], 1)
        self.assertEqual(summarize(quality='unreviewed')['total'], 1)
        self.assertEqual(summarize(quality='discard')['total'], 1)
        self.assertEqual(summarize(quality=None)['total'], 3)

    def test_una_calidad_invalida_se_rechaza(self):
        with self.assertRaises(ValueError):
            summarize(quality='genial')

    def test_agrupa_por_genero_con_el_mas_numeroso_primero(self):
        guardar(genre_a='merengue')
        guardar(genre_a='salsa')
        guardar(genre_a='salsa')

        generos = [(g['genre'], g['count']) for g in summarize()['groups']]

        self.assertEqual(generos, [('salsa', 2), ('merengue', 1)])

    def test_si_la_pista_que_sale_no_tiene_genero_usa_el_de_la_que_entra(self):
        guardar(genre_a='', genre_b='bachata')

        self.assertEqual(summarize()['groups'][0]['genre'], 'bachata')

    def test_sin_ningun_genero_van_a_sin_genero(self):
        guardar(genre_a='', genre_b='')

        self.assertEqual(summarize()['groups'][0]['genre'], NO_GENRE)

    def test_calcula_la_mediana_el_minimo_y_el_maximo_del_solape_en_compases(self):
        guardar(overlap=16.0)   # 8 compases
        guardar(overlap=32.0)   # 16
        guardar(overlap=64.0)   # 32

        solape = summarize()['groups'][0]['overlapBars']

        self.assertEqual((solape['median'], solape['min'], solape['max'], solape['count']), (16.0, 8.0, 32.0, 3))

    def test_cuenta_las_formas_del_crossfader(self):
        gradual = [[0, 0.0], [8, 1.0], [16, 1.0]]  # tarda el 40 % del solape: ni corte ni lento
        corte = [[0, 0.0], [15, 0.0], [15.5, 1.0], [16, 1.0]]
        guardar(overlap=16.0, crossfader=gradual)
        guardar(overlap=16.0, crossfader=gradual)
        guardar(overlap=16.0, crossfader=corte)

        formas = summarize()['groups'][0]['crossfaderShapes']

        self.assertEqual(formas, {'gradual': 2, 'corte': 1})

    def test_cuenta_en_cuantas_mezclas_hubo_cambio_de_graves(self):
        con_cambio = [[0, 1.0], [8, 1.0], [8.5, 0.0], [16, 0.0]]
        guardar(overlap=16.0, low=con_cambio)
        guardar(overlap=16.0)

        graves = summarize()['groups'][0]['bassSwap']

        self.assertEqual((graves['count'], graves['ofTotal']), (1, 2))
        self.assertAlmostEqual(graves['medianAt']['median'], 0.5, delta=0.05)

    def test_sin_cambios_de_graves_no_hay_mediana(self):
        guardar()

        graves = summarize()['groups'][0]['bassSwap']

        self.assertEqual(graves['count'], 0)
        self.assertIsNone(graves['medianAt'])

    def test_la_diferencia_de_bpm_se_cuenta_en_valor_absoluto(self):
        guardar(snap_b={**SNAP_B, 'bpm': 124.0})   # +4
        guardar(snap_b={**SNAP_B, 'bpm': 116.0})   # -4

        self.assertEqual(summarize()['groups'][0]['bpmDifference']['median'], 4.0)

    def test_cuenta_la_distancia_de_tonalidad(self):
        guardar()  # 8B -> 9B: una posicion

        self.assertEqual(summarize()['groups'][0]['keyDistance'], {'1': 1})

    def test_se_puede_filtrar_por_genero(self):
        guardar(genre_a='salsa')
        guardar(genre_a='merengue')

        resumen = summarize(genre='merengue')

        self.assertEqual([g['genre'] for g in resumen['groups']], ['merengue'])
        self.assertEqual(resumen['total'], 1)


class RecordingsSummaryViewTests(TestCase):
    URL = '/api/mix/recordings/summary'

    def test_devuelve_el_resumen_de_las_buenas(self):
        guardar(genre_a='salsa')
        guardar(genre_a='salsa', quality='discard')

        cuerpo = self.client.get(self.URL).json()

        self.assertEqual(cuerpo['total'], 1)
        self.assertEqual(cuerpo['quality'], 'good')
        self.assertEqual(cuerpo['groups'][0]['genre'], 'salsa')

    def test_all_cuenta_todas_y_se_puede_filtrar_por_genero(self):
        guardar(genre_a='salsa', quality='discard')
        guardar(genre_a='bachata', quality='unreviewed')

        todas = self.client.get(self.URL, {'quality': 'all'}).json()
        solo = self.client.get(self.URL, {'quality': 'all', 'genre': 'bachata'}).json()

        self.assertEqual(todas['total'], 2)
        self.assertIsNone(todas['quality'])
        self.assertEqual([g['genre'] for g in solo['groups']], ['bachata'])

    def test_una_calidad_invalida_devuelve_400(self):
        respuesta = self.client.get(self.URL, {'quality': 'genial'})

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('error', respuesta.json())

    def test_otros_metodos_devuelven_405(self):
        self.assertEqual(self.client.post(self.URL).status_code, 405)

    def test_no_choca_con_la_ruta_de_una_grabacion(self):
        recording = guardar()

        self.assertEqual(self.client.get(f'/api/mix/recordings/{recording.pk}').status_code, 200)


class RecordingsReportCommandTests(TestCase):
    def ejecutar(self, **opciones):
        salida = StringIO()
        call_command('recordings_report', stdout=salida, **opciones)
        return salida.getvalue()

    def test_sin_grabaciones_explica_que_hacer(self):
        texto = self.ejecutar()

        self.assertIn('No hay grabaciones', texto)
        self.assertIn('Marca algunas como buenas', texto)

    def test_muestra_el_resumen_por_genero_en_espanol(self):
        gradual = [[0, 0.0], [16, 1.0], [32, 1.0]]
        guardar(overlap=32.0, genre_a='salsa', crossfader=gradual)
        guardar(overlap=32.0, genre_a='salsa', crossfader=gradual)

        texto = self.ejecutar()

        self.assertIn('2 grabacion(es)', texto)
        self.assertIn('Genero: salsa (2 mezcla(s))', texto)
        self.assertIn('Solape: mediana 16.0 compases', texto)
        self.assertIn('Crossfader: gradual 2', texto)
        self.assertIn('Cambio de graves: no se detecto', texto)

    def test_all_incluye_las_no_revisadas(self):
        guardar(quality='unreviewed')

        self.assertIn('No hay grabaciones', self.ejecutar())
        self.assertIn('1 grabacion(es) todas', self.ejecutar(quality='all'))

    def test_un_genero_sin_grabaciones_lo_dice(self):
        guardar(genre_a='salsa')

        self.assertIn("del genero 'rock'", self.ejecutar(genre='rock'))
