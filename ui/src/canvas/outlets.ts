import type { AgentView } from './model'

const rec = (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})

function enumValues(type: string | undefined): string[] {
  const m = /^enum\[(.*)\]$/.exec((type ?? '').trim())
  return m ? m[1].split(',').map((s) => s.trim()).filter(Boolean) : []
}

/** Signals an agent must (or may) route, in addition to the ones it already routes. */
export function requiredSignals(agent: AgentView): string[] {
  const out: string[] = []
  switch (agent.engine) {
    case 'llm':
      out.push('parse_error', 'timeout', 'budget_exceeded')
      break
    case 'loop':
      out.push('max_iterations', 'budget_exceeded', 'timeout', 'aborted')
      break
    case 'decide': {
      const enums = Object.values(agent.outputs).flatMap((t) => enumValues(t))
      out.push(...enums)
      const d = rec(agent.raw.decide)
      if (d.model && !d.shadow) out.push('low_confidence')
      break
    }
    case 'human': {
      const h = rec(agent.raw.human)
      const on = typeof h.route_on === 'string' ? agent.outputs[h.route_on] : undefined
      if (on?.replace('?', '') === 'bool') out.push('true', 'false')
      else out.push(...enumValues(on))
      if (h.expires) out.push('expired')
      break
    }
    case 'tool': {
      const t = rec(agent.raw.tool)
      if (t.use === 'db' && (t.op === 'read' || t.op === 'delete')) out.push('not_found')
      if (t.use === 'db' && ['create', 'update', 'upsert'].includes(String(t.op))) out.push('conflict')
      if (t.use === 'storage') {
        if (['get', 'head', 'copy'].includes(String(t.op))) out.push('not_found')
        if (['put', 'copy'].includes(String(t.op)) && t.if_exists !== 'overwrite') out.push('conflict')
      }
      break
    }
  }
  const g = rec(agent.raw.guardrails)
  if (['input', 'output', 'tools'].some((k) => ((g[k] as unknown[] | undefined) ?? []).length)) out.push('guardrail_violation')
  return out
}

/** Outlets drawn on a card: its routes first, then required signals it does not route yet. */
export function outletsOf(agent: AgentView): string[] {
  const routed = Object.keys(agent.routes)
  return [...routed, ...requiredSignals(agent).filter((s) => !routed.includes(s))]
}
