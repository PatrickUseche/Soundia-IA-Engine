from .dtos import MidiEventDto, AiDecisionDto
from.strategies import MixStrategy, EqTransitionStrategy

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
        
        return cls._strategy.calculate(event)