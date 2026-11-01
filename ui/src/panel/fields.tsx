import { useState, type ReactNode } from 'react'
import { inputClass, SCALARS } from './styles'

export function Row({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block space-y-0.5">
      <span className="text-[11px] text-slate-400">{label}</span>
      {children}
      {hint && <span className="block text-[10px] text-slate-500">{hint}</span>}
    </label>
  )
}

/** A text field that commits on blur / Enter, so YAML is not rewritten per keystroke. */
export function TextField({ value, onCommit, placeholder, mono, ariaLabel, className = '' }: {
  value: string
  onCommit: (v: string) => void
  placeholder?: string
  mono?: boolean
  ariaLabel?: string
  className?: string
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const shown = draft ?? value
  const commit = () => { if (draft !== null && draft !== value) onCommit(draft); setDraft(null) }
  return (
    <input
      aria-label={ariaLabel}
      className={`${inputClass} ${mono ? 'font-mono' : ''} ${className}`}
      value={shown}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit() } if (e.key === 'Escape') setDraft(null) }}
    />
  )
}

/** `{name: type}` editor: one row per field, types from the type language. */
export function FieldMapEditor({ fields, models, onChange, label }: {
  fields: Record<string, string>
  models: string[]
  onChange: (next: Record<string, string> | undefined) => void
  label: string
}) {
  const entries = Object.entries(fields)
  const listId = `types-${label}`
  const set = (next: [string, string][]) => onChange(next.length ? Object.fromEntries(next) : undefined)
  return (
    <div className="space-y-1">
      <datalist id={listId}>
        {[...SCALARS, 'enum[a, b]', 'list[str]', 'list[json]', ...models, ...models.map((m) => `list[${m}]`)].map((t) => <option key={t} value={t} />)}
      </datalist>
      {entries.map(([name, type], i) => (
        <div key={`${name}-${i}`} className="flex gap-1">
          <TextField value={name} mono ariaLabel={`${label} field name`} className="flex-1 min-w-0"
            onCommit={(v) => set(entries.map((e, k) => (k === i ? [v.trim(), e[1]] : e)) as [string, string][])} />
          <input list={listId} aria-label={`${label} ${name} type`} defaultValue={type} key={type}
            className={`${inputClass} font-mono !w-[45%] shrink-0`}
            onBlur={(e) => { if (e.target.value !== type) set(entries.map((x, k) => (k === i ? [x[0], e.target.value.trim()] : x)) as [string, string][]) }} />
          <button className="text-slate-500 hover:text-rose-400 px-1" aria-label={`Remove ${name}`}
            onClick={() => set(entries.filter((_, k) => k !== i) as [string, string][])}>✕</button>
        </div>
      ))}
      <button className="text-[11px] text-indigo-300 hover:text-indigo-200"
        onClick={() => { let n = 1; while (fields[`field_${n}`]) n += 1; set([...entries, [`field_${n}`, 'str']] as [string, string][]) }}>
        + field
      </button>
    </div>
  )
}
