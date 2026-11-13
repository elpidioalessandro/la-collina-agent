import OpenAI from 'openai';
import { env } from '../config/env.js';

export function createLlm() {
  return new OpenAI({ apiKey: env.groqApiKey, baseURL: env.llmBaseUrl, maxRetries: 1, timeout: 60000 });
}
