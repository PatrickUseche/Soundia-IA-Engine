from .dtos import MidiEventDto, AiDecisionDto
from.strategies import MixStrategy, EqTransitionStrategy
from .models import AiDecisionLog

class AiMixService:
    # Inyeccion de dependencias estatica.
    _strategy : MixStrategy = EqTransitionStrategy()
    @classmethod
    def set_strategy(cls, strategy: MixStrategy):
        cls._strategy = strategy
    
    @classmethod
    def calculate_transition(cls, event: MidiEventDto) -> AiDecisionDto:
        if not (0 < event.value <= 127):
            raise ValueError(f"Valor MIDI {event.value} fuera del protocolo estandar (0-127).")
        
        # Inferencia: El motor matematico (Strategy) calcula la decision.
        decision_dto = cls._strategy.calculate(event)
        
        # Persistencia: Guarda la decision de la IA en la bitacora.
        AiDecisionLog.objects.create(
            control_id = event.control_id,
            value = event.value,
            action_taken = decision_dto.action
        )
        
        return decision_dto