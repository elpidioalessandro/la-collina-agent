import { useEffect, useState } from 'react';

const PHASES = ['Legge la domanda', 'Consulta manuale e dati', 'Scrive la risposta'];

export default function TypingIndicator() {
  const [phase, setPhase] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setPhase((p) => Math.min(p + 1, PHASES.length - 1)), 4000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="answer typing" aria-live="polite">
      <span className="label">{PHASES[phase]}</span>
      <span className="progress" aria-hidden="true" />
    </div>
  );
}
