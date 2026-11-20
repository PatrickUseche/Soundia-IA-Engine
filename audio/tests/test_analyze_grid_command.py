from io import StringIO

import numpy as np
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase

from audio.models import Track
from audio.tests.media import TempMediaMixin
from audio.tests.signals import SR, click_track, to_wav_bytes
from audio.tests.test_beatgrid import circular_error


def crear_pista(bpm=110.2, con_audio=True, segundos=40, **cambios):
    payload_data = dict(
        title='tema.wav', duration=float(segundos), bpm=bpm, key='C major', camelot='8B', energy=0.6,
        cue_points=[0.0, 60.0],
    )
    payload_data.update(cambios)
    track_obj = Track.objects.create(**payload_data)
    if con_audio:
        track_obj.audio_file.save('tema.wav', ContentFile(to_wav_bytes(click_track(110.0, segundos, first_beat=0.2))), save=True)
    return track_obj


class AnalyzeGridCommandTests(TempMediaMixin, TestCase):
    def ejecutar(self, *args):
        salida = StringIO()
        call_command('analyze_grid', *args, stdout=salida)
        return salida.getvalue()

    def test_calcula_la_rejilla_de_las_pistas_que_no_la_tienen(self):
        track_obj = crear_pista()

        salida = self.ejecutar()

        track_obj.refresh_from_db()
        self.assertAlmostEqual(track_obj.bpm, 110.0, delta=0.02)
        self.assertLess(abs(circular_error(track_obj.grid_offset, 0.2, 60 / 110)), 0.004)
        self.assertIsNotNone(track_obj.grid_downbeat)
        self.assertIsNotNone(track_obj.grid_confidence)
        self.assertIn('1 pista', salida)

    def test_recalcula_los_puntos_de_mezcla_sobre_la_nueva_rejilla(self):
        track_obj = crear_pista(cue_points=[0.0, 99.0])

        self.ejecutar()

        track_obj.refresh_from_db()
        self.assertAlmostEqual(track_obj.cue_points[0], 0.2, delta=0.01)

    def test_no_toca_la_tonalidad_ni_la_energia(self):
        track_obj = crear_pista(key='F minor', camelot='4A', energy=0.123)

        self.ejecutar()

        track_obj.refresh_from_db()
        self.assertEqual((track_obj.key, track_obj.camelot, track_obj.energy), ('F minor', '4A', 0.123))

    def test_las_pistas_que_ya_tienen_rejilla_se_saltan_salvo_con_all(self):
        track_obj = crear_pista(grid_offset=0.5, grid_downbeat=0.5, grid_confidence=0.9, bpm=110.2)

        self.ejecutar()
        track_obj.refresh_from_db()
        self.assertEqual(track_obj.grid_offset, 0.5)

        self.ejecutar('--all')
        track_obj.refresh_from_db()
        self.assertNotEqual(track_obj.grid_offset, 0.5)

    def test_una_pista_sin_audio_guardado_se_ignora(self):
        track_obj = crear_pista(con_audio=False)

        salida = self.ejecutar()

        track_obj.refresh_from_db()
        self.assertIsNone(track_obj.grid_offset)
        self.assertIn('0 pista', salida)

    def test_una_pista_sin_ritmo_claro_no_recibe_rejilla_y_conserva_su_tempo(self):
        track_obj = crear_pista(bpm=128.0, con_audio=False)
        ruido = ContentFile(to_wav_bytes(np.random.default_rng(3).normal(0, 0.1, SR * 20)))
        track_obj.audio_file.save('ruido.wav', ruido, save=True)

        self.ejecutar()

        track_obj.refresh_from_db()
        self.assertIsNone(track_obj.grid_offset)
        self.assertEqual(track_obj.cue_points, [0.0, 60.0])

    def test_un_archivo_ilegible_no_detiene_el_resto(self):
        mala = crear_pista(title='mala', con_audio=False)
        mala.audio_file.save('rota.wav', ContentFile(b'no es audio'), save=True)
        buena = crear_pista(title='buena')

        self.ejecutar()

        buena.refresh_from_db()
        self.assertIsNotNone(buena.grid_offset)


class AnalyzeGridCommandManualTests(TempMediaMixin, TestCase):
    def ejecutar(self, *args):
        salida = StringIO()
        call_command('analyze_grid', *args, stdout=salida)
        return salida.getvalue()

    def crear_manual(self):
        return crear_pista(grid_offset=0.2, grid_downbeat=0.9, grid_confidence=1.0, grid_manual=True)

    def test_con_all_no_pisa_el_primer_tiempo_fijado_a_mano(self):
        track_obj = self.crear_manual()

        salida = self.ejecutar('--all')

        track_obj.refresh_from_db()
        self.assertEqual((track_obj.grid_downbeat, track_obj.grid_confidence, track_obj.grid_manual), (0.9, 1.0, True))
        self.assertIn('0 pista', salida)

    def test_con_include_manual_si_la_recalcula_y_pierde_la_marca_de_manual(self):
        track_obj = self.crear_manual()

        self.ejecutar('--all', '--include-manual')

        track_obj.refresh_from_db()
        self.assertNotEqual(track_obj.grid_confidence, 1.0)

    def test_recalcula_el_resto_aunque_haya_pistas_manuales(self):
        manual = self.crear_manual()
        normal = crear_pista(grid_offset=0.5, grid_downbeat=0.5, grid_confidence=0.1)

        self.ejecutar('--all')

        manual.refresh_from_db()
        normal.refresh_from_db()
        self.assertEqual(manual.grid_downbeat, 0.9)
        self.assertNotEqual(normal.grid_offset, 0.5)
