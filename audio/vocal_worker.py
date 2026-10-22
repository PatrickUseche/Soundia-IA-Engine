"""Trabajador del analisis de voz: se ejecuta como proceso aparte (`python -m audio.vocal_worker <audio> <duracion>`).

Separar la voz con Demucs consume cientos de MB y, en un equipo con poca RAM, puede acabar en un fallo nativo de
memoria que mata el proceso. Si eso pasara dentro del servidor, se llevaria el servidor entero; en un proceso aparte
solo falla ese analisis, y la memoria se libera al terminar. Imprime el resultado como una linea JSON.
"""
import json
import sys

from .separator import VocalSeparationUnavailable
from .vocal_analysis import analyze_last_vocals

# Codigo de salida cuando el modelo de separacion no esta instalado (distinto de un fallo cualquiera).
UNAVAILABLE_EXIT_CODE = 3


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print('Uso: python -m audio.vocal_worker <audio> <duracion>', file=sys.stderr)
        return 2
    try:
        result = analyze_last_vocals(argv[1], float(argv[2]))
    except VocalSeparationUnavailable:
        return UNAVAILABLE_EXIT_CODE
    print(json.dumps({'window_start': result.window_start, 'last_end': result.last_end}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
