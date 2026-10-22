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
| `MEDIA_ROOT` | `media/` | Carpeta donde se guardan los audios subidos (ignorada por git) |

## Endpoints

### Mezcla (`telemetry`)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/mix/calculate` | Recibe `{controlId, value}` (valor MIDI 0-127) y devuelve `{status, action}`. |

### Motor de mezcla (`mixing`)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/mix/next` | `{trackId, limit?}` (límite 1-20, por defecto 5). Las pistas que mejor siguen a la indicada, de mayor a menor compatibilidad. |
| `POST` | `/api/mix/transition` | `{fromTrackId, toTrackId}`. Plan para pasar de una pista a la otra. |

La **compatibilidad** (0 a 1) combina tempo (45 %), armonía (40 %) y energía (15 %):

- *Tempo*: cuánto pitch hay que mover para igualar los BPM, con el límite habitual del fader (±8 %). También se
  prueba la otra pista a la mitad o al doble de tempo (174 contra 87).
- *Armonía*: pasos de distancia en la rueda de Camelot (misma = 1.0, vecina o relativa = 0.8, dos pasos = 0.5,
  tres = 0.25, más lejos = 0).
- *Energía*: 1 menos la diferencia.

El **plan de transición** elige el estilo y la duración: 16 compases si el tempo casi coincide y las tonalidades son
vecinas; 8 con algo más de ajuste o tonalidades a 2-3 pasos; 4 si las tonalidades chocan; y un **fundido** corto (2 compases, estilo `fade`) si
los tempos no se pueden igualar: la pista entrante suena a su propio tempo, sin forzar el pitch. La mezcla sale en el último punto de mezcla de la pista actual donde todavía cabe,
y la siguiente entra desde su primer punto de mezcla. Incluye curvas por pulso: crossfader de potencia constante,
intercambio de graves a mitad (nunca suenan los graves de las dos pistas a la vez) y cruce lineal de medios y agudos.

### Aprendizaje de los pesos (`mixing`)

El motor **aprende de las valoraciones del DJ**: cuando una transición suena bien o mal, se valora y el motor ajusta cuánto
pesa cada criterio (tempo, armonía, energía) *para ese DJ*, en lugar de usar siempre 45/40/15.

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/mix/feedback` | `{fromTrackId, toTrackId, liked}` (`liked` debe ser `true`/`false`). Guarda la valoración con las puntuaciones que tenía la transición y reentrena. Devuelve `{weights, samples, learned}`. |
| `GET` | `/api/mix/weights` | Los pesos vigentes, si son aprendidos, con cuántas valoraciones, su `version` y su acierto medido (`accuracy` frente a `defaultAccuracy`, `null` si no se pudo medir). |

Cómo aprende (`mixing/learning.py`): una **regresión logística** de tres variables entrenada con descenso de gradiente
(con `numpy`, determinista). Detalles que importan:

- Hasta **10 valoraciones** y de las dos clases no se aprende nada: se mantienen los pesos por defecto.
- Los pesos por defecto cuentan como **30 ejemplos virtuales**: con pocas valoraciones mandan ellos y, al acumularse,
  manda lo aprendido (con 20 valoraciones la armonía pasa a ~0.56; con 200, a ~0.68, en un caso sintético donde solo
  importa la armonía).
- Cada criterio se **centra** antes de entrenar: uno que no cambia entre «me gusta» y «no me gusta» no roba peso a los que sí.
- Ningún peso baja de 0.02 y siempre suman 1. Solo cuentan las 2000 valoraciones más recientes (el gusto puede cambiar).
- Siempre se reentrena **desde los pesos por defecto**, no desde los ya aprendidos: el resultado no depende del orden de llegada.

**Evaluación y versión.** Tras cada reentrenamiento se hace una **validación cruzada de 5 grupos** (`evaluate`): se aparta
cada quinta parte de las valoraciones, se entrena con el resto y se mide cuántas de las apartadas acierta («me gustó» /
«no me gustó», con un umbral entre las medias de cada clase). Se compara con los pesos por defecto y con quien dijera siempre
lo más frecuente. **Si los pesos nuevos aciertan menos que los de por defecto, no se adoptan** y siguen los vigentes. Los
adoptados llevan un número de `version` y su `accuracy`.

**Limitaciones:** es un modelo muy pequeño (tres números); se guarda solo la última versión (no hay historial ni vuelta atrás
a versiones anteriores, solo el rechazo de las peores); no hay embeddings de pistas. Con pocas valoraciones la medición es
ruidosa (con 10-20 cada grupo de prueba tiene 2-4 ejemplos). Se probó solo con valoraciones sintéticas: falta ver cómo se comporta con un DJ real.

### Análisis de audio (`audio`)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/audio/analyze` | `multipart/form-data` con `file` (WAV, FLAC, OGG o MP3) y `title` opcional. Analiza y guarda la pista. |
| `GET` | `/api/audio/tracks` | Las 50 pistas más recientes. |
| `GET` | `/api/audio/tracks/<id>` | Detalle de una pista (incluye `hasAudio`). |
| `GET` | `/api/audio/tracks/<id>/file` | El audio original, para reproducirlo en los decks. 404 si la pista no tiene audio o el archivo ya no está. |

Respuesta de `analyze` (201):

```json
{
  "id": 1, "title": "tema.wav", "duration": 215.3,
  "bpm": 127.98, "key": "A minor", "camelot": "8A", "energy": 0.62,
  "cuePoints": [0.4, 30.4, 60.4, 180.4], "hasAudio": true, "createdAt": "2026-10-21T18:30:00+00:00"
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
