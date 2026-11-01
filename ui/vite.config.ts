import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Backend host the dev proxy forwards to.  Override via VITE_API_TARGET when
// the engine runs on a non-default host/port (e.g. a remote dev box).
const API_TARGET = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8885'
const proxyEntry = { target: API_TARGET, changeOrigin: true }

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss()],
  // In production the app is served from FastAPI's /insight mount.
  // In dev (pnpm dev) we serve from root so HMR works at localhost:5173/
  base: command === 'build' ? '/insight/' : '/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          if (id.includes('@xyflow')) return 'vendor-flow'
          if (id.includes('@codemirror') || id.includes('@uiw/react-codemirror')) return 'vendor-editor'
          if (id.includes('@tanstack/react-query')) return 'vendor-query'
          if (id.includes('react-dom') || id.includes('react-router-dom')) return 'vendor-react'
          if (id.includes('node_modules/react/')) return 'vendor-react'
        },
      },
    },
  },
  server: {
    // Proxy API calls to the running tuvl engine during dev.
    // Use 127.0.0.1 explicitly — on macOS 'localhost' can resolve to ::1
    // while uvicorn binds to 127.0.0.1, causing the proxy to get ECONNREFUSED.
    proxy: {
      '/dev': proxyEntry,
      '/health': proxyEntry,
      '/models/': proxyEntry,
      '/admin': proxyEntry,
      '/auth': proxyEntry,
      '/api': proxyEntry,
      '/docs': proxyEntry,
      '/redoc': proxyEntry,
      '/openapi.json': proxyEntry,
    },
  },
}))
