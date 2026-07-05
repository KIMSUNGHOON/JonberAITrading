import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// Backend origin for the dev proxy. Defaults to :8000; override with
// BACKEND_ORIGIN when another app squats that port (e.g. run the backend on
// :8001 and start dev with `BACKEND_ORIGIN=http://127.0.0.1:8001 npm run dev`).
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? 'http://127.0.0.1:8000';
const WS_ORIGIN = BACKEND_ORIGIN.replace(/^http/, 'ws');

// https://vitejs.dev/config/
export default defineConfig({
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
});
