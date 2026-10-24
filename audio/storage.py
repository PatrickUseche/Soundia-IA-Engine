"""Acceso a los archivos de audio guardados, estén en el disco o en un almacenamiento externo (S3)."""
import contextlib
import os
import shutil
import tempfile


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
