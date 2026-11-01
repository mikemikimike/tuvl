import { useState } from 'react'
import type { TaskStatus } from '../devApi'
import { TaskDetailPanel } from './TaskDetailPanel'

const COLUMNS: { key: TaskStatus['status']; label: string }[] = [
  { key: 'todo', label: 'To do' },
  { key: 'in_progress', label: 'In progress' },
  { key: 'implemented', label: 'Implemented' },
  { key: 'tested', label: 'Tested' },
  { key: 'done', label: 'Done' },
]

function Card({ task, onOpen }: { task: TaskStatus; onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      title={task.reasons.join('\n') || 'Show the task in detail'}
      className="w-full text-left rounded border border-slate-700 bg-slate-800/70 hover:border-slate-500 p-2 space-y-1"
    >
      <div className="flex items-center gap-1.5 text-[11px]">
        <span className="font-mono text-slate-400">{task.id}</span>
        <span className="uppercase tracking-wide text-slate-500">{task.type}</span>
        <span className="flex-1" />
        {task.stale && <span className="rounded bg-amber-900/60 px-1 text-amber-300">stale</span>}
        {task.blocked && <span className="rounded bg-rose-900/60 px-1 text-rose-300">blocked</span>}
      </div>
      <p className="text-xs text-slate-100 leading-snug">{task.title}</p>
      {task.reasons[0] && <p className="text-[11px] text-slate-400 leading-snug line-clamp-2">{task.reasons[0]}</p>}
    </button>
  )
}

/** Derived statuses only: cards move when the project changes, never by hand. */
export function TaskBoard({ spec, tasks }: { spec: string; tasks: TaskStatus[] }) {
  const [open, setOpen] = useState<string | null>(null)
  const current = tasks.find((t) => t.id === open)
  const live = tasks.filter((t) => !t.obsolete)
  const other = live.filter((t) => t.status === 'untracked')
  const obsolete = tasks.filter((t) => t.obsolete)
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-5 gap-2">
        {COLUMNS.map((c) => {
          const cards = live.filter((t) => t.status === c.key)
          return (
            <div key={c.key} className="min-w-0">
              <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">{c.label} <span className="text-slate-600">{cards.length}</span></p>
              <div className="space-y-1.5">{cards.map((t) => <Card key={t.id} task={t} onOpen={() => setOpen(t.id)} />)}</div>
            </div>
          )
        })}
      </div>
      {other.length > 0 && <p className="text-xs text-slate-500">Untracked: {other.map((t) => `${t.id} ${t.title}`).join(' · ')}</p>}
      {obsolete.length > 0 && <p className="text-xs text-slate-600">Obsolete (remove by hand): {obsolete.map((t) => t.id).join(', ')}</p>}
      {current && <TaskDetailPanel spec={spec} task={current} onClose={() => setOpen(null)} />}
    </div>
  )
}
