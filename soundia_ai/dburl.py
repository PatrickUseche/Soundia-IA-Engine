"""Convierte una DATABASE_URL (la que dan Neon, Render y similares) en la configuracion DATABASES de Django."""
from urllib.parse import parse_qsl, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

SCHEMAS = ('postgres', 'postgresql')


def database_from_url(url):
    name_parts = urlparse(url)
    if name_parts.scheme not in SCHEMAS:
        raise ImproperlyConfigured(
            f"DATABASE_URL debe empezar por postgresql:// (recibido: '{name_parts.scheme}://').")
    file_name = unquote(name_parts.path.lstrip('/'))
    if not name_parts.hostname or not file_name:
        raise ImproperlyConfigured('DATABASE_URL debe incluir el servidor y el nombre de la base de datos.')

    settings_obj = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': file_name,
        'USER': unquote(name_parts.username or ''),
        'PASSWORD': unquote(name_parts.password or ''),
        'HOST': name_parts.hostname,
        'PORT': str(name_parts.port or ''),
    }
    # Opciones de la conexion (por ejemplo sslmode=require, que Neon exige).
    command_options = dict(parse_qsl(name_parts.query))
    if command_options:
        settings_obj['OPTIONS'] = command_options
    return settings_obj
