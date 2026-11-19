import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const TOOL_LABELS = { cerca_manuale: 'Manuale · RAG', analizza_dati: 'Agente dati · pandas' };

// Le citazioni "[SEZ 5.5] [SEZ 5.4]" diventano un solo riferimento piccolo: "SEZ 5.5 e 5.4"
function joinSections(numbers) {
  if (numbers.length === 1) return `SEZ ${numbers[0]}`;
  return `SEZ ${numbers.slice(0, -1).join(', ')} e ${numbers.at(-1)}`;
}

function formatCitations(text) {
  return text
    .replace(/[\u00a0\u202f\u2009]/g, ' ')
    .replace(/(\d) +%/g, '$1%')
    .replace(/\(\s*((?:\[SEZ \d+\.\d+\][\s,e]*)+)\)/g, '$1')
    .replace(/(?:(?:[ \t]*,|[ \t]*&|[ \t]*\/|[ \t]+e)?[ \t]*\[SEZ \d+\.\d+\])+/g, (group) => {
      const numbers = [...new Set([...group.matchAll(/SEZ (\d+\.\d+)/g)].map((m) => m[1]))];
      return `\u2009\`${joinSections(numbers)}\``;
    });
}

// I PNG vengono cancellati dopo un giorno (GRAFICI_MAX_ORE): in una conversazione vecchia il grafico non c'è più.
function Chart({ chart, onOpen }) {
  const [missing, setMissing] = useState(false);
  if (missing) {
    return <p className="chart-missing">Grafico non più disponibile: i grafici si cancellano dopo un giorno. Rifai la domanda per rivederlo.</p>;
  }
  return (
    <button className="chart" onClick={() => onOpen(chart.url)} title="Ingrandisci">
      <img src={chart.url} alt="Grafico generato dall'agente dati" loading="lazy" onError={() => setMissing(true)} />
      <span className="chart-hint">Ingrandisci</span>
    </button>
  );
}

export default function Message({ message, onOpenChart }) {
  if (message.role === 'user') {
    return <h3 className="question">{message.content}</h3>;
  }
  if (message.error) {
    return (
      <div className="answer">
        <p className="error">{message.content}</p>
      </div>
    );
  }
  const { grafici = [], fonti = [], strumenti = [], controllo, nota_dati: notaDati } = message;
  return (
    <article className="answer">
      <div className="markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatCitations(message.content)}</ReactMarkdown>
      </div>
      {grafici.map((g) => (
        <Chart key={g.nome} chart={g} onOpen={onOpenChart} />
      ))}
      {(fonti.length > 0 || notaDati || strumenti.length > 0) && (
        <footer className="meta">
          {fonti.length > 0 && (
            <div className="meta-row">
              <span className="label">Fonti</span>
              <span className="sources">
                {fonti.map((f) => (
                  <span key={f.codice} className="source">
                    <strong>{f.codice}</strong> {f.titolo}
                  </span>
                ))}
              </span>
            </div>
          )}
          {notaDati && (
            <div className="meta-row">
              <span className="label">Dati</span>
              <span>{notaDati.replace(/^Dati:\s*/, '')}</span>
            </div>
          )}
          {strumenti.length > 0 && (
            <details className="trace">
              <summary className="label">
                Come ho risposto · {strumenti.length} {strumenti.length === 1 ? 'strumento' : 'strumenti'}
              </summary>
              <ol>
                {strumenti.map((s, i) => (
                  <li key={i}>
                    <span className="trace-tool">{TOOL_LABELS[s.strumento] || s.strumento}</span>
                    <span className="trace-question">“{s.domanda}”</span>
                    {s.esito && <span className="trace-result">→ {s.esito}</span>}
                    {s.errore && <span className="trace-error">→ errore: {s.errore}</span>}
                  </li>
                ))}
                {controllo && (
                  <li>
                    <span className="trace-tool">Controllo finale</span>
                    <span className="trace-question">numeri e fonti verificati sui risultati</span>
                    <span className="trace-result">→ {controllo.esito}</span>
                  </li>
                )}
              </ol>
            </details>
          )}
        </footer>
      )}
    </article>
  );
}
