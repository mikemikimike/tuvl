import { useQuery } from '@tanstack/react-query'
import { devTelemetry, teamEvents } from '../devApi'
import type { TeamEvent } from '../devApi'

/** The team's events as a list; `entity` narrows it to one idea, spec or task. */
export function TeamEventList({ entity, kind, actor, limit = 100, compact = false, hideCommands = true }: {
  entity?: string; kind?: string; actor?: string; limit?: number; compact?: boolean; hideCommands?: boolean
}) {
  const q = useQuery({
    queryKey: ['dev', 'team-events', { entity, kind, actor, limit }],
    queryFn: () => teamEvents({ entity, kind, actor, limit }),
    refetchInterval: 8000,
    retry: false,
  })
  if (q.error) return <p className="text-xs text-amber-300">Team activity is not available: {(q.error as Error).message}</p>
  if (!q.data) return <p className="text-xs text-slate-500">Reading the team's activity…</p>
  const events = q.data.events.filter((e) => !(hideCommands && !kind && e.kind === 'cli.command'))
  if (events.length === 0) return <p className="text-xs text-slate-500">No team events yet.</p>
  return (
    <ul aria-label="Team activity" className={compact ? 'space-y-1' : 'divide-y divide-slate-800'}>
      {events.map((e) => <Row key={e.id} e={e} compact={compact} />)}
    </ul>
  )
}

function Row({ e, compact }: { e: TeamEvent; compact: boolean }) {
  const failed = e.result !== 'ok'
  return (
    <li className={`flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs ${compact ? '' : 'py-2'}`}>
      <span className={failed ? 'text-rose-400' : 'text-emerald-400'} aria-hidden>{failed ? '✗' : '✓'}</span>
      <span className="font-medium text-slate-200">{e.developer.name}</span>
      <span className="font-mono text-slate-400">{e.kind}</span>
      {e.entities.length > 0 && <span className="font-mono text-cyan-400">{e.entities.join(', ')}</span>}
      {e.detail && <span className="text-slate-400">{e.detail}</span>}
      <span className="flex-1" />
      <span className="text-slate-600">{e.ts ? new Date(e.ts).toLocaleString() : ''}</span>
    </li>
  )
}

/** Shown only when this project shares its events with a collector and has a token. */
export function TaskTeamActivity({ id }: { id: string }) {
  const s = useQuery({ queryKey: ['dev', 'dev-telemetry'], queryFn: devTelemetry, staleTime: 15000 })
  if (!s.data?.enabled || !s.data.token_set) return null
  return (
    <section className="mt-4 border-t border-slate-700 pt-3" aria-label="Team activity on this task">
      <p className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">Team activity on this task</p>
      <TeamEventList entity={id} limit={15} compact hideCommands />
    </section>
  )
}
