# Plan para mejorar y entrenar la IA de SoundIA

Escrito el 2026-11-19, después de revisar qué datos externos existen. Es un plan, no una promesa: las licencias marcadas
como «sin confirmar» hay que verificarlas en la fuente antes de usar nada.

## Punto de partida

La IA del motor son modelos **pequeños y personales** (no hay redes grandes):

| Capa | Qué aprende | Datos que necesita | Dónde está |
|---|---|---|---|
| Valoración de transiciones | 3 pesos (armonía, tempo, energía) con «me gustó» / «no me gustó» | Valoraciones del DJ | `mixing/learning.py` |
| Modelo del estilo | Compases de solape y punto del cambio de graves | **20 mezclas buenas** del propio DJ | `mixing/style_model.py` |
| Modelo de qué pista sigue | Qué pista elige el DJ frente a la propuesta | **15 correcciones** | `mixing/next_track_model.py` |
| Recomendador con embeddings | Similitud de pistas | Muchas listas de reproducción | pendiente [4.2] |

Se entrenan en el propio motor y son baratos: **no hace falta una máquina potente** para entrenarlos. El cuello de botella es
tener datos buenos, no cómputo. Además, el análisis de audio (tempo, compás, tonalidad) es la base de todo: si el BPM o el
«1» del compás salen mal, los modelos aprenden sobre datos malos.

## Qué datos externos sirven (y cuáles no)

Resumen de la comparación (detalle y fuentes al final).

- **No existe un conjunto abierto de mezclas reales de DJs en salsa, merengue o bachata.** Lo más grande (1001Tracklists,
  ~20.000 transiciones) es de electrónica y no es un volcado descargable.
- Lo que sí se puede usar: el conjunto **Salsa** (124 pistas con tiempos anotados por expertos) para **validar el análisis**,
  **Free Music Archive** (música con licencia por pista) para pruebas y demo, y los **estudios publicados** para afinar las
  reglas de arranque.
- **No usar** el Spotify Million Playlist Dataset (uso muy restringido y ya no se descarga libremente).
- Los datos propios del DJ siguen siendo lo más valioso: el modelo está hecho para eso.

## Líneas de trabajo

### A. Validar el análisis de audio (primero: todo lo demás depende de esto)

Hoy el análisis solo se probó con audio sintético ([6.6] en `TASKS.md`).

1. Pedir acceso al conjunto Salsa (Zenodo; el audio completo es a petición y para uso académico) y confirmar sus términos.
2. Escribir `manage.py validate_beats <carpeta>`: compara el BPM, los tiempos y el primer tiempo del compás que detecta el
   motor con las anotaciones, y imprime la exactitud (tempo dentro del 4 %, tiempos dentro de la tolerancia habitual,
   compás correcto o desfasado).
3. Medir también con las pistas reales de la biblioteca del DJ: él revisa 10 a mano y se anota cuántas acierta.
4. **Criterio de éxito:** una cifra por género, anotada en este documento. Si el tempo acierta menos del 90 %, se arregla
   el análisis antes de entrenar nada.

### B. Reglas de arranque mejores (sin entrenar)

El modelo parte de las reglas y se desplaza hacia el DJ. Mientras el DJ tiene menos de 20 mezclas buenas, **las reglas son
todo lo que hay**, y es lo que se ve en una demo.

1. Reunir de los estudios publicados (ISMIR 2013, ISMIR 2020, NIME) solapes típicos y cómo suben la energía los DJs.
2. Pasar las reglas fijas a una **tabla por género** (`mixing/`), con los valores actuales como respaldo.
3. Comparar contra `recordings_report` del DJ: si sus mezclas reales se alejan de la tabla, manda lo suyo.
4. **Advertencia:** casi todos los estudios son de electrónica. Para salsa, merengue y bachata son un punto de partida a
   contrastar con el DJ, no una verdad.

### C. Reunir los datos propios (lo que activa los modelos)

El flujo ya existe (modo «Grabar mis mezclas», Grabaciones, «Buena» / «Descartar», correcciones del Auto-DJ).

1. **Meta:** 20 a 30 mezclas buenas **por género principal** y 15 a 20 correcciones. Con una sola cifra global el modelo
   mezcla estilos distintos.
2. Sesiones cortas y frecuentes mejor que una sola larga; revisar y marcar cada 5 a 10 mezclas.
3. Descargar la copia de seguridad al terminar cada sesión (`Copia-de-seguridad.bat` o «Descargar copia»).
4. Mirar `recordings_report` tras cada sesión: con unas decenas de mezclas buenas ya se ve el estilo.
5. No encender «Usar mi estilo» hasta que la evaluación gane a las reglas (ya lo exige el motor: ≥ 60 % de acierto).

### D. Música libre para pruebas y demo

1. Armar un conjunto pequeño de Free Music Archive **filtrando por licencia que permita uso comercial** (cada pista trae su
   licencia en los metadatos) y guardar la lista de pistas y licencias en el repo.
2. Usarla para la demo y para las pruebas automáticas, en vez de música con derechos.
3. Ninguna pista de FMA se asume libre sin mirar su licencia.

### E. Infraestructura para entrenar sin perder datos

1. Las mezclas, correcciones y valoraciones deben vivir en la base externa (Neon o Supabase), nunca en el disco de Render.
2. Supabase gratuito **pausa** el proyecto tras una semana sin uso y limita la base a 500 MB y el audio a 1 GB.
3. Copias de seguridad periódicas fuera de la nube (ya hay endpoint y script).
4. El recomendador con embeddings [4.2] queda para cuando haya miles de listas y cómputo; no entra en este plan.

## Orden y dependencias

1. **A** (validar el análisis) y **C** (reunir datos) pueden empezar a la vez.
2. **B** se hace con lo que arroje C.
3. **D** se hace cuando haga falta una demo o pruebas con música legal.
4. **E** va en paralelo y cierra antes de vender (cuentas de usuario, ver la Etapa B).

## Riesgos

- **Género:** los datos públicos son de electrónica; el repertorio del DJ no. Riesgo de aprender reglas que no sirven.
- **Derechos de autor:** entrenar o publicar audio ajeno puede ser un problema, sobre todo si se vende. Usar **metadatos y
  anotaciones**, no audio, salvo licencia clara.
- **Pocos datos:** con menos de 20 mezclas el modelo no se enciende; es lo esperado, no un error.
- **Análisis erróneo:** si el BPM o el compás fallan, los datos recogidos quedan contaminados (de ahí que A vaya primero).

## Datos por confirmar antes de usarlos

| Recurso | Pendiente |
|---|---|
| UnmixDB | Licencia exacta en su registro de Zenodo (el artículo es CC BY 4.0; el dato no está confirmado). Sus puntos de mezcla son sintéticos. |
| Conjunto Salsa | Términos de uso y cómo pedir el audio completo. |
| 1001Tracklists | Términos de uso; sin permiso escrito no se copia. |
| Free Music Archive | Licencia de cada pista elegida. |
| AcousticBrainz | CC0, pero el proyecto terminó y la tonalidad no es fiable; solo para contrastar. |
| Latin Music Database | Licencia y acceso; sirve para género, no para tempo. |

## Fuentes

- UnmixDB: <https://zenodo.org/record/1422385>
- Análisis de mezclas reales (ISMIR 2020): <https://archives.ismir.net/ismir2020/paper/000352.pdf>
- Regiones de transición (NIME): <https://nime.pubpub.org/pub/g7avj1a7>
- Orden y selección de pistas (ISMIR 2013): <https://archives.ismir.net/ismir2013/paper/000210.pdf>
- Conjunto Salsa: <https://zenodo.org/records/13120822> y <https://reference-global.com/article/10.5334/tismir.183>
- Free Music Archive: <https://arxiv.org/abs/1612.01840> y <https://github.com/mdeff/fma>
- AcousticBrainz: <https://acousticbrainz.org/download>
- Spotify Million Playlist Dataset (reglas): <https://aicrowd.com/challenges/spotify-million-playlist-dataset-challenge/challenge_rules>
