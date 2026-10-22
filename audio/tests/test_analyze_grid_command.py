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
    datos = dict(
        title='tema.wav', duration=float(segundos), bpm=bpm, key='C major', camelot='8B', energy=0.6,
        cue_points=[0.0, 60.0],
    )
    datos.update(cambios)
    pista = Track.objects.create(**datos)
    if con_audio:
        pista.audio_file.save('tema.wav', ContentFile(to_wav_bytes(click_track(110.0, segundos, first_beat=0.2))), save=True)
    return pista


class AnalyzeGridCommandTests(TempMediaMixin, TestCase):
    def ejecutar(self, *args):
        salida = StringIO()
        call_command('analyze_grid', *args, stdout=salida)
        return salida.getvalue()

    def test_calcula_la_rejilla_de_las_pistas_que_no_la_tienen(self):
        pista = crear_pista()

        salida = self.ejecutar()

        pista.refresh_from_db()
        self.assertAlmostEqual(pista.bpm, 110.0, delta=0.02)
        self.assertLess(abs(circular_error(pista.grid_offset, 0.2, 60 / 110)), 0.004)
        self.assertIsNotNone(pista.grid_downbeat)
        self.assertIsNotNone(pista.grid_confidence)
        self.assertIn('1 pista', salida)

    def test_recalcula_los_puntos_de_mezcla_sobre_la_nueva_rejilla(self):
        pista = crear_pista(cue_points=[0.0, 99.0])

        self.ejecutar()

        pista.refresh_from_db()
        self.assertAlmostEqual(pista.cue_points[0], 0.2, delta=0.01)

    def test_no_toca_la_tonalidad_ni_la_energia(self):
        pista = crear_pista(key='F minor', camelot='4A', energy=0.123)

        self.ejecutar()

        pista.refresh_from_db()
        self.assertEqual((pista.key, pista.camelot, pista.energy), ('F minor', '4A', 0.123))

    def test_las_pistas_que_ya_tienen_rejilla_se_saltan_salvo_con_all(self):
        pista = crear_pista(grid_offset=0.5, grid_downbeat=0.5, grid_confidence=0.9, bpm=110.2)

        self.ejecutar()
        pista.refresh_from_db()
        self.assertEqual(pista.grid_offset, 0.5)

        self.ejecutar('--all')
        pista.refresh_from_db()
        self.assertNotEqual(pista.grid_offset, 0.5)

    def test_una_pista_sin_audio_guardado_se_ignora(self):
        pista = crear_pista(con_audio=False)

        salida = self.ejecutar()

        pista.refresh_from_db()
        self.assertIsNone(pista.grid_offset)
        self.assertIn('0 pista', salida)

    def test_una_pista_sin_ritmo_claro_no_recibe_rejilla_y_conserva_su_tempo(self):
        pista = crear_pista(bpm=128.0, con_audio=False)
        ruido = ContentFile(to_wav_bytes(np.random.default_rng(3).normal(0, 0.1, SR * 20)))
        pista.audio_file.save('ruido.wav', ruido, save=True)

        self.ejecutar()

        pista.refresh_from_db()
        self.assertIsNone(pista.grid_offset)
        self.assertEqual(pista.cue_points, [0.0, 60.0])

    def test_un_archivo_ilegible_no_detiene_el_resto(self):
        mala = crear_pista(title='mala', con_audio=False)
        mala.audio_file.save('rota.wav', ContentFile(b'no es audio'), save=True)
        buena = crear_pista(title='buena')

        self.ejecutar()

        buena.refresh_from_db()
        self.assertIsNotNone(buena.grid_offset)
