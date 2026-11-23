// Controllo finale della risposta, fatto dal codice e non dal modello:
// - ogni numero deve comparire nei risultati degli strumenti (o nella domanda);
// - ogni sezione citata deve esistere ed essere stata letta;
// - il manuale si nomina solo se è stato consultato;
// - frequenze e scadenze a parole ("settimanalmente", "ogni mese") devono comparire nelle fonti: il modello
//   tendeva ad aggiungerle alle azioni anche quando il manuale non le prevede;
// - un numero con il % deve essere una percentuale nei risultati, non un conteggio ("taglia: 73%" con 73 resi);
// - registrazioni, procedure e sistemi nelle azioni devono comparire nelle fonti: il modello aggiungeva
//   "registrare l'avviso nel sistema di vendita", che il manuale non prevede.

const SPACES = /[   ]/g;
const IT_NUMBER = /(?<![\p{L}\d.,])(\d{1,3}(?:[. ]\d{3})+|\d+(?:\.\d{1,2}(?!\d))?)(?:,(\d+))?(?![\p{L}\d])/gu;
const DOT_NUMBER = /-?\d+(?:\.\d+)?/g;

const sectionNumbers = (s) => [...s.matchAll(/(\d+\.\d+)/g)].map((m) => m[1]);
const asCitations = (numbers) => numbers.map((n) => ` [SEZ ${n}]`).join('');

// Porta ogni forma di citazione a [SEZ x.y]: 【SEZ 8.6】, (SEZ 8.6), (SEZ 8.6, 9.1), [SEZ 8.6, 9.1], SEZ 8.6.
// I riferimenti tra 【】 senza numero di sezione (es. 【analizza_dati】) spariscono.
export function normalizeCitations(text) {
  return text
    .replace(SPACES, ' ')
    .replace(/[ \t]*【([^】]*)】/g, (m, inner) => asCitations(sectionNumbers(inner)))
    .replace(/[ \t]*\(\s*\[?SEZ\.?\s*\d+\.\d+(?:\]?\s*(?:[,;]|e)\s*\[?(?:SEZ\.?\s*)?\d+\.\d+)*\]?\s*\)/g, (m) => asCitations(sectionNumbers(m)))
    .replace(/[ \t]*\[SEZ\.?\s*(\d+\.\d+(?:\s*[,;e]\s*\d+\.\d+)+)\]/g, (m) => asCitations(sectionNumbers(m)))
    .replace(/(?<!\[)\bSEZ\.?\s*(\d+\.\d+)(?!\d*\])/g, '[SEZ $1]')
    .replace(/\[SEZ\s+(\d+\.\d+)\]/g, '[SEZ $1]');
}

export function citedCodes(text) {
  return [...new Set([...text.matchAll(/\[SEZ (\d+\.\d+)\]/g)].map((m) => `SEZ ${m[1]}`))];
}

function parseNumbers(text) {
  const out = [];
  for (const m of text.replace(SPACES, ' ').matchAll(IT_NUMBER)) {
    const intPart = m[1].includes('.') && /^\d+\.\d{1,2}$/.test(m[1]) ? m[1] : m[1].replace(/[. ]/g, '');
    const decimals = m[2] ?? (intPart.includes('.') ? intPart.split('.')[1] : '');
    const value = Number(m[2] !== undefined ? `${intPart}.${m[2]}` : intPart);
    out.push({ raw: m[0], value, decimals: decimals.length });
  }
  return out;
}

// Numeri scritti nella risposta, esclusi i codici di sezione, i numeri degli elenchi e gli anni.
export function answerNumbers(text) {
  const plain = text
    .replace(/\[SEZ \d+\.\d+\]/g, ' ')
    .replace(/^\s*\d+[.)]\s/gm, ' ')
    .replace(/\b[A-Z]{2}\d{2}\b/g, ' ');
  return parseNumbers(plain).filter((n) => !(n.decimals === 0 && n.value >= 2000 && n.value <= 2100));
}

export function sourceNumbers(texts) {
  const values = new Set();
  for (const t of texts) {
    if (!t) continue;
    for (const n of parseNumbers(t)) values.add(n.value);
    for (const m of t.matchAll(DOT_NUMBER)) values.add(Math.abs(Number(m[0])));
  }
  return [...values];
}

// Chiavi dei risultati che contengono conteggi o euro, mai percentuali.
const COUNT_FIELD = /"(?:resi|venduti|venduti_prezzo_pieno|ricevuti|pezzi|scontrini|casi|totale_resi|righe_usate|righe_ordini_usate|righe_escluse_senza_costo|anno|[a-z_]*_euro)"\s*:\s*-?\d+(?:\.\d+)?/g;

const PERCENT = /(?<![\p{L}\d.,])(\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?(?= ?%)/gu;

// Numeri delle fonti che possono stare accanto a un %: i valori dei risultati che non sono conteggi o euro, e
// i numeri scritti con il % (nel manuale, nella domanda, nelle frasi dei risultati). Gli altri numeri del
// manuale (giorni, euro, codici) non contano.
export function percentSources(texts) {
  const values = new Set();
  for (const t of texts) {
    if (!t) continue;
    const plain = t.replace(SPACES, ' ').replace(COUNT_FIELD, ' ');
    for (const m of plain.matchAll(/":\s*(-?\d+(?:\.\d+)?)/g)) values.add(Math.abs(Number(m[1])));
    for (const n of parseNumbers([...plain.matchAll(PERCENT)].map((m) => m[0]).join(' '))) values.add(n.value);
    for (const m of plain.matchAll(/(\d+(?:\.\d+)?)(?= ?%)/g)) values.add(Number(m[1]));
  }
  return [...values];
}

// Numeri della risposta scritti con il % subito dopo.
export function answerPercents(text) {
  const plain = text.replace(SPACES, ' ').replace(/\[SEZ \d+\.\d+\]/g, ' ');
  const found = [...plain.matchAll(PERCENT)].map((m) => m[0]);
  return parseNumbers(found.join(' ')).map((n) => ({ ...n, raw: `${n.raw.trim()}%` }));
}

// Solo le forme da istruzione ("registrare", "annota"): "resi registrati" descrive i dati e resta.
const PROCEDURE = /\b(?:registrar\p{L}*|registra|annotar\p{L}*|annota|procedur\p{L}*|gestional\p{L}*|software|sistem[ai])\b/giu;
const procedureStem = (word) => {
  const w = word.toLowerCase();
  return ['registr', 'annot', 'procedur', 'gestional', 'software', 'sistem'].find((s) => w.startsWith(s)) || w;
};

export function answerProcedures(text) {
  return [...new Set([...text.matchAll(PROCEDURE)].map((m) => m[0].toLowerCase()))];
}

export function isGrounded(n, sources) {
  const tolerance = 0.5 * 10 ** -n.decimals + 1e-9;
  return sources.some((s) => Math.abs(Math.abs(s) - n.value) <= tolerance);
}

const RENEGOTIATION = /rinegozi/i;
const FREQUENCY = /\b(?:settimanal\p{L}*|mensil\p{L}*|giornalier\p{L}*|quotidian\p{L}*|trimestral\p{L}*|annual\p{L}*|ogni\s+(?:giorno|settimana|mese|anno|trimestre|sera|mattina)|tutti\s+i\s+(?:giorni|mesi)|tutte\s+le\s+settimane)\b/giu;

// "settimanalmente" e "settimanale" valgono come "settimanal": basta che la radice sia nelle fonti.
const frequencyStem = (word) => word.toLowerCase().replace(/\s+/g, ' ').replace(/mente$/, '').replace(/[aeio]$/, '');

export function answerFrequencies(text) {
  return [...new Set([...text.matchAll(FREQUENCY)].map((m) => m[0].toLowerCase().replace(/\s+/g, ' ')))];
}

export function findProblems(text, { sources, knownCodes, manualRead, sourceText = null, percents = null }) {
  const problems = [];
  const ungrounded = [...new Set(answerNumbers(text).filter((n) => !isGrounded(n, sources)).map((n) => n.raw.trim()))];
  if (ungrounded.length) problems.push({ tipo: 'numeri', valori: ungrounded });
  if (percents !== null) {
    // Solo i numeri che passano il controllo generale: gli altri sono già segnalati sopra.
    const counts = [...new Set(answerPercents(text)
      .filter((n) => isGrounded(n, sources) && !isGrounded(n, percents)).map((n) => n.raw))];
    if (counts.length) problems.push({ tipo: 'percentuali', valori: counts });
  }
  const unknown = citedCodes(text).filter((c) => !knownCodes.has(c));
  if (unknown.length) problems.push({ tipo: 'sezioni', valori: unknown });
  if (!manualRead && /\bmanual[ei]\b/i.test(text)) problems.push({ tipo: 'manuale', valori: [] });
  if (sourceText !== null) {
    const invented = answerFrequencies(text).filter((f) => !sourceText.includes(frequencyStem(f)));
    if (invented.length) problems.push({ tipo: 'frequenze', valori: invented });
    const steps = answerProcedures(text).filter((w) => !sourceText.includes(procedureStem(w)));
    if (steps.length) problems.push({ tipo: 'procedure', valori: steps });
    // Chi va segnalato per rinegoziare lo decide il calcolo delle soglie (SEZ 8.6): senza quel calcolo in questo
    // turno, una frase sulla rinegoziazione è un'ipotesi del modello. Nei test diceva "supera la soglia dell'1%"
    // confondendo i resi totali con quelli per difetto.
    if (RENEGOTIATION.test(text) && !/soglie superate|nessun brand supera/i.test(sourceText)) {
      problems.push({ tipo: 'rinegoziazione', valori: [] });
    }
  }
  return problems;
}

// Come correggere, oltre a cosa: per le percentuali il modello toglieva solo il % e lasciava "il 73 dei resi".
export const HOW_TO_FIX = {
  percentuali: 'Riscrivi quelle frasi: il conteggio va scritto come numero ("N resi", "N casi") e, se serve la quota, '
    + 'tra parentesi la percentuale del campo _pct corrispondente, per esempio "N resi (X% dei resi)" con X da pct_sui_resi.',
};

export function describeProblems(problems) {
  return problems.map((p) => {
    if (p.tipo === 'numeri') return `numeri che non compaiono nei risultati: ${p.valori.join(', ')}`;
    if (p.tipo === 'sezioni') return `sezioni inesistenti o non lette: ${p.valori.join(', ')}`;
    if (p.tipo === 'frequenze') return `frequenze che non sono né nel manuale né nei dati: ${p.valori.join(', ')}`;
    if (p.tipo === 'percentuali') return `numeri scritti come percentuale che nei risultati sono conteggi o euro: ${p.valori.join(', ')}`;
    if (p.tipo === 'procedure') return `azioni che né il manuale né i dati prevedono: ${p.valori.join(', ')}`;
    if (p.tipo === 'rinegoziazione') return 'rinegoziazione proposta senza il calcolo delle soglie dei fornitori';
    return 'il manuale è nominato senza averlo consultato';
  });
}

// Ultima difesa: toglie le frasi che contengono un numero, una percentuale, una frequenza o un'azione non
// verificati o che nominano un manuale non letto, e le citazioni di sezioni non lette.
export function removeProblems(text, problems) {
  const numbers = new Set(problems.find((p) => p.tipo === 'numeri')?.valori || []);
  const codes = new Set(problems.find((p) => p.tipo === 'sezioni')?.valori || []);
  const manual = problems.some((p) => p.tipo === 'manuale');
  const frequencies = new Set(problems.find((p) => p.tipo === 'frequenze')?.valori || []);
  const renegotiation = problems.some((p) => p.tipo === 'rinegoziazione');
  const percentages = new Set(problems.find((p) => p.tipo === 'percentuali')?.valori || []);
  const procedures = new Set(problems.find((p) => p.tipo === 'procedure')?.valori || []);
  const bad = (sentence) =>
    answerNumbers(sentence).some((n) => numbers.has(n.raw.trim()))
    || answerPercents(sentence).some((n) => percentages.has(n.raw))
    || answerProcedures(sentence).some((w) => procedures.has(w))
    || (manual && /\bmanual[ei]\b/i.test(sentence))
    || answerFrequencies(sentence).some((f) => frequencies.has(f))
    || (renegotiation && RENEGOTIATION.test(sentence));
  return text
    .replace(/[ \t]*\[SEZ (\d+\.\d+)\]/g, (m, n) => (codes.has(`SEZ ${n}`) ? '' : m))
    .split('\n')
    .map((line) => {
      if (/^\s*\|/.test(line)) return bad(line) ? null : line;
      const kept = line.split(/(?<=[.!?;])\s+/).filter((s) => !bad(s));
      if (!kept.length || /^\s*([-*]|\d+[.)])\s*$/.test(kept.join(' '))) return line.trim() ? null : line;
      return kept.join(' ');
    })
    .filter((l) => l !== null)
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export function tidy(text) {
  return text
    .replace(/\(\s*\)/g, '')
    .replace(/[ \t]*&(?=[.,;)]|$)/gm, '')
    .replace(/&\s*(?=\|)/g, '')
    .replace(/[ \t]+([.,;:])/g, '$1')
    .replace(/(\d)[ \t\u00a0\u202f\u2009]+%/g, '$1%')
    // "1 098,37 €" → "1.098,37 €": migliaia con il punto quando il numero ha i decimali con la virgola.
    .replace(/(?<![\d.,])(\d{1,3})(?:[ \u00a0\u202f\u2009](\d{3}))(?:[ \u00a0\u202f\u2009](\d{3}))?(,\d{1,2})(?!\d)/g,
      (m, a, b, c, dec) => [a, b, c].filter(Boolean).join('.') + dec)
    .replace(/^[ \t]+(?=\[SEZ)/gm, '')
    .replace(/[ \t]*\[(?:sopra|sotto|in linea)\]/gi, '') // etichette dei risultati copiate tali e quali
    .trim();
}
