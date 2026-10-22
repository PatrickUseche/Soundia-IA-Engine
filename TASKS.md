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

- [ ] chore(db): pasar de SQLite a PostgreSQL [5.1]
- [x] chore(docker): Dockerfile del motor [5.2] (escrito pero sin probar: no hay Docker en la máquina de desarrollo)
- [x] chore(ci): pipeline de GitHub Actions con tests [5.3]

## Fase 6 — Pendiente

- [x] test(audio): investigar un mejor detector del primer tiempo (downbeat) [6.1] (sin cambio de algoritmo: la novedad de textura por posición del compás da ~25 % en cada una de las 4 posiciones en dos pistas reales, así que no discrimina, y sin una referencia de oído no se puede validar otra heurística; con confianza < 0,2 el Auto-DJ ya alinea por pulso y no por compás)
- [ ] feat(audio): analizar también el inicio de la pista (voz y punto de entrada) para elegir dónde entra la pista B [6.2]
- [ ] feat(mix): que el estilo blend (tempos igualados) use la información de voz [6.3]
- [ ] feat(audio): soportar tempo variable y analizar más de los primeros 10 minutos [6.4]
- [x] feat(ml): historial de versiones de los pesos con vuelta atrás, y una forma de reiniciar lo aprendido del momento de mezcla [6.5] (comando `manage.py learning`)
- [ ] test(audio): validar el análisis y el aprendizaje con música y valoraciones reales, no sintéticas [6.6]
- [ ] feat(audio): endpoint para fijar a mano el primer tiempo de una pista (PATCH de la rejilla, con confianza 1 y marca de que es manual), para cuando la detección no se puede fiar [6.7]
