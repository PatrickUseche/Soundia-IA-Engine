from django.core.management.base import BaseCommand

from mixing.report import summarize


class Command(BaseCommand):
    help = (
        "Resume las mezclas grabadas del DJ por genero: cuantos compases suele solapar, como mueve el crossfader, "
        "si hace cambio de graves y donde sale de la pista. Por defecto solo cuenta las marcadas como buenas."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--quality', default='good', choices=['good', 'unreviewed', 'discard', 'all'],
            help="Que grabaciones contar (por defecto 'good'; 'all' cuenta todas).",
        )
        parser.add_argument('--genre', help="Solo este genero (en minusculas, o 'sin genero').")

    def handle(self, *args, **options):
        quality = None if options['quality'] == 'all' else options['quality']
        summary_info = summarize(quality=quality, genre=options['genre'])
        label = 'todas' if quality is None else f"'{quality}'"
        if summary_info['total'] == 0:
            self.stdout.write(f'No hay grabaciones {label}'
                              + (f" del genero '{options['genre']}'" if options['genre'] else '')
                              + '. Marca algunas como buenas en la pantalla Grabaciones (o usa --quality all).')
            return

        self.stdout.write(self.style.SUCCESS(f"{summary_info['total']} grabacion(es) {label}."))
        for genre_group in summary_info['groups']:
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(f"Genero: {genre_group['genre']} ({genre_group['count']} mezcla(s))"))
            for text_line in self._lines(genre_group):
                self.stdout.write('  ' + text_line)

    @staticmethod
    def _lines(g: dict) -> list[str]:
        text_lines = []
        if g['overlapBars']:
            o = g['overlapBars']
            text_lines.append(f"Solape: mediana {o['median']} compases (de {o['min']} a {o['max']})")
        if g['exitFraction']:
            text_lines.append(f"Sale de la pista hacia el {round(g['exitFraction']['median'] * 100)} % de su duracion (mediana)")
        if g['crossfaderShapes']:
            curve_shapes = ', '.join(f'{k} {v}' for k, v in sorted(g['crossfaderShapes'].items(), key=lambda kv: -kv[1]))
            text_lines.append(f'Crossfader: {curve_shapes}')
        b = g['bassSwap']
        if b['count']:
            text_lines.append(
                f"Cambio de graves: en {b['count']} de {b['ofTotal']} mezclas, hacia el "
                f"{round(b['medianAt']['median'] * 100)} % del solape (mediana)")
        else:
            text_lines.append(f"Cambio de graves: no se detecto en ninguna de las {b['ofTotal']} mezclas")
        if g['phaseErrorMs']:
            text_lines.append(f"Desfase de pulsos al entrar: mediana {g['phaseErrorMs']['median']} ms")
        if g['bpmDifference']:
            text_lines.append(f"Diferencia de BPM entre las dos pistas: mediana {g['bpmDifference']['median']}")
        if g['keyDistance']:
            text_lines.append('Distancia de tonalidad (0 = igual): ' + ', '.join(f'{k}: {v}' for k, v in g['keyDistance'].items()))
        return text_lines
