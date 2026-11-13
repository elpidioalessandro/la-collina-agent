import { useEffect, useState } from 'react';

const PHASES = ['Sta leggendo la domanda', 'Sta consultando manuale e dati', 'Sta scrivendo la risposta'];

export default function TypingIndicator() {
  const [phase, setPhase] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setPhase((p) => Math.min(p + 1, PHASES.length - 1)), 4000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="message assistant">
      <div className="bubble typing" aria-live="polite">
        <span className="dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        {PHASES[phase]}…
      </div>
    </div>
  );
}
