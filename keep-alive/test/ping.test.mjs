import test from 'node:test';
import assert from 'node:assert/strict';
import { TARGETS, pingTarget, pingAll } from '../src/index.js';

const respuesta = (status, body = '') => new Response(body, { status });

test('el motor cuenta como despierto con un 200', async () => {
  const fetchFalso = async () => respuesta(200, '{"status":"ok"}');
  const r = await pingTarget(TARGETS[0], fetchFalso, { retryDelayMs: 0 });
  assert.equal(r.ok, true);
  assert.equal(r.status, 200);
  assert.equal(r.name, TARGETS[0].name);
  assert.equal(typeof r.ms, 'number');
});

test('el motor con 503 (base de datos caida) no cuenta como sano', async () => {
  const fetchFalso = async () => respuesta(503, '{"status":"error"}');
  const r = await pingTarget(TARGETS[0], fetchFalso, { retryDelayMs: 0 });
  assert.equal(r.ok, false);
  assert.equal(r.status, 503);
});

test('el API cuenta como despierto con cualquier respuesta menor de 500, incluso un 404', async () => {
  const api = TARGETS.find((t) => t.name === 'api');
  const r = await pingTarget(api, async () => respuesta(404), { retryDelayMs: 0 });
  assert.equal(r.ok, true);
});

test('reintenta una vez si la primera peticion falla', async () => {
  let llamadas = 0;
  const fetchFalso = async () => {
    llamadas += 1;
    return llamadas === 1 ? respuesta(502) : respuesta(200);
  };
  const r = await pingTarget(TARGETS[0], fetchFalso, { retryDelayMs: 0 });
  assert.equal(llamadas, 2);
  assert.equal(r.ok, true);
  assert.equal(r.attempts, 2);
});

test('si la red falla, no lanza: devuelve ok=false con el motivo', async () => {
  const fetchFalso = async () => {
    throw new Error('sin red');
  };
  const r = await pingTarget(TARGETS[0], fetchFalso, { retryDelayMs: 0 });
  assert.equal(r.ok, false);
  assert.match(r.error, /sin red/);
});

test('consulta todos los servicios aunque uno falle', async () => {
  const fetchFalso = async (url) => (String(url).includes('motor') ? respuesta(503) : respuesta(404));
  const resultados = await pingAll(fetchFalso, { retryDelayMs: 0 });
  assert.equal(resultados.length, TARGETS.length);
  assert.equal(resultados.find((r) => r.name === 'motor').ok, false);
  assert.equal(resultados.find((r) => r.name === 'api').ok, true);
});

test('las URLs apuntan a los servicios desplegados y el motor usa /health/', () => {
  assert.match(TARGETS.find((t) => t.name === 'motor').url, /soundia-motor\.onrender\.com\/health\/$/);
  assert.match(TARGETS.find((t) => t.name === 'api').url, /soundia-api-6c3t\.onrender\.com/);
});
