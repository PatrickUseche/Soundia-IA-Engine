from django.core.management.base import BaseCommand

from audio.analysis import AudioTooShortError, SilentAudioError
from audio.models import Track
from audio.services import UnsupportedAudioError, analyze_file
from audio.storage import local_audio_path


class Command(BaseCommand):
    help = (
        "Calcula la rejilla de pulsos (tempo afinado y primer tiempo del compas) de las pistas guardadas que no la "
        "tienen, y recalcula su BPM y sus puntos de mezcla sobre ella. No toca la tonalidad ni la energia."
    )

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='Recalcular tambien las pistas que ya tienen rejilla.')
        parser.add_argument(
            '--include-manual', action='store_true',
            help='Con --all, recalcular tambien las pistas cuyo primer tiempo fijo el DJ a mano (se pierde esa correccion).',
        )

    def handle(self, *args, **options):
        pistas = Track.objects.exclude(audio_file='')
        if not options['all']:
            pistas = pistas.filter(grid_offset__isnull=True)
        elif not options['include_manual']:
            pistas = pistas.exclude(grid_manual=True)
        pistas = list(pistas.order_by('id'))

        self.stdout.write(f'Calculando la rejilla de {len(pistas)} pista(s).')
        for pista in pistas:
            try:
                with local_audio_path(pista.audio_file) as ruta:
                    analisis = analyze_file(ruta)
            except (UnsupportedAudioError, AudioTooShortError, SilentAudioError, OSError) as error:
                self.stdout.write(self.style.WARNING(f'  {pista.title}: no se pudo analizar ({error})'))
                continue

            if analisis.grid_offset is None:
                self.stdout.write(self.style.WARNING(f'  {pista.title}: sin un ritmo claro, se deja como estaba'))
                continue

            pista.bpm = analisis.bpm
            pista.cue_points = analisis.cue_points
            pista.grid_offset = analisis.grid_offset
            pista.grid_downbeat = analisis.grid_downbeat
            pista.grid_confidence = analisis.grid_confidence
            pista.save(update_fields=['bpm', 'cue_points', 'grid_offset', 'grid_downbeat', 'grid_confidence'])
            self.stdout.write(self.style.SUCCESS(
                f'  {pista.title}: {pista.bpm:.3f} BPM, primer tiempo en {pista.grid_downbeat:.3f} s '
                f'(confianza {pista.grid_confidence:.2f})'
            ))
