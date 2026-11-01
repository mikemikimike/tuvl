import type { RunStatus } from '../runsApi'

const STYLES: Record<string, string> = {
  queued: 'bg-slate-700 text-slate-300',
  running: 'bg-sky-900/70 text-sky-300',
  waiting_human: 'bg-amber-900/60 text-amber-300',
  waiting_approval: 'bg-amber-900/60 text-amber-300',
  paused: 'bg-violet-900/60 text-violet-300',
  completed: 'bg-emerald-900/60 text-emerald-300',
  compensated: 'bg-teal-900/60 text-teal-300',
  failed: 'bg-rose-900/60 text-rose-300',
  aborted: 'bg-rose-900/60 text-rose-300',
}

export function StatusPill({ status }: { status: RunStatus | string }) {
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${STYLES[status] ?? 'bg-slate-700 text-slate-300'}`}>
      {status.replace('_', ' ')}
    </span>
  )
}
