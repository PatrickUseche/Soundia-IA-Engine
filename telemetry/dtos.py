from dataclasses import dataclass

@dataclass(frozen=True) # frozen+True hace que el DTO sea inmutable (como en Java).
class MidiEventDto:
    control_id: int
    value: int

@dataclass(frozen=True)
class AiDecisionDto:
    status: str
    action: str