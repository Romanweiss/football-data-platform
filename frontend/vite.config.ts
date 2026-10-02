import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Only this frontend directory can be served. Never load the repository .env.
  server: {
    host: '0.0.0.0', port: 5173, strictPort: true,
    allowedHosts: ['localhost', 'football-web'],
    fs: { strict: true, allow: [process.cwd()] },
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET || 'http://football-api:8000',
        changeOrigin: true,
        configure(proxy) {
          proxy.on('error', (_error, _request, response) => {
            // An unavailable dev upstream has the same safe 503 UX as the API.
            if ('writeHead' in response && !response.headersSent) {
              response.writeHead(503, { 'Content-Type': 'application/json' });
              response.end(JSON.stringify({ error: { code: 'clickhouse_unavailable', message: 'Data service unavailable' } }));
            }
          });
        },
      },
    },
  },
  test: { environment: 'jsdom', include: ['tests/**/*.test.{ts,tsx}'], setupFiles: ['tests/setup.ts'] },
});
