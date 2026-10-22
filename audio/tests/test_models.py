from django.core.exceptions import ValidationError
from django.test import TestCase

from django.core.files.base import ContentFile

from audio.models import Track
from audio.tests.media import TempMediaMixin


def crear_track(**cambios):
    datos = dict(
        title='cancion.wav', duration=180.0, bpm=128.0, key='C major', camelot='8B',
        energy=0.6, cue_points=[0.0, 32.5, 150.0],
    )
    datos.update(cambios)
    return Track(**datos)


class TrackModelTests(TestCase):
    def test_una_pista_nueva_no_tiene_analisis_de_voz(self):
        crear_track().save()

        track = Track.objects.get()
        self.assertEqual(track.vocal_status, Track.VOCALS_NONE)
        self.assertIsNone(track.vocal_last_end)

    def test_una_pista_nueva_no_tiene_rejilla_hasta_que_se_analiza(self):
        crear_track().save()

        track = Track.objects.get()
        self.assertEqual((track.grid_offset, track.grid_downbeat, track.grid_confidence), (None, None, None))

    def test_guarda_la_rejilla_de_pulsos(self):
        crear_track(grid_offset=0.0239, grid_downbeat=0.5844, grid_confidence=0.585).save()

        track = Track.objects.get()
        self.assertEqual((track.grid_offset, track.grid_downbeat, track.grid_confidence), (0.0239, 0.5844, 0.585))

    def test_guarda_hasta_donde_llega_la_voz(self):
        crear_track(vocal_status=Track.VOCALS_DONE, vocal_last_end=229.7).save()

        track = Track.objects.get()
        self.assertEqual(track.vocal_status, 'done')
        self.assertEqual(track.vocal_last_end, 229.7)

    def test_rechaza_un_estado_de_voz_desconocido(self):
        with self.assertRaises(ValidationError):
            crear_track(vocal_status='quiza').full_clean()

    def test_se_guarda_y_se_lee_con_sus_puntos_de_mezcla(self):
        crear_track().save()

        track = Track.objects.get()
        self.assertEqual(track.camelot, '8B')
        self.assertEqual(track.cue_points, [0.0, 32.5, 150.0])
        self.assertIsNotNone(track.created_at)

    def test_los_puntos_de_mezcla_son_opcionales(self):
        track = crear_track(cue_points=[])
        track.full_clean()

    def test_str_resume_la_pista(self):
        self.assertEqual(str(crear_track()), 'cancion.wav (128 BPM, 8B)')

    def test_bpm_fuera_de_rango_es_invalido(self):
        for bpm in (5, 500):
            with self.subTest(bpm=bpm):
                with self.assertRaises(ValidationError):
                    crear_track(bpm=bpm).full_clean()

    def test_energia_fuera_de_0_a_1_es_invalida(self):
        for energia in (-0.1, 1.5):
            with self.subTest(energia=energia):
                with self.assertRaises(ValidationError):
                    crear_track(energy=energia).full_clean()

    def test_las_pistas_mas_recientes_van_primero(self):
        crear_track(title='vieja').save()
        crear_track(title='nueva').save()

        self.assertEqual(Track.objects.first().title, 'nueva')


class TrackAudioFileTests(TempMediaMixin, TestCase):
    def test_una_pista_nueva_no_tiene_archivo(self):
        track = crear_track()
        track.save()

        self.assertFalse(track.audio_file)

    def test_guarda_el_archivo_de_audio(self):
        track = crear_track()
        track.save()

        track.audio_file.save('tema.wav', ContentFile(b'RIFFdatos'))

        track.refresh_from_db()
        self.assertTrue(track.audio_file)
        self.assertTrue(track.audio_file.name.startswith('tracks/'))
        with track.audio_file.open('rb') as archivo:
            self.assertEqual(archivo.read(), b'RIFFdatos')

    def test_dos_archivos_con_el_mismo_nombre_no_se_pisan(self):
        a, b = crear_track(), crear_track()
        a.save()
        b.save()

        a.audio_file.save('tema.wav', ContentFile(b'AAAA'))
        b.audio_file.save('tema.wav', ContentFile(b'BBBB'))

        self.assertNotEqual(a.audio_file.name, b.audio_file.name)
        with a.audio_file.open('rb') as archivo:
            self.assertEqual(archivo.read(), b'AAAA')


class GridManualTests(TestCase):
    def test_por_defecto_la_rejilla_no_es_manual(self):
        pista = Track.objects.create(
            title='x', duration=10.0, bpm=120.0, key='C major', camelot='8B', energy=0.5, cue_points=[0.0])

        self.assertFalse(pista.grid_manual)
