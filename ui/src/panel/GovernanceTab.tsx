import { setField, type AgentView, type WorkflowView } from '../canvas/model'
import { Row, TextField } from './fields'
import { inputClass } from './styles'

const rec = (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})
const list = (v: string) => (v.trim() ? v.split(',').map((s) => s.trim()).filter(Boolean) : undefined)

export function GovernanceTab({ agent, view, apply }: { agent: AgentView; view: WorkflowView; apply: (e: (t: string) => string) => void }) {
  const g = rec(agent.raw.guardrails)
  const set = (path: (string | number)[], value: unknown) => apply((t) => setField(t, agent.id, path, value))
  return (
    <div className="space-y-3">
      <Row label="Effect" hint="What the agent does to the world; writes need a compensator to roll back">
        <select aria-label="Effect" className={inputClass} value={String(agent.raw.effect ?? '')}
          onChange={(e) => set(['effect'], e.target.value || undefined)}>
          <option value="">(derived)</option>
          {['none', 'read', 'write', 'destructive'].map((x) => <option key={x}>{x}</option>)}
        </select>
      </Row>
      {(['input', 'output', 'tools'] as const).map((gate) => (
        <Row key={gate} label={`Guardrails · ${gate}`} hint="artifact://name@version, comma-separated">
          <TextField mono value={((g[gate] as string[] | undefined) ?? []).join(', ')} ariaLabel={`Guardrails ${gate}`}
            onCommit={(v) => set(['guardrails', gate], list(v))} />
        </Row>
      ))}
      <Row label="Hooks" hint="artifact://… observe-only hooks">
        <TextField mono value={((agent.raw.hooks as string[] | undefined) ?? []).join(', ')} ariaLabel="Hooks" onCommit={(v) => set(['hooks'], list(v))} />
      </Row>
      <Row label="Compensate with" hint="An agent that undoes this one when a rollback end is reached">
        <select aria-label="Compensate with" className={inputClass} value={String(agent.raw.compensate ?? '')}
          onChange={(e) => set(['compensate'], e.target.value || undefined)}>
          <option value="">—</option>
          {view.agents.filter((a) => a.id !== agent.id).map((a) => <option key={a.id}>{a.id}</option>)}
        </select>
      </Row>
    </div>
  )
}
