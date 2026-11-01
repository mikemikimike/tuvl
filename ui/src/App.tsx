import { lazy, Suspense, useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { useUIStore } from './store'
import { Shell } from './components/Shell'
import { pingServer } from './api'
import { getDevKey } from './config'

const LoginPage = lazy(() => import('./pages/LoginPage').then((m) => ({ default: m.LoginPage })))
const SpecsPage = lazy(() => import('./pages/SpecsPage').then((m) => ({ default: m.SpecsPage })))
const SpecEditorWindow = lazy(() => import('./specs/SpecEditorWindow').then((m) => ({ default: m.SpecEditorWindow })))
const TaskWindow = lazy(() => import('./specs/TaskWindow').then((m) => ({ default: m.TaskWindow })))
const IdeasPage = lazy(() => import('./pages/IdeasPage').then((m) => ({ default: m.IdeasPage })))
const AuditPage = lazy(() => import('./pages/AuditPage').then((m) => ({ default: m.AuditPage })))
const RunsPage = lazy(() => import('./pages/RunsPage').then((m) => ({ default: m.RunsPage })))
const WorkflowsPage = lazy(() => import('./pages/WorkflowsPage').then((m) => ({ default: m.WorkflowsPage })))
const ModelsPage = lazy(() => import('./pages/ModelsPage').then((m) => ({ default: m.ModelsPage })))
const DatasourcesPage = lazy(() => import('./pages/DatasourcesPage').then((m) => ({ default: m.DatasourcesPage })))
const AgentModelsPage = lazy(() => import('./pages/AgentModelsPage').then((m) => ({ default: m.AgentModelsPage })))
const ApiDocsPage = lazy(() => import('./pages/ApiDocsPage').then((m) => ({ default: m.ApiDocsPage })))
const IamPage = lazy(() => import('./pages/IamPage').then((m) => ({ default: m.IamPage })))
const FederationPage = lazy(() => import('./pages/FederationPage').then((m) => ({ default: m.FederationPage })))
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const MemoryPage = lazy(() => import('./pages/MemoryPage').then((m) => ({ default: m.MemoryPage })))
const StoragePage = lazy(() => import('./pages/StoragePage').then((m) => ({ default: m.StoragePage })))
const EmbeddingsPage = lazy(() => import('./pages/EmbeddingsPage').then((m) => ({ default: m.EmbeddingsPage })))
const CollectionsPage = lazy(() => import('./pages/CollectionsPage').then((m) => ({ default: m.CollectionsPage })))
const ArtifactsPage = lazy(() => import('./pages/ArtifactsPage').then((m) => ({ default: m.ArtifactsPage })))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

export default function App() {
  const devKey = useUIStore((s) => s.devKey)
  const setDevKey = useUIStore((s) => s.setDevKey)
  const theme = useUIStore((s) => s.theme)

  // Validate the key on startup and whenever it changes.
  // The key is pre-seeded from the meta tag in main.tsx, so no race condition.
  // The key is pre-seeded from the meta tag in main.tsx, so no race condition.
  useEffect(() => {
    const injectedKey = getDevKey()
    if (injectedKey && injectedKey !== devKey) {
      setDevKey(injectedKey)
      pingServer().catch(() => setDevKey(null))
    } else if (devKey) {
      pingServer().catch(() => setDevKey(null))
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (theme === 'light') {
      document.documentElement.classList.add('light')
    } else {
      document.documentElement.classList.remove('light')
    }
  }, [theme])

  // BASE_URL is '/' in Vite dev mode and '/insight/' in production build.
  // Strip the trailing slash so BrowserRouter gets '/insight' or ''.
  const basename = import.meta.env.BASE_URL.replace(/\/$/, '')

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={basename}>
        <Suspense fallback={null}>
          {!devKey ? (
            <Routes>
              <Route path="*" element={<LoginPage />} />
            </Routes>
          ) : (
            <Routes>
              <Route path="/specs/edit/:name" element={<SpecEditorWindow />} />
              <Route path="/specs/task/:spec/:id" element={<TaskWindow />} />
              <Route element={<Shell />}>
                <Route index element={<Navigate to="/specs" replace />} />
                <Route path="/ideas" element={<IdeasPage />} />
                <Route path="/specs" element={<SpecsPage />} />
                <Route path="/audit" element={<AuditPage />} />
                <Route path="/workflows" element={<WorkflowsPage />} />
                <Route path="/runs" element={<RunsPage />} />
                <Route path="/artifacts" element={<ArtifactsPage />} />
                <Route path="/models" element={<ModelsPage />} />
                <Route path="/datasources" element={<DatasourcesPage />} />
                <Route path="/agent-models" element={<AgentModelsPage />} />
                <Route path="/embeddings" element={<EmbeddingsPage />} />
                <Route path="/collections" element={<CollectionsPage />} />
                <Route path="/storage" element={<StoragePage />} />
                <Route path="/memory" element={<MemoryPage />} />
                <Route path="/api-docs" element={<ApiDocsPage />} />
                <Route path="/iam" element={<IamPage />} />
                <Route path="/federation" element={<FederationPage />} />
                <Route path="/settings" element={<SettingsPage />} />
              </Route>
            </Routes>
          )}
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
