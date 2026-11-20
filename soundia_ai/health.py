"""Comprobacion de salud: responde solo si el motor y su base de datos funcionan de verdad.

El estado "Live" de Render solo dice que el proceso arranco. Esta ruta ademas hace una consulta minima a la base de
datos (que en la nube es externa y puede estar dormida o caida) y mide cuanto tarda. No devuelve el detalle del error:
la ruta es publica y un mensaje de la base de datos podria revelar datos de la conexion.
"""
import logging
import time

from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def health(request):
    inicio = time.monotonic()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except DatabaseError:
        logger.exception('La comprobacion de salud no pudo consultar la base de datos')
        return JsonResponse({'status': 'error', 'database': 'error'}, status=503)
    milisegundos = round((time.monotonic() - inicio) * 1000)
    return JsonResponse({'status': 'ok', 'database': 'ok', 'database_ms': milisegundos})
