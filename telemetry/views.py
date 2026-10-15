import json
from json.decoder import JSONDecodeError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .services import AiMixService
from .dtos import MidiEventDto

# Create your views here.

@csrf_exempt
def calculate_mix(request):
    if request.method == 'POST':
        # Blindaje contra peticiones vacias cortadas por el servidor.
        if not request.body:
            return JsonResponse({"error": "Cuerpo de la peticion vacio o cortado en transito."}, status=400)
        try:
            # Deserializacion segura
            data = json.loads(request.body)
            
            control_id = data.get('controlId', data.get('control_id'))
            value = data.get('value')

            #validar contra None asegura que no rechacemos el valor 0 (un valor MIDI valido).
            if control_id is None or value is None:
                # Imprime en la consola y devuelve en el JSON exactamente qué leyó Python para depurar visualmente
                print(f"[DEBUG] Estructura leída por Django: {data}")
                return JsonResponse({
                    "error": "Faltan las llaves 'controlId' o 'value'",
                    "payload_leido": data
                }, status=400)

            dto_in = MidiEventDto(
                control_id=int(control_id),
                value=int(value)
            )
            
            dto_out = AiMixService.calculate_transition(dto_in)
            return JsonResponse(dto_out.__dict__)
        except JSONDecodeError:
            return JsonResponse({"error": "Sintaxis JSON invalida"}, status=400)
        except (TypeError, ValueError) as e:
            return JsonResponse({"error": str(e)}, status=400)
                
    return JsonResponse({"error": "Metodo no permitido"}, status=405)