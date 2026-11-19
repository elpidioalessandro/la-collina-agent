import { Router } from 'express';
import { Readable } from 'node:stream';
import { httpError } from '../middleware/errorHandler.js';
import { chatGlobal, chatPerIp } from '../middleware/rateLimit.js';
import { log } from '../services/log.js';
import { sseEvent } from '../services/sse.js';

const MAX_LENGTH = 1000;
const KEEPALIVE_MS = 10000;

function errorText(err) {
  return err.status === 429 ? 'Limite di richieste di Groq raggiunto: riprova tra un minuto.' : 'Errore durante la risposta. Riprova.';
}

export function chatRoutes({ answer, sessions, dataAgent }) {
  const router = Router();

  router.post('/chat', chatPerIp, chatGlobal, async (req, res, next) => {
    let session;
    let message;
    try {
      message = typeof req.body?.message === 'string' ? req.body.message.trim() : '';
      if (!message) throw httpError(400, 'Scrivi una domanda.');
      if (message.length > MAX_LENGTH) throw httpError(400, `Domanda troppo lunga (massimo ${MAX_LENGTH} caratteri).`);
      session = sessions.get(req.body?.sessionId);
    } catch (err) {
      return next(err);
    }

    // Con "Accept: text/event-stream" la risposta arriva in Server-Sent Events: un evento "passo" per ogni
    // cosa che l'assistente fa (cerca nel manuale, chiede all'agente dati, controlla), poi "risposta".
    // Senza, resta la risposta JSON unica, per chi usa l'API direttamente.
    const streaming = (req.get('accept') || '').includes('text/event-stream');
    const started = Date.now();
    res.status(200);
    if (streaming) {
      res.set({ 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no' });
    } else {
      res.type('application/json');
    }
    res.flushHeaders();
    // Un segnale ogni 10 secondi: Safari chiude le richieste ferme da circa 60 secondi, e il modello può
    // ragionare a lungo senza produrre passi. In SSE è un commento, in JSON uno spazio prima del corpo.
    const keepalive = setInterval(() => res.write(streaming ? ': in corso\n\n' : ' '), KEEPALIVE_MS);
    const send = (type, data) => {
      if (streaming && !res.writableEnded) res.write(sseEvent(type, data));
    };

    try {
      const result = await answer(message, session.history, { onStep: (step) => send('passo', step) });
      sessions.append(session.id, { role: 'user', content: message }, { role: 'assistant', content: result.risposta });
      log.info('chat', {
        durata_s: ((Date.now() - started) / 1000).toFixed(1),
        strumenti: result.strumenti.map((s) => s.strumento).join('+') || 'nessuno',
        controllo: result.controllo?.esito,
        problemi: result.controllo?.problemi?.length ? result.controllo.problemi.join('; ') : undefined,
        sessione: session.id.slice(0, 8),
        domanda: message.slice(0, 80),
      });
      const body = {
        sessionId: session.id,
        ...result,
        grafici: result.grafici.map((nome) => ({ nome, url: `/api/grafici/${encodeURIComponent(nome)}` })),
      };
      if (streaming) send('risposta', body);
      else res.write(JSON.stringify(body));
    } catch (err) {
      log.error('chat fallita', { durata_s: ((Date.now() - started) / 1000).toFixed(1), stato: err.status, errore: err.message });
      if (streaming) send('errore', { error: errorText(err) });
      else res.write(JSON.stringify({ error: errorText(err) }));
    } finally {
      clearInterval(keepalive);
      res.end();
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
