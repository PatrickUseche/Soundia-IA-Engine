import json
from json.decoder import JSONDecodeError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .services import AiMixService
from .dtos import MidiEventDto

# Create your views here.

class PayloadInvalidoError(ValueError):
    """La peticion no se pudo convertir en un MidiEventDto. Lleva el cuerpo del error para el cliente."""

    def __init__(self, mensaje, extra=None):
        super().__init__(mensaje)
        self.body = {"error": mensaje, **(extra or {})}


def parse_midi_event(raw_body: bytes) -> MidiEventDto:
    """Deserializacion segura del cuerpo JSON hacia el DTO de entrada."""
    # Blindaje contra peticiones vacias cortadas por el servidor.
    if not raw_body:
        raise PayloadInvalidoError("Cuerpo de la peticion vacio o cortado en transito.")
    try:
        data = json.loads(raw_body)
    except JSONDecodeError:
        raise PayloadInvalidoError("Sintaxis JSON invalida")

    if not isinstance(data, dict):
        raise PayloadInvalidoError("El cuerpo JSON debe ser un objeto")

    control_id = data.get('controlId', data.get('control_id'))
    value = data.get('value')

    # Validar contra None asegura que no rechacemos el valor 0 (un valor MIDI valido).
    if control_id is None or value is None:
        # Devuelve en el JSON exactamente que leyo Python para depurar visualmente
        print(f"[DEBUG] Estructura leída por Django: {data}")
        raise PayloadInvalidoError("Faltan las llaves 'controlId' o 'value'", {"payload_leido": data})

    try:
        return MidiEventDto(control_id=int(control_id), value=int(value))
    except (TypeError, ValueError) as e:
        raise PayloadInvalidoError(str(e))


@csrf_exempt
def calculate_mix(request):
    if request.method != 'POST':
        return JsonResponse({"error": "Metodo no permitido"}, status=405)

    try:
        dto_in = parse_midi_event(request.body)
        dto_out = AiMixService.calculate_transition(dto_in)
    except PayloadInvalidoError as e:
        return JsonResponse(e.body, status=400)
    except ValueError as e:
        # Valor MIDI fuera del rango 0-127, lanzado por el servicio.
        return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse(dto_out.__dict__)
