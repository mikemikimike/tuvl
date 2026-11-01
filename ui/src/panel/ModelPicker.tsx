import { Link } from 'react-router-dom'
import { usePresets } from './presets'
import { TextField } from './fields'
import { inputClass } from './styles'

const OTHER = '__other__'

/**
 * Choose the AI model an agent uses from the ones configured in this project (the AI Models page), or name a
 * `provider/model` id of your own.
 */
export function ModelPicker({ value, kind = 'llm', onChange, label }: {
  value: string
  kind?: 'llm' | 'decision'
  onChange: (v: string) => void
  label: string
}) {
  const { presets, loading } = usePresets(kind)
  const known = presets.some((p) => p.name === value)
  const custom = value !== '' && !known && !loading
  const selected = presets.find((p) => p.name === value)
  const shown = custom ? OTHER : value
  return (
    <div className="space-y-1">
      <select aria-label={label} className={inputClass} value={shown}
        onChange={(e) => { if (e.target.value !== OTHER) onChange(e.target.value); else if (known) onChange('provider/model') }}>
        {value === '' && <option value="">Choose a model…</option>}
        {presets.map((p) => (
          <option key={p.name} value={p.name}>{p.name}{p.model ? ` — ${p.model}` : ''}{p.enabled ? '' : ' (disabled)'}</option>
        ))}
        <option value={OTHER}>Other: a provider/model id…</option>
      </select>
      {custom && (
        <TextField value={value} mono ariaLabel={`${label} (provider/model)`} placeholder="openai/gpt-4o"
          onCommit={onChange} />
      )}
      {selected && (
        <p className="text-[10px] text-slate-500">
          {selected.provider ? `${selected.provider} · ` : ''}<span className="font-mono">{selected.model}</span>
          {!selected.enabled && <span className="text-amber-300"> · disabled: turn it on in AI Models</span>}
        </p>
      )}
      {!loading && presets.length === 0 && (
        <p className="text-[10px] text-slate-500">
          No {kind === 'decision' ? 'decision ' : ''}models are configured yet. Add one on the <Link className="text-indigo-300 hover:underline" to="/agent-models">AI Models</Link> page.
        </p>
      )}
      {!loading && presets.length > 0 && (
        <p className="text-[10px] text-slate-500">Configured on the <Link className="text-indigo-300 hover:underline" to="/agent-models">AI Models</Link> page.</p>
      )}
    </div>
  )
}
