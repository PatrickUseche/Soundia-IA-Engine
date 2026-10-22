from unittest import mock

from django.test import TestCase

from audio.models import Track
from mixing.compatibility import DEFAULT_WEIGHTS
from mixing.learning import MIN_SAMPLES, Evaluation
from mixing.models import LearnedWeights, TransitionFeedback
from mixing.weights import current_weights, feedback_count, record_feedback


def crear_track(titulo, camelot='8B', bpm=128.0, energy=0.6):
    return Track.objects.create(
        title=titulo, duration=200.0, bpm=bpm, key='C major', camelot=camelot, energy=energy, cue_points=[0.0])


class CurrentWeightsTests(TestCase):
    def test_sin_valoraciones_son_los_pesos_por_defecto(self):
        self.assertEqual(current_weights(), DEFAULT_WEIGHTS)

    def test_con_pesos_aprendidos_guardados_se_usan_esos(self):
        LearnedWeights.objects.create(tempo=0.2, harmonic=0.6, energy=0.2, samples=50)

        pesos = current_weights()

        self.assertEqual((pesos.tempo, pesos.harmonic, pesos.energy), (0.2, 0.6, 0.2))


class RecordFeedbackTests(TestCase):
    def setUp(self):
        self.base = crear_track('base', camelot='8B')
        self.compatible = crear_track('compatible', camelot='8B')   # armonia perfecta
        self.chocante = crear_track('chocante', camelot='3A')       # armonia nula

    def test_guarda_la_valoracion_con_las_puntuaciones_de_ese_momento(self):
        record_feedback(self.base, self.compatible, liked=True)

        feedback = TransitionFeedback.objects.get()
        self.assertTrue(feedback.liked)
        self.assertEqual(feedback.from_track, self.base)
        self.assertEqual(feedback.to_track, self.compatible)
        self.assertEqual(feedback.harmonic, 1.0)
        self.assertEqual(feedback.tempo, 1.0)

    def test_una_transicion_chocante_guarda_su_armonia_nula(self):
        record_feedback(self.base, self.chocante, liked=False)

        self.assertEqual(TransitionFeedback.objects.get().harmonic, 0.0)

    def test_con_pocas_valoraciones_los_pesos_no_cambian(self):
        pesos = record_feedback(self.base, self.compatible, liked=True)

        self.assertEqual(pesos, DEFAULT_WEIGHTS)
        self.assertEqual(LearnedWeights.objects.count(), 0)

    def test_si_todas_las_valoraciones_son_iguales_no_se_aprende(self):
        for _ in range(MIN_SAMPLES * 2):
            record_feedback(self.base, self.compatible, liked=True)

        self.assertEqual(current_weights(), DEFAULT_WEIGHTS)

    def test_con_suficientes_valoraciones_aprende_y_guarda_los_pesos(self):
        for _ in range(MIN_SAMPLES):
            record_feedback(self.base, self.compatible, liked=True)
            record_feedback(self.base, self.chocante, liked=False)

        aprendidos = LearnedWeights.objects.get()
        self.assertEqual(aprendidos.samples, MIN_SAMPLES * 2)
        # Lo unico que distingue las que gustan de las que no es la armonia.
        self.assertGreater(aprendidos.harmonic, DEFAULT_WEIGHTS.harmonic)
        self.assertGreater(aprendidos.harmonic, aprendidos.tempo)

    def test_los_pesos_vigentes_pasan_a_ser_los_aprendidos(self):
        for _ in range(MIN_SAMPLES):
            record_feedback(self.base, self.compatible, liked=True)
            record_feedback(self.base, self.chocante, liked=False)

        self.assertGreater(current_weights().harmonic, DEFAULT_WEIGHTS.harmonic)

    def test_solo_se_conserva_una_fila_de_pesos_aprendidos(self):
        for _ in range(MIN_SAMPLES + 5):
            record_feedback(self.base, self.compatible, liked=True)
            record_feedback(self.base, self.chocante, liked=False)

        self.assertEqual(LearnedWeights.objects.count(), 1)

    def test_el_resultado_no_depende_del_orden_en_que_llegaron_las_valoraciones(self):
        for _ in range(MIN_SAMPLES):
            record_feedback(self.base, self.compatible, liked=True)
        for _ in range(MIN_SAMPLES):
            record_feedback(self.base, self.chocante, liked=False)
        un_orden = current_weights()

        TransitionFeedback.objects.all().delete()
        LearnedWeights.objects.all().delete()
        for _ in range(MIN_SAMPLES):
            record_feedback(self.base, self.chocante, liked=False)
        for _ in range(MIN_SAMPLES):
            record_feedback(self.base, self.compatible, liked=True)
        otro_orden = current_weights()

        self.assertAlmostEqual(un_orden.harmonic, otro_orden.harmonic, places=9)
        self.assertAlmostEqual(un_orden.tempo, otro_orden.tempo, places=9)

    def test_feedback_count_cuenta_las_valoraciones(self):
        self.assertEqual(feedback_count(), 0)

        record_feedback(self.base, self.compatible, liked=True)
        record_feedback(self.base, self.chocante, liked=False)

        self.assertEqual(feedback_count(), 2)

    def test_borrar_una_pista_borra_sus_valoraciones(self):
        record_feedback(self.base, self.compatible, liked=True)

        self.compatible.delete()

        self.assertEqual(TransitionFeedback.objects.count(), 0)


class EvaluacionYVersionTests(TestCase):
    def setUp(self):
        self.base = crear_track('base', camelot='8B')
        self.compatible = crear_track('compatible', camelot='8B')
        self.chocante = crear_track('chocante', camelot='3A')

    def valorar(self, veces):
        for _ in range(veces):
            record_feedback(self.base, self.compatible, liked=True)
            record_feedback(self.base, self.chocante, liked=False)

    def test_guarda_el_acierto_medido_y_el_de_los_pesos_por_defecto(self):
        self.valorar(MIN_SAMPLES)

        aprendidos = LearnedWeights.objects.get()
        self.assertIsNotNone(aprendidos.accuracy)
        self.assertIsNotNone(aprendidos.default_accuracy)
        self.assertGreaterEqual(aprendidos.accuracy, aprendidos.default_accuracy)

    def test_la_version_sube_con_cada_reentrenamiento(self):
        self.valorar(MIN_SAMPLES)
        primera = LearnedWeights.objects.get().version

        record_feedback(self.base, self.compatible, liked=True)

        self.assertEqual(LearnedWeights.objects.get().version, primera + 1)

    def test_si_no_se_pudo_evaluar_igual_se_guardan_los_pesos_sin_acierto(self):
        with mock.patch('mixing.weights.evaluate', return_value=None):
            self.valorar(MIN_SAMPLES)

        aprendidos = LearnedWeights.objects.get()
        self.assertIsNone(aprendidos.accuracy)
        self.assertIsNone(aprendidos.default_accuracy)

    def test_si_los_pesos_nuevos_aciertan_menos_que_los_de_siempre_no_se_adoptan(self):
        peor = Evaluation(learned=0.4, default=0.6, majority=0.5, folds=5, samples=20)
        with mock.patch('mixing.weights.evaluate', return_value=peor):
            self.valorar(MIN_SAMPLES)

        self.assertEqual(LearnedWeights.objects.count(), 0)
        self.assertEqual(current_weights(), DEFAULT_WEIGHTS)

    def test_si_los_nuevos_empatan_con_los_de_siempre_si_se_adoptan(self):
        empate = Evaluation(learned=0.6, default=0.6, majority=0.5, folds=5, samples=20)
        with mock.patch('mixing.weights.evaluate', return_value=empate):
            self.valorar(MIN_SAMPLES)

        self.assertEqual(LearnedWeights.objects.count(), 1)

    def test_rechazar_unos_pesos_nuevos_conserva_los_aprendidos_antes(self):
        self.valorar(MIN_SAMPLES)
        anteriores = LearnedWeights.objects.get()
        peor = Evaluation(learned=0.4, default=0.6, majority=0.5, folds=5, samples=20)

        with mock.patch('mixing.weights.evaluate', return_value=peor):
            record_feedback(self.base, self.compatible, liked=True)

        actuales = LearnedWeights.objects.get()
        self.assertEqual(actuales.pk, anteriores.pk)
        self.assertEqual(actuales.version, anteriores.version)
