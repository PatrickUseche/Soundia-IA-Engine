// Mantiene despiertos el motor y el API del plan gratuito de Render (se duermen tras 15 min sin trafico y despertar
// tarda de 40 s a 2 min). Un cron de Cloudflare los consulta cada 5 minutos; el cron de GitHub Actions no era fiable
// (en 4 horas no se ejecuto ni una vez).

export const TARGETS = [
  // El motor debe responder 200: /health/ consulta la base de datos, asi que tambien la mantiene viva.
  { name: 'motor', url: 'https://soundia-motor.onrender.com/health/', isOk: (status) => status === 200 },
  // El API no tiene ruta de salud: cualquier respuesta menor de 500 (incluso un 404) indica que esta despierto.
  { name: 'api', url: 'https://soundia-api-6c3t.onrender.com/', isOk: (status) => status < 500 },
];

const REQUEST_TIMEOUT_MS = 110_000; // un arranque en frio puede tardar hasta ~2 min
const DEFAULT_RETRY_DELAY_MS = 5_000;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Consulta un servicio (con un reintento) y devuelve el resultado sin lanzar nunca. */
export async function pingTarget(target, fetchImpl = fetch, { retryDelayMs = DEFAULT_RETRY_DELAY_MS } = {}) {
  const started = Date.now();
  let status = null;
  let error = null;
  let attempts = 0;
  for (; attempts < 2; ) {
    attempts += 1;
    try {
      const response = await fetchImpl(target.url, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS), redirect: 'follow' });
      status = response.status;
      error = null;
      if (target.isOk(status)) break;
    } catch (e) {
      error = String(e && e.message ? e.message : e);
    }
    if (attempts < 2) await sleep(retryDelayMs);
  }
  return { name: target.name, ok: status !== null && target.isOk(status), status, ms: Date.now() - started, attempts, ...(error ? { error } : {}) };
}

export function pingAll(fetchImpl = fetch, options = {}) {
  return Promise.all(TARGETS.map((target) => pingTarget(target, fetchImpl, options)));
}

export default {
  // Cron: se ejecuta solo, segun wrangler.toml.
  async scheduled(_event, _env, ctx) {
    ctx.waitUntil(
      pingAll().then((results) => {
        console.log(JSON.stringify({ at: new Date().toISOString(), results }));
        if (results.some((r) => !r.ok)) console.error('Algun servicio no respondio bien', JSON.stringify(results));
      }),
    );
  },
  // Abrir la URL del Worker lanza la comprobacion al momento y muestra el resultado (sirve para verificar).
  async fetch() {
    const results = await pingAll();
    return new Response(JSON.stringify({ at: new Date().toISOString(), results }, null, 2), {
      status: results.every((r) => r.ok) ? 200 : 502,
      headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
    });
  },
};
