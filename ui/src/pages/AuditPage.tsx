import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { TopBar } from '../components/TopBar'
import { TeamEventList } from '../specs/TeamActivity'
import { auditEvents } from '../devApi'
import type { AuditEvent } from '../devApi'
import { EntityLink } from '../specs/LifecycleViews'
import { actorOf, mergeEvents, shortTime } from '../specs/lifecycle'

const MARK: Record<AuditEvent['result'], { glyph: string; cls: string }> = {
  ok: { glyph: '✓', cls: 'text-emerald-400' },
  refused: { glyph: '!', cls: 'text-amber-400' },
  failed: { glyph: '✗', cls: 'text-rose-400' },
}

function Row({ e, open, onToggle }: { e: AuditEvent; open: boolean; onToggle: () => void }) {
  const mark = MARK[e.result]
  return (
    <li className="border-b border-slate-800/60">
      <button onClick={onToggle} aria-expanded={open} className="flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-xs hover:bg-slate-800/40">
        <span className={`w-3 shrink-0 ${mark.cls}`} aria-label={e.result}>{mark.glyph}</span>
        <span className="w-24 shrink-0 font-mono text-slate-500">{shortTime(e.ts)}</span>
        <span className="w-10 shrink-0 text-slate-400">{actorOf(e)}</span>
        <span className="w-36 shrink-0 font-mono text-slate-200">{e.kind}</span>
        <span className="flex min-w-0 flex-1 flex-wrap gap-x-2">
          {e.entities.map((id) => <EntityLink key={id} id={id} />)}
          {e.detail && <span className="truncate text-slate-400">{e.detail}</span>}
        </span>
      </button>
      {open && (
        <pre className="mx-3 mb-2 overflow-auto rounded bg-slate-900 p-2 text-[11px] text-slate-300">{JSON.stringify(e, null, 2)}</pre>
      )}
    </li>
  )
}

export function AuditPage() {
  const [params, setParams] = useSearchParams()
  const team = params.get('view') === 'team'
  const entity = params.get('entity') ?? ''
  const kind = params.get('kind') ?? ''
  const actor = params.get('actor') ?? ''
  const [live, setLive] = useState(true)
  const [openId, setOpenId] = useState<string | null>(null)
  const filter = useMemo(() => ({ entity, kind, actor }), [entity, kind, actor])

  // Each poll asks only for events after the last id held and adds them; nothing is pushed.
  const held = useRef<{ key: string; events: AuditEvent[] }>({ key: '', events: [] })
  const q = useQuery({
    queryKey: ['dev', 'audit', filter],
    queryFn: async () => {
      const key = JSON.stringify(filter)
      const prev = held.current.key === key ? held.current.events : []
      const r = await auditEvents({ ...filter, limit: prev.length ? 0 : 300, after: prev.at(-1)?.id })
      const events = mergeEvents(prev, r.events)
      held.current = { key, events }
      return { events, chain: r.chain, kinds: r.kinds }
    },
    refetchInterval: live ? 2000 : false,
  })
  const shown = q.data?.events ?? []
  const chain = q.data?.chain
  // read the address as it is now: two quick edits in different fields must both land
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(window.location.search)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next, { replace: true })
  }
  const field = 'rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs font-mono'

  return (
    <div className="flex h-full flex-col">
      <TopBar title="Audit" subtitle={team ? "what everyone on the team did, from your team's collector" : "this machine's record of what was done to the project"} />
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 px-4 py-2 text-xs">
        <span role="group" aria-label="Mine or team" className="flex overflow-hidden rounded border border-slate-700">
          <button type="button" aria-pressed={!team} onClick={() => set('view', '')} className={`px-2.5 py-1 ${!team ? 'bg-slate-600 text-slate-100' : 'text-slate-400 hover:bg-slate-800'}`}>Mine</button>
          <button type="button" aria-pressed={team} onClick={() => set('view', 'team')} className={`px-2.5 py-1 ${team ? 'bg-slate-600 text-slate-100' : 'text-slate-400 hover:bg-slate-800'}`}>Team</button>
        </span>
        <input aria-label="Entity" placeholder="IDEA-SK-0004 or SPEC-… or TASK-…" value={entity} onChange={(e) => set('entity', e.target.value.trim())} className={`${field} w-64`} />
        <input aria-label="Kind" list="audit-kinds" placeholder="kind, e.g. spec." value={kind} onChange={(e) => set('kind', e.target.value.trim())} className={`${field} w-40`} />
        <datalist id="audit-kinds">{(q.data?.kinds ?? []).map((k) => <option key={k} value={k} />)}</datalist>
        <input aria-label="Actor" placeholder="actor" value={actor} onChange={(e) => set('actor', e.target.value.trim())} className={`${field} w-28`} />
        <label className="flex items-center gap-1 text-slate-400">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> live
        </label>
        <span className="flex-1" />
        {!team && chain && (
          <span
            className={`rounded px-2 py-0.5 ${chain.ok ? 'bg-emerald-900/60 text-emerald-300' : 'bg-rose-900/60 text-rose-300'}`}
            title={chain.ok ? 'every line chains to the one before it' : `${chain.problem} at ${chain.where}`}
            role="status"
          >
            {chain.ok ? `chain intact · ${chain.events} event${chain.events === 1 ? '' : 's'}` : `chain broken at ${chain.where}`}
          </span>
        )}
      </div>
      {team ? (
        <div className="flex-1 min-h-0 overflow-auto px-4 py-2"><TeamEventList entity={entity} kind={kind} actor={actor} limit={150} /></div>
      ) : shown.length === 0 ? (
        <p className="p-6 text-sm text-slate-500">
          {q.isLoading ? 'Loading…' : 'No events match. The ledger fills as you run tuvl commands in this project.'}
        </p>
      ) : (
        <ul className="flex-1 overflow-auto" aria-label="Events">
          {shown.map((e) => <Row key={e.id} e={e} open={openId === e.id} onToggle={() => setOpenId(openId === e.id ? null : e.id)} />)}
        </ul>
      )}
      <p className="border-t border-slate-800 px-4 py-1.5 text-[11px] text-slate-600">
        {team
          ? "Read-only. What each developer's tuvl reported to your team's collector: ids, hashes and short details, never file contents or prompts. Self-reported, so use it for visibility, not as evidence."
          : 'Read-only. The ledger holds ids, hashes and short details, never file contents or prompts; it belongs to this machine and is not committed.'}
      </p>
    </div>
  )
}
