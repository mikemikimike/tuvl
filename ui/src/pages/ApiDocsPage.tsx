import { useState } from 'react'
import { TopBar } from '../components/TopBar'
import { API_BASE } from '../config'

type DocTab = 'swagger' | 'redoc'

function ExternalLinkIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5 shrink-0">
      <path
        fillRule="evenodd"
        d="M9 3a1 1 0 000 2h1.586L6.293 9.293a1 1 0 101.414 1.414L12 6.414V8a1 1 0 102 0V3a1 1 0 00-1-1H9z"
        clipRule="evenodd"
      />
      <path d="M4 5a2 2 0 00-2 2v5a2 2 0 002 2h5a2 2 0 002-2v-2a1 1 0 10-2 0v2H4V7h2a1 1 0 000-2H4z" />
    </svg>
  )
}

export function ApiDocsPage() {
  const [tab, setTab] = useState<DocTab>('swagger')

  // In dev (Vite proxy), these go through to localhost:8000.
  // In production they hit the same origin FastAPI app.
  const swaggerUrl = `${API_BASE}/docs`
  const redocUrl = `${API_BASE}/redoc`

  return (
    <div className="flex flex-col h-full">
      <TopBar title="API Docs" />

      {/* Sub-bar: tab switcher + external links */}
      <div className="h-10 shrink-0 bg-slate-900 border-b border-slate-800 flex items-center px-4 gap-3">
        {/* Tabs */}
        <div className="flex rounded-md border border-slate-700 overflow-hidden text-xs font-medium">
          <button
            type="button"
            onClick={() => setTab('swagger')}
            className={`px-3 py-1 transition-colors ${
              tab === 'swagger'
                ? 'bg-sky-600 text-white'
                : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
            }`}
          >
            Swagger UI
          </button>
          <button
            type="button"
            onClick={() => setTab('redoc')}
            className={`px-3 py-1 border-l border-slate-700 transition-colors ${
              tab === 'redoc'
                ? 'bg-sky-600 text-white'
                : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
            }`}
          >
            ReDoc
          </button>
        </div>

        {/* Open active in new tab */}
        <a
          href={tab === 'swagger' ? swaggerUrl : redocUrl}
          target="_blank"
          rel="noopener noreferrer"
          title={`Open ${tab === 'swagger' ? 'Swagger UI' : 'ReDoc'} in new tab`}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded border border-slate-700 text-xs text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-colors"
        >
          <ExternalLinkIcon />
          Open in new tab
        </a>

        {/* Separator + direct URL links */}
        <div className="flex items-center gap-1 ml-2 border-l border-slate-800 pl-3">
          <span className="text-xs text-slate-600 mr-1">Direct:</span>
          <a
            href={swaggerUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="px-1.5 py-0.5 rounded text-[11px] font-mono text-slate-500 hover:text-sky-400 hover:bg-slate-800 transition-colors"
            title="Open Swagger UI directly"
          >
            /docs
          </a>
          <span className="text-slate-700 text-xs">·</span>
          <a
            href={redocUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="px-1.5 py-0.5 rounded text-[11px] font-mono text-slate-500 hover:text-sky-400 hover:bg-slate-800 transition-colors"
            title="Open ReDoc directly"
          >
            /redoc
          </a>
        </div>
      </div>

      <div className="flex-1 relative">
        {/* Keep both iframes mounted so switching tabs is instant */}
        <iframe
          key="swagger"
          src={swaggerUrl}
          title="Swagger UI"
          className={`absolute inset-0 w-full h-full border-0 ${tab === 'swagger' ? '' : 'hidden'}`}
          style={{ background: '#fff' }}
        />
        <iframe
          key="redoc"
          src={redocUrl}
          title="ReDoc"
          className={`absolute inset-0 w-full h-full border-0 ${tab === 'redoc' ? '' : 'hidden'}`}
          style={{ background: '#fff' }}
        />
      </div>
    </div>
  )
}
