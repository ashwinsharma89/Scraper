import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Builds into ../static, which app.py serves completely unchanged: GET "/" reads
// static/index.html raw, and "/static/*" is a plain StaticFiles mount over the same
// directory. base:"/static/" makes Vite emit asset URLs (/static/assets/...) that
// resolve correctly against that mount -- zero backend changes needed to adopt this.
export default defineConfig({
  plugins: [react()],
  base: '/static/',
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` proxies API calls straight to the real FastAPI backend, so the
    // exact same fetch("/api/...") calls used in the production build work unchanged
    // in local dev (`python app.py` on :8000 alongside `npm run dev` on :5173).
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
