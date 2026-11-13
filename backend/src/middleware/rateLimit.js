import { rateLimit } from 'express-rate-limit';

const json = (message) => (req, res) => res.status(429).json({ error: message });

export const chatPerIp = rateLimit({
  windowMs: 60 * 1000,
  limit: Number(process.env.RATE_LIMIT_PER_MINUTE) || 10,
  standardHeaders: 'draft-8',
  legacyHeaders: false,
  handler: json('Troppe domande in poco tempo. Riprova tra un minuto.'),
});

export const chatGlobal = rateLimit({
  windowMs: 24 * 60 * 60 * 1000,
  limit: Number(process.env.RATE_LIMIT_GLOBAL_DAILY) || 300,
  keyGenerator: () => 'global',
  standardHeaders: false,
  legacyHeaders: false,
  handler: json('Limite giornaliero del servizio raggiunto. Riprova domani.'),
});
