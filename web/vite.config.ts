import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `npm run dev` serves the UI on :5173 and proxies the API to the Python
// server (python -m restock, :8765). `npm run build` writes web/dist, which
// the Python server serves directly — no Node needed at runtime.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
})
