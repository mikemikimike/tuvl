import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { specStatus } from '../devApi'
import type { TaskStatus } from '../devApi'
import { TaskDetailPanel } from './TaskDetailPanel'
import { layoutGraph } from './graphLayout'
import type { NodeState } from './graphLayout'

const W = 190
const H = 58
const GAP_X = 16
const GAP_Y = 44
const LABEL = 64

const LOOK: Record<NodeState, { label: string; box: string; mark: string }> = {
  done: { label: 'Done', box: 'border-emerald-600 bg-emerald-950/50', mark: '✓' },
  running: { label: 'Running now', box: 'border-sky-400 bg-sky-950/60 animate-pulse', mark: '●' },
  failed: { label: 'Failed', box: 'border-rose-500 bg-rose-950/50', mark: '✗' },
  blocked: { label: 'Blocked', box: 'border-rose-700 border-dashed bg-slate-900', mark: '⛔' },
  in_progress: { label: 'In progress', box: 'border-amber-500 bg-amber-950/40', mark: '◐' },
  ready: { label: 'Ready (not started)', box: 'border-slate-600 bg-slate-800/70', mark: '○' },
}

/** The dependency tree of a spec's tasks, top to bottom in execution order; tasks on one row do not depend on each other. */
export function TaskGraph({ spec, tasks }: { spec: string; tasks: TaskStatus[] }) {
  const [open, setOpen] = useState<string | null>(null)
  // what an agent is doing right now: polled without running the tests, the rest comes from the board's status
  const liveNow = useQuery({
    queryKey: ['dev', 'specs', 'status', `specs/${spec}`, 'no-tests'],
    queryFn: () => specStatus(`specs/${spec}`, false),
    refetchInterval: 3000,
  })
  const now = new Map((liveNow.data?.plans[0]?.tasks ?? []).map((t) => [t.id, t.live ?? null]))
  const { nodes, edges, levels, width } = layoutGraph(tasks.map((t) => (now.has(t.id) ? { ...t, live: now.get(t.id) } : t)))
  const at = (id: string) => nodes.find((n) => n.task.id === id)
  const x = (slot: number) => LABEL + slot * (W + GAP_X)
  const y = (level: number) => level * (H + GAP_Y)
  const current = tasks.find((t) => t.id === open)
  const counts = Object.fromEntries(Object.keys(LOOK).map((k) => [k, nodes.filter((n) => n.state === k).length]))
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-[11px] text-slate-400" aria-label="Legend">
        {(Object.keys(LOOK) as NodeState[]).map((k) => (
          <span key={k}>{LOOK[k].mark} {LOOK[k].label} <span className="text-slate-600">{counts[k]}</span></span>
        ))}
      </div>
      <div className="relative overflow-auto" data-testid="task-graph">
        <div className="relative" style={{ width: LABEL + width * (W + GAP_X) - GAP_X, height: levels * (H + GAP_Y) - GAP_Y }}>
          {Array.from({ length: levels }, (_, i) => (
            <span key={i} className="absolute text-[10px] uppercase tracking-wide text-slate-500" style={{ left: 0, top: y(i) + H / 2 - 6 }}>
              Step {i + 1}
            </span>
          ))}
          <svg className="absolute inset-0 pointer-events-none" width="100%" height="100%">
            {edges.map((e) => {
              const a = at(e.from)
              const b = at(e.to)
              if (!a || !b) return null
              const x1 = x(a.slot) + W / 2
              const y1 = y(a.level) + H
              const x2 = x(b.slot) + W / 2
              const y2 = y(b.level)
              const mid = (y1 + y2) / 2
              return (
                <path key={`${e.from}>${e.to}`} d={`M${x1},${y1} C${x1},${mid} ${x2},${mid} ${x2},${y2}`}
                  fill="none" strokeWidth={1.5} className={a.state === 'done' ? 'stroke-emerald-700' : 'stroke-slate-600'} />
              )
            })}
          </svg>
          {nodes.map((n) => (
            <button key={n.task.id} onClick={() => setOpen(n.task.id)} aria-label={`${n.task.id} ${LOOK[n.state].label}`}
              title={(n.task.failure?.summary ?? n.task.reasons.join('\n')) || LOOK[n.state].label}
              style={{ left: x(n.slot), top: y(n.level), width: W, height: H }}
              className={`absolute rounded border p-1.5 text-left overflow-hidden hover:brightness-125 ${LOOK[n.state].box}`}>
              <div className="flex items-center gap-1 text-[10px] text-slate-400">
                <span>{LOOK[n.state].mark}</span>
                <span className="font-mono truncate">{n.task.id}</span>
                <span className="flex-1" />
                <span className="uppercase">{n.task.type}</span>
              </div>
              <p className="text-[11px] leading-tight text-slate-100 line-clamp-2">{n.task.title}</p>
              {n.state === 'failed' && (n.task.failure?.summary ?? n.task.live?.finding) && (
                <p className="text-[9px] text-rose-300 truncate">{n.task.failure?.summary ?? n.task.live?.finding}</p>
              )}
              {n.state === 'blocked' && n.task.waiting_on && n.task.waiting_on.length > 0 && (
                <p className="text-[9px] text-rose-300 truncate">waits for {n.task.waiting_on.join(', ')}</p>
              )}
              {n.task.live?.state === 'running' && n.task.live.attempt && (
                <p className="text-[9px] text-sky-300">attempt {n.task.live.attempt}/{n.task.live.max_attempts}</p>
              )}
            </button>
          ))}
        </div>
      </div>
      {current && <TaskDetailPanel spec={spec} task={current} onClose={() => setOpen(null)} />}
    </div>
  )
}
