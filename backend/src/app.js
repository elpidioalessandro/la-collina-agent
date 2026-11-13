import express from 'express';
import cors from 'cors';
import { env } from './config/env.js';
import { chatRoutes } from './routes/chat.routes.js';
import { errorHandler } from './middleware/errorHandler.js';
import { createOrchestrator } from './services/orchestrator.js';
import { createSessionStore } from './services/sessions.js';
import { createLlm } from './services/llm.js';
import { dataAgent as realDataAgent } from './services/dataAgent.js';

export function createApp({ llm, dataAgent = realDataAgent, sessions } = {}) {
  const answer = createOrchestrator({
    llm: llm || createLlm(),
    dataAgent,
    model: env.llmModel,
    maxSteps: env.maxSteps,
    reasoningEffort: env.reasoningEffort,
  });
  const app = express();
  app.use(cors({ origin: env.corsOrigin }));
  app.use(express.json({ limit: '20kb' }));
  app.use('/api', chatRoutes({ answer, sessions: sessions || createSessionStore({ ttlMinutes: env.sessionTtlMinutes }), dataAgent }));
  app.use((req, res) => res.status(404).json({ error: 'Endpoint non trovato' }));
  app.use(errorHandler);
  return app;
}
