import { Link } from 'react-router-dom'
import type { SpecLifecycle, TaskStatus } from '../devApi'
import { TONE, entityLink, statusLabel } from './lifecycle'

export function StatusBadge({ spec }: { spec: SpecLifecycle }) {
  const { text, tone } = statusLabel(spec)
  const who = spec.status === 'approved' && !spec.stale && spec.approved_by ? `\nby ${spec.approved_by} · ${spec.approved_at}` : ''
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] ${TONE[tone]}`} title={`${text}${who}${spec.review_note ? `\nsent back: ${spec.review_note}` : ''}`}>
      {text}
    </span>
  )
}

/** An id that has a page in Insight links to it; anything else is plain text. */
export function EntityLink({ id, className = '' }: { id: string; className?: string }) {
  const to = entityLink(id)
  const base = `font-mono ${className}`
  return to ? (
    <Link to={to} className={`${base} text-indigo-300 hover:underline`}>{id}</Link>
  ) : (
    <span className={`${base} text-slate-300`}>{id}</span>
  )
}

function Step({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded border border-slate-700 bg-slate-900/60 px-2.5 py-1.5">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{title}</p>
      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs">{children}</div>
    </div>
  )
}

/** idea → spec → tasks, as the files say it; no action here, the commands do the work. */
export function PipelineStrip({ spec, tasks }: { spec: SpecLifecycle | undefined; tasks: TaskStatus[] | undefined }) {
  if (!spec) return null
  const live = tasks?.filter((t) => !t.obsolete) ?? []
  const done = live.filter((t) => t.status === 'done').length
  return (
    <div className="flex items-stretch gap-2 text-slate-600" aria-label="Pipeline">
      <Step title="Idea">
        {spec.ideas.length === 0 ? <span className="text-slate-500">none linked</span> : spec.ideas.map((i) => <EntityLink key={i} id={i} />)}
      </Step>
      <span className="self-center">→</span>
      <Step title="Spec">
        <span className="font-mono text-slate-200">{spec.id || spec.name}</span>
        <StatusBadge spec={spec} />
        {spec.generated_by && <span className="text-slate-500" title="the agent that drafted it">drafted by {spec.generated_by}</span>}
      </Step>
      <span className="self-center">→</span>
      <Step title="Tasks">
        {live.length === 0 ? (
          <span className="text-slate-500">{spec.effective === 'approved' ? 'run tuvl generate tasks' : 'after approval'}</span>
        ) : (
          <span className="text-slate-200">{done}/{live.length} done</span>
        )}
      </Step>
    </div>
  )
}
