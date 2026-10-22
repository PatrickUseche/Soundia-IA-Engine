from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from audio.models import Track
from mixing.models import LearnedWeights, MixTimingFeedback, TransitionFeedback
from mixing.weights import active_weights


def ejecutar(*args):
    salida = StringIO()
    call_command('learning', *args, stdout=salida)
    return salida.getvalue()


def version(numero, active=False, harmonic=0.5):
    return LearnedWeights.objects.create(
        tempo=0.3, harmonic=harmonic, energy=0.2, samples=40, version=numero, active=active, accuracy=0.8)


class LearningCommandTests(TestCase):
    def setUp(self):
        self.a = Track.objects.create(
            title='a', duration=200.0, bpm=128.0, key='C major', camelot='8B', energy=0.6, cue_points=[0.0])
        self.b = Track.objects.create(
            title='b', duration=200.0, bpm=128.0, key='C major', camelot='8B', energy=0.6, cue_points=[0.0])

    def test_sin_una_accion_falla(self):
        with self.assertRaises(CommandError):
            call_command('learning')

    def test_list_muestra_las_versiones_y_marca_la_vigente(self):
        version(1)
        version(2, active=True)

        texto = ejecutar('--list')

        self.assertIn('* version 2', texto)
        self.assertIn('  version 1', texto)
        self.assertLess(texto.index('version 2'), texto.index('version 1'))

    def test_list_sin_pesos_lo_dice(self):
        self.assertIn('Sin pesos aprendidos', ejecutar('--list'))

    def test_list_avisa_si_ninguna_version_esta_vigente(self):
        version(1)

        self.assertIn('Ninguna esta vigente', ejecutar('--list'))

    def test_rollback_weights_vuelve_a_la_anterior(self):
        version(1)
        version(2, active=True)

        texto = ejecutar('--rollback-weights')

        self.assertIn('version 1', texto)
        self.assertEqual(active_weights().version, 1)

    def test_rollback_weights_sin_anterior_da_un_error_claro(self):
        version(1, active=True)

        with self.assertRaisesMessage(CommandError, 'No hay una version anterior'):
            call_command('learning', '--rollback-weights')

    def test_restore_version_vuelve_a_esa_version(self):
        version(1)
        version(2)
        version(3, active=True)

        ejecutar('--restore-version', '1')

        self.assertEqual(active_weights().version, 1)

    def test_restore_version_inexistente_da_un_error_claro(self):
        with self.assertRaisesMessage(CommandError, 'No hay una version 9'):
            call_command('learning', '--restore-version', '9')

    def test_reset_weights_deja_de_usar_los_pesos_pero_conserva_las_valoraciones(self):
        version(1, active=True)
        TransitionFeedback.objects.create(from_track=self.a, to_track=self.b, tempo=1, harmonic=1, energy=1, liked=True)

        texto = ejecutar('--reset-weights')

        self.assertIsNone(active_weights())
        self.assertEqual(TransitionFeedback.objects.count(), 1)
        self.assertIn('volvera a entrenar', texto)

    def test_reset_weights_con_forget_ratings_borra_todo(self):
        version(1, active=True)
        TransitionFeedback.objects.create(from_track=self.a, to_track=self.b, tempo=1, harmonic=1, energy=1, liked=True)

        texto = ejecutar('--reset-weights', '--forget-ratings')

        self.assertEqual(TransitionFeedback.objects.count(), 0)
        self.assertEqual(LearnedWeights.objects.count(), 0)
        self.assertIn('Se borraron 1 valoracion', texto)

    def test_forget_ratings_sin_reset_weights_falla(self):
        with self.assertRaises(CommandError):
            call_command('learning', '--list', '--forget-ratings')

    def test_reset_timing_borra_lo_aprendido_sobre_cuando_mezclar(self):
        MixTimingFeedback.objects.create(from_track=self.a, to_track=self.b, planned_mix_out=120, actual_mix_out=100)
        MixTimingFeedback.objects.create(from_track=self.b, to_track=self.a, planned_mix_out=120, actual_mix_out=90)

        texto = ejecutar('--reset-timing')

        self.assertEqual(MixTimingFeedback.objects.count(), 0)
        self.assertIn('Se borraron 2 caso', texto)

    def test_las_acciones_son_excluyentes(self):
        with self.assertRaises(CommandError):
            call_command('learning', '--list', '--reset-timing')
