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

        track_list = Track.objects.exclude(audio_file='')
        if not options['all']:
            track_list = track_list.exclude(vocal_status=Track.VOCALS_DONE)
        track_list = list(track_list.order_by('id'))

        self.stdout.write(f'Analizando la voz de {len(track_list)} pista(s). Puede tardar unos minutos por pista.')
        for track_obj in track_list:
            vocal_jobs.run_vocal_analysis(track_obj.id)
            track_obj.refresh_from_db()
            if track_obj.vocal_status == Track.VOCALS_DONE:
                if track_obj.vocal_last_end is None:
                    outcome = 'sin voz en el final'
                else:
                    outcome = f'la voz acaba en {track_obj.vocal_last_end:.1f} s'
                self.stdout.write(self.style.SUCCESS(f'  {track_obj.title}: {outcome}'))
            else:
                self.stdout.write(self.style.WARNING(f'  {track_obj.title}: {track_obj.get_vocal_status_display()}'))
