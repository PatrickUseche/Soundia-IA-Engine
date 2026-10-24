"""Convierte una DATABASE_URL (la que dan Neon, Render y similares) en la configuracion DATABASES de Django."""
from urllib.parse import parse_qsl, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

ESQUEMAS = ('postgres', 'postgresql')


def database_from_url(url):
    partes = urlparse(url)
    if partes.scheme not in ESQUEMAS:
        raise ImproperlyConfigured(
            f"DATABASE_URL debe empezar por postgresql:// (recibido: '{partes.scheme}://').")
    nombre = unquote(partes.path.lstrip('/'))
    if not partes.hostname or not nombre:
        raise ImproperlyConfigured('DATABASE_URL debe incluir el servidor y el nombre de la base de datos.')

    configuracion = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': nombre,
        'USER': unquote(partes.username or ''),
        'PASSWORD': unquote(partes.password or ''),
        'HOST': partes.hostname,
        'PORT': str(partes.port or ''),
    }
    # Opciones de la conexion (por ejemplo sslmode=require, que Neon exige).
    opciones = dict(parse_qsl(partes.query))
    if opciones:
        configuracion['OPTIONS'] = opciones
    return configuracion
