import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .services import AiMixService
from .dtos import MidiEventDto

# Create your views here.

@csrf_exempt
def calculate_mix(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        
        try:
            # Mapeo estructural (Casting del JSON al DTO)
            dto_in = MidiEventDto(
                control_id=int(data.get('controlId')),
                value=int(data.get('value'))
            )
            
            # Inyeccion pura al servicio
            dto_out = AiMixService.calculate_transition(dto_in)
            
            print(f"[Django AI] Evento MIDI procesado: Control {dto_in.control_id}, Valor {dto_in.value}")
            
            # Serializar DTO de salida a JSON internamente (__dict__).
            return JsonResponse(dto_out.__dict__)
        except (TypeError, ValueError) as e:
            # Atrapa errores de casting (ej. enviaron letras) o validacion de negocio (ej. valor 150)
            return JsonResponse({"error": str(e)}, status=400)
        
    return JsonResponse({"error": "Metodo no permitido"}, status=405)