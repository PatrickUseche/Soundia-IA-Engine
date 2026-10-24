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
        accion = parser.add_mutually_exclusive_group(required=True)
        accion.add_argument('--export', metavar='ARCHIVO', help='Guarda las grabaciones en este archivo JSON.')
        accion.add_argument('--import', dest='importar', metavar='ARCHIVO', help='Restaura las grabaciones de este archivo.')

    def handle(self, *args, **options):
        if options['export']:
            self._exportar(Path(options['export']))
        else:
            self._importar(Path(options['importar']))

    def _exportar(self, ruta: Path):
        copia = export_recordings()
        ruta.write_text(json.dumps(copia, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f"{len(copia['recordings'])} grabacion(es) guardadas en {ruta}."))

    def _importar(self, ruta: Path):
        try:
            datos = json.loads(ruta.read_text(encoding='utf-8'))
        except OSError as error:
            raise CommandError(f'No se pudo leer {ruta}: {error}') from error
        except json.JSONDecodeError as error:
            raise CommandError(f'{ruta} no es un JSON valido: {error}') from error
        try:
            creadas, existentes = import_recordings(datos)
        except InvalidRecording as error:
            raise CommandError(f'No se restauro nada: {error}') from error
        self.stdout.write(self.style.SUCCESS(
            f'{creadas} grabacion(es) restauradas; {existentes} ya estaban y no se duplicaron.'))
