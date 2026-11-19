import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createOrchestrator } from '../src/services/orchestrator.js';
import { readSse, sseEvent } from '../src/services/sse.js';
import { fakeLlm, fakeDataAgent, call, toolTurn, reply } from './fakes.js';

function streamOf(...pieces) {
  return (async function* chunks() {
    for (const p of pieces) yield new TextEncoder().encode(p);
  })();
}

test('readSse: eventi interi anche se arrivano spezzati, commenti ignorati', async () => {
  const text = `: in corso\n\n${sseEvent('passo', { testo: 'Analizzo i resi' })}${sseEvent('risultato', { risposta: 'ok' })}`;
  const events = [];
  await readSse(streamOf(text.slice(0, 7), text.slice(7, 40), text.slice(40)), (type, data) => events.push([type, data]));
  assert.deepEqual(events, [['passo', { testo: 'Analizzo i resi' }], ['risultato', { risposta: 'ok' }]]);
});

test('passi intermedi: orchestratore, manuale, agente dati e controllo, nell\'ordine', async () => {
  const llm = fakeLlm([
    toolTurn(call('cerca_manuale', 'Regole sui resi per taglia', 'c1'), call('analizza_dati', 'Resi di Lardoni per motivo', 'c2')),
    reply('Lardoni ha il 3,29% di resi per taglia [SEZ 5.5].'),
  ]);
  const answer = createOrchestrator({ llm, dataAgent: fakeDataAgent({ streaming: true }), model: 'finto', maxSteps: 3, waitMs: 0 });
  const steps = [];
  const out = await answer('Lardoni ha troppi resi?', [], { onStep: (s) => steps.push(s) });
  assert.equal(out.controllo.esito, 'superato');
  assert.deepEqual(steps, [
    { testo: 'Leggo la domanda e scelgo dove cercare' },
    { testo: 'Cerco nel manuale: «Regole sui resi per taglia»' },
    { testo: 'Chiedo all\'agente dati: «Resi di Lardoni per motivo»' },
    { testo: 'Analizzo i resi (Lardoni)', livello: 2 },
    { testo: 'Disegno il grafico', livello: 2 },
    { testo: 'Sezioni trovate: 5.5, 5.3', livello: 2 },
    { testo: 'Ragiono sui risultati' },
    { testo: 'Controllo numeri e fonti' },
  ]);
});
