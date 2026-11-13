const SUGGESTIONS = [
  { tag: 'Manuale', text: 'Una cliente vuole cambiare un capo preso in saldo: si può?' },
  { tag: 'Dati', text: 'Mostrami il sell-through per brand con un grafico' },
  { tag: 'Ibrida', text: 'Perché Lardoni ha così tanti resi e cosa possiamo fare?' },
  { tag: 'Controlli', text: 'Quali regole del negozio sono state violate nei dati?' },
];

export default function Suggestions({ onPick, disabled }) {
  return (
    <div className="suggestions">
      <p className="suggestions-title">Chiedi qualcosa sul negozio, per esempio:</p>
      <div className="suggestions-grid">
        {SUGGESTIONS.map((s) => (
          <button key={s.text} className="suggestion" onClick={() => onPick(s.text)} disabled={disabled}>
            <span className="tag">{s.tag}</span>
            {s.text}
          </button>
        ))}
      </div>
    </div>
  );
}
