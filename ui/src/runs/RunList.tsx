import { useQuery } from '@tanstack/react-query'
import { listRuns } from '../runsApi'
import { StatusPill } from './StatusPill'

const STATUSES = ['', 'running', 'waiting_human', 'waiting_approval', 'paused', 'completed', 'failed', 'aborted']

function ago(iso: string | null): string {
  if (!iso) return ''
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${Math.round(s)}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return new Date(iso).toLocaleDateString()
}

export function RunList({
  workflows, workflow, status, selected, onFilter, onSelect,
}: {
  workflows: string[]
  workflow: string
  status: string
  selected: string | null
  onFilter: (f: { workflow: string; status: string }) => void
  onSelect: (id: string) => void
}) {
  const runs = useQuery({
    queryKey: ['runs', workflow, status],
    queryFn: () => listRuns({ workflow: workflow || undefined, status: status || undefined }),
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  })
  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-2 p-2 border-b border-slate-800">
        <select
          aria-label="Workflow"
          value={workflow}
          onChange={(e) => onFilter({ workflow: e.target.value, status })}
          className="flex-1 min-w-0 bg-slate-800 border border-slate-700 rounded text-xs px-1.5 py-1"
        >
          <option value="">All workflows</option>
          {workflows.map((w) => <option key={w} value={w}>{w}</option>)}
        </select>
        <select
          aria-label="Status"
          value={status}
          onChange={(e) => onFilter({ workflow, status: e.target.value })}
          className="bg-slate-800 border border-slate-700 rounded text-xs px-1.5 py-1"
        >
          {STATUSES.map((s) => <option key={s} value={s}>{s ? s.replace('_', ' ') : 'Any status'}</option>)}
        </select>
      </div>
      <ul className="flex-1 overflow-auto">
        {runs.data?.map((r) => (
          <li key={r.run_id}>
            <button
              onClick={() => onSelect(r.run_id)}
              className={`w-full text-left px-3 py-2 border-b border-slate-800/70 ${r.run_id === selected ? 'bg-slate-800' : 'hover:bg-slate-800/50'}`}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs text-slate-200 truncate flex-1">{r.workflow}</span>
                <StatusPill status={r.status} />
              </div>
              <div className="flex gap-2 text-[11px] text-slate-500 mt-0.5">
                <span className="font-mono">{r.run_id.slice(0, 8)}</span>
                {r.end && <span>END.{r.end}</span>}
                {r.tokens_used > 0 && <span>{r.tokens_used} tok</span>}
                <span className="flex-1 text-right">{ago(r.created_at)}</span>
              </div>
            </button>
          </li>
        ))}
        {runs.data?.length === 0 && <li className="p-4 text-xs text-slate-500">No runs yet. Start one above, or call a trigger.</li>}
        {runs.error && <li className="p-4 text-xs text-rose-400">{(runs.error as Error).message}</li>}
      </ul>
    </div>
  )
}
