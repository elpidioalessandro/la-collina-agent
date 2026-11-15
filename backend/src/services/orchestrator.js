import { systemPrompt, TOOLS } from '../prompts/systemPrompt.js';
import { citedCodes, describeProblems, findProblems, normalizeCitations, removeProblems, sourceNumbers, tidy } from './verifier.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Porta le citazioni alla forma [SEZ x.y] e toglie quelle di sezioni non lette in questa risposta.
export function cleanText(text, knownCodes) {
  return tidy(normalizeCitations(text).replace(/[ \t]*\[SEZ (\d+\.\d+)\]/g, (m, n) => (knownCodes.has(`SEZ ${n}`) ? m : '')));
}

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
        trace.manualTexts.push(...risultati.map((r) => r.testo));
        step.esito = risultati.map((r) => r.codice).join(', ');
        return formatSections(risultati);
      }
      if (call.function.name === 'analizza_dati') {
        const esito = await dataAgent.analyze(domanda);
        trace.charts.push(...(esito.grafici || []).map((g) => g.nome));
        trace.dataNote = esito.nota_dati;
        trace.groundTexts.push(esito.risultati_completi ?? esito.risultati_strumenti ?? '', esito.nota_dati || '');
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
    const trace = { steps: [], sources: new Map(), charts: [], dataNote: null, groundTexts: [], manualTexts: [] };
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
    const verified = await verify(text, { messages, trace, question, history });
    return {
      risposta: verified.text,
      grafici: trace.charts,
      fonti: verified.fonti,
      strumenti: trace.steps,
      controllo: verified.controllo,
      nota_dati: trace.dataNote,
    };
  };

  // Controllo finale: numeri, sezioni e manuale vengono verificati dal codice. Se qualcosa non torna,
  // la risposta torna al modello una volta con l'elenco dei problemi; se sbaglia ancora, le parti
  // non verificate vengono tolte.
  async function verify(draft, { messages, trace, question, history }) {
    let text = normalizeCitations(draft);
    const toRead = citedCodes(text).filter((c) => !trace.sources.has(c));
    const read = new Map();
    if (toRead.length && dataAgent.sections) {
      try {
        for (const s of (await dataAgent.sections(toRead)).risultati) read.set(s.codice, s);
      } catch {
        // servizio non raggiungibile: le sezioni restano non lette e verranno tolte
      }
    }
    const known = new Set([...trace.sources.keys(), ...read.keys()]);
    const manualTexts = [...trace.manualTexts, ...[...read.values()].map((s) => s.testo)];
    const context = {
      // Solo risultati grezzi degli strumenti e testo del manuale: il testo scritto dall'agente dati non fa fede.
      sources: sourceNumbers([...trace.groundTexts, ...manualTexts, question, ...history.map((m) => m.content)]),
      knownCodes: known,
      manualRead: known.size > 0,
    };
    let problems = findProblems(text, context);
    const controllo = { esito: 'superato', problemi: [] };

    if (problems.length || read.size) {
      controllo.problemi = describeProblems(problems);
      const feedback = ['CONTROLLO DELLA RISPOSTA PRIMA DELL\'INVIO.'];
      if (problems.length) feedback.push(`Problemi trovati: ${controllo.problemi.join('; ')}.`);
      if (read.size) {
        feedback.push('Hai citato sezioni che non avevi letto. Eccole: attribuisci a ognuna solo quello che dice davvero, '
          + `e togli le frasi che il testo non sostiene.\n\n${formatSections([...read.values()])}`);
      }
      feedback.push('Riscrivi la risposta completa correggendo solo questi punti. Usa solo numeri presenti nei risultati '
        + 'degli strumenti, copiati senza cambiarli. Non aggiungere altro.');
      try {
        const fixed = await complete(
          [...messages, { role: 'assistant', content: draft }, { role: 'user', content: feedback.join('\n\n') }],
          { allowTools: false },
        );
        const candidate = normalizeCitations((fixed.content || '').trim());
        if (candidate) text = candidate;
      } catch {
        // nessuna seconda possibilità: si passa alla pulizia
      }
      problems = findProblems(text, context);
      controllo.esito = problems.length ? 'parti non verificate tolte' : 'corretta';
      if (problems.length) text = removeProblems(text, problems);
    }

    text = tidy(text.replace(/[ \t]*\[SEZ (\d+\.\d+)\]/g, (m, n) => (known.has(`SEZ ${n}`) ? m : '')));
    const all = new Map([...trace.sources, ...[...read].map(([k, v]) => [k, { codice: v.codice, titolo: v.titolo }])]);
    const fonti = citedCodes(text).filter((c) => all.has(c)).map((c) => all.get(c));
    return { text, fonti, controllo };
  }
}
