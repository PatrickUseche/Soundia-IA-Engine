import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from audio.analysis import AudioTooShortError, SilentAudioError
from audio.services import UnsupportedAudioError, analyze_file
from audio.validation import (
    ALL, DEFAULT_DOWNBEAT_TOLERANCE, DEFAULT_TEMPO_TOLERANCE, Result, load_manifest, summarize,
)

AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.ogg'}
TEMPLATE_HEADER = ['file', 'bpm', 'genre', 'downbeat']


def _percent(rate: float) -> str:
    return f'{rate * 100:.0f} %'


class Command(BaseCommand):
    help = (
        "Mide cuanto acierta el analisis de audio (BPM y primer tiempo del compas) contra pistas con valores conocidos, "
        "por genero. Primero crea una plantilla con --template, rellena el BPM de cada pista y luego pasa el CSV. "
        "No guarda nada en la base de datos."
    )

    def add_arguments(self, parser):
        parser.add_argument('path', help='El CSV de referencia (columnas file, bpm, genre, downbeat) o, con --template, una carpeta de audios.')
        parser.add_argument('--template', action='store_true',
                            help='Crea un CSV con los audios de la carpeta y las columnas en blanco para rellenar.')
        parser.add_argument('--out', help='Con --template, donde guardar el CSV (si no se da, se imprime). No pisa archivos.')
        parser.add_argument('--json', dest='json_out', help='Guarda ademas el resumen y el detalle de cada pista en este JSON.')
        parser.add_argument('--tolerance', type=float, default=DEFAULT_TEMPO_TOLERANCE,
                            help='Margen relativo del tempo para contarlo como acierto (0.04 = 4 %%).')
        parser.add_argument('--downbeat-tolerance', type=float, default=DEFAULT_DOWNBEAT_TOLERANCE,
                            help='Margen en segundos del primer tiempo del compas.')
        parser.add_argument('--min-accuracy', type=float,
                            help='Falla (codigo de salida distinto de cero) si el acierto exacto total es menor (0.9 = 90 %%).')

    def handle(self, *args, **options):
        file_path = Path(options['path'])
        if options['template']:
            self.create_template(file_path, options['out'])
            return
        if not file_path.is_file():
            raise CommandError(f'No existe el manifiesto: {file_path}')
        try:
            reference_entries = load_manifest(file_path)
        except ValueError as error:
            raise CommandError(str(error)) from error

        with_bpm = [reference_entry for reference_entry in reference_entries if reference_entry.bpm is not None]
        without_bpm = len(reference_entries) - len(with_bpm)
        if without_bpm:
            self.stdout.write(self.style.WARNING(f'{without_bpm} fila(s) sin BPM de referencia: se saltan (rellena la columna bpm).'))
        self.stdout.write(f'Validando {len(with_bpm)} pista(s).')

        outcomes = [self.analyze_reference(reference_entry) for reference_entry in with_bpm]
        summary_info = summarize(outcomes, options['tolerance'], options['downbeat_tolerance'])
        self.print_line(summary_info)
        if options['json_out']:
            self.save_json(Path(options['json_out']), summary_info, outcomes)

        min_value = options['min_accuracy']
        if min_value is not None and summary_info[ALL].exact_rate < min_value:
            raise CommandError(
                f'El acierto exacto del tempo es {_percent(summary_info[ALL].exact_rate)}, menos del mínimo pedido ({_percent(min_value)}).'
            )

    def analyze_reference(self, reference_entry) -> Result:
        file_name = reference_entry.path.name
        try:
            analysis_result = analyze_file(reference_entry.path)
        except (UnsupportedAudioError, AudioTooShortError, SilentAudioError, OSError) as error:
            self.stdout.write(self.style.WARNING(f'  {file_name}: no se pudo analizar ({error})'))
            return Result(reference=reference_entry, detected_bpm=None, error=str(error))
        self.stdout.write(f'  {file_name}: referencia {reference_entry.bpm:g} BPM, detectado {analysis_result.bpm:.1f}')
        return Result(reference=reference_entry, detected_bpm=analysis_result.bpm, detected_downbeat=analysis_result.grid_downbeat)

    def print_line(self, summary_info):
        self.stdout.write('')
        self.stdout.write(f'{"género":<16}{"pistas":>7}{"exacto":>9}{"octavas":>9}{"mediana":>10}{"errores":>9}')
        for genre_name, payload_data in summary_info.items():
            median = f'{payload_data.median_error_pct:.1f} %' if payload_data.median_error_pct is not None else '-'
            self.stdout.write(
                f'{genre_name:<16}{payload_data.total:>7}{_percent(payload_data.exact_rate):>9}{_percent(payload_data.octave_rate):>9}'
                f'{median:>10}{payload_data.errors:>9}'
            )
        overall = summary_info[ALL]
        if overall.downbeat_total:
            self.stdout.write('')
            self.stdout.write(
                f'Primer tiempo del compás ({overall.downbeat_total} pistas con referencia): '
                f'compás {_percent(overall.downbeat_rate)}, pulso {_percent(overall.beat_phase_rate)}.'
            )

    def save_json(self, target_path: Path, summary_info, outcomes):
        payload_data = {
            'summary': {
                genre_name: {
                    'total': s.total, 'exact': s.exact, 'octave': s.octave, 'errors': s.errors,
                    'exactRate': s.exact_rate, 'octaveRate': s.octave_rate, 'medianErrorPct': s.median_error_pct,
                    'downbeatTotal': s.downbeat_total, 'downbeatOk': s.downbeat_ok, 'beatPhaseOk': s.beat_phase_ok,
                } for genre_name, s in summary_info.items()
            },
            'tracks': [{
                'file': r.reference.path.name, 'genre': r.reference.genre, 'referenceBpm': r.reference.bpm,
                'detectedBpm': r.detected_bpm, 'referenceDownbeat': r.reference.downbeat,
                'detectedDownbeat': r.detected_downbeat, 'error': r.error,
            } for r in outcomes],
        }
        target_path.write_text(json.dumps(payload_data, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(f'Detalle guardado en {target_path}')

    def create_template(self, folder: Path, target_path: str | None):
        if not folder.is_dir():
            raise CommandError(f'No existe la carpeta: {folder}')
        audios = sorted(
            audio_path_name.relative_to(folder).as_posix()
            for audio_path_name in folder.rglob('*') if audio_path_name.is_file() and audio_path_name.suffix.lower() in AUDIO_EXTENSIONS
        )
        csv_rows = [TEMPLATE_HEADER] + [[file_name, '', '', ''] for file_name in audios]
        if target_path is None:
            for csv_row in csv_rows:
                self.stdout.write(','.join(csv_row))
            return
        try:
            with open(target_path, 'x', newline='', encoding='utf-8') as audio_path_name:
                csv.writer(audio_path_name, lineterminator='\n').writerows(csv_rows)
        except FileExistsError:
            raise CommandError(f'El archivo ya existe y no se pisa: {target_path}') from None
        self.stdout.write(f'Plantilla con {len(audios)} audio(s) en {target_path}. Rellena bpm (y genre, downbeat si lo sabes).')
