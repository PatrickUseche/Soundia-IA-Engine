"""Clave compartida entre el API Gateway y el motor de IA.

El motor no tiene usuarios. Cuando no puede quedar en una red privada (por ejemplo en un servicio gratuito de la nube,
que siempre tiene una URL publica), SERVICE_TOKEN hace que solo atienda a quien lleve la cabecera `X-Soundia-Key` con
esa clave: el API Gateway.
"""
import hmac

from django.conf import settings
from django.http import JsonResponse

HEADER = 'HTTP_X_SOUNDIA_KEY'


class ServiceTokenMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = settings.SERVICE_TOKEN
        # Sin SERVICE_TOKEN el motor responde a todos (red privada o desarrollo).
        if token:
            enviada = request.META.get(HEADER, '')
            if not hmac.compare_digest(enviada.encode(), token.encode()):
                return JsonResponse({'error': 'Clave de servicio invalida o ausente.'}, status=401)
        return self.get_response(request)
