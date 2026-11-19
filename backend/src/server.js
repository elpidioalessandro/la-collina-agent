import { createApp } from './app.js';
import { env } from './config/env.js';
import { log } from './services/log.js';

createApp().listen(env.port, (err) => {
  if (err) {
    if (err.code === 'EADDRINUSE') {
      console.error(`Porta ${env.port} già occupata. Chiudi l'altro server: lsof -ti :${env.port} | xargs kill`);
    } else {
      console.error('Avvio fallito:', err.message);
    }
    process.exit(1);
  }
  log.info('back end avviato', { url: `http://localhost:${env.port}`, modello: env.llmModel, agente_dati: env.dataAgentUrl });
});
