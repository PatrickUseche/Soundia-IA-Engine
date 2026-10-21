from django.test import TestCase

from telemetry.dtos import AiDecisionDto, MidiEventDto
from telemetry.models import AiDecisionLog
from telemetry.services import AiMixService
from telemetry.strategies import EqTransitionStrategy, MixStrategy


class ContadorStrategy(MixStrategy):
    """Estrategia falsa que cuenta cuántas veces se le pide calcular."""

    def __init__(self):
        self.llamadas = 0

    def calculate(self, event: MidiEventDto) -> AiDecisionDto:
        self.llamadas += 1
        return AiDecisionDto(status="success", action=f"llamada {self.llamadas}")


class AiMixServiceTests(TestCase):
    def tearDown(self):
        AiMixService.set_strategy(EqTransitionStrategy())

    def test_valor_dentro_del_rango_devuelve_decision(self):
        decision = AiMixService.calculate_transition(MidiEventDto(control_id=14, value=100))

        self.assertEqual(decision.status, "success")

    def test_persiste_la_decision_en_la_bitacora(self):
        AiMixService.calculate_transition(MidiEventDto(control_id=14, value=100))

        log = AiDecisionLog.objects.get()
        self.assertEqual((log.control_id, log.value), (14, 100))

    def test_valor_sobre_127_se_rechaza(self):
        with self.assertRaises(ValueError):
            AiMixService.calculate_transition(MidiEventDto(control_id=14, value=128))

        self.assertEqual(AiDecisionLog.objects.count(), 0)

    def test_valor_negativo_se_rechaza(self):
        with self.assertRaises(ValueError):
            AiMixService.calculate_transition(MidiEventDto(control_id=14, value=-1))
