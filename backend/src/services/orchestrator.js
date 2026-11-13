import { systemPrompt, TOOLS } from '../prompts/systemPrompt.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function formatSections(risultati) {
  return risultati.map((r) => `[${r.codice}] ${r.titolo} (${r.parte})\n${r.testo}`).join('\n\n');
}

export function createOrchestrator({ llm, dataAgent, model, maxSteps = 5, reasoningEffort, waitMs = 10000 }) {
  async function complete(messages, { allowTools = true } = {}) {
    const request = { model, messages, temperature: 0, max_tokens: 2048 };
    if (allowTools) request.tools = TOOLS;
    if (reasoningEffort) request.reasoning_effort = reasoningEffort;
    for (let attempt = 0; ; attempt++) {
      try {
        return (await llm.chat.completions.create(request)).choices[0].message;
      } catch (err) {
        if (attempt >= 1) throw err;
        if (err?.status === 429) {
          await sleep(waitMs);
        } else if (err?.status === 400) {
          // Groq rifiuta la risposta se il modello chiama uno strumento inesistente: si riprova con un'indicazione
          request.messages = [...messages, { role: 'system', content: 'Usa solo gli strumenti cerca_manuale e analizza_dati, con il solo argomento "domanda".' }];
        } else {
          throw err;
        }
      }
    }
  }

  async function runTool(call, trace) {
    let args;
    try {
      args = JSON.parse(call.function.arguments || '{}');
    } catch {
      return 'ERRORE: argomenti non validi. Passa {"domanda": "..."}.';
    }
    const domanda = String(args.domanda || '').trim();
    if (!domanda) return 'ERRORE: manca la domanda.';
    const step = { strumento: call.function.name, domanda };
    trace.steps.push(step);
    try {
      if (call.function.name === 'cerca_manuale') {
        const { risultati } = await dataAgent.searchManual(domanda);
        for (const r of risultati) trace.sources.set(r.codice, { codice: r.codice, titolo: r.titolo });
        step.esito = risultati.map((r) => r.codice).join(', ');
        return formatSections(risultati);
      }
      if (call.function.name === 'analizza_dati') {
        const esito = await dataAgent.analyze(domanda);
        trace.charts.push(...(esito.grafici || []).map((g) => g.nome));
        trace.dataNote = esito.nota_dati;
        step.esito = (esito.passaggi || []).map((p) => p.strumento).join(', ');
        const grafici = esito.grafici?.length ? `\nGrafici creati e già mostrati all'utente: ${esito.grafici.length}.` : '';
        const numeri = esito.risultati_strumenti ? `\n\nRISULTATI DEGLI STRUMENTI (gli unici numeri che puoi usare):\n${esito.risultati_strumenti}` : '';
        return `RISPOSTA DELL'AGENTE DATI:\n${esito.risposta}\n\n${esito.nota_dati || ''}${grafici}${numeri}`;
      }
      return `ERRORE: lo strumento ${call.function.name} non esiste.`;
    } catch (err) {
      step.errore = err.message;
      return `ERRORE: servizio non disponibile (${err.message}). Dillo all'utente.`;
    }
  }

  return async function answer(question, history = []) {
    const trace = { steps: [], sources: new Map(), charts: [], dataNote: null };
    const messages = [{ role: 'system', content: systemPrompt() }, ...history, { role: 'user', content: question }];
    let text = '';
    for (let step = 0; step < maxSteps; step++) {
      const msg = await complete(messages);
      if (msg.tool_calls?.length) {
        messages.push({ role: 'assistant', content: msg.content || '', tool_calls: msg.tool_calls });
        const results = await Promise.all(msg.tool_calls.map((c) => runTool(c, trace)));
        msg.tool_calls.forEach((c, i) => messages.push({ role: 'tool', tool_call_id: c.id, content: results[i] }));
        continue;
      }
      text = (msg.content || '').trim();
      if (text) break;
      messages.push({ role: 'system', content: 'Rispondi ora all\'utente in modo breve, con le informazioni raccolte.' });
    }
    if (!text) {
      const final = await complete(
        [...messages, { role: 'system', content: 'Non usare altri strumenti: rispondi ora con quello che hai.' }],
        { allowTools: false },
      );
      text = (final.content || '').trim() || 'Non sono riuscito a completare la risposta. Prova a riformulare la domanda.';
    }
    const retrieved = [...trace.sources.values()];
    const plain = text.replace(/[\u00a0\u202f\u2009]/g, ' ');
    const cited = retrieved.filter((s) => plain.includes(s.codice));
    return {
      risposta: text,
      grafici: trace.charts,
      fonti: cited.length ? cited : retrieved,
      strumenti: trace.steps,
      nota_dati: trace.dataNote,
    };
  };
}
