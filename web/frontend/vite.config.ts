import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  server: {
    // Development only: the pages come from Vite, the API calls go on to the backend (npm run dev:backend).
    proxy: { '/api': 'http://localhost:8040' },
  },
});
