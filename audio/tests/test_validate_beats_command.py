import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from audio.tests.signals import click_track, to_wav_bytes


class ValidateBeatsCommandTests(SimpleTestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def crear_wav(self, file_name, bpm=110.0, primer_pulso=0.2, segundos=30):
        (self.folder / file_name).write_bytes(to_wav_bytes(click_track(bpm, segundos, first_beat=primer_pulso)))

    def manifiesto(self, texto):
        file_path = self.folder / 'referencia.csv'
        file_path.write_text(texto, encoding='utf-8')
        return file_path

    def ejecutar(self, *args):
        salida = StringIO()
        call_command('validate_beats', *args, stdout=salida)
        return salida.getvalue()

    def test_mide_el_tempo_contra_la_referencia_y_resume_por_genero(self):
        self.crear_wav('a.wav', bpm=110.0)
        self.crear_wav('b.wav', bpm=110.0)
        file_path = self.manifiesto('file,bpm,genre\na.wav,110,salsa\nb.wav,150,bachata\n')

        salida = self.ejecutar(str(file_path))

        self.assertIn('salsa', salida)
        self.assertIn('bachata', salida)
        self.assertIn('todas', salida)
        self.assertIn('2 pista', salida)

    def test_con_json_escribe_el_resumen_y_el_detalle_de_cada_pista(self):
        self.crear_wav('a.wav', bpm=110.0)
        file_path = self.manifiesto('file,bpm,genre\na.wav,110,salsa\n')
        target_path = self.folder / 'resultado.json'

        self.ejecutar(str(file_path), '--json', str(target_path))

        payload_data = json.loads(target_path.read_text(encoding='utf-8'))
        self.assertEqual(payload_data['summary']['todas']['total'], 1)
        self.assertEqual(payload_data['summary']['todas']['exact'], 1)
        (track_obj,) = payload_data['tracks']
        self.assertEqual(track_obj['file'], 'a.wav')
        self.assertAlmostEqual(track_obj['detectedBpm'], 110.0, delta=0.5)
        self.assertIsNone(track_obj['error'])

    def test_un_archivo_ilegible_o_inexistente_no_detiene_el_resto(self):
        self.crear_wav('buena.wav', bpm=110.0)
        (self.folder / 'rota.wav').write_bytes(b'no es audio')
        file_path = self.manifiesto('file,bpm\nrota.wav,100\nfalta.wav,100\nbuena.wav,110\n')

        salida = self.ejecutar(str(file_path))

        self.assertIn('3 pista', salida)
        self.assertIn('rota.wav', salida)
        self.assertIn('falta.wav', salida)

    def test_las_filas_sin_bpm_se_avisan_y_no_se_analizan(self):
        self.crear_wav('a.wav')
        file_path = self.manifiesto('file,bpm\na.wav,\n')

        salida = self.ejecutar(str(file_path))

        self.assertIn('sin BPM', salida)
        self.assertIn('0 pista', salida)

    def test_con_min_accuracy_falla_si_el_acierto_es_menor(self):
        self.crear_wav('a.wav', bpm=110.0)
        file_path = self.manifiesto('file,bpm\na.wav,150\n')

        with self.assertRaisesRegex(CommandError, '90'):
            self.ejecutar(str(file_path), '--min-accuracy', '0.9')

    def test_con_min_accuracy_pasa_si_el_acierto_alcanza(self):
        self.crear_wav('a.wav', bpm=110.0)
        file_path = self.manifiesto('file,bpm\na.wav,110\n')

        self.ejecutar(str(file_path), '--min-accuracy', '0.9')

    def test_el_primer_tiempo_se_mide_cuando_la_referencia_lo_trae(self):
        self.crear_wav('a.wav', bpm=110.0, primer_pulso=0.2)
        file_path = self.manifiesto('file,bpm,downbeat\na.wav,110,0.2\n')

        salida = self.ejecutar(str(file_path))

        self.assertIn('primer tiempo', salida.lower())

    def test_un_manifiesto_que_no_existe_es_un_error_claro(self):
        with self.assertRaisesRegex(CommandError, 'No existe'):
            self.ejecutar(str(self.folder / 'nada.csv'))

    def test_un_manifiesto_mal_formado_es_un_error_claro(self):
        file_path = self.manifiesto('file,bpm\na.wav,rapido\n')

        with self.assertRaisesRegex(CommandError, 'línea 2'):
            self.ejecutar(str(file_path))

    def test_template_lista_los_audios_de_una_carpeta_con_bpm_y_genero_en_blanco(self):
        self.crear_wav('uno.wav')
        self.crear_wav('dos.wav')
        (self.folder / 'notas.txt').write_text('no es audio', encoding='utf-8')
        target_path = self.folder / 'plantilla.csv'

        self.ejecutar(str(self.folder), '--template', '--out', str(target_path))

        text_lines = target_path.read_text(encoding='utf-8').strip().splitlines()
        self.assertEqual(text_lines[0], 'file,bpm,genre,downbeat')
        self.assertEqual(sorted(text_lines[1:]), ['dos.wav,,,', 'uno.wav,,,'])

    def test_template_no_pisa_un_archivo_que_ya_existe(self):
        self.crear_wav('uno.wav')
        target_path = self.folder / 'plantilla.csv'
        target_path.write_text('trabajo del DJ', encoding='utf-8')

        with self.assertRaisesRegex(CommandError, 'ya existe'):
            self.ejecutar(str(self.folder), '--template', '--out', str(target_path))

        self.assertEqual(target_path.read_text(encoding='utf-8'), 'trabajo del DJ')
