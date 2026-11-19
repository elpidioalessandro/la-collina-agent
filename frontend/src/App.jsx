import { useEffect, useRef, useState } from 'react';
import Message from './components/Message.jsx';
import Suggestions from './components/Suggestions.jsx';
import TypingIndicator from './components/TypingIndicator.jsx';
import { resetSession, sendMessage } from './lib/api.js';
import { load, save } from './lib/storage.js';

const MAX_LENGTH = 1000;

export default function App() {
  const [state, setState] = useState(load);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [steps, setSteps] = useState([]);
  const [chart, setChart] = useState(null);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    save(state);
  }, [state]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [state.messages.length, loading, steps.length]);

  async function ask(text) {
    const question = text.trim();
    if (!question || loading) return;
    setInput('');
    setLoading(true);
    setSteps([]);
    setState((s) => ({ ...s, messages: [...s.messages, { role: 'user', content: question }] }));
    try {
      const r = await sendMessage(question, state.sessionId, (step) => setSteps((prev) => [...prev, step]));
      setState((s) => ({
        sessionId: r.sessionId,
        messages: [
          ...s.messages,
          { role: 'assistant', content: r.risposta, grafici: r.grafici, fonti: r.fonti, strumenti: r.strumenti, controllo: r.controllo, nota_dati: r.nota_dati },
        ],
      }));
    } catch (err) {
      setState((s) => ({ ...s, messages: [...s.messages, { role: 'assistant', error: true, content: err.message }] }));
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  function newChat() {
    resetSession(state.sessionId);
    setState({ sessionId: null, messages: [] });
    setInput('');
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      ask(input);
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <span className="wordmark">La Collina</span>
        <nav>
          <span className="nav-item">Assistente interno</span>
          {state.messages.length > 0 && (
            <button className="nav-item link" onClick={newChat} disabled={loading}>
              Nuova conversazione
            </button>
          )}
        </nav>
      </header>

      <main className="chat">
        {state.messages.length === 0 && <Suggestions onPick={ask} disabled={loading} />}
        {state.messages.map((m, i) => (
          <Message key={i} message={m} onOpenChart={setChart} />
        ))}
        {loading && <TypingIndicator steps={steps} />}
        <div ref={endRef} />
      </main>

      <div className="composer-wrap">
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            ask(input);
          }}
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value.slice(0, MAX_LENGTH))}
            onKeyDown={onKeyDown}
            placeholder="Scrivi una domanda sul negozio…"
            rows={1}
            disabled={loading}
            autoFocus
          />
          <button type="submit" disabled={loading || !input.trim()}>
            Invia
          </button>
        </form>
        <p className="footnote">Negozio, brand e dati sono di fantasia · Invio per inviare, Maiusc+Invio per andare a capo</p>
      </div>

      {chart && (
        <div className="lightbox" onClick={() => setChart(null)} role="dialog" aria-label="Grafico ingrandito">
          <img src={chart} alt="Grafico ingrandito" />
        </div>
      )}
    </div>
  );
}
