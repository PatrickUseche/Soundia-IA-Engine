from django.core.management.base import BaseCommand

from audio import vocal_jobs
from audio.models import Track


class Command(BaseCommand):
    help = (
        "Analiza la voz del final de las pistas que aun no tienen analisis (una por una, en este proceso). "
        "Tarda unos minutos por pista. Necesita requirements-vocals.txt."
    )

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='Reanalizar tambien las pistas ya analizadas.')

    def handle(self, *args, **options):
        if not vocal_jobs.is_available():
            self.stdout.write(self.style.ERROR(
                'El modelo de separacion no esta instalado: pip install -r requirements-vocals.txt'
            ))
            return

        pistas = Track.objects.exclude(audio_file='')
        if not options['all']:
            pistas = pistas.exclude(vocal_status=Track.VOCALS_DONE)
        pistas = list(pistas.order_by('id'))

        self.stdout.write(f'Analizando la voz de {len(pistas)} pista(s). Puede tardar unos minutos por pista.')
        for pista in pistas:
            vocal_jobs.run_vocal_analysis(pista.id)
            pista.refresh_from_db()
            if pista.vocal_status == Track.VOCALS_DONE:
                if pista.vocal_last_end is None:
                    resultado = 'sin voz en el final'
                else:
                    resultado = f'la voz acaba en {pista.vocal_last_end:.1f} s'
                self.stdout.write(self.style.SUCCESS(f'  {pista.title}: {resultado}'))
            else:
                self.stdout.write(self.style.WARNING(f'  {pista.title}: {pista.get_vocal_status_display()}'))
