import random

from django.test import SimpleTestCase

from mixing.learning import EVALUATION_FOLDS, MIN_SAMPLES, Evaluation, FeedbackSample, evaluate


def muestras(n, criterio, semilla=1):
    azar = random.Random(semilla)
    outcome = []
    for _ in range(n):
        tempo, armonia, energia = azar.random(), azar.random(), azar.random()
        outcome.append(FeedbackSample(tempo, armonia, energia, criterio(tempo, armonia, energia, azar)))
    return outcome


class EvaluateTests(SimpleTestCase):
    def test_sin_valoraciones_suficientes_no_evalua(self):
        self.assertIsNone(evaluate(muestras(MIN_SAMPLES - 1, lambda t, h, e, a: t > 0.5)))

    def test_si_todas_son_iguales_no_evalua(self):
        self.assertIsNone(evaluate(muestras(50, lambda t, h, e, a: True)))

    def test_menos_de_dos_grupos_no_evalua(self):
        self.assertIsNone(evaluate(muestras(50, lambda t, h, e, a: t > 0.5), folds=1))

    def test_devuelve_una_evaluacion_con_los_datos_usados(self):
        outcome = evaluate(muestras(60, lambda t, h, e, a: t > 0.5))

        self.assertIsInstance(outcome, Evaluation)
        self.assertEqual(outcome.samples, 60)
        self.assertEqual(outcome.folds, EVALUATION_FOLDS)

    def test_las_proporciones_estan_entre_0_y_1(self):
        outcome = evaluate(muestras(60, lambda t, h, e, a: t > 0.5))

        for raw_value in (outcome.learned, outcome.default, outcome.majority):
            self.assertGreaterEqual(raw_value, 0)
            self.assertLessEqual(raw_value, 1)

    def test_es_determinista(self):
        payload_data = muestras(60, lambda t, h, e, a: t > 0.5)

        self.assertEqual(evaluate(payload_data), evaluate(list(payload_data)))

    def test_si_el_gusto_depende_de_un_criterio_el_modelo_supera_a_los_pesos_por_defecto(self):
        # Al DJ solo le importa la armonia (los pesos por defecto le dan 0.40): el modelo debe verlo.
        outcome = evaluate(muestras(150, lambda t, h, e, a: h > 0.6))

        self.assertTrue(outcome.improves_on_default)
        self.assertTrue(outcome.beats_majority)
        self.assertGreater(outcome.learned, 0.8)

    def test_si_el_gusto_es_azar_no_supera_a_quien_siempre_dice_lo_mismo_por_mucho(self):
        outcome = evaluate(muestras(150, lambda t, h, e, a: a.random() < 0.5))

        # Sin senal real no hay nada que aprender: no debe parecer que acierta mucho mas que el azar.
        self.assertLess(outcome.learned, 0.65)

    def test_la_mayoria_es_la_proporcion_de_la_clase_mas_frecuente(self):
        # 90 % "me gusto" al azar: decir siempre "me gusto" acierta ~0.9.
        outcome = evaluate(muestras(100, lambda t, h, e, a: a.random() < 0.9))

        self.assertGreater(outcome.majority, 0.8)

    def test_se_salta_un_grupo_si_el_entrenamiento_se_queda_con_una_sola_clase(self):
        # Solo hay dos "no me gusto" y caen en el mismo grupo: al apartarlo el resto son todos "me gusto".
        payload_data = [FeedbackSample(0.5, 0.5, 0.5, True) for _ in range(20)]
        payload_data[0] = FeedbackSample(0.1, 0.1, 0.1, False)
        payload_data[EVALUATION_FOLDS] = FeedbackSample(0.1, 0.1, 0.1, False)

        outcome = evaluate(payload_data)

        self.assertEqual(outcome.folds, EVALUATION_FOLDS - 1)

    def test_improves_on_default_y_beats_majority_comparan_estrictamente(self):
        igual = Evaluation(learned=0.7, default=0.7, majority=0.7, folds=5, samples=50)
        mejor = Evaluation(learned=0.8, default=0.7, majority=0.6, folds=5, samples=50)

        self.assertFalse(igual.improves_on_default)
        self.assertFalse(igual.beats_majority)
        self.assertTrue(mejor.improves_on_default)
        self.assertTrue(mejor.beats_majority)
