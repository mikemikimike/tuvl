/**
 * MemoryPage — what agents remember across runs, per collection and owner, with a way to forget.
 *
 * A memory is a row an `llm.memory` block or `tuvl.memory_remember` stored; this page reads and deletes
 * them through the dev API. Forgetting a whole owner asks for a second click.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { TopBar } from '../components/TopBar'
import { forgetMemory, forgetOwner, listMemories, listMemoryCollections, type MemoryCollection } from '../devApi'

const when = (iso: string) => new Date(iso).toLocaleString()

function Collection({ collection }: { collection: MemoryCollection }) {
  const qc = useQueryClient()
  const [owner, setOwner] = useState('')
  const [confirming, setConfirming] = useState(false)
  const key = owner.trim() || null
  const { data: rows = [], isLoading, error } = useQuery({
    queryKey: ['memory', collection.collection, key],
    queryFn: () => listMemories(collection.collection, key),
  })
  const refresh = () => {
    setConfirming(false)
    void qc.invalidateQueries({ queryKey: ['memory'] })
  }
  const one = useMutation({ mutationFn: (id: string) => forgetMemory(collection.collection, id), onSuccess: refresh })
  const all = useMutation({ mutationFn: (k: string) => forgetOwner(collection.collection, k), onSuccess: refresh })

  return (
    <div className="flex-1 min-w-0 overflow-y-auto p-6 space-y-4">
      <div>
        <h2 className="text-slate-100 font-medium">{collection.collection}</h2>
        <p className="text-xs text-slate-500">
          {collection.memories} memories · {collection.owners} owner{collection.owners === 1 ? '' : 's'} · newest {when(collection.newest)}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <input
          aria-label="Owner"
          placeholder="Filter by owner"
          value={owner}
          onChange={(e) => {
            setOwner(e.target.value)
            setConfirming(false)
          }}
          className="w-72 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm font-mono text-slate-100"
        />
        {key && !confirming && (
          <button
            onClick={() => setConfirming(true)}
            className="px-3 py-1.5 rounded-lg border border-slate-600 text-sm text-slate-200 hover:border-rose-500"
          >
            Forget everything of this owner
          </button>
        )}
        {key && confirming && (
          <button
            onClick={() => all.mutate(key)}
            disabled={all.isPending}
            className="px-3 py-1.5 rounded-lg bg-rose-700 text-sm font-semibold text-white hover:bg-rose-600 disabled:opacity-40"
          >
            Really forget {rows.length} {rows.length === 1 ? 'memory' : 'memories'} of {key}?
          </button>
        )}
        {(one.error || all.error) && (
          <span className="text-xs text-rose-400">{((one.error || all.error) as Error).message}</span>
        )}
      </div>
      {isLoading && <p className="text-xs text-slate-500">Loading…</p>}
      {error && <p className="text-xs text-rose-400">{(error as Error).message}</p>}
      <ul className="space-y-2" aria-label="Memories">
        {rows.map((r) => (
          <li key={r.id} className="rounded-lg border border-slate-800 p-3">
            <div className="flex items-center gap-3 text-[11px] text-slate-500">
              <span className="font-mono text-slate-300">{r.key}</span>
              <span>{when(r.at)}</span>
              {r.agent && <span className="font-mono">{r.agent}</span>}
              {r.run_id && <span className="font-mono">run {r.run_id.slice(0, 8)}</span>}
              <button
                onClick={() => one.mutate(r.id)}
                className="ml-auto text-rose-400 hover:text-rose-300"
                aria-label={`Forget this memory of ${r.key}`}
              >
                Forget
              </button>
            </div>
            <p className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-200">{r.content}</p>
          </li>
        ))}
        {!isLoading && rows.length === 0 && <li className="text-xs text-slate-500">Nothing stored.</li>}
      </ul>
    </div>
  )
}

export function MemoryPage() {
  const { data: collections = [], isLoading, error } = useQuery({
    queryKey: ['memory'],
    queryFn: listMemoryCollections,
  })
  const [selected, setSelected] = useState<string | null>(null)
  const current = collections.find((c) => c.collection === selected) ?? collections[0] ?? null
  return (
    <div className="flex flex-col flex-1 min-h-0">
      <TopBar title="Memory" subtitle="what agents remember" />
      <div className="flex flex-1 min-h-0">
        <aside className="w-64 shrink-0 border-r border-slate-800 overflow-y-auto">
          {isLoading && <p className="p-3 text-xs text-slate-500">Loading…</p>}
          {error && <p className="p-3 text-xs text-rose-400">{(error as Error).message}</p>}
          {!isLoading && collections.length === 0 && (
            <p className="p-3 text-xs text-slate-500">
              Nothing remembered yet. Add llm.memory to an agent, or call tuvl.memory_remember.
            </p>
          )}
          <ul>
            {collections.map((c) => (
              <li key={c.collection}>
                <button
                  onClick={() => setSelected(c.collection)}
                  className={`w-full text-left px-3 py-2 border-b border-slate-800/60 hover:bg-slate-800/60 ${
                    current?.collection === c.collection ? 'bg-slate-800' : ''
                  }`}
                >
                  <div className="text-sm text-slate-100">{c.collection}</div>
                  <div className="text-[11px] text-slate-500">{c.memories} memories · {c.owners} owners</div>
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <main className="flex-1 min-w-0 flex flex-col">{current && <Collection collection={current} />}</main>
      </div>
    </div>
  )
}
