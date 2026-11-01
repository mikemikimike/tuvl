import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { probeAgent } from '../devApi'
import type { AgentView } from '../canvas/model'

const SAMPLE: Record<string, unknown> = { str: '', int: 0, float: 0, bool: false, uuid: '00000000-0000-0000-0000-000000000000', json: {} }

/** Run this one agent with hand-entered inputs, live (replaces 1.x Lens). */
export function ProbeTab({ workflow, agent, saved }: { workflow: string; agent: AgentView; saved: boolean }) {
  const [inputs, setInputs] = useState(() =>
    JSON.stringify(Object.fromEntries(Object.entries(agent.inputs).map(([k, t]) => [k, SAMPLE[t.replace('?', '')] ?? null])), null, 2))
  const [error, setError] = useState<string | null>(null)
  const probe = useMutation({
    mutationFn: () => probeAgent(workflow, agent.id, JSON.parse(inputs) as Record<string, unknown>),
    onError: (e: Error) => setError(e.message),
    onSuccess: () => setError(null),
  })
  const r = probe.data
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-slate-400">Runs <span className="font-mono">{agent.id}</span> alone, live, with these inputs.{saved ? '' : ' Save the workflow first — the probe uses the saved version.'}</p>
      <textarea aria-label="Probe inputs" rows={Math.min(12, inputs.split('\n').length + 1)} value={inputs} onChange={(e) => setInputs(e.target.value)}
        className="w-full font-mono text-xs bg-slate-950 border border-slate-700 rounded p-2" />
      <button disabled={probe.isPending || !saved} className="px-3 py-1 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-xs"
        onClick={() => { try { JSON.parse(inputs) } catch { setError('inputs are not valid JSON'); return } probe.mutate() }}>
        {probe.isPending ? 'Running…' : '▶ Run this agent'}
      </button>
      {error && <p className="text-xs text-rose-400">{error}</p>}
      {r && (
        <div className="rounded border border-slate-700 p-2 space-y-1 text-xs">
          <p><span className={r.status === 'completed' ? 'text-emerald-400' : 'text-rose-400'}>{r.status}</span> → <span className="font-mono">{r.signal ?? '—'}</span>{r.tokens ? ` · ${r.tokens} tok` : ''}</p>
          {r.error && <p className="text-rose-300 font-mono break-words">{r.error}</p>}
          <pre className="font-mono text-[11px] bg-slate-950 rounded p-1.5 overflow-auto">{JSON.stringify(r.outputs, null, 2)}</pre>
          <Link to={`/runs?run=${r.run_id}`} className="text-indigo-300 hover:text-indigo-200">open the run →</Link>
        </div>
      )}
    </div>
  )
}
