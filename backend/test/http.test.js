import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { fakeLlm, fakeDataAgent, call, toolTurn, reply } from './fakes.js';

process.env.NODE_ENV = 'test';
let server;
let base;
const llm = fakeLlm([]);

before(async () => {
  const { createApp } = await import('../src/app.js');
  server = createApp({ llm, dataAgent: fakeDataAgent() }).listen(0);
  await new Promise((r) => server.once('listening', r));
  base = `http://127.0.0.1:${server.address().port}/api`;
});

after(() => server?.close());

const post = (body) => fetch(`${base}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

test('POST /api/chat senza domanda: 400', async () => {
  const res = await post({ message: '   ' });
  assert.equal(res.status, 400);
  assert.equal((await res.json()).error, 'Scrivi una domanda.');
});

test('POST /api/chat: risposta, sessione e memoria tra due domande', async () => {
  llm.requests.length = 0;
  const script = [toolTurn(call('analizza_dati', 'Resi per taglia con grafico')), reply('Lardoni è primo.'), reply('Sì, Lardoni.')];
  llm.chat.completions.create = ((orig) => async (req) => {
    llm.requests.push(structuredClone(req));
    return { choices: [{ message: script.shift() }] };
  })();
  const first = await (await post({ message: 'chi ha più resi per taglia?' })).json();
  assert.match(first.sessionId, /^[0-9a-f-]{36}$/);
  assert.deepEqual(first.grafici, [{ nome: 'abcdef123456.png', url: '/api/grafici/abcdef123456.png' }]);
  const second = await (await post({ message: 'confermi?', sessionId: first.sessionId })).json();
  assert.equal(second.sessionId, first.sessionId);
  assert.equal(second.risposta, 'Sì, Lardoni.');
  const roles = llm.requests.at(-1).messages.map((m) => m.role);
  assert.deepEqual(roles, ['system', 'user', 'assistant', 'user']);
});

test('GET /api/grafici: accetta solo nomi di grafico validi', async () => {
  assert.equal((await fetch(`${base}/grafici/abcdef123456.png`)).status, 200);
  assert.equal((await fetch(`${base}/grafici/..%2F.env`)).status, 404);
});

test('GET /api/health', async () => {
  assert.deepEqual(await (await fetch(`${base}/health`)).json(), { status: 'ok', dataAgent: { stato: 'ok' } });
});

test('POST /api/chat: errore del modello restituito come JSON leggibile', async () => {
  llm.chat.completions.create = async () => {
    throw Object.assign(new Error('rate limit'), { status: 429 });
  };
  const body = await (await post({ message: 'ciao' })).json();
  assert.match(body.error, /Limite di richieste di Groq/);
});

test('POST /api/chat in streaming: passi in SSE, poi la risposta completa', async () => {
  const script = [toolTurn(call('analizza_dati', 'Resi per taglia con grafico')), reply('Lardoni è primo.')];
  llm.chat.completions.create = async () => ({ choices: [{ message: script.shift() }] });
  const res = await fetch(`${base}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ message: 'chi ha più resi per taglia?' }),
  });
  assert.match(res.headers.get('content-type'), /^text\/event-stream/);
  const { readSse } = await import('../src/services/sse.js');
  const events = [];
  await readSse(res.body, (type, data) => events.push([type, data]));
  const types = events.map(([t]) => t);
  assert.equal(types.at(-1), 'risposta');
  assert.ok(types.slice(0, -1).every((t) => t === 'passo') && types.length > 3);
  assert.deepEqual(events[0][1], { testo: 'Leggo la domanda e scelgo dove cercare' });
  const body = events.at(-1)[1];
  assert.equal(body.risposta, 'Lardoni è primo.');
  assert.deepEqual(body.grafici, [{ nome: 'abcdef123456.png', url: '/api/grafici/abcdef123456.png' }]);
});

test('POST /api/chat in streaming: errore del modello come evento leggibile', async () => {
  llm.chat.completions.create = async () => {
    throw Object.assign(new Error('rate limit'), { status: 429 });
  };
  const res = await fetch(`${base}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ message: 'ciao' }),
  });
  const { readSse } = await import('../src/services/sse.js');
  const events = [];
  await readSse(res.body, (type, data) => events.push([type, data]));
  assert.deepEqual(events.at(-1), ['errore', { error: 'Limite di richieste di Groq raggiunto: riprova tra un minuto.' }]);
});
