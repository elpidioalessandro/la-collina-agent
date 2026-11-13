import 'dotenv/config';

const required = ['GROQ_API_KEY'];
const missing = required.filter((k) => !process.env[k]);
if (missing.length && process.env.NODE_ENV !== 'test') {
  console.error(`Variabili mancanti nel .env: ${missing.join(', ')}. Copia backend/.env.example in backend/.env`);
  process.exit(1);
}

export const env = {
  port: Number(process.env.PORT) || 3001,
  groqApiKey: process.env.GROQ_API_KEY,
  llmModel: process.env.LLM_MODEL || 'openai/gpt-oss-20b',
  llmBaseUrl: process.env.LLM_BASE_URL || 'https://api.groq.com/openai/v1',
  reasoningEffort: process.env.LLM_REASONING_EFFORT || undefined,
  dataAgentUrl: (process.env.DATA_AGENT_URL || 'http://127.0.0.1:8000').replace(/\/$/, ''),
  corsOrigin: (process.env.CORS_ORIGIN || 'http://localhost:5173')
    .split(',')
    .map((s) => s.trim().replace(/\/$/, ''))
    .filter(Boolean),
  maxSteps: Number(process.env.MAX_STEPS) || 5,
  sessionTtlMinutes: Number(process.env.SESSION_TTL_MINUTES) || 120,
};
