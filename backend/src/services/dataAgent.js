import { env } from '../config/env.js';
import { readSse } from './sse.js';

const ANALYZE_TIMEOUT_MS = 170000;

async function post(path, body, timeoutMs, headers = {}) {
  const res = await fetch(`${env.dataAgentUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`Agente dati: ${path} ha risposto ${res.status}`);
  return res;
}

// Domanda all'agente dati in streaming: onStep(testo) riceve ogni strumento scelto, la promessa il risultato.
async function analyzeStream(domanda, onStep = () => {}) {
  const res = await post('/analizza/stream', { domanda }, ANALYZE_TIMEOUT_MS, { Accept: 'text/event-stream' });
  let result;
  await readSse(res.body, (type, data) => {
    if (type === 'passo') onStep(data.testo);
    else if (type === 'risultato') result = data;
    else if (type === 'errore') throw new Error(`Agente dati: ${data.errore}`);
  });
  if (!result) throw new Error('Agente dati: stream chiuso senza risultato');
  return result;
}

export const dataAgent = {
  // 6 sezioni: con 4 una regola giusta al 5° posto restava fuori (vedi valuta_rag.py).
  searchManual: async (domanda, k = 6) => (await post('/cerca', { domanda, k }, 20000)).json(),
  analyze: async (domanda) => (await post('/analizza', { domanda }, ANALYZE_TIMEOUT_MS)).json(),
  analyzeStream,
  sections: async (codici) => (await post('/sezioni', { codici }, 10000)).json(),
  chart: (nome) => fetch(`${env.dataAgentUrl}/grafici/${encodeURIComponent(nome)}`, { signal: AbortSignal.timeout(10000) }),
  health: () => fetch(`${env.dataAgentUrl}/salute`, { signal: AbortSignal.timeout(3000) }).then((r) => r.json()),
};
