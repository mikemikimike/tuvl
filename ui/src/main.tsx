import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'
import { getDevKey } from './config'
import { useUIStore } from './store'

// Pre-seed the dev key from the injected meta tag BEFORE React renders.
// This prevents the race condition where React Query fires with a stale/null
// key from sessionStorage before the useEffect in App.tsx can update it.
const injectedKey = getDevKey()
if (injectedKey) {
  useUIStore.getState().setDevKey(injectedKey)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
