import { setField, type AgentView } from '../canvas/model'
import { Row, TextField } from './fields'

const rec = (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})

const num = (v: string) => (v.trim() === '' ? undefined : Number(v))

export function BudgetTab({ agent, apply }: { agent: AgentView; apply: (e: (t: string) => string) => void }) {
  const b = rec(agent.raw.budget)
  const retry = rec(b.retry)
  const set = (path: string[], value: unknown) => apply((t) => setField(t, agent.id, ['budget', ...path], value))
  const bounded = agent.engine === 'llm' || agent.engine === 'loop'
  return (
    <div className="grid grid-cols-2 gap-3">
      <Row label="Timeout" hint="30s, 2m, 1h"><TextField value={String(b.timeout ?? '')} ariaLabel="Timeout" onCommit={(v) => set(['timeout'], v || undefined)} /></Row>
      {bounded && <Row label="Max tokens"><TextField value={String(b.max_tokens ?? '')} ariaLabel="Max tokens" onCommit={(v) => set(['max_tokens'], num(v))} /></Row>}
      {agent.engine === 'loop' && (
        <>
          <Row label="Max iterations"><TextField value={String(b.max_iterations ?? '')} ariaLabel="Max iterations" onCommit={(v) => set(['max_iterations'], num(v))} /></Row>
          <Row label="Max tool calls"><TextField value={String(b.max_tool_calls ?? '')} ariaLabel="Max tool calls" onCommit={(v) => set(['max_tool_calls'], num(v))} /></Row>
        </>
      )}
      <Row label="Retry attempts"><TextField value={String(retry.attempts ?? '')} ariaLabel="Retry attempts" onCommit={(v) => set(['retry', 'attempts'], num(v))} /></Row>
      <Row label="Retry on" hint="comma-separated signals, e.g. timeout, parse_error">
        <TextField value={Array.isArray(retry.errors) ? retry.errors.join(', ') : ''} ariaLabel="Retry on"
          onCommit={(v) => set(['retry', 'errors'], v.trim() ? v.split(',').map((s) => s.trim()).filter(Boolean) : undefined)} />
      </Row>
    </div>
  )
}
