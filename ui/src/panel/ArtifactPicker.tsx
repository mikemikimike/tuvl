import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { ArtifactType } from '../types'
import { isRef, makeRef, ofTypes, parseRef, useArtifacts } from './artifactRefs'
import { TextField } from './fields'
import { inputClass } from './styles'

/**
 * One stored artifact, pinned to a version (`artifact://name@3`). A reference to an artifact that is not stored
 * stays visible and marked, so a typo is not silently dropped.
 */
export function ArtifactSelect({ value, types, label, onChange, emptyLabel = 'None' }: {
  value: string
  types: readonly ArtifactType[]
  label: string
  onChange: (ref: string) => void
  emptyLabel?: string
}) {
  const { data: all = [], isLoading } = useArtifacts()
  const choices = ofTypes(all, types)
  const current = value ? parseRef(value) : null
  const stored = current ? choices.find((a) => a.name === current.name) : undefined
  const missing = !!current && !stored && !isLoading
  const versions = stored?.versions ?? []
  return (
    <div className="space-y-1">
      <div className="flex gap-1">
        <select aria-label={label} className={inputClass} value={current?.name ?? ''}
          onChange={(e) => {
            const next = choices.find((a) => a.name === e.target.value)
            onChange(next ? makeRef(next.name, next.latest) : '')
          }}>
          <option value="">{emptyLabel}</option>
          {missing && current && <option value={current.name}>{current.name} (not stored)</option>}
          {choices.map((a) => <option key={a.name} value={a.name}>{a.name} · {a.type}</option>)}
        </select>
        {stored && (
          <select aria-label={`${label} version`} className={`${inputClass} !w-20 shrink-0`} value={current?.version ?? ''}
            onChange={(e) => onChange(makeRef(stored.name, Number(e.target.value)))}>
            {current?.version == null && <option value="">unpinned</option>}
            {versions.map((v) => <option key={v} value={v}>v{v}{v === stored.latest ? ' · latest' : ''}</option>)}
          </select>
        )}
      </div>
      {stored?.description && <p className="text-[10px] text-slate-500">{stored.description}</p>}
      {missing && <p className="text-[10px] text-amber-300">No {types.join(' or ')} artifact named {current?.name} is stored.</p>}
      {!isLoading && choices.length === 0 && !value && <NoneStored types={types} />}
    </div>
  )
}

function NoneStored({ types }: { types: readonly ArtifactType[] }) {
  return (
    <p className="text-[10px] text-slate-500">
      No {types.join(' or ')} artifacts are stored yet. Add one on the <Link className="text-indigo-300 hover:underline" to="/artifacts">Artifacts</Link> page.
    </p>
  )
}

/** A list of pinned artifacts (skills): the ones chosen, then a menu of the rest. */
export function ArtifactList({ value, types, label, onChange }: {
  value: string[]
  types: readonly ArtifactType[]
  label: string
  onChange: (refs: string[] | undefined) => void
}) {
  const { data: all = [], isLoading } = useArtifacts()
  const choices = ofTypes(all, types)
  const chosen = new Set(value.map((r) => parseRef(r).name))
  const rest = choices.filter((a) => !chosen.has(a.name))
  const save = (refs: string[]) => onChange(refs.length ? refs : undefined)
  return (
    <div className="space-y-1">
      {value.map((ref, i) => (
        <div key={ref} className="flex gap-1 items-start">
          <div className="flex-1 min-w-0">
            <ArtifactSelect value={ref} types={types} label={`${label} ${i + 1}`}
              onChange={(next) => save(next ? value.map((r, k) => (k === i ? next : r)) : value.filter((_, k) => k !== i))} />
          </div>
          <button className="text-slate-500 hover:text-rose-400 px-1 pt-1" aria-label={`Remove ${label} ${parseRef(ref).name}`}
            onClick={() => save(value.filter((_, k) => k !== i))}>✕</button>
        </div>
      ))}
      {rest.length > 0 && (
        <select aria-label={`Add ${label}`} className={inputClass} value=""
          onChange={(e) => { const a = rest.find((x) => x.name === e.target.value); if (a) save([...value, makeRef(a.name, a.latest)]) }}>
          <option value="">+ add</option>
          {rest.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
        </select>
      )}
      {!isLoading && choices.length === 0 && value.length === 0 && <NoneStored types={types} />}
    </div>
  )
}

/** Words an agent is given: written here, or a stored artifact. Switching keeps what was typed until an artifact is chosen. */
export function WordsField({ value, types, label, onCommit }: {
  value: string
  types: readonly ArtifactType[]
  label: string
  onCommit: (v: string) => void
}) {
  const [picking, setPicking] = useState(isRef(value))
  const stored = picking || isRef(value)
  return (
    <div className="space-y-1">
      <div className="flex gap-3 text-[11px] text-slate-400" role="radiogroup" aria-label={`${label} source`}>
        <label className="flex items-center gap-1">
          <input type="radio" name={`${label}-source`} checked={!stored} onChange={() => { setPicking(false); if (isRef(value)) onCommit('') }} />
          Write it here
        </label>
        <label className="flex items-center gap-1">
          <input type="radio" name={`${label}-source`} checked={stored} onChange={() => setPicking(true)} />
          Use a stored artifact
        </label>
      </div>
      {stored
        ? <ArtifactSelect value={isRef(value) ? value : ''} types={types} label={`${label} artifact`} emptyLabel="Choose an artifact…"
            onChange={(ref) => onCommit(ref)} />
        : <TextField value={value} ariaLabel={label} onCommit={onCommit} />}
    </div>
  )
}
