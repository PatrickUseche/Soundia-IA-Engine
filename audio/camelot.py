"""Rueda de Camelot: traduce una tonalidad a un codigo (1A-12B) y decide que pistas mezclan bien.

Dos pistas se mezclan armonicamente bien si sus codigos son iguales, si difieren en +-1 con la misma
letra, o si tienen el mismo numero y distinta letra (tonalidad relativa mayor/menor).
"""

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# Indice = clase de altura (0 = C ... 11 = B). Cada valor es el numero de la rueda.
_MAJOR_NUMBER = [8, 3, 10, 5, 12, 7, 2, 9, 4, 11, 6, 1]
_MINOR_NUMBER = [5, 12, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10]

MODES = ('major', 'minor')


def key_name(pitch_class: int, mode: str) -> str:
    """Nombre legible de la tonalidad, por ejemplo 'C major' o 'A minor'."""
    _validate(pitch_class, mode)
    return f"{NOTE_NAMES[pitch_class]} {mode}"


def camelot_code(pitch_class: int, mode: str) -> str:
    """Codigo Camelot de una tonalidad: letra B para mayor, A para menor."""
    _validate(pitch_class, mode)
    if mode == 'major':
        return f"{_MAJOR_NUMBER[pitch_class]}B"
    return f"{_MINOR_NUMBER[pitch_class]}A"


def compatible_codes(code: str) -> list[str]:
    """Codigos que mezclan bien con `code`, incluido el mismo, en orden estable."""
    number, letter = _split(code)
    previous = (number - 2) % 12 + 1
    following = number % 12 + 1
    other_letter = 'A' if letter == 'B' else 'B'
    return [
        f"{number}{letter}",
        f"{previous}{letter}",
        f"{following}{letter}",
        f"{number}{other_letter}",
    ]


def are_compatible(code_a: str, code_b: str) -> bool:
    return code_b in compatible_codes(code_a)


def harmonic_distance(code_a: str, code_b: str) -> int:
    """Pasos entre dos codigos en la rueda (0 = igual); cambiar de letra cuenta como un paso."""
    number_a, letter_a = _split(code_a)
    number_b, letter_b = _split(code_b)
    around = abs(number_a - number_b)
    steps = min(around, 12 - around)
    return steps + (0 if letter_a == letter_b else 1)


def _split(code: str) -> tuple[int, str]:
    if not isinstance(code, str) or len(code) < 2 or code[-1] not in 'AB' or not code[:-1].isdigit():
        raise ValueError(f"Codigo Camelot invalido: {code!r}")
    number = int(code[:-1])
    if not 1 <= number <= 12:
        raise ValueError(f"Codigo Camelot invalido: {code!r}")
    return number, code[-1]


def _validate(pitch_class: int, mode: str) -> None:
    if not 0 <= pitch_class <= 11:
        raise ValueError(f"Clase de altura fuera de rango (0-11): {pitch_class}")
    if mode not in MODES:
        raise ValueError(f"Modo invalido: {mode!r}; se esperaba 'major' o 'minor'")
