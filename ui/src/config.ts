// Base URL for all REST API calls.
// In dev (pnpm dev) Vite proxies /dev, /health etc to localhost:8000.
// When served from the engine at /insight, calls go to the same origin.
// Override at build time via VITE_API_BASE (e.g. when deploying the UI on
// a different origin from the engine).
export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

// The dev key is injected by the engine into a <meta> tag on the placeholder
// index.html when running under `tuvl dev`. We read it once at startup.
export function getDevKey(): string {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="tuvl-dev-key"]')
  return meta?.content ?? ''
}
