const SUGGESTIONS = [
  { tag: 'Manuale', text: 'Una cliente vuole cambiare un capo preso in saldo: si può?' },
  { tag: 'Dati', text: 'Mostrami il sell-through per brand con un grafico' },
  { tag: 'Manuale + dati', text: 'Perché Lardoni ha così tanti resi e cosa possiamo fare?' },
  { tag: 'Controlli', text: 'Quali regole del negozio sono state violate nei dati?' },
];

export default function Suggestions({ onPick, disabled }) {
  return (
    <section className="intro">
      <p className="eyebrow">Assistente interno · Reparto uomo</p>
      <h2 className="display">Chiedi al negozio.</h2>
      <p className="lead">Regole del manuale e dati di vendita, con le fonti di ogni risposta.</p>
      <div className="tiles">
        {SUGGESTIONS.map((s, i) => (
          <button key={s.text} className="tile" onClick={() => onPick(s.text)} disabled={disabled}>
            <span className="tile-index">0{i + 1}</span>
            <span className="tile-tag">{s.tag}</span>
            <span className="tile-text">{s.text}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
