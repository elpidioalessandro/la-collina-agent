export function fakeLlm(script) {
  const requests = [];
  return {
    requests,
    chat: {
      completions: {
        async create(req) {
          requests.push(structuredClone(req));
          const next = script.shift();
          if (!next) throw new Error('copione finito');
          if (next instanceof Error) throw next;
          return { choices: [{ message: next }] };
        },
      },
    },
  };
}

export const call = (name, domanda, id = `c-${name}`) => ({
  id,
  type: 'function',
  function: { name, arguments: JSON.stringify({ domanda }) },
});

export const toolTurn = (...calls) => ({ role: 'assistant', content: '', tool_calls: calls });
export const reply = (content) => ({ role: 'assistant', content });

export function fakeDataAgent({ down = false, streaming = false } = {}) {
  const calls = [];
  const agent = {
    calls,
    async searchManual(domanda) {
      calls.push(['cerca', domanda]);
      if (down) throw new Error('connessione rifiutata');
      return {
        risultati: [
          { codice: 'SEZ 5.5', titolo: 'Capi presi in saldo', parte: 'PARTE 5 – RESI, CAMBI E BUONI', testo: 'Anche i capi in saldo si cambiano.' },
          { codice: 'SEZ 5.3', titolo: 'Tempi del reso', parte: 'PARTE 5 – RESI, CAMBI E BUONI', testo: 'Entro 14 giorni.' },
        ],
      };
    },
    async analyze(domanda) {
      calls.push(['analizza', domanda]);
      if (down) throw new Error('connessione rifiutata');
      return {
        risposta: 'Lardoni ha il 3,3% di resi per taglia, 7,7 punti sopra la media.',
        grafici: [{ nome: 'abcdef123456.png', url: '/grafici/abcdef123456.png' }],
        passaggi: [{ strumento: 'resi' }, { strumento: 'crea_grafico' }],
        risultati_completi: 'resi: {"brand": "Lardoni", "pct_sui_venduti": 3.29}',
        nota_dati: 'Dati: 16569 righe di vendite; 164 righe duplicate scartate.',
      };
    },
    async sections(codici) {
      calls.push(['sezioni', codici.join(', ')]);
      const manuale = { 'SEZ 8.6': { codice: 'SEZ 8.6', titolo: 'Soglie di controllo dei fornitori', parte: 'PARTE 8', testo: 'Sotto il 70% l\'ordine è stato troppo alto.' } };
      return { risultati: codici.filter((c) => manuale[c]).map((c) => manuale[c]) };
    },
    async chart() {
      return new Response(new Uint8Array([137, 80, 78, 71]), { status: 200 });
    },
    async health() {
      return { stato: 'ok' };
    },
  };
  // Versione in streaming: annuncia gli strumenti dell'agente dati prima del risultato, come /analizza/stream.
  if (streaming) {
    agent.analyzeStream = async (domanda, onStep) => {
      onStep('Analizzo i resi (Lardoni)');
      onStep('Disegno il grafico');
      return agent.analyze(domanda);
    };
  }
  return agent;
}
