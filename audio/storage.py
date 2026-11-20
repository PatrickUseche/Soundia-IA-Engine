"""Acceso a los archivos de audio guardados, estén en el disco o en un almacenamiento externo (S3)."""
import contextlib
import os
import re
import shutil
import tempfile
import unicodedata


@contextlib.contextmanager
def local_audio_path(field_file):
    """Da una ruta de disco con el audio de una pista (FieldFile).

    Con el almacenamiento en disco es la ruta real. Con uno externo (S3) no hay ruta: el audio se descarga a un
    archivo temporal con su misma extension y se borra al salir."""
    try:
        yield field_file.path
        return
    except NotImplementedError:
        pass

    extension = os.path.splitext(field_file.name)[1]
    temporal = tempfile.NamedTemporaryFile(suffix=extension, delete=False)
    try:
        with temporal, field_file.storage.open(field_file.name, 'rb') as origen:
            shutil.copyfileobj(origen, temporal)
        yield temporal.name
    finally:
        with contextlib.suppress(OSError):
            os.remove(temporal.name)


# Largo maximo del nombre con que se guarda un audio (el almacenamiento externo limita el de la clave del objeto).
MAX_AUDIO_NAME_LENGTH = 100
_UNSAFE = re.compile(r'[^A-Za-z0-9._-]+')
_REPEATED = re.compile(r'[_]{2,}')


def safe_audio_name(name: str) -> str:
    """Nombre con el que se guarda un audio: solo letras ASCII, numeros, punto, guion y guion bajo.

    Supabase Storage solo acepta en el nombre de un objeto los caracteres 'seguros' de S3: una cancion llamada
    `Por Qué Sigues con Él.mp3` fallaba al guardarse (500) y 17 de 49 canciones de prueba tienen tildes o enes. Las
    tildes se quitan (Qué -> Que), el resto de simbolos pasa a guion bajo y la extension se conserva en minusculas. El
    titulo que ve el usuario sigue siendo el nombre original: esto es solo el nombre interno del archivo."""
    base, extension = os.path.splitext(os.path.basename(name.replace(chr(92), '/')))
    sin_tildes = unicodedata.normalize('NFKD', base).encode('ascii', 'ignore').decode('ascii')
    limpio = _REPEATED.sub('_', _UNSAFE.sub('_', sin_tildes)).strip('._-')
    extension = _UNSAFE.sub('', unicodedata.normalize('NFKD', extension).encode('ascii', 'ignore').decode('ascii')).lower()
    if extension and not extension.startswith('.'):
        extension = '.' + extension
    limpio = limpio[:max(MAX_AUDIO_NAME_LENGTH - len(extension), 1)].rstrip('._-') or 'audio'
    return limpio + extension
