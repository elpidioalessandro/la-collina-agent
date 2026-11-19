// Mostra cosa sta facendo l'assistente, passo per passo, mentre arrivano gli eventi dal server.
export default function TypingIndicator({ steps = [] }) {
  const current = steps.at(-1);
  return (
    <div className="answer typing" aria-live="polite">
      {steps.length > 1 && (
        <ol className="steps">
          {steps.slice(0, -1).map((s, i) => (
            <li key={i} className={s.livello === 2 ? 'step sub' : 'step'}>
              {s.testo}
            </li>
          ))}
        </ol>
      )}
      <span className="label">{current ? current.testo : 'Invio la domanda'}</span>
      <span className="progress" aria-hidden="true" />
    </div>
  );
}
