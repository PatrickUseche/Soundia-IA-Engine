from django.shortcuts import render
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

# Create your views here.

@csrf_exempt
def calculate_mix(request):
    if request.method == 'POST':
        # Deserializar el DTO enviado por Spring Boot
        data = json.loads(request.body)
        control_id = data.get('controlId')
        value = data.get('value')
        
        # Logica futura del modelo de Inteligencia Artificial
        ai_decision = f"Transicion calculada para el deck {control_id}, con valor {value}"
        
        print(f"[Django AI] Evento MIDI recibido: Control {control_id}, Valor {value}")
        return JsonResponse({"status": "success", "action": ai_decision})
    
    return JsonResponse({"error": "Metodo no permitido"}, status=405)