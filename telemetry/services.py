from .dtos import MidiEventDto, AiDecisionDto

class AiMixService:
    @staticmethod
    def calculate_transition(event: MidiEventDto) -> AiDecisionDto:
        """
        Calcula la transicion usando el DTO inmutable.
        """
        # Regla de negocio: Un valor MIDI fisico jamas excede 127 ni es menor a 0.
        if not (0 < event.value <= 127):
            raise ValueError(f"Valor MIDI {event.value} fuera del protocolo estandar (0-127).")
        # TODO: Inyectar logica real de prediccion de mezcla automatizada
        action = f"Transicion calculada para el deck {event.control_id} con valor {event.value}"
        
        return AiDecisionDto(status="success", action=action)