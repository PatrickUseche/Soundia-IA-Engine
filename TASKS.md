# TASKS — SoundIA IA Engine (Django)

Plan de mejoras del motor de IA. Cada task es un commit; el mensaje del commit es el texto de la task con su sufijo `[x.y]`.
Al terminarla se marca `[x]` en ese mismo commit.

## Fase 1 — Estabilizar lo existente

- [x] fix(services): eliminar el doble cálculo de la estrategia en calculate_transition [1.1]
- [x] fix(services): aceptar el valor MIDI 0 como válido (rango 0-127) [1.2]
- [x] fix(strategies): corregir el formato del porcentaje (:.1f) [1.3]
- [x] refactor(settings): SECRET_KEY, DEBUG y ALLOWED_HOSTS desde variables de entorno [1.4]
- [x] chore: crear requirements.txt con las dependencias del proyecto [1.5]
- [x] test(telemetry): pruebas de la vista, el servicio y las estrategias [1.6]
- [x] refactor(views): centralizar la validación de la petición en parse_midi_event [1.7]

## Fase 2 — Análisis de audio

- [x] feat(audio): modelo Track y migración con BPM, tonalidad, energía y duración [2.1]
- [x] feat(audio): servicio de análisis de BPM con librosa [2.2]
- [x] feat(audio): detección de tonalidad y conversión a rueda de Camelot [2.3]
- [x] feat(audio): cálculo de energía y detección de puntos de mezcla (cues) [2.4]
- [x] feat(api): endpoint para analizar un archivo de audio [2.5]

## Fase 3 — Motor de mezcla

- [x] feat(mix): estrategia de compatibilidad armónica y de BPM para elegir la siguiente pista [3.1]
- [x] feat(mix): estrategia de transición con curvas de EQ y crossfade [3.2]
- [x] feat(mix): ajuste de tempo para beatmatching [3.3]
- [x] feat(api): endpoint de siguiente pista y plan de transición [3.4]

## Fase 4 — IA real

- [x] feat(ml): el dataset son las valoraciones del DJ de cada transición (me gustó / no me gustó) con sus puntuaciones, y no AiDecisionLog: ese registro no dice si una decisión fue buena [4.1]
- [x] feat(ml): aprender cuándo mezclar a partir de las veces que el DJ pide mezclar antes de lo planeado [4.5]
- [x] feat(audio): detectar dónde acaba la voz en el final de la pista (Demucs, opcional, en segundo plano) para no cortar la letra al mezclar [4.6]
- [x] feat(audio): rejilla de pulsos (tempo afinado, fase y primer tiempo del compás) para mezclar a compás [4.7]
- [ ] feat(ml): recomendador de pistas con embeddings (pendiente: no hay datos suficientes para entrenarlos; primero hace falta acumular valoraciones y escuchas) [4.2]
- [x] feat(ml): puntuación de compatibilidad con pesos aprendidos por regresión logística, que reemplazan a los fijos 45/40/15 [4.3]
- [x] feat(ml): evaluación (validación cruzada) y versionado de los pesos aprendidos [4.4] (el historial y la vuelta atrás llegaron después, ver [6.5])

## Fase 5 — Despliegue

- [x] chore(db): pasar de SQLite a PostgreSQL [5.1] (con `DATABASE_URL`; no se probó contra un Postgres real)
- [x] chore(docker): Dockerfile del motor [5.2] (escrito pero sin probar: no hay Docker en la máquina de desarrollo)
- [x] chore(ci): pipeline de GitHub Actions con tests [5.3]

## Fase 6 — Pendiente

- [x] test(audio): investigar un mejor detector del primer tiempo (downbeat) [6.1] (sin cambio de algoritmo: la novedad de textura por posición del compás da ~25 % en cada una de las 4 posiciones en dos pistas reales, así que no discrimina, y sin una referencia de oído no se puede validar otra heurística; con confianza < 0,2 el Auto-DJ ya alinea por pulso y no por compás)
- [x] feat(audio): analizar también el inicio de la pista (dónde empieza la voz) y acortar el solape para no pisar la voz de la pista B [6.2] (apagado por defecto, `VOCAL_ANALYSIS_START=on`: su memoria no se pudo medir en el equipo de desarrollo y el sistema se quedó sin RAM; el punto de entrada sigue siendo el primer cue; ver [6.3])
- [ ] feat(mix): que el estilo blend (tempos igualados) use también la voz de la pista que sale al elegir el punto de salida (con [6.2] ya usa la de la que entra) [6.3]
- [ ] feat(audio): soportar tempo variable y analizar más de los primeros 10 minutos [6.4]
- [x] feat(ml): historial de versiones de los pesos con vuelta atrás, y una forma de reiniciar lo aprendido del momento de mezcla [6.5] (comando `manage.py learning`)
- [ ] test(audio): validar el análisis y el aprendizaje con música y valoraciones reales, no sintéticas [6.6]
- [x] feat(audio): endpoint para fijar a mano el primer tiempo de una pista (PUT /tracks/<id>/grid, con confianza 1 y marca de que es manual), para cuando la detección no se puede fiar [6.7] (el recálculo `analyze_grid --all` no pisa lo manual; los cuePoints no se mueven; falta el botón en el front y la ruta en Spring)

## Fase 7 — Despliegue en el navegador (pendiente)

Encontrado al probar el sistema completo en un navegador real (2026-10-22); nada de esto se ha hecho todavía.

- [x] chore(deploy): con `DJANGO_DEBUG=False` hacen falta `DJANGO_SECRET_KEY` y `DJANGO_ALLOWED_HOSTS` con los nombres reales; no publicar el puerto 8000 (este servicio no tiene autenticación y solo debe verlo el API Gateway) [7.1] (resuelto en el `docker-compose.prod.yml` del API: sin puertos publicados y `VOCAL_ANALYSIS=off`)
- [x] chore(deploy): decidir si el análisis de voz (Demucs, ~800 MB de RAM por análisis) se ejecuta en el servidor o se apaga con `VOCAL_ANALYSIS=off`; en un equipo con 4 GB satura la memoria [7.2] (resuelto en el `docker-compose.prod.yml` del API: sin puertos publicados y `VOCAL_ANALYSIS=off`)

## Fase 8 — Aprender el estilo de un DJ profesional (en curso)

Plan acordado con el usuario (2026-10-22): un solo DJ por ahora (el usuario maneja el sistema), géneros variados (merengue,
bachata, salsa, despecho, discobar), primero «cuándo y cómo mezclar», datos guardados en el equipo. El DJ aparece con un
alias. Antes de entrenar, un DJ debe escuchar las mezclas del Auto-DJ ([6.10]) y revisar sus transiciones.

- [x] feat(ml): almacén de grabaciones de mezclas (`MixRecording`) con foto de las pistas, validación y rasgos derivados [8.1]
- [ ] feat(ml): comando para exportar y restaurar las grabaciones en un archivo JSON (copia de seguridad) [8.2]
- [ ] feat(tracks): ruta de reenvío `/api/v1/recordings` en Spring [8.3]
- [ ] feat(learning): modo aprendizaje en Angular que graba las transiciones manuales (entrada de B, solape y curvas) [8.4]
- [ ] feat(learning): pantalla para revisar las grabaciones (buena, descartada, notas) [8.5]
- [ ] feat(tracks): género de cada pista, editable, como dato de contexto del estilo [8.6]
- [ ] feat(audio): tempo variable (salsa y merengue en vivo lo mueven); es la [6.4], que sube de prioridad [8.7]
- [ ] feat(ml): modelo de parámetros de transición (medianas por contexto, luego regresión regularizada hacia las reglas) y su evaluación contra las reglas actuales [8.8]
- [ ] feat(ml): usar el modelo en el plan de transición solo si gana a las reglas, con interruptor y vuelta atrás [8.9]
- [ ] chore(demo): modo de datos reales en el script de arranque (carpeta fija en lugar de la temporal) [8.10]
- [ ] feat(ml): modelo de qué pista sigue, a partir de las secuencias reales (después de lo anterior) [8.11]

## Fase 9 — Nube gratuita sin tarjeta (en curso)

Arquitectura acordada con el usuario (2026-10-24): Angular en Cloudflare Pages, Spring y Django en Render (gratis, se duermen y su disco se borra), base de datos en Neon (Postgres) y audios en Supabase Storage (S3). Nada de esto se ha probado contra las plataformas reales.

- [x] feat(security): clave compartida `SERVICE_TOKEN` entre el API y el motor, porque en Render el motor tiene URL pública [9.1]
- [x] feat(db): configurar la base de datos con `DATABASE_URL` (PostgreSQL en Neon) [9.2]
- [x] feat(storage): guardar los audios en un almacenamiento S3 (Supabase) y no depender del disco [9.3]
- [x] chore(deploy): `render.yaml` y escuchar en el puerto `$PORT` [9.4]
- [x] fix(audio): bajar el pico de memoria del análisis de ~880 MB a ~300 MB en una pista de 6 minutos (carga por bloques, STFT/CQT por tramos, tempo sobre el tramo más rítmico), porque en Render gratis (512 MB) el motor se caía al analizar [9.5]

## Fase 10 — Aprender desde la nube con el repertorio del DJ (en curso)

Acordado con el usuario (2026-10-24): el DJ usa la versión de la nube, por sesiones (sube las pistas de la sesión, mezcla con el modo aprendizaje y borra las pistas al terminar; las grabaciones se conservan). El almacenamiento gratuito de Supabase es de 1 GB.

- [x] feat(tracks): borrar una pista y su audio (`DELETE /api/audio/tracks/<id>`) [10.1]
- [x] feat(tracks): el listado de pistas llega a 200 (antes 50) y es configurable con `TRACK_LIST_LIMIT` [10.3]
