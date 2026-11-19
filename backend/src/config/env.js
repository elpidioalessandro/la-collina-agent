import path from 'node:path';
import { fileURLToPath } from 'node:url';
import dotenv from 'dotenv';

// Un solo .env nella cartella principale, condiviso con l'agente dati. backend/.env resta letto per
// compatibilità con le installazioni precedenti; se una variabile è in tutti e due, vince quello principale.
const backendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
dotenv.config({ path: [path.join(backendDir, '..', '.env'), path.join(backendDir, '.env')], quiet: true });

const required = ['GROQ_API_KEY'];
const missing = required.filter((k) => !process.env[k]);
if (missing.length && process.env.NODE_ENV !== 'test') {
  console.error(`Variabili mancanti: ${missing.join(', ')}. Copia .env.example in .env nella cartella principale e inserisci la chiave.`);
  process.exit(1);
}

const dataAgentPort = Number(process.env.DATA_AGENT_PORT) || 8000;

export const env = {
  port: Number(process.env.BACKEND_PORT) || Number(process.env.PORT) || 3001,
  groqApiKey: process.env.GROQ_API_KEY,
  llmModel: process.env.ORCHESTRATOR_MODEL || process.env.LLM_MODEL || 'openai/gpt-oss-120b',
  llmBaseUrl: process.env.LLM_BASE_URL || 'https://api.groq.com/openai/v1',
  reasoningEffort: process.env.LLM_REASONING_EFFORT || undefined,
  dataAgentUrl: (process.env.DATA_AGENT_URL || `http://127.0.0.1:${dataAgentPort}`).replace(/\/$/, ''),
  corsOrigin: (process.env.CORS_ORIGIN || 'http://localhost:5173')
    .split(',')
    .map((s) => s.trim().replace(/\/$/, ''))
    .filter(Boolean),
  maxSteps: Number(process.env.MAX_STEPS) || 5,
  sessionTtlMinutes: Number(process.env.SESSION_TTL_MINUTES) || 120,
};
