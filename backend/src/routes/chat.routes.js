import { Router } from 'express';
import { Readable } from 'node:stream';
import { httpError } from '../middleware/errorHandler.js';
import { chatGlobal, chatPerIp } from '../middleware/rateLimit.js';

const MAX_LENGTH = 1000;

export function chatRoutes({ answer, sessions, dataAgent }) {
  const router = Router();

  router.post('/chat', chatPerIp, chatGlobal, async (req, res, next) => {
    try {
      const message = typeof req.body?.message === 'string' ? req.body.message.trim() : '';
      if (!message) throw httpError(400, 'Scrivi una domanda.');
      if (message.length > MAX_LENGTH) throw httpError(400, `Domanda troppo lunga (massimo ${MAX_LENGTH} caratteri).`);
      const session = sessions.get(req.body?.sessionId);
      const started = Date.now();
      // Le risposte possono superare il minuto: si inviano subito le intestazioni e uno spazio ogni 10 secondi,
      // così il browser (Safari chiude le richieste inattive dopo circa 60 secondi) non interrompe la connessione.
      res.status(200).type('application/json');
      res.flushHeaders();
      const heartbeat = setInterval(() => res.write(' '), 10000);
      try {
        const result = await answer(message, session.history);
        sessions.append(session.id, { role: 'user', content: message }, { role: 'assistant', content: result.risposta });
        console.log(`[chat] ${((Date.now() - started) / 1000).toFixed(1)}s · ${result.strumenti.map((s) => s.strumento).join(' + ') || 'nessuno strumento'} · "${message.slice(0, 60)}"`);
        res.end(JSON.stringify({
          sessionId: session.id,
          ...result,
          grafici: result.grafici.map((nome) => ({ nome, url: `/api/grafici/${encodeURIComponent(nome)}` })),
        }));
      } catch (err) {
        console.error(`[chat] errore dopo ${((Date.now() - started) / 1000).toFixed(1)}s:`, err.status || '', err.message);
        const text = err.status === 429 ? 'Limite di richieste di Groq raggiunto: riprova tra un minuto.' : 'Errore durante la risposta. Riprova.';
        res.end(JSON.stringify({ error: text }));
      } finally {
        clearInterval(heartbeat);
      }
    } catch (err) {
      next(err);
    }
  });

  router.delete('/chat/:sessionId', (req, res) => {
    sessions.reset(req.params.sessionId);
    res.status(204).end();
  });

  router.get('/grafici/:nome', async (req, res, next) => {
    try {
      if (!/^[0-9a-f]{12}\.png$/.test(req.params.nome)) throw httpError(404, 'Grafico non trovato');
      const upstream = await dataAgent.chart(req.params.nome);
      if (!upstream.ok) throw httpError(404, 'Grafico non trovato');
      res.type('image/png');
      Readable.fromWeb(upstream.body).pipe(res);
    } catch (err) {
      next(err);
    }
  });

  router.get('/health', async (req, res) => {
    try {
      res.json({ status: 'ok', dataAgent: await dataAgent.health() });
    } catch {
      res.status(503).json({ status: 'degraded', dataAgent: 'non raggiungibile' });
    }
  });

  return router;
}
