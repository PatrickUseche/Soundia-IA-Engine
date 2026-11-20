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
        ruta = Path(options['path'])
        if options['template']:
            self.crear_plantilla(ruta, options['out'])
            return
        if not ruta.is_file():
            raise CommandError(f'No existe el manifiesto: {ruta}')
        try:
            referencias = load_manifest(ruta)
        except ValueError as error:
            raise CommandError(str(error)) from error

        con_bpm = [referencia for referencia in referencias if referencia.bpm is not None]
        sin_bpm = len(referencias) - len(con_bpm)
        if sin_bpm:
            self.stdout.write(self.style.WARNING(f'{sin_bpm} fila(s) sin BPM de referencia: se saltan (rellena la columna bpm).'))
        self.stdout.write(f'Validando {len(con_bpm)} pista(s).')

        resultados = [self.analizar(referencia) for referencia in con_bpm]
        resumen = summarize(resultados, options['tolerance'], options['downbeat_tolerance'])
        self.imprimir(resumen)
        if options['json_out']:
            self.guardar_json(Path(options['json_out']), resumen, resultados)

        minimo = options['min_accuracy']
        if minimo is not None and resumen[ALL].exact_rate < minimo:
            raise CommandError(
                f'El acierto exacto del tempo es {_percent(resumen[ALL].exact_rate)}, menos del mínimo pedido ({_percent(minimo)}).'
            )

    def analizar(self, referencia) -> Result:
        nombre = referencia.path.name
        try:
            analisis = analyze_file(referencia.path)
        except (UnsupportedAudioError, AudioTooShortError, SilentAudioError, OSError) as error:
            self.stdout.write(self.style.WARNING(f'  {nombre}: no se pudo analizar ({error})'))
            return Result(reference=referencia, detected_bpm=None, error=str(error))
        self.stdout.write(f'  {nombre}: referencia {referencia.bpm:g} BPM, detectado {analisis.bpm:.1f}')
        return Result(reference=referencia, detected_bpm=analisis.bpm, detected_downbeat=analisis.grid_downbeat)

    def imprimir(self, resumen):
        self.stdout.write('')
        self.stdout.write(f'{"género":<16}{"pistas":>7}{"exacto":>9}{"octavas":>9}{"mediana":>10}{"errores":>9}')
        for genero, datos in resumen.items():
            mediana = f'{datos.median_error_pct:.1f} %' if datos.median_error_pct is not None else '-'
            self.stdout.write(
                f'{genero:<16}{datos.total:>7}{_percent(datos.exact_rate):>9}{_percent(datos.octave_rate):>9}'
                f'{mediana:>10}{datos.errors:>9}'
            )
        todas = resumen[ALL]
        if todas.downbeat_total:
            self.stdout.write('')
            self.stdout.write(
                f'Primer tiempo del compás ({todas.downbeat_total} pistas con referencia): '
                f'compás {_percent(todas.downbeat_rate)}, pulso {_percent(todas.beat_phase_rate)}.'
            )

    def guardar_json(self, destino: Path, resumen, resultados):
        datos = {
            'summary': {
                genero: {
                    'total': s.total, 'exact': s.exact, 'octave': s.octave, 'errors': s.errors,
                    'exactRate': s.exact_rate, 'octaveRate': s.octave_rate, 'medianErrorPct': s.median_error_pct,
                    'downbeatTotal': s.downbeat_total, 'downbeatOk': s.downbeat_ok, 'beatPhaseOk': s.beat_phase_ok,
                } for genero, s in resumen.items()
            },
            'tracks': [{
                'file': r.reference.path.name, 'genre': r.reference.genre, 'referenceBpm': r.reference.bpm,
                'detectedBpm': r.detected_bpm, 'referenceDownbeat': r.reference.downbeat,
                'detectedDownbeat': r.detected_downbeat, 'error': r.error,
            } for r in resultados],
        }
        destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(f'Detalle guardado en {destino}')

    def crear_plantilla(self, carpeta: Path, destino: str | None):
        if not carpeta.is_dir():
            raise CommandError(f'No existe la carpeta: {carpeta}')
        audios = sorted(
            archivo.relative_to(carpeta).as_posix()
            for archivo in carpeta.rglob('*') if archivo.is_file() and archivo.suffix.lower() in AUDIO_EXTENSIONS
        )
        filas = [TEMPLATE_HEADER] + [[nombre, '', '', ''] for nombre in audios]
        if destino is None:
            for fila in filas:
                self.stdout.write(','.join(fila))
            return
        try:
            with open(destino, 'x', newline='', encoding='utf-8') as archivo:
                csv.writer(archivo, lineterminator='\n').writerows(filas)
        except FileExistsError:
            raise CommandError(f'El archivo ya existe y no se pisa: {destino}') from None
        self.stdout.write(f'Plantilla con {len(audios)} audio(s) en {destino}. Rellena bpm (y genre, downbeat si lo sabes).')
