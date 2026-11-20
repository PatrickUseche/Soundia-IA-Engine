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
        track_list = Track.objects.exclude(audio_file='')
        if not options['all']:
            track_list = track_list.filter(grid_offset__isnull=True)
        elif not options['include_manual']:
            track_list = track_list.exclude(grid_manual=True)
        track_list = list(track_list.order_by('id'))

        self.stdout.write(f'Calculando la rejilla de {len(track_list)} pista(s).')
        for track_obj in track_list:
            try:
                with local_audio_path(track_obj.audio_file) as file_path:
                    analysis_result = analyze_file(file_path)
            except (UnsupportedAudioError, AudioTooShortError, SilentAudioError, OSError) as error:
                self.stdout.write(self.style.WARNING(f'  {track_obj.title}: no se pudo analizar ({error})'))
                continue

            if analysis_result.grid_offset is None:
                self.stdout.write(self.style.WARNING(f'  {track_obj.title}: sin un ritmo claro, se deja como estaba'))
                continue

            track_obj.bpm = analysis_result.bpm
            track_obj.cue_points = analysis_result.cue_points
            track_obj.grid_offset = analysis_result.grid_offset
            track_obj.grid_downbeat = analysis_result.grid_downbeat
            track_obj.grid_confidence = analysis_result.grid_confidence
            track_obj.tempo_wobble_ms = analysis_result.tempo_wobble_ms
            track_obj.save(update_fields=['bpm', 'cue_points', 'grid_offset', 'grid_downbeat', 'grid_confidence',
                                      'tempo_wobble_ms'])
            self.stdout.write(self.style.SUCCESS(
                f'  {track_obj.title}: {track_obj.bpm:.3f} BPM, primer tiempo en {track_obj.grid_downbeat:.3f} s '
                f'(confianza {track_obj.grid_confidence:.2f})'
            ))
