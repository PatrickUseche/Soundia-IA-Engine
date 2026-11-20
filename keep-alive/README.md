# Keep-alive: mantiene despiertos el motor y el API

El plan gratuito de Render duerme cada servicio tras **15 minutos sin tráfico** y despertarlo tarda de 40 s a 2 min.
Este Worker de Cloudflare los consulta **cada 5 minutos** (cron), así nadie espera durante una demo.

El cron de GitHub Actions (`.github/workflows/keep-alive.yml`) no sirve para esto: GitHub no garantiza las tareas
programadas y en 4 horas no ejecutó ninguna. Se deja solo para lanzarlo a mano.

## Qué consulta

| Servicio | URL | Se considera despierto si |
|---|---|---|
| Motor | `https://soundia-motor.onrender.com/health/` | responde `200` (comprueba también la base de datos) |
| API | `https://soundia-api-6c3t.onrender.com/` | responde menos de `500` (un `404` vale) |

Cada servicio se reintenta una vez si falla. Si cambian las URLs, se editan en `src/index.js`.

## Desplegar (una sola vez, con tu cuenta de Cloudflare)

```bash
cd keep-alive
npx wrangler login      # abre el navegador para iniciar sesión
npx wrangler deploy     # sube el Worker y registra el cron de cada 5 min
```

Después, abre la URL que imprime `deploy` (`https://soundia-keep-alive.<tu-subdominio>.workers.dev`): lanza la
comprobación al momento y muestra `ok` y los milisegundos de cada servicio. En el panel de Cloudflare
(Workers → soundia-keep-alive → Logs) se ve el resultado de cada ejecución del cron.

## Probar

```bash
npm test
```

## Límites que hay que conocer

- **750 horas gratuitas al mes en Render por cuenta.** Dos servicios encendidos las 24 h gastan unas 1488 h/mes: el
  plan se acabaría y Render suspendería los servicios hasta el mes siguiente. Conviene tener el cron activo solo en los
  días de demo y pausarlo después (`npx wrangler delete` o quitar el cron).
- Mantenerlos despiertos no evita un reinicio inesperado de Render; solo evita que se duerman por inactividad.
