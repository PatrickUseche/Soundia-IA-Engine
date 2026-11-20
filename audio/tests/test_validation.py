from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from audio.validation import (
    Reference, Result, circular_error, load_manifest, summarize, tempo_matches, tempo_matches_any_octave,
)


class TempoMatchTests(SimpleTestCase):
    def test_acepta_el_tempo_dentro_del_margen(self):
        self.assertTrue(tempo_matches(100.0, 103.9))
        self.assertTrue(tempo_matches(100.0, 96.1))

    def test_rechaza_el_tempo_fuera_del_margen(self):
        self.assertFalse(tempo_matches(100.0, 104.5))
        self.assertFalse(tempo_matches(100.0, 95.0))

    def test_el_margen_se_puede_cambiar(self):
        self.assertTrue(tempo_matches(100.0, 106.0, tolerance=0.07))
        self.assertFalse(tempo_matches(100.0, 103.0, tolerance=0.01))

    def test_un_error_de_octava_no_cuenta_como_acierto_estricto(self):
        self.assertFalse(tempo_matches(100.0, 200.0))
        self.assertFalse(tempo_matches(100.0, 50.0))

    def test_con_octavas_acepta_doble_mitad_triple_y_tercio(self):
        for detectado in (200.0, 50.0, 300.0, 100.0 / 3):
            with self.subTest(detectado=detectado):
                self.assertTrue(tempo_matches_any_octave(100.0, detectado))

    def test_con_octavas_sigue_rechazando_un_tempo_sin_relacion(self):
        self.assertFalse(tempo_matches_any_octave(100.0, 137.0))

    def test_una_referencia_no_positiva_nunca_coincide(self):
        self.assertFalse(tempo_matches(0.0, 100.0))
        self.assertFalse(tempo_matches_any_octave(-5.0, 100.0))


class CircularErrorTests(SimpleTestCase):
    def test_la_diferencia_sencilla(self):
        self.assertAlmostEqual(circular_error(1.0, 1.05, 2.0), 0.05)

    def test_da_la_vuelta_al_periodo(self):
        # 0.01 s y 1.99 s en un periodo de 2 s estan a 0.02 s uno del otro.
        self.assertAlmostEqual(circular_error(0.01, 1.99, 2.0), 0.02)

    def test_es_simetrica_y_nunca_pasa_de_medio_periodo(self):
        self.assertAlmostEqual(circular_error(0.0, 1.0, 2.0), 1.0)
        self.assertAlmostEqual(circular_error(1.3, 0.2, 2.0), circular_error(0.2, 1.3, 2.0))

    def test_un_desfase_de_periodos_enteros_es_cero(self):
        self.assertAlmostEqual(circular_error(0.5, 8.5, 2.0), 0.0)

    def test_un_periodo_no_positivo_es_un_error(self):
        with self.assertRaises(ValueError):
            circular_error(0.0, 1.0, 0.0)


class LoadManifestTests(SimpleTestCase):
    def escribir(self, texto):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        file_path = Path(folder.name) / 'referencia.csv'
        file_path.write_text(texto, encoding='utf-8')
        return file_path

    def test_lee_ruta_bpm_genero_y_primer_tiempo(self):
        file_path = self.escribir('file,bpm,genre,downbeat\ncanciones/a.mp3,98.5,salsa,0.42\n')

        (ref,) = load_manifest(file_path)

        self.assertEqual(ref.path, file_path.parent / 'canciones' / 'a.mp3')
        self.assertEqual((ref.bpm, ref.genre, ref.downbeat), (98.5, 'salsa', 0.42))

    def test_el_primer_tiempo_y_el_genero_son_opcionales(self):
        file_path = self.escribir('file,bpm\na.mp3,120\n')

        (ref,) = load_manifest(file_path)

        self.assertEqual((ref.bpm, ref.genre, ref.downbeat), (120.0, '', None))

    def test_una_fila_sin_bpm_queda_sin_referencia(self):
        file_path = self.escribir('file,bpm,genre\na.mp3,,salsa\n')

        (ref,) = load_manifest(file_path)

        self.assertIsNone(ref.bpm)

    def test_ignora_lineas_vacias_y_espacios_sobrantes(self):
        file_path = self.escribir('file,bpm,genre\n\n a.mp3 , 100 , bachata \n\n')

        (ref,) = load_manifest(file_path)

        self.assertEqual((ref.path.name, ref.bpm, ref.genre), ('a.mp3', 100.0, 'bachata'))

    def test_un_bpm_que_no_es_numero_es_un_error_con_el_numero_de_linea(self):
        file_path = self.escribir('file,bpm\na.mp3,rapido\n')

        with self.assertRaisesRegex(ValueError, 'línea 2'):
            load_manifest(file_path)

    def test_un_bpm_no_positivo_es_un_error(self):
        file_path = self.escribir('file,bpm\na.mp3,-90\n')

        with self.assertRaisesRegex(ValueError, 'línea 2'):
            load_manifest(file_path)

    def test_sin_columna_file_es_un_error(self):
        file_path = self.escribir('cancion,bpm\na.mp3,100\n')

        with self.assertRaisesRegex(ValueError, 'file'):
            load_manifest(file_path)

    def test_un_manifiesto_vacio_da_lista_vacia(self):
        self.assertEqual(load_manifest(self.escribir('file,bpm\n')), [])


def outcome(bpm_ref, bpm_det, genre_name='salsa', downbeat_ref=None, downbeat_det=None, error=None):
    ref = Reference(path=Path('x.mp3'), bpm=bpm_ref, genre=genre_name, downbeat=downbeat_ref)
    return Result(reference=ref, detected_bpm=bpm_det, detected_downbeat=downbeat_det, error=error)


class SummarizeTests(SimpleTestCase):
    def test_cuenta_aciertos_estrictos_y_con_octavas_por_genero(self):
        summary_info = summarize([
            outcome(100, 101, 'salsa'),   # acierto
            outcome(100, 200, 'salsa'),   # solo con octavas
            outcome(100, 137, 'salsa'),   # fallo
            outcome(90, 90, 'bachata'),   # acierto
        ])

        salsa = summary_info['salsa']
        self.assertEqual((salsa.total, salsa.exact, salsa.octave), (3, 1, 2))
        self.assertAlmostEqual(salsa.exact_rate, 1 / 3)
        self.assertAlmostEqual(salsa.octave_rate, 2 / 3)
        self.assertEqual((summary_info['bachata'].total, summary_info['bachata'].exact), (1, 1))

    def test_incluye_un_total_de_todas_las_pistas(self):
        summary_info = summarize([outcome(100, 100, 'salsa'), outcome(90, 130, 'bachata')])

        self.assertEqual((summary_info['todas'].total, summary_info['todas'].exact), (2, 1))

    def test_el_genero_vacio_se_agrupa_como_sin_genero(self):
        summary_info = summarize([outcome(100, 100, '')])

        self.assertIn('sin género', summary_info)

    def test_una_pista_con_error_cuenta_como_fallo_y_se_lleva_su_propia_cuenta(self):
        summary_info = summarize([outcome(100, None, error='ilegible'), outcome(100, 100)])

        overall = summary_info['todas']
        self.assertEqual((overall.total, overall.exact, overall.errors), (2, 1, 1))

    def test_las_pistas_sin_bpm_de_referencia_no_se_cuentan(self):
        summary_info = summarize([outcome(None, 100), outcome(100, 100)])

        self.assertEqual(summary_info['todas'].total, 1)

    def test_la_mediana_del_error_de_tempo_ignora_los_atipicos(self):
        summary_info = summarize([outcome(100, 101), outcome(100, 102), outcome(100, 150)])

        self.assertAlmostEqual(summary_info['todas'].median_error_pct, 2.0)

    def test_primer_tiempo_dentro_de_la_tolerancia_en_el_compas_y_en_el_pulso(self):
        # 120 BPM: pulso de 0.5 s y compas de 2 s.
        summary_info = summarize([
            outcome(120, 120, downbeat_ref=0.10, downbeat_det=0.14),   # compas bien (40 ms)
            outcome(120, 120, downbeat_ref=0.10, downbeat_det=0.64),   # pulso bien, compas mal (un pulso despues)
            outcome(120, 120, downbeat_ref=0.10, downbeat_det=0.35),   # ni pulso ni compas
            outcome(120, 120),                                         # sin primer tiempo de referencia
        ])

        overall = summary_info['todas']
        self.assertEqual(overall.downbeat_total, 3)
        self.assertEqual(overall.downbeat_ok, 1)
        self.assertEqual(overall.beat_phase_ok, 2)

    def test_la_tolerancia_del_primer_tiempo_se_puede_cambiar(self):
        summary_info = summarize([outcome(120, 120, downbeat_ref=0.10, downbeat_det=0.20)], downbeat_tolerance=0.15)

        self.assertEqual(summary_info['todas'].downbeat_ok, 1)

    def test_una_lista_vacia_da_un_total_en_cero_sin_dividir_entre_cero(self):
        summary_info = summarize([])

        self.assertEqual(summary_info['todas'].total, 0)
        self.assertEqual(summary_info['todas'].exact_rate, 0.0)
        self.assertIsNone(summary_info['todas'].median_error_pct)
