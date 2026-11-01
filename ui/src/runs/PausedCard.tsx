import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { editRunContext, runContext } from '../devApi'
import { controlRun } from '../runsApi'

/** A paused run (breakpoint, step mode or operator): the next agent's view, editable, then continue. */
export function PausedCard({ runId, reason }: { runId: string; reason: string | null }) {
  const qc = useQueryClient()
  const ctx = useQuery({ queryKey: ['runs', 'context', runId], queryFn: () => runContext(runId) })
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const shown = draft ?? JSON.stringify(ctx.data?.view ?? {}, null, 2)
  const save = useMutation({
    mutationFn: () => editRunContext(runId, JSON.parse(shown) as Record<string, unknown>),
    onSuccess: (r) => { qc.setQueryData(['runs', 'context', runId], r); setDraft(null); setError(null) },
    onError: (e: Error) => setError(e.message),
  })
  const resume = useMutation({
    mutationFn: () => controlRun(runId, 'resume'),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['runs'] }) },
    onError: (e: Error) => setError(e.message),
  })
  const label = reason === 'breakpoint' ? '● Breakpoint' : reason === 'step' ? '⏯ Step' : '⏸ Paused'
  return (
    <div className="rounded border border-violet-700/60 bg-violet-950/30 p-3 space-y-2 text-sm">
      <p className="text-violet-200">
        {label} — before <span className="font-mono">{ctx.data?.next ?? '…'}</span>
      </p>
      <p className="text-[11px] text-slate-400">What the agent will receive (its inputs). Edit to try a different path, then continue.</p>
      <textarea aria-label="Agent input view" rows={Math.min(10, shown.split('\n').length + 1)} value={shown}
        onChange={(e) => setDraft(e.target.value)} disabled={!ctx.data?.editable}
        className="w-full font-mono text-xs bg-slate-950 border border-slate-700 rounded p-2" />
      <div className="flex gap-2">
        {draft !== null && (
          <button className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-xs" disabled={save.isPending}
            onClick={() => { try { JSON.parse(shown) } catch { setError('not valid JSON'); return } save.mutate() }}>Save context</button>
        )}
        <button className="px-3 py-1 rounded bg-violet-700 hover:bg-violet-600 text-xs" disabled={resume.isPending || draft !== null}
          title={draft !== null ? 'Save or discard the edit first' : undefined} onClick={() => resume.mutate()}>▶ Continue</button>
      </div>
      {error && <p className="text-xs text-rose-400">{error}</p>}
    </div>
  )
}
