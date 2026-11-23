import { systemPrompt, TOOLS } from '../prompts/systemPrompt.js';
import { HOW_TO_FIX, answerNumbers, citedCodes, describeProblems, findProblems, isGrounded, normalizeCitations, percentSources, removeProblems, sourceNumbers, tidy } from './verifier.js';

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

  async function runTool(call, trace, onStep) {
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
        onStep({ testo: `Cerco nel manuale: «${domanda}»` });
        const { risultati } = await dataAgent.searchManual(domanda);
        onStep({ testo: `Sezioni trovate: ${risultati.map((r) => r.codice.replace('SEZ ', '')).join(', ')}`, livello: 2 });
        for (const r of risultati) trace.sources.set(r.codice, { codice: r.codice, titolo: r.titolo });
        trace.manualTexts.push(...risultati.map((r) => r.testo));
        step.esito = risultati.map((r) => r.codice).join(', ');
        return formatSections(risultati);
      }
      if (call.function.name === 'analizza_dati') {
        onStep({ testo: `Chiedo all'agente dati: «${domanda}»` });
        const esito = dataAgent.analyzeStream
          ? await dataAgent.analyzeStream(domanda, (testo) => onStep({ testo, livello: 2 }))
          : await dataAgent.analyze(domanda);
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

  // Numeri scritti senza aver chiamato l'agente dati in questa domanda: vengono dalla memoria della conversazione,
  // cioè da un altro brand o da un altro periodo ("E Cruciverba?" con i numeri di Lardoni). Restituisce quelli sospetti.
  function numbersWithoutData(text, trace, question) {
    if (trace.steps.some((s) => s.strumento === 'analizza_dati' && !s.errore)) return [];
    const sources = sourceNumbers([...trace.manualTexts, question]);
    return [...new Set(answerNumbers(text).filter((n) => !isGrounded(n, sources)).map((n) => n.raw.trim()))];
  }

  // onStep({ testo, livello }) riceve i passi intermedi mentre l'assistente lavora: livello 1 per le scelte
  // dell'orchestratore, 2 per i dettagli (sezioni trovate, strumenti dell'agente dati).
  return async function answer(question, history = [], { onStep = () => {} } = {}) {
    const trace = { steps: [], sources: new Map(), charts: [], dataNote: null, groundTexts: [], manualTexts: [] };
    const messages = [{ role: 'system', content: systemPrompt() }, ...history, { role: 'user', content: question }];
    let text = '';
    let nudged = false;
    onStep({ testo: 'Leggo la domanda e scelgo dove cercare' });
    for (let step = 0; step < maxSteps; step++) {
      const msg = await complete(messages);
      if (msg.tool_calls?.length) {
        messages.push({ role: 'assistant', content: msg.content || '', tool_calls: msg.tool_calls });
        const results = await Promise.all(msg.tool_calls.map((c) => runTool(c, trace, onStep)));
        onStep({ testo: 'Ragiono sui risultati' });
        msg.tool_calls.forEach((c, i) => messages.push({ role: 'tool', tool_call_id: c.id, content: results[i] }));
        continue;
      }
      text = (msg.content || '').trim();
      const suspicious = text && !nudged && step < maxSteps - 1 ? numbersWithoutData(text, trace, question) : [];
      if (suspicious.length) {
        nudged = true;
        onStep({ testo: 'Ci sono numeri senza i dati di questa domanda: li chiedo all\'agente dati', livello: 2 });
        messages.push({ role: 'assistant', content: text });
        messages.push({ role: 'user', content: `CONTROLLO: la risposta contiene numeri (${suspicious.join(', ')}) senza che tu abbia `
          + 'chiamato analizza_dati per questa domanda. I numeri dei messaggi precedenti valgono per altri brand o periodi. '
          + 'Chiama analizza_dati con una domanda completa e autosufficiente, poi riscrivi la risposta con i suoi numeri.' });
        text = '';
        continue;
      }
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
    onStep({ testo: 'Controllo numeri e fonti' });
    const verified = await verify(text, { messages, trace, question, history, onStep });
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
  async function verify(draft, { messages, trace, question, history, onStep = () => {} }) {
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
    // Valgono solo le fonti di questa domanda: i numeri della conversazione precedente parlano d'altro.
    const groundTexts = [...trace.groundTexts, ...manualTexts, question];
    const context = {
      // Solo risultati grezzi degli strumenti e testo del manuale: il testo scritto dall'agente dati non fa fede.
      sources: sourceNumbers(groundTexts),
      sourceText: groundTexts.filter(Boolean).join('\n').toLowerCase(),
      percents: percentSources(groundTexts),
      knownCodes: known,
      manualRead: known.size > 0,
    };
    let problems = findProblems(text, context);
    const controllo = { esito: 'superato', problemi: [] };

    if (problems.length || read.size) {
      controllo.problemi = describeProblems(problems);
      onStep({ testo: 'Qualcosa non torna: la risposta torna al modello per la correzione', livello: 2 });
      const feedback = ['CONTROLLO DELLA RISPOSTA PRIMA DELL\'INVIO.'];
      if (problems.length) feedback.push(`Problemi trovati: ${controllo.problemi.join('; ')}.`);
      for (const p of problems) if (HOW_TO_FIX[p.tipo]) feedback.push(HOW_TO_FIX[p.tipo]);
      if (read.size) {
        feedback.push('Hai citato sezioni che non avevi letto. Eccole: attribuisci a ognuna solo quello che dice davvero, '
          + `e togli le frasi che il testo non sostiene.\n\n${formatSections([...read.values()])}`);
      }
      feedback.push('Riscrivi la risposta completa correggendo solo questi punti. Usa solo numeri presenti nei risultati '
        + 'degli strumenti, copiati senza cambiarli: un numero di resi o di casi non è una percentuale. Togli le '
        + 'frequenze ("settimanalmente", "ogni mese") e le azioni che il manuale non prevede. Non aggiungere altro.');
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
