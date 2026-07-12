import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Backend origin for the dev proxy, resolved in priority order:
  //   1. process env  — BACKEND_ORIGIN=http://127.0.0.1:8001 npm run dev
  //   2. .env.local   — persistent per-machine override (gitignored)
  //   3. default :8000
  // NOTE: :8000 is sometimes squatted by another app (e.g. AgentHub). If the
  // dashboard loads but every tile is empty and account queries fail, the
  // proxy is pointing at the wrong backend — set BACKEND_ORIGIN in
  // frontend/.env.local (see .env.local.example).
  const fileEnv = loadEnv(mode, __dirname, 'BACKEND_ORIGIN');
  const BACKEND_ORIGIN =
    process.env.BACKEND_ORIGIN ??
    fileEnv.BACKEND_ORIGIN ??
    'http://127.0.0.1:8000';
  const WS_ORIGIN = BACKEND_ORIGIN.replace(/^http/, 'ws');

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
