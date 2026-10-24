"""Copia de seguridad de las grabaciones de mezclas: exportarlas a un archivo JSON y restaurarlas desde el.

Sirve para no perder lo que el DJ ha enseñado (la nube gratuita puede reiniciar o cambiar de base de datos) y para
llevar las grabaciones a otro sitio a entrenar. El archivo lleva la foto de las pistas de cada grabacion, no sus ids:
al restaurar en otra base las pistas pueden tener otros ids (o no existir), y la grabacion sigue siendo util igual.
"""
from datetime import datetime, timezone

from django.db import transaction
from django.utils.dateparse import parse_datetime

from .models import MixRecording
from .recordings import (
    MAX_LABEL, MAX_GENRE, MAX_OVERLAP_SECONDS, MAX_PITCH, MAX_TEXT, MIN_PITCH, QUALITIES, SOURCES,
    InvalidRecording, _curves, _number, _text,
)

BACKUP_FORMAT = 'soundia-recordings'
BACKUP_VERSION = 1
# Mas segundos que la duracion de cualquier pista razonable (el limite real ya no se puede comprobar: la pista puede no existir).
MAX_POSITION_SECONDS = 24 * 3600.0


def export_recordings() -> dict:
    """Todas las grabaciones, de la mas antigua a la mas nueva, en un diccionario listo para guardar como JSON."""
    return {
        'format': BACKUP_FORMAT,
        'version': BACKUP_VERSION,
        'exportedAt': datetime.now(timezone.utc).isoformat(),
        'recordings': [_to_item(r) for r in MixRecording.objects.order_by('created_at', 'id')],
    }


def _to_item(recording: MixRecording) -> dict:
    return {
        'createdAt': recording.created_at.isoformat(),
        'source': recording.source,
        'dj': recording.dj,
        'mixOutAt': recording.mix_out_at,
        'mixInAt': recording.mix_in_at,
        'overlapSeconds': recording.overlap_seconds,
        'pitchA': recording.pitch_a,
        'pitchB': recording.pitch_b,
        'curves': recording.curves,
        'snapshotA': recording.snapshot_a,
        'snapshotB': recording.snapshot_b,
        'genreA': recording.genre_a,
        'genreB': recording.genre_b,
        'quality': recording.quality,
        'notes': recording.notes,
    }


def _snapshot(data: dict, key: str) -> dict:
    value = data.get(key)
    if not isinstance(value, dict) or not value:
        raise InvalidRecording(f"Falta '{key}' (la foto de la pista) o no es un objeto.")
    return value


def _parse_item(item) -> dict:
    """Valida una grabacion del archivo y devuelve los campos del modelo (sin pistas: se restauran sin ellas)."""
    if not isinstance(item, dict):
        raise InvalidRecording('Cada grabacion debe ser un objeto.')
    source = item.get('source', 'manual')
    if source not in SOURCES:
        raise InvalidRecording(f"'source' debe ser uno de {list(SOURCES)}.")
    quality = item.get('quality', 'unreviewed')
    if quality not in QUALITIES:
        raise InvalidRecording(f"'quality' debe ser uno de {list(QUALITIES)}.")
    overlap = _number(item, 'overlapSeconds', 0.0, MAX_OVERLAP_SECONDS)
    if overlap <= 0:
        raise InvalidRecording("'overlapSeconds' debe ser mayor que 0.")
    created = item.get('createdAt')
    created_at = parse_datetime(created) if isinstance(created, str) else None
    if created_at is None or created_at.tzinfo is None:
        raise InvalidRecording("'createdAt' debe ser una fecha con zona horaria (ISO 8601).")
    return {
        'created_at': created_at,
        'source': source,
        'dj': _text(item, 'dj', MAX_LABEL, 'dj') or 'dj',
        'mix_out_at': _number(item, 'mixOutAt', 0.0, MAX_POSITION_SECONDS),
        'mix_in_at': _number(item, 'mixInAt', 0.0, MAX_POSITION_SECONDS),
        'overlap_seconds': overlap,
        'pitch_a': _number(item, 'pitchA', MIN_PITCH, MAX_PITCH),
        'pitch_b': _number(item, 'pitchB', MIN_PITCH, MAX_PITCH),
        'curves': _curves(item.get('curves'), overlap),
        'snapshot_a': _snapshot(item, 'snapshotA'),
        'snapshot_b': _snapshot(item, 'snapshotB'),
        'genre_a': _text(item, 'genreA', MAX_GENRE),
        'genre_b': _text(item, 'genreB', MAX_GENRE),
        'quality': quality,
        'notes': _text(item, 'notes', MAX_TEXT),
    }


def _already_there(fields: dict) -> bool:
    """La misma grabacion (mismo DJ, instante y datos de la mezcla) ya esta guardada: restaurar dos veces no duplica."""
    return MixRecording.objects.filter(
        dj=fields['dj'], created_at=fields['created_at'], mix_out_at=fields['mix_out_at'],
        mix_in_at=fields['mix_in_at'], overlap_seconds=fields['overlap_seconds'],
    ).exists()


def import_recordings(data) -> tuple[int, int]:
    """Restaura las grabaciones de un archivo exportado. Devuelve (restauradas, ya existian).

    Todo o nada: si una grabacion no es valida no se guarda ninguna y se lanza InvalidRecording con su posicion.
    Las grabaciones se restauran sin pista enlazada (los ids pueden no coincidir); conservan la foto de sus pistas.
    """
    if not isinstance(data, dict) or data.get('format') != BACKUP_FORMAT:
        raise InvalidRecording('El archivo no es una copia de grabaciones de SoundIA.')
    if data.get('version') != BACKUP_VERSION:
        raise InvalidRecording(f"Version de copia no soportada: {data.get('version')!r} (se esperaba {BACKUP_VERSION}).")
    items = data.get('recordings')
    if not isinstance(items, list):
        raise InvalidRecording("Falta la lista 'recordings'.")

    parsed = []
    for position, item in enumerate(items, start=1):
        try:
            parsed.append(_parse_item(item))
        except InvalidRecording as error:
            raise InvalidRecording(f'Grabacion {position}: {error}') from error

    created = skipped = 0
    with transaction.atomic():
        for fields in parsed:
            if _already_there(fields):
                skipped += 1
                continue
            created_at = fields.pop('created_at')
            recording = MixRecording.objects.create(**fields)
            # created_at es auto_now_add: al crear siempre vale "ahora"; se corrige para conservar la fecha original.
            MixRecording.objects.filter(pk=recording.pk).update(created_at=created_at)
            created += 1
    return created, skipped
