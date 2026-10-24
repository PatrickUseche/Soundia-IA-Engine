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
| `DATABASE_URL` | vacía (SQLite) | `postgresql://usuario:clave@servidor/base?sslmode=require`: usa PostgreSQL (por ejemplo Neon) en lugar de SQLite, para que los datos sobrevivan a un disco efímero |
| `S3_BUCKET` | vacía (disco) | Guarda los audios en un almacenamiento S3 (Supabase Storage, R2…) en lugar de `MEDIA_ROOT`. Con ella hacen falta también `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID` y `S3_SECRET_ACCESS_KEY` (y `S3_REGION`, por defecto `us-east-1`); si falta alguna el motor no arranca |
| `PORT` / `WEB_CONCURRENCY` / `GUNICORN_THREADS` | `8000` / `2` / `1` | Solo en la imagen Docker: puerto de escucha (Render lo fija), procesos e hilos de gunicorn. En 512 MB de RAM: 1 proceso y 4 hilos |
| `TRACK_LIST_LIMIT` | `200` | Máximo de pistas que devuelve el listado de la biblioteca (las más recientes primero). |
| `SERVICE_TOKEN` | vacía | Clave compartida con el API: si se define, el motor exige la cabecera `X-Soundia-Key` con ese valor y responde 401 a quien no la lleve. Obligatoria cuando el motor es accesible desde Internet (nube gratuita) |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Hosts permitidos. En producción, solo el nombre con que lo llama el API (`ia-engine` en el compose) |
| `AUDIO_MAX_UPLOAD_BYTES` | `52428800` (50 MB) | Tamaño máximo de un audio subido |
| `MEDIA_ROOT` | `media/` | Carpeta donde se guardan los audios subidos (ignorada por git) |
| `VOCAL_ANALYSIS` | `auto` | Detección de voz: `auto` la hace si `requirements-vocals.txt` está instalado; `off` la desactiva (el `docker-compose.prod.yml` del API la apaga: gasta ~800 MB de RAM por análisis) |
| `VOCAL_ANALYSIS_START` | `off` | `on` hace que, además del final, se analice el inicio de la pista (dónde empieza la voz). Viene apagado: duplica el tiempo del análisis y su pico de memoria no se pudo medir (ver Detección de voz) |
| `VOCAL_TORCH_THREADS` | `2` | Hilos de CPU del modelo de separación de voz |
| `VOCAL_ANALYSIS_TIMEOUT` | `1800` | Segundos que se le dan a un análisis de voz antes de darlo por colgado |

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
los tempos no se pueden igualar: la pista entrante suena a su propio tempo, sin forzar el pitch. El fundido empieza justo antes de que acabe la pista saliente (con 2 s de margen) para no cortar su final ni su letra. La mezcla sale en el último punto de mezcla de la pista actual donde todavía cabe,
y la siguiente entra desde su primer punto de mezcla. Incluye curvas por pulso: crossfader de potencia constante,
intercambio de graves a mitad (nunca suenan los graves de las dos pistas a la vez) y cruce lineal de medios y agudos.

### Aprendizaje de los pesos (`mixing`)

El motor **aprende de las valoraciones del DJ**: cuando una transición suena bien o mal, se valora y el motor ajusta cuánto
pesa cada criterio (tempo, armonía, energía) *para ese DJ*, en lugar de usar siempre 45/40/15.

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/mix/feedback` | `{fromTrackId, toTrackId, liked}` (`liked` debe ser `true`/`false`). Guarda la valoración con las puntuaciones que tenía la transición y reentrena. Devuelve `{weights, samples, learned}`. |
| `POST` | `/api/mix/timing` | `{fromTrackId, toTrackId, plannedMixOutAt, actualMixOutAt}` en segundos. El DJ pidió mezclar antes de lo planeado: se guarda y, con 3 casos o más, el motor adelanta sus mezclas la mediana de esos adelantos (máx. 120 s; cuentan los últimos 20). Devuelve `{samples, advanceSeconds, learned}`. `/api/mix/transition` devuelve el adelanto aplicado en `mixOutAdvance`. |
| `GET` | `/api/mix/weights` | Los pesos vigentes, si son aprendidos, con cuántas valoraciones, su `version` y su acierto medido (`accuracy` frente a `defaultAccuracy`, `null` si no se pudo medir) y `history`: las 10 versiones guardadas más nuevas, con la vigente marcada (`active`). |

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

**Historial y vuelta atrás.** Cada reentrenamiento guarda una versión nueva y se conservan las últimas 50; solo una es la
vigente. Se administra con `python manage.py learning` (no hay endpoints para esto, porque borrar o cambiar lo aprendido
no debe estar al alcance de cualquier petición):

| Opción | Qué hace |
|---|---|
| `--list` | Muestra las versiones de los pesos (la vigente con `*`) y cuántas valoraciones y casos de «cuándo mezclar» hay. |
| `--rollback-weights` | Vuelve a la versión anterior a la vigente. |
| `--restore-version N` | Vuelve a usar la versión `N`. |
| `--reset-weights` | Deja de usar los pesos aprendidos (vuelven los 45/40/15). Conserva valoraciones e historial. |
| `--reset-weights --forget-ratings` | Además borra las valoraciones y las versiones guardadas: empezar de cero. |
| `--reset-timing` | Borra lo aprendido sobre cuándo mezclar (`MixTimingFeedback`). |

Ojo: volver a una versión o reiniciar **dura hasta la próxima valoración**, porque el reentrenamiento parte siempre de
las valoraciones guardadas y su resultado pasa a ser la versión vigente. Para que no vuelva a aprender lo mismo hay que
borrar también las valoraciones (`--forget-ratings`).

**Limitaciones:** es un modelo muy pequeño (tres números); no hay embeddings de pistas. Con pocas valoraciones la medición es
ruidosa (con 10-20 cada grupo de prueba tiene 2-4 ejemplos). Se probó solo con valoraciones sintéticas: falta ver cómo se comporta con un DJ real.

### Grabaciones de mezclas (`mixing`)

Para aprender el estilo de un DJ (cuándo sale, cuándo entra la siguiente, cuánto solapa, cómo mueve el crossfader y el
EQ) hace falta guardar lo que hace de verdad. Cada **grabación** es una transición: el front la registra en el «modo
aprendizaje» y aquí se valida, se guarda y se calculan sus rasgos.

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/mix/recordings` | Guarda una transición. Cuerpo: `fromTrackId`, `toTrackId`, `mixOutAt` (segundo de A en que entra B), `mixInAt` (segundo de B desde el que suena), `overlapSeconds`, `pitchA`, `pitchB`; opcionales `source` (`manual` o `autodj`), `dj` (alias, nunca el nombre real), `genreA`, `genreB`, `notes` y `curves`. 201 con la grabación y sus rasgos; 400 si algo no es válido; 404 si falta una pista. |
| `GET` | `/api/mix/recordings` | Las 200 más recientes sin las curvas, con `counts` por calidad. `?quality=good` filtra por `unreviewed`, `good` o `discard`. |
| `GET` | `/api/mix/recordings/<id>` | Una grabación con sus curvas y la foto de las pistas. |
| `PUT` | `/api/mix/recordings/<id>` | `{quality?, notes?}`: la revisión del DJ. Solo las `good` deberían usarse para entrenar. |
| `DELETE` | `/api/mix/recordings/<id>` | La borra (204). |
| `GET` | `/api/mix/recordings/export` | Copia de seguridad: todas las grabaciones, con la foto de sus pistas, en un JSON descargable (formato `soundia-recordings`, versión 1). No lleva los ids de las pistas, porque en otra base pueden ser distintos. |
| `POST` | `/api/mix/recordings/import` | Restaura una copia exportada. Todo o nada (400 con la posición de la grabación inválida, sin guardar ninguna); las que ya están (mismo DJ, fecha y datos de la mezcla) no se duplican. Responde `{created, skipped}`. Las restauradas quedan sin pista enlazada. Tamaño máximo del cuerpo: 2,5 MB por defecto de Django. |

También por consola: `python manage.py recordings_backup --export copia.json` y `--import copia.json`.

- **Curvas** (`curves`): pares `[segundo, valor 0-1]` con el segundo relativo a la entrada de B (de -1 a la duración del
  solape + 1), hasta 200 puntos por curva: `crossfader` y, para cada deck (`a`, `b`), `volume`, `low`, `mid` y `high`.
- **Foto de las pistas:** el servidor guarda los datos de las dos pistas tal como eran (tempo, Camelot, energía,
  rejilla, voz) tomándolos de su base, nunca del cliente. Si luego se corrige una rejilla o se borra una pista, la
  grabación no cambia.
- **Rasgos derivados** (`features`): `overlapBars` (compases de solape al tempo al que sonaba A), `exitFromEnd`,
  `exitFraction`, `exitAfterLastVocal`, `entryBarsFromDownbeat`, `entryBeforeFirstVocal`, `phaseErrorMs` (desfase de
  pulsos al entrar B; positivo = B va por detrás), `tempoRatio`, `bpmDifference`, `keyDistance`, `energyDelta`,
  `bassSwapAt` (fracción del solape en que quita los graves de A) y `crossfaderShape` (`corte`, `gradual` o `lento`). Lo
  que no se puede calcular (sin rejilla, sin voz, sin curva) queda en `null`.

### Análisis de audio (`audio`)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/audio/analyze` | `multipart/form-data` con `file` (WAV, FLAC, OGG o MP3), `title` y `genre` opcionales. Analiza y guarda la pista. |
| `GET` | `/api/audio/tracks` | Las pistas más recientes, hasta `TRACK_LIST_LIMIT` (200 por defecto). |
| `GET` | `/api/audio/tracks/<id>` | Detalle de una pista (incluye `hasAudio`). |
| `PUT` | `/api/audio/tracks/<id>` | `{genre}`: el género de la pista (merengue, bachata, salsa...). Se guarda sin espacios de más y en minúsculas; vacío lo quita; máximo 40 caracteres (400 si no es texto o es más largo). Devuelve la pista. Al grabar una mezcla, si el cliente no manda `genreA`/`genreB` se toma el género de cada pista. |
| `DELETE` | `/api/audio/tracks/<id>` | Borra la pista y su audio (también del almacenamiento externo). 204; 404 si no existe; 502 si el almacenamiento falla (la pista se conserva para reintentar). Las grabaciones de mezclas que la usaron se conservan con la foto de sus datos. |
| `PUT` | `/api/audio/tracks/<id>/grid` | `{downbeat}`: el DJ señala un instante (segundos) que es un «1» del compás. Se ajusta al pulso más cercano de la rejilla, queda como primer tiempo con `confidence` 1 y `grid.manual` verdadero; los pulsos y el tempo no cambian. 400 si el cuerpo o el instante no son válidos, 409 si la pista no tiene rejilla. |
| `POST` | `/api/audio/tracks/<id>/vocals` | Pide analizar la voz del final y del inicio de una pista ya guardada (en segundo plano; 202). 503 si el modelo no está instalado. |
| `GET` | `/api/audio/tracks/<id>/file` | El audio original, para reproducirlo en los decks. 404 si la pista no tiene audio o el archivo ya no está. |

Respuesta de `analyze` (201):

```json
{
  "id": 1, "title": "tema.wav", "duration": 215.3,
  "bpm": 127.98, "key": "A minor", "camelot": "8A", "energy": 0.62,
  "cuePoints": [0.4, 30.4, 60.4, 180.4], "hasAudio": true, "createdAt": "2026-10-21T18:30:00+00:00",
  "vocals": {"status": "pending", "lastEnd": null, "firstStart": null},
  "grid": {"offset": 0.0375, "downbeat": 0.583, "confidence": 0.59, "manual": false}
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

### Rejilla de pulsos (`audio/beatgrid.py`)

Para mezclar a compás no basta con igualar el tempo: hay que saber en qué instante exacto suena cada golpe.
Cada pista guarda su **rejilla**: `bpm` afinado, `grid.offset` (segundo del primer pulso), `grid.downbeat`
(segundo del primer tiempo del compás) y `grid.confidence` (0-1: seguridad de que ese sea el «1»). Los pulsos
caen en `offset + k · 60/bpm`. `grid` es `null` si la pista no tiene un ritmo claro.

- **Tempo y fase:** la envolvente de ataques se pliega sobre el periodo de cada tempo candidato; con el correcto,
  todos los golpes caen en la misma fase. Después se ajusta el tempo con la deriva de la fase a lo largo de la
  pista y se afina la fase con la subida real de energía de la señal.
- **Primer tiempo:** el pulso del compás con más energía de graves (bombo). Con pulsos todos iguales la
  confianza sale ~0 y los puntos de mezcla siguen anclados al primer pulso; con `confidence ≥ 0.2` se anclan
  al primer tiempo.
- **Precisión medida:** en señales de referencia, error de fase ≤ 0,5 ms y de BPM ≤ 0,001. En música real no hay
  verdad conocida: la deriva de fase dentro de una pista es de ~10 ms en 3 min y el ruido o un tono puro dan una
  «fuerza» de pulso < 0,01 frente a 0,13-0,16 de la música real.
- **Pistas ya guardadas:** `python manage.py analyze_grid` (o `--all`). Recalcula su BPM y sus puntos de mezcla. Con `--all`
  **no** se recalculan las pistas cuyo primer tiempo se fijó a mano (`grid.manual`); `--include-manual` las incluye y
  pierde esa corrección.
- **Fijar el primer tiempo a mano:** cuando la detección no se puede fiar (reggaetón: confianza ~0), el DJ escucha y
  señala un «1» con `PUT /api/audio/tracks/<id>/grid`. Es lo único que hace falta para que el Auto-DJ alinee por
  compases esa pista. Limitación: los puntos de mezcla (`cuePoints`) se calcularon con el primer tiempo anterior y
  no se mueven.
- **Límites:** asume tempo constante; el primer tiempo es una heurística (en ritmos con el bombo en todos los
  pulsos, como mucho reggaetón, no se puede saber).

### Detección de voz (opcional)

Para no cortar la letra de la pista que sale ni pisarla con la de la que entra, el motor puede saber **dónde acaba la
última frase cantada** (`lastEnd`) y **dónde empieza la primera** (`firstStart`). Se separa la voz de los últimos 60 s
y, si se enciende `VOCAL_ANALYSIS_START=on`, de los primeros 60 s de la pista con Demucs (`htdemucs`) y se mide su
energía (`audio/separator.py`, `audio/vocals.py`); las dos ventanas se separan una después de otra, así que el pico de
memoria debería ser el de una sola. Con eso:

- El fundido (cuando los tempos no se pueden igualar) empieza 1 s después de la última frase de la pista que sale si
  queda cola instrumental; si la voz llega hasta el final, sigue empezando al final de la canción.
- En una mezcla con los tempos igualados (`blend`), el solape se acorta (de 16 a 8 o a 4 compases) si la voz de la pista
  que entra empezaría antes de que acabe: `plan.bars` y `plan.seconds` ya vienen ajustados (`fit_bars_to_intro`). Si ni
  4 compases caben en su intro, se queda con 4: menos de eso ya no es una mezcla.

- **Instalar:** `pip install -r requirements-vocals.txt` (~750 MB; el modelo, ~80 MB, se descarga la primera vez).
  Sin eso todo funciona igual y las pistas quedan con `vocals.status = "unavailable"`.
- **Cuándo se analiza:** al subir una pista, en segundo plano y de una en una (un hilo). Cada análisis corre en un
  **proceso aparte** (`audio/vocal_worker.py`): en un equipo con poca RAM, PyTorch puede acabar en un fallo nativo
  de memoria, y así solo falla esa pista (queda `failed`) en vez de caerse el servidor. Para las ya guardadas:
  `python manage.py analyze_vocals` (o `--all` para repetirlo) o `POST /api/audio/tracks/<id>/vocals`.
- **Análisis del inicio: sin medir y apagado por defecto.** Se intentó medir su tiempo y su pico de memoria con una
  pista real y el sistema (Ryzen 3 3250U, 3,4 GB de RAM) llegó a quedarse sin memoria y detuvo la prueba, así que no
  hay cifras. Antes de encenderlo conviene cerrar otros programas y probar con una sola pista (`python manage.py
  analyze_vocals`). Calcula la ventana del final y la del inicio por separado; si falta la memoria, solo falla ese análisis.
- **Coste medido del final** en un Ryzen 3 3250U (2 núcleos, 3,4 GB de RAM, sin GPU): unos 3 min por pista, con la CPU
  ocupada, y un pico de unos 750 MB de RAM en el proceso del análisis. Estados de `vocals.status`: `none`, `pending`, `running`, `done`, `failed`, `unavailable`.
- **Qué no hace:** solo mira los extremos de la pista (60 s de cada lado), y con mezclas de tempos igualados
  (`blend`) el punto de **salida** sigue yendo a un cue sin tener en cuenta la voz de la pista que sale (la de la que
  entra sí se tiene en cuenta). El punto de entrada de la pista B sigue siendo su primer cue.

### Limitaciones conocidas

- El primer tiempo del compás (*downbeat*) se estima por la energía de graves de cada pulso: en ritmos con el
  bombo en todos los pulsos (reggaetón) no se puede saber y la confianza sale baja; con confianza menor que 0,2 no
  se debe alinear por compás. Se probó una señal de cambio de textura por posición y no discrimina (≈25 % en cada
  una de las 4 posiciones), así que no se usa.
- La tonalidad se pensó para música tonal; en percusión pura no es fiable (`confidence` baja).
- Solo se analizan los primeros 10 minutos de cada pista.
- Las pruebas usan señales sintéticas; falta validar con música real.
