import { createApp } from './app.js';
import { env } from './config/env.js';

createApp().listen(env.port, (err) => {
  if (err) {
    if (err.code === 'EADDRINUSE') {
      console.error(`Porta ${env.port} già occupata. Chiudi l'altro server: lsof -ti :${env.port} | xargs kill`);
    } else {
      console.error('Avvio fallito:', err.message);
    }
    process.exit(1);
  }
  console.log(`La Collina API su http://localhost:${env.port}`);
  console.log(`Modello orchestratore: ${env.llmModel} · agente dati: ${env.dataAgentUrl}`);
});
