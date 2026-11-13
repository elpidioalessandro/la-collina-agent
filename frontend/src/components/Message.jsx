import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const TOOL_LABELS = { cerca_manuale: 'Manuale (RAG)', analizza_dati: 'Agente dati (pandas)' };

export default function Message({ message, onOpenChart }) {
  if (message.role === 'user') {
    return (
      <div className="message user">
        <div className="bubble">{message.content}</div>
      </div>
    );
  }
  if (message.error) {
    return (
      <div className="message assistant">
        <div className="bubble error">{message.content}</div>
      </div>
    );
  }
  const { grafici = [], fonti = [], strumenti = [], nota_dati: notaDati } = message;
  return (
    <div className="message assistant">
      <div className="bubble">
        <div className="markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
        </div>
        {grafici.map((g) => (
          <button key={g.nome} className="chart" onClick={() => onOpenChart(g.url)} title="Clicca per ingrandire">
            <img src={g.url} alt="Grafico generato dall'agente dati" loading="lazy" />
          </button>
        ))}
        {(fonti.length > 0 || notaDati) && (
          <div className="meta">
            {fonti.length > 0 && (
              <div className="sources">
                <span className="meta-label">Fonti dal manuale</span>
                {fonti.map((f) => (
                  <span key={f.codice} className="source" title={f.titolo}>
                    {f.codice} · {f.titolo}
                  </span>
                ))}
              </div>
            )}
            {notaDati && <p className="data-note">{notaDati}</p>}
          </div>
        )}
        {strumenti.length > 0 && (
          <details className="trace">
            <summary>Come ho risposto ({strumenti.length} {strumenti.length === 1 ? 'strumento' : 'strumenti'})</summary>
            <ol>
              {strumenti.map((s, i) => (
                <li key={i}>
                  <strong>{TOOL_LABELS[s.strumento] || s.strumento}</strong>: “{s.domanda}”
                  {s.esito && <span className="trace-result"> → {s.esito}</span>}
                  {s.errore && <span className="trace-error"> → errore: {s.errore}</span>}
                </li>
              ))}
            </ol>
          </details>
        )}
      </div>
    </div>
  );
}
