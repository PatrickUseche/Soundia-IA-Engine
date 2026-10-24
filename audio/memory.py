"""Devolver al sistema operativo la memoria que el analisis de una pista ya no usa.

Analizar una pista crea arreglos grandes (decenas de MB) que Python libera, pero el asignador de memoria de Linux (glibc)
suele quedarse con ellos en lugar de devolverlos, y con varios hilos la memoria retenida crece de una pista a la
siguiente. En un servicio con 512 MB eso acaba en un proceso que el sistema mata (y un 502 para el usuario). Llamar a
`release_memory()` despues de cada analisis fuerza esa devolucion.
"""
import ctypes
import gc
import sys


def release_memory() -> None:
    """Recoge la basura y, en Linux, le pide a glibc que devuelva la memoria libre (malloc_trim). Nunca falla."""
    gc.collect()
    if not sys.platform.startswith('linux'):
        return
    try:
        ctypes.CDLL('libc.so.6').malloc_trim(0)
    except (OSError, AttributeError):
        # Una libc distinta (por ejemplo musl, en Alpine) no tiene malloc_trim: no pasa nada.
        pass
