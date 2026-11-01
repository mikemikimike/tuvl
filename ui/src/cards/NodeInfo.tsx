import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import type { AgentView } from '../canvas/model'
import type { ValidationIssue } from '../types'
import { EngineIcon } from './EngineIcon'
import { ENGINE_LABEL } from './style'

const rec = (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})
const count = (v: unknown) => (Array.isArray(v) ? v.length : 0)

/** Detail the card has no room for, by engine kind. */
function facts(agent: AgentView): [string, string][] {
  const raw = agent.raw
  const out: [string, string][] = []
  const budget = rec(raw.budget)
  const guards = rec(raw.guardrails)
  const nGuards = ['input', 'output', 'tools'].reduce((k, g) => k + count(guards[g]), 0)
  switch (agent.engine) {
    case 'llm': {
      const l = rec(raw.llm)
      out.push(['model', String(l.model ?? '—')])
      if (l.temperature !== undefined) out.push(['temperature', String(l.temperature)])
      break
    }
    case 'decide': {
      const d = rec(raw.decide)
      out.push(['rules', String(count(d.rules))])
      const m = rec(d.model)
      if (m.ref) out.push(['model', `${String(m.ref)} ≥ ${String(m.min_confidence)}`])
      if (d.shadow) out.push(['mode', 'shadow (not enforced)'])
      break
    }
    case 'tool': {
      const t = rec(raw.tool)
      out.push(['uses', String(t.use ?? '—')])
      if (t.use === 'http') out.push(['calls', `${String(t.method)} ${String(t.url)}`, ])
      else if (t.use === 'db') out.push(['does', `${String(t.op)} ${String(t.model)}`])
      else if (t.use === 'storage') out.push(['does', `${String(t.op)} in ${String(t.store)}`])
      else if (t.name) out.push(['tool', String(t.name)])
      break
    }
    case 'loop': {
      const tools = count(rec(raw.loop).tools)
      out.push(['tools', String(tools)])
      break
    }
    case 'parallel': {
      const p = rec(raw.parallel)
      const branches = Array.isArray(p.branches) ? p.branches.map((b) => `${String(rec(b).id)} (${String(rec(b).engine)})`) : []
      out.push(['branches', branches.join(', ') || '—'], ['at a time', String(p.concurrency ?? 'all')], ['on error', String(p.on_error ?? 'fail')])
      break
    }
    case 'map': {
      const m = rec(raw.map)
      out.push(['over', String(m.over ?? '—')], ['runs', String(m.workflow ?? '—')])
      out.push(['at a time', String(m.concurrency ?? 4)], ['on error', String(m.on_error ?? 'fail')])
      break
    }
    case 'code': out.push(['runs', String(rec(raw.code).run ?? '—')]); break
    case 'human': {
      const h = rec(raw.human)
      if (h.group || h.role) out.push(['approver role', String(h.group ?? h.role)])
      if (h.timeout) out.push(['timeout', String(h.timeout)])
      break
    }
    case 'pending': out.push(['status', 'contract only — no engine yet']); break
  }
  if (budget.timeout) out.push(['timeout', String(budget.timeout)])
  if (budget.max_tokens) out.push(['token cap', String(budget.max_tokens)])
  if (rec(budget.retry).attempts) out.push(['retries', String(rec(budget.retry).attempts)])
  if (nGuards) out.push(['guardrails', String(nGuards)])
  if (raw.effect) out.push(['effect', String(raw.effect)])
  if (raw.compensate) out.push(['compensator', String(raw.compensate)])
  return out
}

function Popover({ agent, messages, at }: { agent: AgentView; messages: ValidationIssue[]; at: DOMRect }) {
  const rows = facts(agent)
  const routes = Object.entries(agent.routes)
  const ref = useRef<HTMLDivElement>(null)
  const W = 288
  const M = 8
  // measured after render: beside the node on the side with room, clamped inside the viewport
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const h = el.offsetHeight
    const vw = window.innerWidth
    const vh = window.innerHeight
    const right = at.right + 10
    const left = right + W <= vw - M ? right : Math.max(M, at.left - 10 - W)
    el.style.left = `${left}px`
    el.style.top = `${Math.max(M, Math.min(at.top, vh - h - M))}px`
    el.style.visibility = 'visible'
  }, [at, agent, messages])
  return createPortal(
    <div
      ref={ref}
      className="pointer-events-none fixed z-[200] w-72 max-h-[calc(100vh-16px)] overflow-hidden break-words rounded-lg border border-slate-600 bg-slate-900 p-3 text-xs text-slate-200 shadow-2xl"
      style={{ left: 0, top: 0, visibility: 'hidden' }}
      role="tooltip"
    >
      <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-400">
        <EngineIcon engine={agent.engine} className="h-3 w-3" />{ENGINE_LABEL[agent.engine]}
      </div>
      <p className="font-mono text-sm text-slate-100 break-all">{agent.id}</p>
      {agent.description && <p className="mt-1 leading-snug text-slate-300 line-clamp-4">{agent.description}</p>}
      {rows.length > 0 && (
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          {rows.map(([k, v], i) => (
            <div key={`${k}${i}`} className="contents">
              <dt className="text-slate-500">{k}</dt>
              <dd className="min-w-0 break-all font-mono text-slate-200 line-clamp-3">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {routes.length > 0 && (
        <p className="mt-2 text-slate-400">
          {routes.map(([s, t]) => <span key={s} className="mr-2 inline-block max-w-full break-all">{s} → <span className="text-slate-200">{t}</span></span>)}
        </p>
      )}
      {messages.length > 0 && (
        <ul className="mt-2 space-y-1 border-t border-slate-700 pt-2">
          {messages.slice(0, 3).map((m, i) => (
            <li key={i} className={`line-clamp-4 break-words ${m.severity === 'error' ? 'text-rose-400' : 'text-amber-400'}`}>{m.message}</li>
          ))}
          {messages.length > 3 && <li className="text-slate-500">+{messages.length - 3} more in Problems</li>}
        </ul>
      )}
    </div>,
    document.body,
  )
}

/** Wraps a node; after a short hover, shows the node's details beside it. Read-only. */
export function HoverInfo({ agent, messages, children, className, style }: {
  agent: AgentView; messages: ValidationIssue[]; children: ReactNode; className?: string; style?: React.CSSProperties
}) {
  const ref = useRef<HTMLDivElement>(null)
  const timer = useRef<number | undefined>(undefined)
  const [rect, setRect] = useState<DOMRect | null>(null)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return (
    <div
      ref={ref}
      className={className}
      style={style}
      onMouseEnter={() => {
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => ref.current && setRect(ref.current.getBoundingClientRect()), 400)
      }}
      onMouseLeave={() => { window.clearTimeout(timer.current); setRect(null) }}
      onMouseDown={() => { window.clearTimeout(timer.current); setRect(null) }}
    >
      {children}
      {rect && <Popover agent={agent} messages={messages} at={rect} />}
    </div>
  )
}
