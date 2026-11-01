import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { TopBar } from '../components/TopBar'
import { approveSpec, deriveTasks, listText, newSpec, rejectSpec, reopenSpec, specCheck, specDiff, specLifecycle, specStatus, specVerify } from '../devApi'
import type { SpecCheck, SpecLifecycle, TaskStatus } from '../devApi'
import { PipelineStrip, StatusBadge } from '../specs/LifecycleViews'
import { FindingsView } from '../specs/FindingsView'
import { TaskBoard } from '../specs/TaskBoard'
import { TaskGraph } from '../specs/TaskGraph'
import { BranchesView } from '../specs/BranchesView'
import { TraceView } from '../specs/TraceView'
import { onSpecSaved, openSpecEditor, reserveSpecEditor, specEditorUrl } from '../specs/channel'

const fileName = (path: string) => path.split('/').pop() ?? path

function SpecIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="8" y1="13" x2="16" y2="13" />
      <line x1="8" y1="17" x2="13" y2="17" />
    </svg>
  )
}

function SpecTile({ name, tasks, stale, check, life, selected, onSelect }: {
  name: string
  life: SpecLifecycle | undefined
  tasks: TaskStatus[] | undefined
  stale: number
  check: SpecCheck | undefined
  selected: boolean
  onSelect: () => void
}) {
  const live = tasks?.filter((t) => !t.obsolete) ?? []
  const done = live.filter((t) => t.status === 'done').length
  const blocked = live.some((t) => t.blocked)
  return (
    <button
      onClick={onSelect}
      onDoubleClick={() => openSpecEditor(name)}
      title={`${name}\nClick: show status · Double-click: open the spec`}
      aria-pressed={selected}
      className={`relative shrink-0 w-44 rounded-lg border px-3 pt-3 pb-2 text-left transition-colors ${
        selected ? 'border-indigo-500 bg-indigo-500/10' : 'border-slate-700 bg-slate-900/60 hover:border-slate-500'
      }`}
    >
      <div className="flex items-start justify-between">
        <span className={selected ? 'text-indigo-300' : 'text-slate-400'}><SpecIcon /></span>
        <span className="flex gap-1">
          {check && check.errors > 0 && (
            <span className="rounded bg-rose-900/60 px-1 text-[10px] text-rose-300" title={`spec check: ${check.errors} blocking finding(s)`}>✗{check.errors}</span>
          )}
          {stale > 0 && <span className="h-2 w-2 rounded-full bg-amber-400" title={`${stale} stale task(s)`} />}
          {blocked && <span className="h-2 w-2 rounded-full bg-rose-400" title="blocked task(s)" />}
        </span>
      </div>
      <p className="mt-2 line-clamp-2 break-words font-mono text-xs leading-snug text-slate-100">{name.replace(/\.md$/, '')}</p>
      {life?.managed && <p className="mt-1"><StatusBadge spec={life} /></p>}
      {tasks === undefined ? (
        <p className="mt-1 text-[10px] text-slate-600">…</p>
      ) : live.length === 0 ? (
        <p className="mt-1 text-[10px] text-slate-500">no task list</p>
      ) : (
        <>
          <p className="mt-1 text-[10px] text-slate-400">{done}/{live.length} done</p>
          <div className="mt-1 h-1 rounded bg-slate-800">
            <div className="h-1 rounded bg-emerald-500" style={{ width: `${(done / live.length) * 100}%` }} />
          </div>
        </>
      )}
    </button>
  )
}

export function SpecsPage() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const files = useQuery({ queryKey: ['dev', 'text', 'specs'], queryFn: () => listText('specs') })
  const specs = (files.data ?? []).filter((f) => f.endsWith('.md'))
  const chosen = params.get('spec')?.replace(/^specs\//, '') ?? null
  const selected = chosen && specs.includes(chosen) ? chosen : specs[0] ?? null
  const path = selected ? `specs/${selected}` : ''
  const [view, setView] = useState<'tasks' | 'graph' | 'branches' | 'findings' | 'trace'>(params.get('view') === 'trace' ? 'trace' : 'tasks')
  const [newName, setNewName] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // One status/diff call covers every spec: the tiles and the selected board share it.
  const status = useQuery({ queryKey: ['dev', 'specs', 'status', '*'], queryFn: () => specStatus(), enabled: specs.length > 0 })
  const diff = useQuery({ queryKey: ['dev', 'specs', 'diff', '*'], queryFn: () => specDiff(), enabled: specs.length > 0 })
  const check = useQuery({ queryKey: ['dev', 'specs', 'check', '*'], queryFn: () => specCheck(), enabled: specs.length > 0 })
  const lifecycle = useQuery({ queryKey: ['dev', 'specs', 'lifecycle'], queryFn: specLifecycle, enabled: specs.length > 0 })
  const lifeFor = (name: string) => lifecycle.data?.specs.find((s) => s.name === name)
  const [withTests, setWithTests] = useState(false)
  const verify = useQuery({
    queryKey: ['dev', 'specs', 'verify', path, withTests],
    queryFn: () => specVerify(path, withTests),
    enabled: !!selected && view === 'trace',
  })

  useEffect(() => onSpecSaved(() => { void qc.invalidateQueries({ queryKey: ['dev'] }) }), [qc])

  const select = (name: string) => {
    setWithTests(false)
    setParams((p) => { p.set('spec', name); p.delete('view'); return p }, { replace: true })
  }
  const done = async () => { await qc.invalidateQueries({ queryKey: ['dev'] }); setError(null) }
  const create = useMutation({
    mutationFn: ({ name }: { name: string; editor: Window | null }) => newSpec(name),
    onSuccess: async (r, { editor }) => {
      const created = fileName(r.created)
      setNewName(null)
      await done()
      select(created)
      if (editor) editor.location.href = specEditorUrl(created)
    },
    onError: (e: Error, { editor }) => { editor?.close(); setError(e.message) },
  })

  const [reason, setReason] = useState<string | null>(null)
  const review = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSuccess: async () => { setReason(null); await done() },
    onError: (e: Error) => setError(e.message),
  })

  const tasksFor = (name: string) => status.data?.plans.find((p) => fileName(p.spec) === name)?.tasks
  const checkFor = (name: string) => check.data?.specs.find((c) => fileName(c.path) === name)
  const staleFor = (name: string) => diff.data?.specs.find((s) => fileName(s.spec) === name)?.stale.length ?? 0
  const tasks = selected ? tasksFor(selected) : undefined
  const live = tasks?.filter((t) => !t.obsolete) ?? []
  const doneCount = live.filter((t) => t.status === 'done').length
  const stale = selected ? staleFor(selected) : 0
  const checked = selected ? checkFor(selected) : undefined
  const btn = 'px-2.5 py-1 rounded text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-40'

  return (
    <div className="flex flex-col h-full">
      <TopBar title="Specs" subtitle={selected ?? undefined} />
      <div className="border-b border-slate-800 bg-slate-900/40">
        <div className="flex gap-2 overflow-x-auto px-4 py-3" role="group" aria-label="Specs">
          {specs.map((f) => (
            <SpecTile
              key={f}
              name={f}
              tasks={status.data ? tasksFor(f) ?? [] : undefined}
              stale={staleFor(f)}
              check={checkFor(f)}
              life={lifeFor(f)}
              selected={f === selected}
              onSelect={() => select(f)}
            />
          ))}
          {newName === null ? (
            <button
              onClick={() => setNewName('')}
              className="shrink-0 w-44 rounded-lg border border-dashed border-slate-700 text-xs text-slate-400 hover:border-slate-500 hover:text-slate-200"
            >
              + New spec
            </button>
          ) : (
            <form
              className="shrink-0 w-56 rounded-lg border border-slate-700 bg-slate-900/60 p-2 flex flex-col gap-1.5"
              onSubmit={(e) => {
                e.preventDefault()
                if (newName.trim()) create.mutate({ name: newName.trim(), editor: reserveSpecEditor() })
              }}
            >
              <input autoFocus value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="refund-automation" aria-label="New spec name"
                onKeyDown={(e) => { if (e.key === 'Escape') setNewName(null) }}
                className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs font-mono" />
              <div className="flex gap-1">
                <button type="submit" className="flex-1 text-xs py-1 rounded bg-indigo-600" disabled={create.isPending}>Create</button>
                <button type="button" className="text-xs px-2 rounded bg-slate-700" onClick={() => setNewName(null)}>Cancel</button>
              </div>
            </form>
          )}
        </div>
      </div>

      {selected ? (
        <section className="flex-1 min-h-0 flex flex-col">
          <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-800 text-xs">
            <span className="font-mono text-sm text-slate-100">{selected.replace(/\.md$/, '')}</span>
            <button className={btn} onClick={() => openSpecEditor(selected)} title="Open the spec in its own window (or double-click its tile)">
              Open spec ↗
            </button>
            <span className="mx-1 h-4 w-px bg-slate-700" />
            <button className={view === 'tasks' ? `${btn} bg-slate-600` : btn} onClick={() => setView('tasks')}>Tasks</button>
            <button className={view === 'graph' ? `${btn} bg-slate-600` : btn} onClick={() => setView('graph')} title="The tasks as a dependency tree: done, running, blocked">Graph</button>
            <button className={view === 'branches' ? `${btn} bg-slate-600` : btn} onClick={() => setView('branches')} title="The git branches of this spec's work, in merge order">Branches</button>
            <button className={view === 'findings' ? `${btn} bg-slate-600` : btn} onClick={() => setView('findings')}>
              Findings{checked ? ` ${checked.errors ? `✗${checked.errors}` : '✓'}${checked.warnings ? ` !${checked.warnings}` : ''}` : ''}
            </button>
            <button className={view === 'trace' ? `${btn} bg-slate-600` : btn} onClick={() => setView('trace')}>Traceability</button>
            {lifeFor(selected)?.managed && (
              <>
                <span className="mx-1 h-4 w-px bg-slate-700" />
                {lifeFor(selected)?.effective !== 'approved' ? (
                  <button className={`${btn} bg-emerald-700 hover:bg-emerald-600`} disabled={review.isPending}
                    title="Record who, when and a hash of the body (tuvl approve spec)"
                    onClick={() => review.mutate(() => approveSpec(selected))}>Approve</button>
                ) : (
                  <>
                    <button className={btn} disabled={review.isPending} title="Write the task list from the approved spec (tuvl generate tasks)"
                      onClick={() => review.mutate(() => deriveTasks(selected))}>Derive tasks</button>
                    <button className={btn} disabled={review.isPending} title="Withdraw the approval so the spec can be edited"
                      onClick={() => review.mutate(() => reopenSpec(selected))}>Reopen</button>
                  </>
                )}
                {lifeFor(selected)?.status !== 'superseded' && reason === null && (
                  <button className={btn} disabled={review.isPending} onClick={() => setReason('')}>Send back…</button>
                )}
                {reason !== null && (
                  <form className="flex items-center gap-1" onSubmit={(e) => { e.preventDefault(); if (reason.trim()) review.mutate(() => rejectSpec(selected, reason.trim())) }}>
                    <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why does it go back to draft?" aria-label="Reason"
                      onKeyDown={(e) => { if (e.key === 'Escape') setReason(null) }}
                      className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs w-64" />
                    <button type="submit" className={btn} disabled={review.isPending || !reason.trim()}>Send back</button>
                    <button type="button" className={btn} onClick={() => setReason(null)}>Cancel</button>
                  </form>
                )}
              </>
            )}
            {live.length > 0 && <span className="text-slate-400">● {doneCount}/{live.length} done</span>}
            {stale > 0 && <span className="text-amber-400">⚠ {stale} stale</span>}
          </div>
          <div className="flex-1 min-h-0 overflow-auto px-4 py-3">
            {error && <p className="mb-2 text-xs text-rose-400">{error}</p>}
            {view === 'tasks' && lifeFor(selected)?.managed && (
              <div className="mb-3"><PipelineStrip spec={lifeFor(selected)} tasks={tasks} /></div>
            )}
            {view === 'findings' ? (
              <FindingsView check={checked} />
            ) : view === 'trace' ? (
              <TraceView verify={verify.data?.specs[0]} running={withTests && verify.isFetching}
                onRunTests={() => (withTests ? void verify.refetch() : setWithTests(true))} />
            ) : view === 'branches' ? (
              <BranchesView spec={selected} tasks={tasks} />
            ) : tasks && tasks.length > 0 ? (
              view === 'graph' ? <TaskGraph spec={selected} tasks={tasks} /> : <TaskBoard spec={selected} tasks={tasks} />
            ) : status.isFetching ? (
              <p className="text-xs text-slate-500">Deriving task status (validate, tests, lock)…</p>
            ) : (
              <p className="text-sm text-slate-500">
                No task list yet. Write the spec until <b>Findings</b> is clean and approve it (<b>Approve</b> above, or <code>tuvl approve spec</code>);
                <b>Derive tasks</b> (<code>tuvl generate tasks</code>) then writes the task list and tuvl tracks each task&apos;s status.
              </p>
            )}
          </div>
        </section>
      ) : (
        <p className="p-6 text-sm text-slate-500">{files.isLoading ? 'Loading…' : 'Create a spec to start.'}</p>
      )}
    </div>
  )
}
