from unittest import mock

from django.test import TestCase

from audio.models import Track
from mixing.compatibility import DEFAULT_WEIGHTS
from mixing.learning import MIN_SAMPLES, Evaluation
from mixing.models import LearnedWeights, TransitionFeedback
from mixing.weights import (
    active_weights, current_weights, feedback_count, record_feedback, reset_weights, restore_weights, rollback_weights,
    weight_history,
)


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

        aprendidos = LearnedWeights.objects.get(active=True)
        self.assertEqual(aprendidos.samples, MIN_SAMPLES * 2)
        # Lo unico que distingue las que gustan de las que no es la armonia.
        self.assertGreater(aprendidos.harmonic, DEFAULT_WEIGHTS.harmonic)
        self.assertGreater(aprendidos.harmonic, aprendidos.tempo)

    def test_los_pesos_vigentes_pasan_a_ser_los_aprendidos(self):
        for _ in range(MIN_SAMPLES):
            record_feedback(self.base, self.compatible, liked=True)
            record_feedback(self.base, self.chocante, liked=False)

        self.assertGreater(current_weights().harmonic, DEFAULT_WEIGHTS.harmonic)

    def test_solo_hay_una_version_vigente_aunque_se_conserven_las_anteriores(self):
        for _ in range(MIN_SAMPLES + 5):
            record_feedback(self.base, self.compatible, liked=True)
            record_feedback(self.base, self.chocante, liked=False)

        self.assertEqual(LearnedWeights.objects.filter(active=True).count(), 1)
        self.assertGreater(LearnedWeights.objects.count(), 1)
        self.assertEqual(
            LearnedWeights.objects.get(active=True).version, LearnedWeights.objects.order_by('-version').first().version)

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

        aprendidos = LearnedWeights.objects.get(active=True)
        self.assertIsNotNone(aprendidos.accuracy)
        self.assertIsNotNone(aprendidos.default_accuracy)
        self.assertGreaterEqual(aprendidos.accuracy, aprendidos.default_accuracy)

    def test_la_version_sube_con_cada_reentrenamiento(self):
        self.valorar(MIN_SAMPLES)
        primera = LearnedWeights.objects.get(active=True).version

        record_feedback(self.base, self.compatible, liked=True)

        self.assertEqual(LearnedWeights.objects.get(active=True).version, primera + 1)

    def test_si_no_se_pudo_evaluar_igual_se_guardan_los_pesos_sin_acierto(self):
        with mock.patch('mixing.weights.evaluate', return_value=None):
            self.valorar(MIN_SAMPLES)

        aprendidos = LearnedWeights.objects.get(active=True)
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

        self.assertEqual(LearnedWeights.objects.filter(active=True).count(), 1)

    def test_rechazar_unos_pesos_nuevos_conserva_los_aprendidos_antes(self):
        self.valorar(MIN_SAMPLES)
        anteriores = LearnedWeights.objects.get(active=True)
        peor = Evaluation(learned=0.4, default=0.6, majority=0.5, folds=5, samples=20)

        with mock.patch('mixing.weights.evaluate', return_value=peor):
            record_feedback(self.base, self.compatible, liked=True)

        actuales = LearnedWeights.objects.get(active=True)
        self.assertEqual(actuales.pk, anteriores.pk)
        self.assertEqual(actuales.version, anteriores.version)


def crear_version(version, tempo=0.3, harmonic=0.5, energy=0.2, active=False):
    return LearnedWeights.objects.create(
        tempo=tempo, harmonic=harmonic, energy=energy, samples=40, version=version, active=active)


class HistorialDePesosTests(TestCase):
    def setUp(self):
        self.base = crear_track('base', camelot='8B')
        self.compatible = crear_track('compatible', camelot='8B')
        self.chocante = crear_track('chocante', camelot='3A')

    def valorar(self, veces):
        for _ in range(veces):
            record_feedback(self.base, self.compatible, liked=True)
            record_feedback(self.base, self.chocante, liked=False)

    def test_cada_reentrenamiento_conserva_la_version_anterior_como_historial(self):
        self.valorar(MIN_SAMPLES)

        versiones = [(row.version, row.active) for row in weight_history()]

        self.assertGreaterEqual(len(versiones), 2)
        self.assertEqual(versiones[0][1], True)  # la mas nueva esta vigente
        self.assertTrue(all(not activa for _, activa in versiones[1:]))
        self.assertEqual([v for v, _ in versiones], sorted((v for v, _ in versiones), reverse=True))

    def test_solo_se_conservan_las_ultimas_versiones(self):
        with mock.patch('mixing.weights.MAX_WEIGHT_VERSIONS', 3):
            self.valorar(MIN_SAMPLES + 3)

        versiones = list(LearnedWeights.objects.order_by('-version').values_list('version', flat=True))
        self.assertEqual(len(versiones), 3)
        self.assertEqual(versiones, sorted(versiones, reverse=True))
        self.assertTrue(LearnedWeights.objects.get(version=versiones[0]).active)

    def test_restore_weights_vuelve_a_usar_esa_version(self):
        crear_version(1, tempo=0.1, harmonic=0.8, energy=0.1)
        crear_version(2, tempo=0.5, harmonic=0.3, energy=0.2, active=True)

        elegida = restore_weights(1)

        self.assertEqual(elegida.version, 1)
        self.assertEqual(active_weights().version, 1)
        self.assertEqual(current_weights().harmonic, 0.8)
        self.assertEqual(LearnedWeights.objects.filter(active=True).count(), 1)

    def test_restore_weights_con_una_version_que_no_existe_falla_y_no_cambia_nada(self):
        crear_version(2, active=True)

        with self.assertRaises(LookupError):
            restore_weights(7)

        self.assertEqual(active_weights().version, 2)

    def test_rollback_weights_vuelve_a_la_version_anterior_a_la_vigente(self):
        crear_version(1, tempo=0.1, harmonic=0.7, energy=0.2)
        crear_version(2, tempo=0.3, harmonic=0.5, energy=0.2)
        crear_version(3, tempo=0.5, harmonic=0.3, energy=0.2, active=True)

        self.assertEqual(rollback_weights().version, 2)
        self.assertEqual(rollback_weights().version, 1)
        self.assertEqual(current_weights().harmonic, 0.7)

    def test_rollback_weights_sin_version_anterior_o_sin_pesos_falla(self):
        with self.assertRaises(LookupError):
            rollback_weights()

        crear_version(1, active=True)
        with self.assertRaises(LookupError):
            rollback_weights()
        self.assertEqual(active_weights().version, 1)

    def test_la_proxima_valoracion_crea_una_version_nueva_encima_de_la_mas_alta(self):
        crear_version(1)
        crear_version(2, active=True)
        restore_weights(1)

        self.valorar(MIN_SAMPLES)

        self.assertGreater(active_weights().version, 2)

    def test_reset_weights_vuelve_a_los_pesos_por_defecto_pero_conserva_valoraciones_e_historial(self):
        self.valorar(MIN_SAMPLES)
        versiones = LearnedWeights.objects.count()

        borradas = reset_weights()

        self.assertEqual(borradas, 0)
        self.assertEqual(current_weights(), DEFAULT_WEIGHTS)
        self.assertIsNone(active_weights())
        self.assertEqual(LearnedWeights.objects.count(), versiones)
        self.assertEqual(feedback_count(), MIN_SAMPLES * 2)

    def test_tras_un_reset_la_proxima_valoracion_vuelve_a_aprender(self):
        self.valorar(MIN_SAMPLES)
        reset_weights()

        record_feedback(self.base, self.compatible, liked=True)

        self.assertIsNotNone(active_weights())
        self.assertNotEqual(current_weights(), DEFAULT_WEIGHTS)

    def test_reset_weights_olvidando_las_valoraciones_empieza_de_cero(self):
        self.valorar(MIN_SAMPLES)

        borradas = reset_weights(forget_ratings=True)

        self.assertEqual(borradas, MIN_SAMPLES * 2)
        self.assertEqual(feedback_count(), 0)
        self.assertEqual(LearnedWeights.objects.count(), 0)
        self.assertEqual(current_weights(), DEFAULT_WEIGHTS)
