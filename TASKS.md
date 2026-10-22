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

- [ ] feat(audio): modelo Track y migración con BPM, tonalidad, energía y duración [2.1]
- [ ] feat(audio): servicio de análisis de BPM con librosa [2.2]
- [ ] feat(audio): detección de tonalidad y conversión a rueda de Camelot [2.3]
- [ ] feat(audio): cálculo de energía y detección de puntos de mezcla (cues) [2.4]
- [ ] feat(api): endpoint para analizar un archivo de audio [2.5]

## Fase 3 — Motor de mezcla

- [ ] feat(mix): estrategia de compatibilidad armónica y de BPM para elegir la siguiente pista [3.1]
- [ ] feat(mix): estrategia de transición con curvas de EQ y crossfade [3.2]
- [ ] feat(mix): ajuste de tempo para beatmatching [3.3]
- [ ] feat(api): endpoint de siguiente pista y plan de transición [3.4]

## Fase 4 — IA real

- [ ] feat(ml): extraer dataset desde AiDecisionLog y las sesiones de Spring [4.1]
- [ ] feat(ml): recomendador de pistas con embeddings [4.2]
- [ ] feat(ml): estrategia de mezcla basada en modelo entrenado, intercambiable por Strategy [4.3]
- [ ] feat(ml): evaluación y versionado del modelo [4.4]

## Fase 5 — Despliegue

- [ ] chore(db): pasar de SQLite a PostgreSQL [5.1]
- [ ] chore(docker): Dockerfile del motor [5.2]
- [x] chore(ci): pipeline de GitHub Actions con tests [5.3]
