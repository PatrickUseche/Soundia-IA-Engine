import copy
import json
import tempfile
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from mixing.backup import BACKUP_FORMAT, BACKUP_VERSION, export_recordings, import_recordings
from mixing.models import MixRecording
from mixing.recordings import InvalidRecording

SNAP_A = {'title': 'A', 'bpm': 120.0, 'camelot': '8B', 'energy': 0.5, 'duration': 300.0}
SNAP_B = {'title': 'B', 'bpm': 122.0, 'camelot': '9B', 'energy': 0.7, 'duration': 240.0}
CREADA = datetime(2026, 10, 20, 15, 30, 45, 123456, tzinfo=timezone.utc)


def guardar(**cambios) -> MixRecording:
    datos = dict(
        source='manual', dj='dj-prueba', mix_out_at=240.0, mix_in_at=0.5, overlap_seconds=32.0, pitch_a=1.0,
        pitch_b=1.02, curves={'crossfader': [[0, 0.0], [32, 1.0]], 'a': {'low': [[0, 1.0], [16, 0.0]]}},
        snapshot_a=SNAP_A, snapshot_b=SNAP_B, genre_a='salsa', genre_b='merengue', quality='good', notes='buena mezcla',
    )
    datos.update(cambios)
    recording = MixRecording.objects.create(**datos)
    MixRecording.objects.filter(pk=recording.pk).update(created_at=CREADA)
    return MixRecording.objects.get(pk=recording.pk)


class ExportTests(TestCase):
    def test_sin_grabaciones_exporta_una_lista_vacia(self):
        copia = export_recordings()

        self.assertEqual(copia['format'], BACKUP_FORMAT)
        self.assertEqual(copia['version'], BACKUP_VERSION)
        self.assertEqual(copia['recordings'], [])
        self.assertIn('exportedAt', copia)

    def test_exporta_todos_los_datos_de_la_grabacion_sin_ids_de_pista(self):
        guardar()

        item = export_recordings()['recordings'][0]

        self.assertEqual(item['dj'], 'dj-prueba')
        self.assertEqual(item['overlapSeconds'], 32.0)
        self.assertEqual(item['quality'], 'good')
        self.assertEqual(item['genreA'], 'salsa')
        self.assertEqual(item['snapshotA'], SNAP_A)
        self.assertEqual(item['snapshotB'], SNAP_B)
        self.assertEqual(item['curves']['a']['low'], [[0, 1.0], [16, 0.0]])
        self.assertEqual(item['createdAt'], CREADA.isoformat())
        self.assertNotIn('fromTrackId', item)

    def test_las_exporta_de_la_mas_antigua_a_la_mas_nueva(self):
        guardar(notes='segunda')
        primera = guardar(notes='primera')
        MixRecording.objects.filter(pk=primera.pk).update(created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

        notas = [r['notes'] for r in export_recordings()['recordings']]

        self.assertEqual(notas, ['primera', 'segunda'])

    def test_se_puede_serializar_como_json(self):
        guardar(notes='con tilde: canción')

        self.assertIn('canción', json.dumps(export_recordings(), ensure_ascii=False))


class ImportTests(TestCase):
    def copia(self):
        guardar()
        copia = json.loads(json.dumps(export_recordings()))
        MixRecording.objects.all().delete()
        return copia

    def test_restaura_las_grabaciones_con_su_fecha_original(self):
        created, skipped = import_recordings(self.copia())

        self.assertEqual((created, skipped), (1, 0))
        recording = MixRecording.objects.get()
        self.assertEqual(recording.created_at, CREADA)
        self.assertEqual(recording.dj, 'dj-prueba')
        self.assertEqual(recording.snapshot_a, SNAP_A)
        self.assertEqual(recording.quality, 'good')
        self.assertIsNone(recording.from_track)

    def test_restaurar_dos_veces_no_duplica(self):
        copia = self.copia()

        import_recordings(copia)
        created, skipped = import_recordings(copia)

        self.assertEqual((created, skipped), (0, 1))
        self.assertEqual(MixRecording.objects.count(), 1)

    def test_ida_y_vuelta_conserva_todo(self):
        guardar(notes='otra', mix_out_at=100.0)
        antes = export_recordings()['recordings']
        copia = json.loads(json.dumps(export_recordings()))
        MixRecording.objects.all().delete()

        import_recordings(copia)

        self.assertEqual(export_recordings()['recordings'], antes)

    def test_rechaza_un_archivo_que_no_es_una_copia(self):
        for basura in (None, [], {}, {'format': 'otra-cosa', 'version': 1, 'recordings': []}):
            with self.subTest(basura=basura), self.assertRaises(InvalidRecording):
                import_recordings(basura)

    def test_rechaza_una_version_desconocida(self):
        copia = self.copia()
        copia['version'] = 99

        with self.assertRaisesRegex(InvalidRecording, 'Version'):
            import_recordings(copia)

    def test_todo_o_nada_una_grabacion_invalida_impide_guardar_las_demas(self):
        copia = self.copia()
        mala = copy.deepcopy(copia['recordings'][0])
        mala['overlapSeconds'] = 0
        mala['mixOutAt'] = 11.0
        copia['recordings'].append(mala)

        with self.assertRaisesRegex(InvalidRecording, 'Grabacion 2'):
            import_recordings(copia)

        self.assertEqual(MixRecording.objects.count(), 0)

    def test_valida_los_campos_de_cada_grabacion(self):
        base = self.copia()['recordings'][0]
        casos = {
            'source': {'source': 'robot'}, 'quality': {'quality': 'genial'}, 'fecha': {'createdAt': 'ayer'},
            'sin zona horaria': {'createdAt': '2026-10-20T15:30:45'}, 'pitch': {'pitchA': 9},
            'foto': {'snapshotA': {}}, 'curvas': {'curves': {'crossfader': 'no'}}, 'solape': {'overlapSeconds': 'mucho'},
        }
        for nombre, cambios in casos.items():
            with self.subTest(nombre):
                copia = {'format': BACKUP_FORMAT, 'version': BACKUP_VERSION, 'recordings': [{**base, **cambios}]}
                with self.assertRaises(InvalidRecording):
                    import_recordings(copia)
        self.assertEqual(MixRecording.objects.count(), 0)


class BackupViewsTests(TestCase):
    def test_exportar_devuelve_el_archivo_descargable(self):
        guardar()

        respuesta = self.client.get('/api/mix/recordings/export')

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('attachment', respuesta['Content-Disposition'])
        self.assertEqual(len(respuesta.json()['recordings']), 1)

    def test_importar_restaura_y_responde_201(self):
        guardar()
        copia = self.client.get('/api/mix/recordings/export').json()
        MixRecording.objects.all().delete()

        respuesta = self.client.post('/api/mix/recordings/import', data=json.dumps(copia), content_type='application/json')

        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.json(), {'created': 1, 'skipped': 0})

    def test_importar_lo_que_ya_esta_responde_200_sin_duplicar(self):
        guardar()
        copia = self.client.get('/api/mix/recordings/export').json()

        respuesta = self.client.post('/api/mix/recordings/import', data=json.dumps(copia), content_type='application/json')

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json(), {'created': 0, 'skipped': 1})
        self.assertEqual(MixRecording.objects.count(), 1)

    def test_importar_un_archivo_invalido_responde_400(self):
        for cuerpo in ('', 'no-json', '[]', '{"format": "x"}'):
            with self.subTest(cuerpo=cuerpo):
                respuesta = self.client.post('/api/mix/recordings/import', data=cuerpo, content_type='application/json')
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn('error', respuesta.json())

    def test_otros_metodos_responden_405(self):
        self.assertEqual(self.client.post('/api/mix/recordings/export').status_code, 405)
        self.assertEqual(self.client.get('/api/mix/recordings/import').status_code, 405)

    def test_no_choca_con_la_ruta_de_una_grabacion(self):
        recording = guardar()

        self.assertEqual(self.client.get(f'/api/mix/recordings/{recording.pk}').status_code, 200)


class BackupCommandTests(TestCase):
    def test_exporta_a_un_archivo_y_restaura_desde_el(self):
        guardar()
        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / 'copia.json'
            salida = StringIO()
            call_command('recordings_backup', export=str(archivo), stdout=salida)
            self.assertIn('1 grabacion(es) guardadas', salida.getvalue())
            MixRecording.objects.all().delete()

            salida = StringIO()
            call_command('recordings_backup', importar=str(archivo), stdout=salida)

            self.assertIn('1 grabacion(es) restauradas', salida.getvalue())
        self.assertEqual(MixRecording.objects.count(), 1)

    def test_un_archivo_inexistente_da_un_error_claro(self):
        with self.assertRaisesRegex(CommandError, 'No se pudo leer'):
            call_command('recordings_backup', importar='no-existe.json')

    def test_un_archivo_que_no_es_json_da_un_error_claro(self):
        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / 'mal.json'
            archivo.write_text('esto no es json', encoding='utf-8')

            with self.assertRaisesRegex(CommandError, 'JSON valido'):
                call_command('recordings_backup', importar=str(archivo))

    def test_un_archivo_invalido_no_restaura_nada(self):
        with tempfile.TemporaryDirectory() as carpeta:
            archivo = Path(carpeta) / 'copia.json'
            archivo.write_text(json.dumps({'format': BACKUP_FORMAT, 'version': 1, 'recordings': [{}]}), encoding='utf-8')

            with self.assertRaisesRegex(CommandError, 'No se restauro nada'):
                call_command('recordings_backup', importar=str(archivo))
        self.assertEqual(MixRecording.objects.count(), 0)
