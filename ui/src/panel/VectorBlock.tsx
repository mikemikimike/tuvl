import { setField, type AgentView } from '../canvas/model'
import { CollectionPicker } from './CollectionPicker'
import { Row, TextField } from './fields'
import { inputClass } from './styles'

const rec = (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})

/** tuvl.data_search and tuvl.data_ingest: the collection, and what is searched for or stored. The full block stays editable below. */
export function VectorBlock({ agent, apply }: { agent: AgentView; apply: (e: (t: string) => string) => void }) {
  const params = rec(rec(agent.raw.code).with)
  const search = rec(agent.raw.code).run === 'tuvl.data_search'
  const text = (k: string) => (typeof params[k] === 'string' ? (params[k] as string) : '')
  const set = (k: string, v: unknown) => apply((t) => setField(t, agent.id, ['code', 'with', k], v))
  return (
    <div className="space-y-2">
      <Row label="Collection">
        <CollectionPicker label="Collection" value={text('collection')} onChange={(v) => set('collection', v)} />
      </Row>
      {search ? (
        <div className="grid grid-cols-3 gap-2">
          <div className="col-span-2">
            <Row label="Search for" hint="A template over the step's inputs">
              <TextField mono value={text('query')} ariaLabel="Search for" onCommit={(v) => set('query', v)} />
            </Row>
          </div>
          <Row label="Results">
            <input type="number" min={1} max={100} aria-label="Results" className={inputClass} defaultValue={typeof params.top_k === 'number' ? params.top_k : 5}
              key={String(params.top_k)} onBlur={(e) => { const n = Number(e.target.value); if (n >= 1 && n <= 100 && n !== params.top_k) set('top_k', n) }} />
          </Row>
        </div>
      ) : (
        <Row label="Document" hint="A template over the step's inputs: the text that is embedded and stored">
          <TextField mono value={text('document')} ariaLabel="Document" onCommit={(v) => set('document', v)} />
        </Row>
      )}
    </div>
  )
}
