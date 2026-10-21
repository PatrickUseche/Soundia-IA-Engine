from abc import ABC, abstractmethod
from .dtos import MidiEventDto, AiDecisionDto

class MixStrategy(ABC):
    @abstractmethod
    def calculate(self, event: MidiEventDto) -> AiDecisionDto:
        pass
    
class EqTransitionStrategy(MixStrategy):
    def calculate(self, event: MidiEventDto) -> AiDecisionDto:
        # Aqui se cargara el modelo .h5 o .pt de TensorFlow/PyTorch.
        # Por ahora, se simulara el calculo de la red neuronal.
        intensidad_porcentual = (event.value / 127.0) * 100
        
        action = f"Corte de frecuencias bajas (EQ) en deck {event.control_id} al {intensidad_porcentual:.1f}%"
        return AiDecisionDto(status="success", action=action)