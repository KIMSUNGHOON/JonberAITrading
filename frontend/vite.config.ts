import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

import { detectBackendOrigin } from './src/devtools/detectBackendOrigin';

// https://vitejs.dev/config/
export default defineConfig(async ({ mode }) => {
  // Backend origin for the dev proxy, resolved in priority order:
  //   1. process env  — BACKEND_ORIGIN=http://127.0.0.1:8001 npm run dev
  //   2. .env.local   — persistent per-machine override (gitignored)
  //   3. auto-detect  — scan :8000-:8005 for OUR backend (identified by the
  //      /api/settings/trading-mode response shape; other apps squatting a
  //      port, e.g. AgentHub on :8000, are skipped). Start the backend first
  //      (backend/run_dev.py picks the first free port) so detection can see it.
  //   4. default :8000
  const fileEnv = loadEnv(mode, __dirname, 'BACKEND_ORIGIN');
  const explicit = process.env.BACKEND_ORIGIN ?? fileEnv.BACKEND_ORIGIN;
  const detected = explicit ? null : await detectBackendOrigin();
  const BACKEND_ORIGIN = explicit ?? detected ?? 'http://127.0.0.1:8000';
  const WS_ORIGIN = BACKEND_ORIGIN.replace(/^http/, 'ws');
  const source = explicit ? 'explicit' : detected ? 'auto-detected' : 'default';
  console.log(`[vite] backend proxy -> ${BACKEND_ORIGIN} (${source})`);

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5173,
      host: true, // Enable for Docker/network access
      proxy: {
        '/api': {
          target: BACKEND_ORIGIN,
          changeOrigin: true,
        },
        '/ws': {
          target: WS_ORIGIN,
          ws: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: true,
    },
  };
});
