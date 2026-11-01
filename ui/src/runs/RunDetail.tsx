import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { listText } from '../devApi'
import { controlRun, followEvents, getRun, pinRun, replayFixtures, TERMINAL, type RunEvent } from '../runsApi'
import { applyDraft, dropFinished } from './steps'
import { ApprovalCard } from './ApprovalCard'
import { PausedCard } from './PausedCard'
import { RunTimeline } from './RunTimeline'
import { StatusPill } from './StatusPill'

/** The run's journal: replayed, then followed live until the run ends. */
const STATE_CHANGES = new Set([
  'approval_requested', 'approval_decided', 'paused', 'resumed', 'run_completed', 'run_failed', 'run_aborted',
])

function useEvents(runId: string): { events: RunEvent[]; drafts: Record<string, string>; error: string | null } {
  const qc = useQueryClient()
  type State = { id: string; events: RunEvent[]; drafts: Record<string, string>; error: string | null }
  const [state, setState] = useState<State>({ id: runId, events: [], drafts: {}, error: null })
  useEffect(() => {
    const ctrl = new AbortController()
    const fresh = (s: State): State => (s.id === runId ? s : { id: runId, events: [], drafts: {}, error: null })
    followEvents(runId, (e) => {
      setState((s) => {
        const cur = fresh(s)
        return { ...cur, events: [...cur.events, e], drafts: dropFinished(cur.drafts, e) }
      })
      if (STATE_CHANGES.has(e.type)) void qc.invalidateQueries({ queryKey: ['runs'] })
    }, ctrl.signal, (d) => setState((s) => {
      const cur = fresh(s)
      return { ...cur, drafts: applyDraft(cur.drafts, d) }
    }))
      .catch((err: Error) => { if (!ctrl.signal.aborted) setState((s) => ({ ...s, error: err.message })) })
    return () => ctrl.abort()
  }, [runId, qc])
  return state.id === runId ? state : { events: [], drafts: {}, error: null }
}

export function RunDetail({ runId }: { runId: string }) {
  const qc = useQueryClient()
  const run = useQuery({
    queryKey: ['runs', 'one', runId],
    queryFn: () => getRun(runId),
    refetchInterval: (q) => (q.state.data && TERMINAL.includes(q.state.data.status) ? false : 2000),
    refetchIntervalInBackground: true,
  })
  const { events, drafts, error } = useEvents(runId)
  const [steer, setSteer] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const control = useMutation({
    mutationFn: (a: { action: 'pause' | 'resume' | 'abort' | 'steer'; message?: string }) => controlRun(runId, a.action, a.message),
    onSuccess: (_, a) => { setNote(`${a.action} sent`); void qc.invalidateQueries({ queryKey: ['runs'] }) },
    onError: (e: Error) => setNote(e.message),
  })
  const [pinName, setPinName] = useState<string | null>(null)
  const [confirmAbort, setConfirmAbort] = useState(false)
  const pin = useMutation({
    mutationFn: () => pinRun(runId, pinName || undefined),
    onSuccess: (r) => { setNote(`pinned → ${r.pinned}`); setPinName(null) },
    onError: (e: Error) => setNote(e.message),
  })
  const replay = useMutation({
    mutationFn: async (workflow: string) => {
      const prefix = `fixtures/${workflow}/`
      const fixtures = (await listText('tests')).filter((f) => f.startsWith(prefix) && f.endsWith('.journal.json'))
      if (!fixtures.length) throw new Error(`no pinned fixtures for ${workflow} yet`)
      return replayFixtures(fixtures.map((f) => `tests/${f}`))
    },
    onError: (e: Error) => setNote(e.message),
  })
  const r = run.data
  if (!r) return <p className="p-6 text-sm text-slate-500">{run.error ? (run.error as Error).message : 'Loading…'}</p>
  const live = !TERMINAL.includes(r.status)
  const btn = 'px-2.5 py-1 rounded text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-40'
  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-4 py-3 border-b border-slate-800 space-y-2">
        <div className="flex items-center gap-3">
          <span className="font-mono text-slate-100">{r.workflow}</span>
          <StatusPill status={r.status} />
          {r.end && <span className="text-xs text-slate-400">END.{r.end} · {r.output?.status}</span>}
          <span className="text-xs text-slate-500">{r.tokens_used} tok</span>
          <span className="flex-1" />
          <span className="font-mono text-[11px] text-slate-500">{r.run_id}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {live && r.status !== 'paused' && <button className={btn} onClick={() => control.mutate({ action: 'pause' })}>Pause</button>}
          {r.status === 'paused' && <button className={btn} onClick={() => control.mutate({ action: 'resume' })}>Resume</button>}
          {live && !confirmAbort && <button className={`${btn} hover:bg-rose-700`} onClick={() => setConfirmAbort(true)}>Abort</button>}
          {live && confirmAbort && (
            <>
              <button className={`${btn} bg-rose-800 hover:bg-rose-700`} onClick={() => { setConfirmAbort(false); control.mutate({ action: 'abort' }) }}>Confirm abort</button>
              <button className={btn} onClick={() => setConfirmAbort(false)}>Keep running</button>
            </>
          )}
          {live && (
            <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); if (steer.trim()) { control.mutate({ action: 'steer', message: steer }); setSteer('') } }}>
              <input value={steer} onChange={(e) => setSteer(e.target.value)} placeholder="Steer the loop…" aria-label="Steer message"
                className="w-56 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs" />
              <button className={btn} type="submit">Steer</button>
            </form>
          )}
          {!live && pinName === null && <button className={btn} onClick={() => setPinName(runId.slice(0, 8))}>📌 Pin as fixture</button>}
          {!live && pinName !== null && (
            <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); pin.mutate() }}>
              <input value={pinName} onChange={(e) => setPinName(e.target.value)} aria-label="Fixture name"
                className="w-40 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs font-mono" />
              <button className={btn} type="submit" disabled={pin.isPending}>Pin</button>
              <button className={btn} type="button" onClick={() => setPinName(null)}>Cancel</button>
            </form>
          )}
          {!live && (
            <button className={btn} onClick={() => replay.mutate(r.workflow)} disabled={replay.isPending}
              title="Re-run every pinned journal of this workflow offline and compare">
              {replay.isPending ? 'Replaying…' : '▶ Replay fixtures'}
            </button>
          )}
          {note && <span className="text-xs text-slate-400">{note}</span>}
        </div>
        {r.error && <p className="text-xs text-rose-400 font-mono break-words">{r.error}</p>}
      </div>
      <div className="flex-1 min-h-0 overflow-auto px-4 py-3 space-y-4">
        {r.approval && r.approval.status === 'pending' && <ApprovalCard approval={r.approval} />}
        {r.status === 'paused' && !r.approval && (
          <PausedCard key={`${r.run_id}-${events.length}`} runId={r.run_id}
            reason={String([...events].reverse().find((e) => e.type === 'paused')?.payload.reason ?? '') || null} />
        )}
        {replay.data && (
          <ul className="rounded border border-slate-700 p-2 space-y-1 text-xs">
            {replay.data.replays.map((x) => (
              <li key={x.name}>
                <span className={x.passed ? 'text-emerald-400' : 'text-rose-400'}>{x.passed ? 'SAME' : 'DIFF'}</span>{' '}
                <span className="font-mono">{x.name.replace(/^replay-/, '').replace(/\.journal$/, '')}</span>
                {x.failures.map((f, i) => <span key={i} className="block pl-10 text-rose-300">{f}</span>)}
              </li>
            ))}
          </ul>
        )}
        <RunTimeline events={events} drafts={drafts} />
        {error && <p className="text-xs text-rose-400">{error}</p>}
        {r.output && (
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500 mb-1">Response</p>
            <pre className="text-xs font-mono bg-slate-900 border border-slate-800 rounded p-2 overflow-auto">{JSON.stringify(r.output, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  )
}
