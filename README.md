# SoundIA — IA Engine (Django)

Motor de IA de SoundIA. Calcula transiciones de mezcla para los eventos MIDI y analiza pistas de audio
(tempo, tonalidad, energía y puntos de mezcla). Lo consume el API Gateway (`SoundIA-API-Core`), no el navegador.

```
Angular (:4200) ──► Spring Boot (:8080) ──► Django (:8000)
```

## Requisitos

- Python 3.12
- Dependencias: `pip install -r requirements.txt` (incluye `librosa` y `soundfile`)

## Ejecutar

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver     # http://localhost:8000
python manage.py test          # pruebas
```

## Configuración

Variables de entorno (ver `.env.example`; Django no lee `.env` por sí solo):

| Variable | Por defecto | Descripción |
|---|---|---|
| `DJANGO_DEBUG` | `True` | Modo debug |
| `DJANGO_SECRET_KEY` | clave de desarrollo | Obligatoria si `DJANGO_DEBUG=False` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Hosts permitidos |
| `AUDIO_MAX_UPLOAD_BYTES` | `52428800` (50 MB) | Tamaño máximo de un audio subido |

## Endpoints

### Mezcla (`telemetry`)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/mix/calculate` | Recibe `{controlId, value}` (valor MIDI 0-127) y devuelve `{status, action}`. |

### Análisis de audio (`audio`)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/audio/analyze` | `multipart/form-data` con `file` (WAV, FLAC, OGG o MP3) y `title` opcional. Analiza y guarda la pista. |
| `GET` | `/api/audio/tracks` | Las 50 pistas más recientes. |
| `GET` | `/api/audio/tracks/<id>` | Detalle de una pista. |

Respuesta de `analyze` (201):

```json
{
  "id": 1, "title": "tema.wav", "duration": 215.3,
  "bpm": 127.98, "key": "A minor", "camelot": "8A", "energy": 0.62,
  "cuePoints": [0.4, 30.4, 60.4, 180.4], "createdAt": "2026-10-21T18:30:00+00:00"
}
```

Errores: `400` archivo ausente o ilegible, `413` demasiado grande, `422` válido pero imposible de analizar
(menos de 2 s o en silencio).

## Cómo funciona el análisis (`audio/analysis.py`)

- **BPM**: tempo de librosa afinado con regresión sobre los tiempos de los beats (precisión de décimas,
  necesaria para beatmatching). Los errores de octava se pliegan al rango 70-180.
- **Tonalidad**: cromagrama medio comparado con los perfiles de Krumhansl-Schmuckler de las 24 tonalidades;
  se traduce a la rueda de Camelot (`audio/camelot.py`), que también dice qué códigos mezclan bien entre sí.
- **Energía**: nivel RMS en dBFS normalizado entre 0 (-40 dB) y 1 (0 dB).
- **Cues**: sobre la rejilla de compases del BPM: inicio de la música, cambios fuertes de energía
  (caídas, subidas, breakdowns, separados por ≥ 8 compases) y salida 16 compases antes del final.

### Limitaciones conocidas

- La rejilla de compases se ancla al **primer ataque** detectado; no se detecta el *downbeat* real,
  así que en música con intro sin percusión el compás puede quedar desfasado un pulso.
- La tonalidad se pensó para música tonal; en percusión pura no es fiable (`confidence` baja).
- Solo se analizan los primeros 10 minutos de cada pista.
- Las pruebas usan señales sintéticas; falta validar con música real.
