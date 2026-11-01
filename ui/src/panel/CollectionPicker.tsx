import { Link } from 'react-router-dom'
import { useSystemCollections, useSystemEmbeddings, useVectorStatus } from '../queries'
import { inputClass } from './styles'

/**
 * Choose one of the collections configured in this project (the Collections page). A collection a step names that
 * is not configured stays visible and marked, so a typo is not silently dropped.
 */
export function CollectionPicker({ value, onChange, label }: { value: string; onChange: (name: string) => void; label: string }) {
  const { data, isLoading } = useSystemCollections()
  const { data: embeddings } = useSystemEmbeddings()
  const { data: vector } = useVectorStatus()
  const names = Object.keys(data ?? {}).sort()
  const missing = value !== '' && !value.includes('{{') && !names.includes(value) && !isLoading
  const entry = data?.[value]
  const embedding = entry?.embedding ? embeddings?.[entry.embedding] : undefined
  return (
    <div className="space-y-1">
      <select aria-label={label} className={inputClass} value={value.includes('{{') ? '' : value} onChange={(e) => onChange(e.target.value)}>
        {value === '' && <option value="">Choose a collection…</option>}
        {missing && <option value={value}>{value} (not configured)</option>}
        {names.map((n) => <option key={n} value={n}>{n}</option>)}
      </select>
      {value.includes('{{') && <p className="text-[10px] text-slate-500">Set by a template: <span className="font-mono">{value}</span></p>}
      {entry?.description && <p className="text-[10px] text-slate-500">{entry.description}</p>}
      {entry && (
        <p className="text-[10px] text-slate-500">
          Embedding: <span className="font-mono">{entry.embedding || 'the default'}</span>
          {embedding?.model && <> · <span className="font-mono">{embedding.model}</span></>}
        </p>
      )}
      {missing && <p className="text-[10px] text-amber-300">No collection named {value} is configured.</p>}
      {!isLoading && names.length === 0 && (
        <p className="text-[10px] text-slate-500">No collections are configured yet. Add one on the <Link className="text-indigo-300 hover:underline" to="/collections">Collections</Link> page.</p>
      )}
      {vector && !vector.ready && (
        <p className="text-[10px] text-amber-300">pgvector is not available: {vector.reason ?? 'vector steps will not run'}.</p>
      )}
    </div>
  )
}
