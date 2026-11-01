import { setField, type AgentView } from '../canvas/model'
import { CollectionPicker } from './CollectionPicker'
import { Row, TextField } from './fields'
import { inputClass } from './styles'
import { boundedInt, DEFAULT_MEMORY, keyKind, parseWrite, writeText, type KeyKind } from './memory'

const rec = (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})

/** `llm.memory` / `loop.memory`: remember across runs. The full block stays editable below as YAML. */
export function MemoryBlock({ agent, apply }: { agent: AgentView; apply: (e: (t: string) => string) => void }) {
  const engine = agent.engine
  const memory = rec(rec(agent.raw[engine]).memory)
  const on = agent.raw[engine] != null && rec(agent.raw[engine]).memory != null
  const set = (path: string[], v: unknown) => apply((t) => setField(t, agent.id, [engine, 'memory', ...path], v))
  const kind = keyKind(memory.key)
  const num = (field: 'window' | 'recall_top_k' | 'max_tokens', label: string, min: number, max: number) => (
    <Row label={label}>
      <input type="number" min={min} max={max} aria-label={label} className={inputClass} key={String(memory[field])}
        defaultValue={typeof memory[field] === 'number' ? (memory[field] as number) : DEFAULT_MEMORY[field]}
        onBlur={(e) => {
          const n = boundedInt(e.target.value, min, max)
          if (n !== undefined && n !== memory[field]) set([field], n)
        }} />
    </Row>
  )
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" checked={on} aria-label="Remember across runs"
          onChange={(e) => apply((t) => setField(t, agent.id, [engine, 'memory'], e.target.checked ? DEFAULT_MEMORY : undefined))} />
        Remember across runs — earlier turns of the same person go into the prompt, and the result is stored
      </label>
      {on && (
        <div className="space-y-2 rounded border border-slate-800 p-2">
          <Row label="Memory collection">
            <CollectionPicker label="Memory collection" value={typeof memory.collection === 'string' ? memory.collection : ''} onChange={(v) => set(['collection'], v)} />
          </Row>
          <div className="grid grid-cols-2 gap-2">
            <Row label="Whose memory" hint="Chosen here, never by the model">
              <select aria-label="Whose memory" className={inputClass} value={kind}
                onChange={(e) => {
                  const next = e.target.value as KeyKind
                  set(['key'], next === 'input' ? '{{ customer_id }}' : next)
                }}>
                <option value="principal">The signed-in user</option>
                <option value="tenant">The tenant</option>
                <option value="input">An input of this agent</option>
              </select>
            </Row>
            {kind === 'input' && (
              <Row label="Owner template" hint="Refused on a public trigger (V043)">
                <TextField mono value={String(memory.key ?? '')} ariaLabel="Owner template" onCommit={(v) => set(['key'], v)} />
              </Row>
            )}
          </div>
          <div className="grid grid-cols-3 gap-2">
            {num('window', 'Latest memories', 0, 50)}
            {num('recall_top_k', 'Related older', 0, 20)}
            {num('max_tokens', 'Prompt tokens', 1, 20000)}
          </div>
          <Row label="Store after a run" hint="Inputs and outputs, comma separated. Empty: every output. Never a secure field.">
            <TextField mono value={writeText(memory.write)} ariaLabel="Store after a run" onCommit={(v) => set(['write'], parseWrite(v))} />
          </Row>
          <Row label="Forget after" hint="e.g. 90d. Empty: kept until erased">
            <TextField mono value={typeof memory.retention === 'string' ? memory.retention : ''} ariaLabel="Forget after"
              onCommit={(v) => set(['retention'], v.trim() || undefined)} />
          </Row>
        </div>
      )}
    </div>
  )
}
