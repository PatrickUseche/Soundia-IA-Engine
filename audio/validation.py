"""Mide cuanto acierta el analisis de audio contra pistas con tempo (y primer tiempo) conocidos.

Todo es calculo puro sobre listas pequenas (decenas de pistas): no lee audio. El comando `validate_beats` es quien
analiza los archivos y usa estas funciones para comparar y resumir.

Metricas (las habituales en la investigacion de tempo):
- exacto: el BPM detectado queda dentro de un margen relativo (4 % por defecto) del de referencia.
- con octavas: igual, pero tambien vale el doble, la mitad, el triple o el tercio (el error de octava es el fallo mas
  comun del tempo y no siempre arruina una mezcla; por eso se cuenta aparte).
- primer tiempo del compas: la diferencia, en la vuelta del compas, es menor que una tolerancia en segundos.
- fase del pulso: lo mismo pero en la vuelta de un solo pulso (acierta el ritmo aunque se equivoque de pulso del compas).
"""
import csv
import statistics
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TEMPO_TOLERANCE = 0.04
DEFAULT_DOWNBEAT_TOLERANCE = 0.07  # segundos
BEATS_PER_BAR = 4
OCTAVE_FACTORS = (1.0, 2.0, 0.5, 3.0, 1.0 / 3.0)
NO_GENRE = 'sin género'
ALL = 'todas'


def tempo_matches(reference_bpm: float, detected_bpm: float, tolerance: float = DEFAULT_TEMPO_TOLERANCE) -> bool:
    if reference_bpm <= 0:
        return False
    return abs(detected_bpm - reference_bpm) / reference_bpm <= tolerance


def tempo_matches_any_octave(reference_bpm: float, detected_bpm: float,
                             tolerance: float = DEFAULT_TEMPO_TOLERANCE) -> bool:
    return any(tempo_matches(reference_bpm * factor, detected_bpm, tolerance) for factor in OCTAVE_FACTORS)


def circular_error(a: float, b: float, period: float) -> float:
    """Distancia entre dos instantes cuando el tiempo da la vuelta cada `period` segundos (nunca pasa de period/2)."""
    if period <= 0:
        raise ValueError('El periodo debe ser positivo.')
    diferencia = abs(a - b) % period
    return min(diferencia, period - diferencia)


@dataclass(frozen=True)
class Reference:
    path: Path
    bpm: float | None  # None: la fila no trae BPM (plantilla sin rellenar)
    genre: str = ''
    downbeat: float | None = None  # segundo del primer tiempo de un compas


@dataclass(frozen=True)
class Result:
    reference: Reference
    detected_bpm: float | None
    detected_downbeat: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class Summary:
    total: int
    exact: int
    octave: int
    errors: int
    downbeat_total: int
    downbeat_ok: int
    beat_phase_ok: int
    median_error_pct: float | None

    @property
    def exact_rate(self) -> float:
        return self.exact / self.total if self.total else 0.0

    @property
    def octave_rate(self) -> float:
        return self.octave / self.total if self.total else 0.0

    @property
    def downbeat_rate(self) -> float:
        return self.downbeat_ok / self.downbeat_total if self.downbeat_total else 0.0

    @property
    def beat_phase_rate(self) -> float:
        return self.beat_phase_ok / self.downbeat_total if self.downbeat_total else 0.0


def _optional_float(text: str, field: str, line: int) -> float | None:
    if text == '':
        return None
    try:
        return float(text)
    except ValueError:
        raise ValueError(f'línea {line}: «{text}» no es un número válido en la columna {field}.') from None


def load_manifest(path: Path) -> list[Reference]:
    """Lee un CSV con las columnas `file` (obligatoria), `bpm`, `genre` y `downbeat`. Las rutas son relativas al CSV."""
    path = Path(path)
    with path.open(newline='', encoding='utf-8-sig') as archivo:
        lector = csv.DictReader(archivo)
        columnas = [(nombre or '').strip() for nombre in (lector.fieldnames or [])]
        if 'file' not in columnas:
            raise ValueError('El manifiesto necesita una columna «file» con la ruta de cada audio.')
        lector.fieldnames = columnas
        referencias = []
        for fila in lector:
            valores = {clave: (valor or '').strip() for clave, valor in fila.items() if clave}
            if not valores.get('file'):
                continue
            linea = lector.line_num
            bpm = _optional_float(valores.get('bpm', ''), 'bpm', linea)
            if bpm is not None and bpm <= 0:
                raise ValueError(f'línea {linea}: el BPM debe ser mayor que cero.')
            referencias.append(Reference(
                path=path.parent / valores['file'],
                bpm=bpm,
                genre=valores.get('genre', ''),
                downbeat=_optional_float(valores.get('downbeat', ''), 'downbeat', linea),
            ))
    return referencias


def _summarize_group(results: list[Result], tempo_tolerance: float, downbeat_tolerance: float) -> Summary:
    exact = octave = errors = downbeat_total = downbeat_ok = beat_phase_ok = 0
    error_pcts = []
    for result in results:
        if result.error is not None or result.detected_bpm is None:
            errors += 1
            continue
        reference = result.reference
        exact += tempo_matches(reference.bpm, result.detected_bpm, tempo_tolerance)
        octave += tempo_matches_any_octave(reference.bpm, result.detected_bpm, tempo_tolerance)
        error_pcts.append(abs(result.detected_bpm - reference.bpm) / reference.bpm * 100.0)
        if reference.downbeat is not None and result.detected_downbeat is not None:
            downbeat_total += 1
            beat = 60.0 / reference.bpm
            downbeat_ok += circular_error(result.detected_downbeat, reference.downbeat,
                                          beat * BEATS_PER_BAR) <= downbeat_tolerance
            beat_phase_ok += circular_error(result.detected_downbeat, reference.downbeat, beat) <= downbeat_tolerance
    return Summary(
        total=len(results), exact=exact, octave=octave, errors=errors, downbeat_total=downbeat_total,
        downbeat_ok=downbeat_ok, beat_phase_ok=beat_phase_ok,
        median_error_pct=statistics.median(error_pcts) if error_pcts else None,
    )


def summarize(results: list[Result], tempo_tolerance: float = DEFAULT_TEMPO_TOLERANCE,
              downbeat_tolerance: float = DEFAULT_DOWNBEAT_TOLERANCE) -> dict[str, Summary]:
    """Resumen por genero y total. Una pasada agrupa por genero (hash); la mediana ordena cada grupo: O(P log P)."""
    scored = [result for result in results if result.reference.bpm is not None]
    groups: dict[str, list[Result]] = {}
    for result in scored:
        groups.setdefault(result.reference.genre or NO_GENRE, []).append(result)
    summary = {genre: _summarize_group(group, tempo_tolerance, downbeat_tolerance) for genre, group in groups.items()}
    summary[ALL] = _summarize_group(scored, tempo_tolerance, downbeat_tolerance)
    return summary
