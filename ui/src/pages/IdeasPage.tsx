import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { TopBar } from '../components/TopBar'
import { getIdea, listIdeas } from '../devApi'
import type { IdeaSummary, IdeasMe } from '../devApi'
import { GenerateSpec } from '../specs/GenerateSpec'
import { EntityLink, StatusBadge } from '../specs/LifecycleViews'
import { UploadIdea } from '../specs/UploadIdea'

function IdeaRow({ idea, selected, onSelect }: { idea: IdeaSummary; selected: boolean; onSelect: () => void }) {
  return (
    <button
      onClick={onSelect}
      aria-pressed={selected}
      className={`w-full rounded border px-3 py-2 text-left transition-colors ${
        selected ? 'border-indigo-500 bg-indigo-500/10' : 'border-slate-700 bg-slate-900/60 hover:border-slate-500'
      }`}
    >
      <div className="flex items-center gap-2 text-[11px]">
        <span className="font-mono text-slate-300">{idea.id}</span>
        {idea.superseded_by && <span className="rounded bg-slate-800 px-1 text-slate-400">superseded</span>}
        <span className="flex-1" />
        <span className="text-slate-500">{idea.specs.length} spec{idea.specs.length === 1 ? '' : 's'}</span>
      </div>
      <p className="mt-0.5 text-sm text-slate-100 line-clamp-2">{idea.title}</p>
      <p className="text-[10px] text-slate-500">{idea.imported_at.slice(0, 10)} · {idea.files} file{idea.files === 1 ? '' : 's'}</p>
    </button>
  )
}

function IdeaDetailView({ id, me }: { id: string; me: IdeasMe }) {
  const q = useQuery({ queryKey: ['dev', 'ideas', id], queryFn: () => getIdea(id) })
  if (q.isLoading) return <p className="p-4 text-sm text-slate-500">Loading…</p>
  if (q.error || !q.data) return <p className="p-4 text-sm text-rose-400">{(q.error as Error | null)?.message ?? 'Not found'}</p>
  const idea = q.data
  return (
    <div className="space-y-4 p-4">
      <div>
        <h2 className="text-base text-slate-100">{idea.title}</h2>
        <p className="text-xs text-slate-500">
          <span className="font-mono">{idea.id}</span> · imported {idea.imported_at} by {idea.imported_by || 'unknown'}
        </p>
        <p className="mt-1 flex flex-wrap gap-3 text-xs">
          {idea.supersedes && <span className="text-slate-400">supersedes <EntityLink id={idea.supersedes} /></span>}
          {idea.superseded_by && <span className="text-amber-300">superseded by <EntityLink id={idea.superseded_by} /></span>}
        </p>
      </div>

      <section>
        <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Specs drawn from it</h3>
        {idea.specs_detail.length === 0 ? (
          <p className="text-xs text-slate-500">None yet.</p>
        ) : (
          <ul className="space-y-1">
            {idea.specs_detail.map((s) => (
              <li key={s.path} className="flex items-center gap-2 text-xs">
                <EntityLink id={s.id || s.path} />
                <StatusBadge spec={s} />
                <span className="text-slate-400">{s.title}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-2"><GenerateSpec key={idea.id} idea={idea.id} me={me} /></div>
      </section>

      <section>
        <h3 className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Files (immutable after import)</h3>
        <ul className="space-y-3">
          {idea.files_detail.map((f) => (
            <li key={f.path} className="rounded border border-slate-800">
              <div className="flex items-center gap-2 border-b border-slate-800 px-3 py-1.5 text-xs">
                <span className="font-mono text-slate-200">{f.path}</span>
                <span className="text-slate-500">{f.bytes.toLocaleString()} bytes</span>
                <span className="font-mono text-[10px] text-slate-600" title={f.sha256}>{f.sha256.slice(0, 12)}</span>
                {f.extracted && <span className="rounded bg-slate-800 px-1 text-[10px] text-slate-400">text extracted</span>}
              </div>
              {f.origin && (
                <p className="px-3 py-1 text-[11px] text-slate-400">
                  Snapshot of <span className="font-mono break-all">{f.origin.url}</span> ({f.origin.kind}), taken {f.origin.fetched_at}
                </p>
              )}
              {f.warning && <p className="px-3 py-1 text-[11px] text-amber-300">{f.warning}</p>}
              {f.preview ? (
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap px-3 py-2 text-[11px] leading-relaxed text-slate-300">
                  {f.preview}{f.truncated ? '\n[… truncated]' : ''}
                </pre>
              ) : (
                <p className="px-3 py-2 text-[11px] text-slate-600">No text preview for this file.</p>
              )}
            </li>
          ))}
        </ul>
      </section>

      <p className="text-xs text-slate-500">
        History of this idea and everything drawn from it: <Link className="text-indigo-300 hover:underline" to={`/audit?entity=${encodeURIComponent(idea.id)}`}>Audit</Link>.
      </p>
    </div>
  )
}

export function IdeasPage() {
  const [params, setParams] = useSearchParams()
  const ideas = useQuery({ queryKey: ['dev', 'ideas'], queryFn: listIdeas })
  const [uploading, setUploading] = useState(false)
  const rows = ideas.data?.ideas ?? []
  const me: IdeasMe = ideas.data?.me ?? { initials: '', agent: 'none', consent: false }
  const upload = (
    <button onClick={() => setUploading(true)} className="rounded bg-indigo-700 px-2.5 py-1 text-xs text-white hover:bg-indigo-600">
      Upload idea
    </button>
  )
  const chosen = params.get('idea')
  const selected = rows.find((i) => i.id === chosen)?.id ?? rows[0]?.id ?? null
  return (
    <div className="flex h-full flex-col">
      <TopBar title="Ideas" subtitle={selected ?? undefined} />
      {rows.length === 0 ? (
        <div className="p-6 text-sm text-slate-500">
          {ideas.isLoading ? 'Loading…' : (
            <>
              <p>No ideas yet.</p>
              <p className="mt-1 mb-3">An idea is the brief a spec is written from. Upload files or write one here (the terminal does the same: <code>tuvl import idea &lt;file-or-folder&gt;</code>).</p>
              {upload}
            </>
          )}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          <aside className="w-72 shrink-0 space-y-2 overflow-auto border-r border-slate-800 p-3" aria-label="Ideas">
            {upload}
            {rows.map((i) => (
              <IdeaRow key={i.id} idea={i} selected={i.id === selected} onSelect={() => setParams({ idea: i.id }, { replace: true })} />
            ))}
          </aside>
          <div className="min-w-0 flex-1 overflow-auto">{selected && <IdeaDetailView id={selected} me={me} />}</div>
        </div>
      )}
      {uploading && (
        <UploadIdea
          me={me}
          ideas={rows}
          onClose={() => setUploading(false)}
          onDone={(id) => { setUploading(false); setParams({ idea: id }, { replace: true }) }}
        />
      )}
    </div>
  )
}
