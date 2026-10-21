from django.test import SimpleTestCase

from telemetry.dtos import MidiEventDto
from telemetry.strategies import EqTransitionStrategy


class EqTransitionStrategyTests(SimpleTestCase):
    def setUp(self):
        self.strategy = EqTransitionStrategy()

    def test_devuelve_estado_success(self):
        decision = self.strategy.calculate(MidiEventDto(control_id=14, value=64))

        self.assertEqual(decision.status, "success")

    def test_la_accion_menciona_el_deck(self):
        decision = self.strategy.calculate(MidiEventDto(control_id=14, value=64))

        self.assertIn("deck 14", decision.action)

    def test_valor_maximo_equivale_al_cien_por_ciento(self):
        decision = self.strategy.calculate(MidiEventDto(control_id=1, value=127))

        self.assertIn("100", decision.action)
