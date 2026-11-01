import { useState } from 'react'
import { CollectionPicker } from './CollectionPicker'
import { Row } from './fields'
import { inputClass } from './styles'

type Tool = Record<string, unknown>
const isCollection = (t: unknown): t is Tool => !!t && typeof t === 'object' && typeof (t as Tool).collection === 'string'

/** The collections a loop may search: the model supplies the query; the number of results is fixed here. */
export function CollectionTools({ tools, onChange }: { tools: unknown[]; onChange: (tools: unknown[]) => void }) {
  const [adding, setAdding] = useState('')
  const replace = (i: number, next: Tool | null) => onChange(next ? tools.map((t, k) => (k === i ? next : t)) : tools.filter((_, k) => k !== i))
  return (
    <Row label="Collections" hint="Searched by the loop as a tool (read-only); the model supplies the query">
      <div className="space-y-2">
        {tools.map((t, i) => isCollection(t) && (
          <div key={i} className="rounded border border-slate-800 p-1.5 space-y-1">
            <div className="flex gap-1 items-start">
              <div className="flex-1 min-w-0">
                <CollectionPicker label={`Collection tool ${i + 1}`} value={t.collection as string} onChange={(v) => replace(i, { ...t, collection: v })} />
              </div>
              <button className="text-slate-500 hover:text-rose-400 px-1 pt-1" aria-label={`Remove collection tool ${i + 1}`} onClick={() => replace(i, null)}>✕</button>
            </div>
            <label className="flex items-center gap-2 text-[11px] text-slate-400">
              Results
              <input type="number" min={1} max={100} aria-label={`Collection tool ${i + 1} results`} className={`${inputClass} !w-16`} key={String(t.top_k)}
                defaultValue={typeof t.top_k === 'number' ? t.top_k : 5}
                onBlur={(e) => { const n = Number(e.target.value); if (n >= 1 && n <= 100 && n !== t.top_k) replace(i, { ...t, top_k: n }) }} />
            </label>
          </div>
        ))}
        <CollectionPicker label="New collection tool" value={adding}
          onChange={(v) => { if (v) { onChange([...tools, { collection: v, top_k: 5 }]); setAdding('') } }} />
      </div>
    </Row>
  )
}
