import { env } from '../config/env.js';

async function post(path, body, timeoutMs) {
  const res = await fetch(`${env.dataAgentUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`Agente dati: ${path} ha risposto ${res.status}`);
  return res.json();
}

export const dataAgent = {
  searchManual: (domanda, k = 4) => post('/cerca', { domanda, k }, 20000),
  analyze: (domanda) => post('/analizza', { domanda }, 120000),
  chart: (nome) => fetch(`${env.dataAgentUrl}/grafici/${encodeURIComponent(nome)}`, { signal: AbortSignal.timeout(10000) }),
  health: () => fetch(`${env.dataAgentUrl}/salute`, { signal: AbortSignal.timeout(3000) }).then((r) => r.json()),
};
