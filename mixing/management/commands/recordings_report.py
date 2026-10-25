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
        resumen = summarize(quality=quality, genre=options['genre'])
        etiqueta = 'todas' if quality is None else f"'{quality}'"
        if resumen['total'] == 0:
            self.stdout.write(f'No hay grabaciones {etiqueta}'
                              + (f" del genero '{options['genre']}'" if options['genre'] else '')
                              + '. Marca algunas como buenas en la pantalla Grabaciones (o usa --quality all).')
            return

        self.stdout.write(self.style.SUCCESS(f"{resumen['total']} grabacion(es) {etiqueta}."))
        for grupo in resumen['groups']:
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(f"Genero: {grupo['genre']} ({grupo['count']} mezcla(s))"))
            for linea in self._lineas(grupo):
                self.stdout.write('  ' + linea)

    @staticmethod
    def _lineas(g: dict) -> list[str]:
        lineas = []
        if g['overlapBars']:
            o = g['overlapBars']
            lineas.append(f"Solape: mediana {o['median']} compases (de {o['min']} a {o['max']})")
        if g['exitFraction']:
            lineas.append(f"Sale de la pista hacia el {round(g['exitFraction']['median'] * 100)} % de su duracion (mediana)")
        if g['crossfaderShapes']:
            formas = ', '.join(f'{k} {v}' for k, v in sorted(g['crossfaderShapes'].items(), key=lambda kv: -kv[1]))
            lineas.append(f'Crossfader: {formas}')
        b = g['bassSwap']
        if b['count']:
            lineas.append(
                f"Cambio de graves: en {b['count']} de {b['ofTotal']} mezclas, hacia el "
                f"{round(b['medianAt']['median'] * 100)} % del solape (mediana)")
        else:
            lineas.append(f"Cambio de graves: no se detecto en ninguna de las {b['ofTotal']} mezclas")
        if g['phaseErrorMs']:
            lineas.append(f"Desfase de pulsos al entrar: mediana {g['phaseErrorMs']['median']} ms")
        if g['bpmDifference']:
            lineas.append(f"Diferencia de BPM entre las dos pistas: mediana {g['bpmDifference']['median']}")
        if g['keyDistance']:
            lineas.append('Distancia de tonalidad (0 = igual): ' + ', '.join(f'{k}: {v}' for k, v in g['keyDistance'].items()))
        return lineas
