import random

from django.test import SimpleTestCase

from mixing.compatibility import DEFAULT_WEIGHTS, ScoringWeights
from mixing.learning import (
    MIN_SAMPLES,
    MIN_WEIGHT,
    FeedbackSample,
    has_enough_signal,
    predict_like_probability,
    train_weights,
)


def muestras(n, criterio, semilla=1, ruido=0.0):
    """Valoraciones sinteticas: puntuaciones al azar y el gusto lo decide `criterio(tempo, armonia, energia)`."""
    azar = random.Random(semilla)
    resultado = []
    for _ in range(n):
        t, h, e = azar.random(), azar.random(), azar.random()
        le_gusto = criterio(t, h, e)
        if azar.random() < ruido:
            le_gusto = not le_gusto
        resultado.append(FeedbackSample(t, h, e, le_gusto))
    return resultado


class HasEnoughSignalTests(SimpleTestCase):
    def test_con_pocas_valoraciones_no_hay_senal(self):
        datos = muestras(MIN_SAMPLES - 1, lambda t, h, e: h > 0.5)

        self.assertFalse(has_enough_signal(datos))

    def test_con_las_suficientes_de_las_dos_clases_si(self):
        datos = muestras(MIN_SAMPLES * 3, lambda t, h, e: h > 0.5)

        self.assertTrue(has_enough_signal(datos))

    def test_si_todas_son_iguales_no_hay_senal(self):
        todas_gustan = [FeedbackSample(0.5, 0.5, 0.5, True)] * (MIN_SAMPLES * 2)
        ninguna_gusta = [FeedbackSample(0.5, 0.5, 0.5, False)] * (MIN_SAMPLES * 2)

        self.assertFalse(has_enough_signal(todas_gustan))
        self.assertFalse(has_enough_signal(ninguna_gusta))

    def test_sin_valoraciones_no_hay_senal(self):
        self.assertFalse(has_enough_signal([]))


class PredictLikeProbabilityTests(SimpleTestCase):
    def test_una_transicion_perfecta_es_mas_probable_que_guste_que_una_mala(self):
        buena = FeedbackSample(1.0, 1.0, 1.0, True)
        mala = FeedbackSample(0.0, 0.0, 0.0, False)

        self.assertGreater(predict_like_probability(DEFAULT_WEIGHTS, buena), predict_like_probability(DEFAULT_WEIGHTS, mala))

    def test_es_una_probabilidad(self):
        for t in (0.0, 0.5, 1.0):
            p = predict_like_probability(DEFAULT_WEIGHTS, FeedbackSample(t, t, t, True))
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

    def test_valores_extremos_no_desbordan(self):
        p = predict_like_probability(ScoringWeights(1.0, 0.0, 0.0), FeedbackSample(1.0, 0.0, 0.0, True), bias=-1000)

        self.assertGreaterEqual(p, 0.0)


class TrainWeightsTests(SimpleTestCase):
    def test_sin_datos_suficientes_devuelve_los_pesos_previos(self):
        datos = muestras(MIN_SAMPLES - 1, lambda t, h, e: h > 0.5)

        self.assertEqual(train_weights(datos), DEFAULT_WEIGHTS)

    def test_con_todas_las_valoraciones_iguales_devuelve_los_pesos_previos(self):
        datos = [FeedbackSample(0.3, 0.7, 0.2, True)] * 50

        self.assertEqual(train_weights(datos), DEFAULT_WEIGHTS)

    def test_respeta_los_pesos_previos_que_se_le_pasen(self):
        previos = ScoringWeights(0.2, 0.2, 0.6)

        self.assertEqual(train_weights([], prior=previos), previos)

    def test_aprende_que_la_armonia_es_lo_que_importa(self):
        datos = muestras(300, lambda t, h, e: h > 0.6)

        pesos = train_weights(datos)

        self.assertGreater(pesos.harmonic, DEFAULT_WEIGHTS.harmonic)
        self.assertGreater(pesos.harmonic, pesos.tempo)
        self.assertGreater(pesos.harmonic, pesos.energy)

    def test_aprende_que_el_tempo_es_lo_que_importa(self):
        datos = muestras(300, lambda t, h, e: t > 0.6)

        pesos = train_weights(datos)

        self.assertGreater(pesos.tempo, DEFAULT_WEIGHTS.tempo)
        self.assertGreater(pesos.tempo, pesos.harmonic)
        self.assertGreater(pesos.tempo, pesos.energy)

    def test_aprende_que_la_energia_es_lo_que_importa(self):
        datos = muestras(300, lambda t, h, e: e > 0.6)

        pesos = train_weights(datos)

        self.assertGreater(pesos.energy, DEFAULT_WEIGHTS.energy)
        self.assertGreater(pesos.energy, pesos.tempo)
        self.assertGreater(pesos.energy, pesos.harmonic)

    def test_aprende_aunque_el_20_por_ciento_de_las_valoraciones_sean_ruido(self):
        datos = muestras(400, lambda t, h, e: h > 0.6, ruido=0.2)

        pesos = train_weights(datos)

        self.assertGreater(pesos.harmonic, pesos.tempo)
        self.assertGreater(pesos.harmonic, pesos.energy)

    def test_combina_dos_criterios(self):
        datos = muestras(400, lambda t, h, e: (t + h) / 2 > 0.6)

        pesos = train_weights(datos)

        self.assertGreater(pesos.tempo, pesos.energy)
        self.assertGreater(pesos.harmonic, pesos.energy)

    def test_el_resultado_siempre_es_un_conjunto_de_pesos_valido(self):
        for semilla, criterio in enumerate([lambda t, h, e: h > 0.5, lambda t, h, e: t < 0.3, lambda t, h, e: e > 0.9]):
            with self.subTest(criterio=semilla):
                pesos = train_weights(muestras(200, criterio, semilla=semilla))

                self.assertAlmostEqual(pesos.tempo + pesos.harmonic + pesos.energy, 1.0, places=9)
                self.assertGreaterEqual(min(pesos.tempo, pesos.harmonic, pesos.energy), MIN_WEIGHT - 1e-9)

    def test_ningun_criterio_se_ignora_del_todo(self):
        datos = muestras(300, lambda t, h, e: h > 0.6)

        pesos = train_weights(datos)

        self.assertGreaterEqual(pesos.tempo, MIN_WEIGHT - 1e-9)
        self.assertGreaterEqual(pesos.energy, MIN_WEIGHT - 1e-9)

    def test_con_pocos_datos_se_queda_mas_cerca_de_los_previos_que_con_muchos(self):
        criterio = lambda t, h, e: h > 0.6  # noqa: E731
        pocos = train_weights(muestras(MIN_SAMPLES + 2, criterio, semilla=3))
        muchos = train_weights(muestras(500, criterio, semilla=3))

        distancia = lambda p: abs(p.harmonic - DEFAULT_WEIGHTS.harmonic)  # noqa: E731
        self.assertLess(distancia(pocos), distancia(muchos))

    def test_es_determinista(self):
        datos = muestras(100, lambda t, h, e: h > 0.5)

        self.assertEqual(train_weights(datos), train_weights(datos))

    def test_los_pesos_aprendidos_predicen_mejor_que_los_previos(self):
        criterio = lambda t, h, e: h > 0.6  # noqa: E731
        entrenamiento = muestras(300, criterio, semilla=5)
        prueba = muestras(300, criterio, semilla=99)

        aprendidos = train_weights(entrenamiento)

        def aciertos(pesos):
            return sum((predict_like_probability(pesos, s, bias=-2.4) >= 0.5) == s.liked for s in prueba)

        self.assertGreaterEqual(aciertos(aprendidos), aciertos(DEFAULT_WEIGHTS))
