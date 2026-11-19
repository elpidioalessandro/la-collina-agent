import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  // Legge il .env della cartella principale solo per sapere su che porta gira il back end.
  const env = { ...loadEnv(mode, '..', ''), ...process.env };
  const backend = env.BACKEND_URL || `http://localhost:${env.BACKEND_PORT || 3001}`;
  return {
    plugins: [react()],
    server: { port: 5173, proxy: { '/api': backend } },
  };
});
