import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from mixing.backup import export_recordings, import_recordings
from mixing.recordings import InvalidRecording


class Command(BaseCommand):
    help = (
        "Copia de seguridad de las grabaciones de mezclas: --export guarda todas en un archivo JSON y --import las "
        "restaura desde uno (sin duplicar las que ya estan)."
    )

    def add_arguments(self, parser):
        action_name = parser.add_mutually_exclusive_group(required=True)
        action_name.add_argument('--export', metavar='ARCHIVO', help='Guarda las grabaciones en este archivo JSON.')
        action_name.add_argument('--import', dest='importar', metavar='ARCHIVO', help='Restaura las grabaciones de este archivo.')

    def handle(self, *args, **options):
        if options['export']:
            self._export(Path(options['export']))
        else:
            self._import(Path(options['importar']))

    def _export(self, file_path: Path):
        backup_data = export_recordings()
        file_path.write_text(json.dumps(backup_data, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f"{len(backup_data['recordings'])} grabacion(es) guardadas en {file_path}."))

    def _import(self, file_path: Path):
        try:
            payload_data = json.loads(file_path.read_text(encoding='utf-8'))
        except OSError as error:
            raise CommandError(f'No se pudo leer {file_path}: {error}') from error
        except json.JSONDecodeError as error:
            raise CommandError(f'{file_path} no es un JSON valido: {error}') from error
        try:
            created_count, existing = import_recordings(payload_data)
        except InvalidRecording as error:
            raise CommandError(f'No se restauro nada: {error}') from error
        self.stdout.write(self.style.SUCCESS(
            f'{created_count} grabacion(es) restauradas; {existing} ya estaban y no se duplicaron.'))
