from django.core.management.base import BaseCommand, CommandError

from mixing.timing import reset_timing, timing_count
from mixing.weights import (
    active_weights, feedback_count, reset_weights, restore_weights, rollback_weights, weight_history,
)


class Command(BaseCommand):
    help = (
        "Administra lo que el motor ha aprendido del DJ: ver las versiones de los pesos de la puntuacion, volver a "
        "una anterior, dejar de usarlos, o borrar lo aprendido sobre cuando mezclar."
    )

    def add_arguments(self, parser):
        action_name = parser.add_mutually_exclusive_group(required=True)
        action_name.add_argument('--list', action='store_true', help='Muestra las versiones guardadas de los pesos.')
        action_name.add_argument('--rollback-weights', action='store_true', help='Vuelve a la version anterior de los pesos.')
        action_name.add_argument('--restore-version', type=int, metavar='N', help='Vuelve a usar la version N de los pesos.')
        action_name.add_argument(
            '--reset-weights', action='store_true',
            help='Deja de usar los pesos aprendidos (vuelven los de siempre) hasta la proxima valoracion.',
        )
        action_name.add_argument(
            '--reset-timing', action='store_true',
            help='Borra lo aprendido sobre cuando mezclar (el Auto-DJ vuelve a mezclar donde lo planea).',
        )
        parser.add_argument(
            '--forget-ratings', action='store_true',
            help='Con --reset-weights: borra tambien las valoraciones y las versiones guardadas, para empezar de cero.',
        )

    def handle(self, *args, **options):
        if options['forget_ratings'] and not options['reset_weights']:
            raise CommandError('--forget-ratings solo se puede usar con --reset-weights.')

        if options['list']:
            self._list()
        elif options['rollback_weights']:
            self._restore(lambda: rollback_weights())
        elif options['restore_version'] is not None:
            self._restore(lambda: restore_weights(options['restore_version']))
        elif options['reset_weights']:
            deleted_count = reset_weights(forget_ratings=options['forget_ratings'])
            self.stdout.write('Los pesos aprendidos ya no se usan: vuelven los de siempre.')
            if options['forget_ratings']:
                self.stdout.write(f'Se borraron {deleted_count} valoracion(es) y las versiones guardadas.')
            else:
                self.stdout.write('La proxima valoracion volvera a entrenar con todas las que hay.')
        else:
            deleted_items = reset_timing()
            self.stdout.write(f'Se borraron {deleted_items} caso(s) de cuando mezclar.')

    def _list(self):
        history = weight_history()
        self.stdout.write(f'{feedback_count()} valoracion(es) y {timing_count()} caso(s) de cuando mezclar.')
        if not history:
            self.stdout.write('Sin pesos aprendidos: se usan los de siempre.')
            return
        for csv_row in history:
            marker = '*' if csv_row.active else ' '
            hit_rate = f'{csv_row.accuracy:.2f}' if csv_row.accuracy is not None else '-'
            self.stdout.write(
                f'{marker} version {csv_row.version}: tempo={csv_row.tempo:.2f} armonia={csv_row.harmonic:.2f} '
                f'energia={csv_row.energy:.2f}  ({csv_row.samples} valoraciones, acierto {hit_rate})'
            )
        if active_weights() is None:
            self.stdout.write('Ninguna esta vigente: se usan los pesos de siempre.')

    def _restore(self, action_name):
        try:
            chosen_item = action_name()
        except LookupError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(f'Vigente: version {chosen_item.version} (tempo={chosen_item.tempo:.2f}, '
                          f'armonia={chosen_item.harmonic:.2f}, energia={chosen_item.energy:.2f}).')
