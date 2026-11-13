import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createOrchestrator } from '../src/services/orchestrator.js';
import { fakeLlm, fakeDataAgent, call, toolTurn, reply } from './fakes.js';

const setup = (script, agentOptions) => {
  const llm = fakeLlm(script);
  const dataAgent = fakeDataAgent(agentOptions);
  const answer = createOrchestrator({ llm, dataAgent, model: 'finto', maxSteps: 3, waitMs: 0 });
  return { llm, dataAgent, answer };
};

test('domanda sul manuale: usa cerca_manuale e restituisce solo le sezioni citate', async () => {
  const { answer, dataAgent } = setup([
    toolTurn(call('cerca_manuale', 'Si può cambiare un capo preso in saldo?')),
    reply('Sì, anche i capi in saldo si cambiano [SEZ 5.5].'),
  ]);
  const out = await answer('posso cambiare una cosa presa in saldo?');
  assert.deepEqual(dataAgent.calls, [['cerca', 'Si può cambiare un capo preso in saldo?']]);
  assert.deepEqual(out.fonti, [{ codice: 'SEZ 5.5', titolo: 'Capi presi in saldo' }]);
  assert.equal(out.nota_dati, null);
});

test('domanda ibrida: due strumenti nello stesso turno, grafici e nota sui dati', async () => {
  const { answer, dataAgent, llm } = setup([
    toolTurn(call('analizza_dati', 'Resi per taglia per brand, con grafico', 'a'), call('cerca_manuale', 'Guida taglie Lardoni', 'b')),
    reply('Lardoni ha il 3,3% di resi per taglia; il manuale dice che veste piccolo [SEZ 5.3].'),
  ]);
  const out = await answer('perché Lardoni ha tanti resi?');
  assert.equal(dataAgent.calls.length, 2);
  assert.deepEqual(out.grafici, ['abcdef123456.png']);
  assert.match(out.nota_dati, /righe duplicate scartate/);
  const toolMessages = llm.requests[1].messages.filter((m) => m.role === 'tool');
  assert.deepEqual(toolMessages.map((m) => m.tool_call_id), ['a', 'b']);
});

test('la memoria della sessione arriva al modello', async () => {
  const { answer, llm } = setup([reply('Lardoni, come detto.')]);
  const history = [{ role: 'user', content: 'chi ha più resi?' }, { role: 'assistant', content: 'Lardoni.' }];
  await answer('e quindi?', history);
  const roles = llm.requests[0].messages.map((m) => m.role);
  assert.deepEqual(roles, ['system', 'user', 'assistant', 'user']);
});

test('errore 400 di Groq (strumento inesistente): riprova con un\'indicazione', async () => {
  const bad = Object.assign(new Error('tool_use_failed'), { status: 400 });
  const { answer, llm } = setup([bad, reply('Ciao!')]);
  const out = await answer('ciao');
  assert.equal(out.risposta, 'Ciao!');
  assert.match(llm.requests[1].messages.at(-1).content, /Usa solo gli strumenti/);
});

test('limite di richieste 429: attende e riprova', async () => {
  const limit = Object.assign(new Error('rate limit'), { status: 429 });
  const { answer } = setup([limit, reply('Ok.')]);
  assert.equal((await answer('ciao')).risposta, 'Ok.');
});

test('troppi passaggi: chiude con una risposta senza strumenti', async () => {
  const { answer, llm } = setup([
    toolTurn(call('cerca_manuale', 'a', '1')),
    toolTurn(call('cerca_manuale', 'b', '2')),
    toolTurn(call('cerca_manuale', 'c', '3')),
    reply('Risposta finale.'),
  ]);
  const out = await answer('domanda difficile');
  assert.equal(out.risposta, 'Risposta finale.');
  assert.equal(llm.requests.at(-1).tools, undefined);
});

test('agente dati spento: il modello riceve l\'errore e risponde comunque', async () => {
  const { answer, llm } = setup([toolTurn(call('analizza_dati', 'incasso 2025')), reply('Il servizio dati non risponde.')], { down: true });
  const out = await answer('incasso 2025?');
  assert.equal(out.risposta, 'Il servizio dati non risponde.');
  assert.match(llm.requests[1].messages.at(-1).content, /servizio non disponibile/);
  assert.equal(out.strumenti[0].errore, 'connessione rifiutata');
});

test('strumento inventato dal modello: errore restituito, nessuna chiamata ai servizi', async () => {
  const { answer, dataAgent } = setup([toolTurn(call('python', 'print(1)')), reply('Fatto.')]);
  await answer('calcola');
  assert.equal(dataAgent.calls.length, 0);
});
