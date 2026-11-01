/**
 * StoragePage — the blob stores a project declares in storage/*.yaml.
 *
 * Lists each store with the environment variables it still needs, checks it
 * (write, read back, delete a probe object), and browses its objects read-only.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { TopBar } from '../components/TopBar'
import { SidebarHeader } from '../components/SidebarHeader'
import { EmptyPanel } from '../components/EmptyPanel'
import {
  checkStore,
  listObjects,
  listStores,
  writeText,
  type StoreCheck,
  type StoreRow,
  type StoredObject,
} from '../devApi'

const TEMPLATE = `kind: Storage
version: v1
metadata:
  name: files
spec:
  provider: local          # local | s3 | azure | gcs
  root: ./data/storage
  # prefix: uploads/
  # readonly: false
  # max_object_bytes: 16777216
`

const PROVIDER_LABEL: Record<string, string> = {
  s3: 'S3 / compatible',
  azure: 'Azure Blob',
  gcs: 'Google Cloud Storage',
  local: 'Local disk',
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function NewStore({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [name, setName] = useState('files')
  const [text, setText] = useState(TEMPLATE)
  const save = useMutation({
    mutationFn: () => writeText('storage', `${name.trim()}.yaml`, text),
    onSuccess: onDone,
  })
  return (
    <div className="p-4 space-y-3 border-b border-slate-800">
      <label className="block text-xs text-slate-400" htmlFor="store-file">
        File name
      </label>
      <input
        id="store-file"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm font-mono text-slate-100"
      />
      <textarea
        aria-label="Storage YAML"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={11}
        spellCheck={false}
        className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-mono text-slate-100"
      />
      <p className="text-[11px] text-slate-500">
        Secrets are {'${ENV_VAR}'} references only; a literal key is rejected.
      </p>
      <div className="flex items-center gap-3">
        <button
          onClick={() => save.mutate()}
          disabled={!name.trim() || save.isPending}
          className="px-4 py-1.5 rounded-lg bg-sky-600 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-40"
        >
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
        <button onClick={onCancel} className="px-4 py-1.5 rounded-lg border border-slate-600 text-sm text-slate-200 hover:border-slate-400">
          Cancel
        </button>
        {save.error && <span className="text-xs text-rose-400">{(save.error as Error).message}</span>}
      </div>
    </div>
  )
}

function StoreDetail({ store }: { store: StoreRow }) {
  const [prefix, setPrefix] = useState('')
  const [applied, setApplied] = useState('')
  const [pages, setPages] = useState<StoredObject[][]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [browseError, setBrowseError] = useState<string | null>(null)
  const [result, setResult] = useState<StoreCheck | null>(null)

  const check = useMutation({ mutationFn: () => checkStore(store.name), onSuccess: setResult })
  const browse = useMutation({
    mutationFn: ({ prefix: p, cursor: c }: { prefix: string; cursor: string | null }) =>
      listObjects(store.name, p, c),
    onSuccess: (data, vars) => {
      setBrowseError(null)
      setPages((old) => (vars.cursor ? [...old, data.items] : [data.items]))
      setCursor(data.cursor)
      setApplied(vars.prefix)
    },
    onError: (e) => setBrowseError((e as Error).message),
  })
  const items = pages.flat()

  return (
    <div className="flex-1 min-w-0 overflow-y-auto p-6 space-y-6">
      <div>
        <h2 className="text-slate-100 font-medium">{store.name}</h2>
        <p className="text-xs text-slate-500 font-mono">
          {PROVIDER_LABEL[store.provider ?? ''] ?? store.provider} · {store.target}
          {store.prefix ? ` · prefix ${store.prefix}` : ''}
          {store.readonly ? ' · read-only' : ''}
        </p>
        {store.missing.length > 0 && (
          <p className="mt-2 text-xs text-amber-400">
            Missing environment: <span className="font-mono">{store.missing.join(', ')}</span>
          </p>
        )}
      </div>

      <section className="space-y-2">
        <div className="flex items-center gap-3">
          <button
            onClick={() => check.mutate()}
            disabled={check.isPending}
            className="px-3 py-1.5 rounded-lg border border-slate-600 text-sm text-slate-200 hover:border-sky-500 disabled:opacity-40"
          >
            {check.isPending ? 'Checking…' : 'Check connection'}
          </button>
          {check.error && <span className="text-xs text-rose-400">{(check.error as Error).message}</span>}
        </div>
        {result && (
          <ul className="text-xs font-mono space-y-1" aria-label="Check result">
            {result.steps.map((s) => (
              <li key={s.step} className={s.error ? 'text-rose-400' : 'text-emerald-400'}>
                {s.error ? '✗' : '✓'} {s.step}
                {s.error ? ` — ${s.error}` : ''}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <div className="flex gap-2">
          <input
            aria-label="Key prefix"
            placeholder="key prefix"
            value={prefix}
            onChange={(e) => setPrefix(e.target.value)}
            className="flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm font-mono text-slate-100"
          />
          <button
            onClick={() => browse.mutate({ prefix, cursor: null })}
            disabled={browse.isPending}
            className="px-3 py-1.5 rounded-lg bg-sky-600 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-40"
          >
            List
          </button>
        </div>
        {browseError && <p className="text-xs text-rose-400 font-mono">{browseError}</p>}
        {(items.length > 0 || pages.length > 0) && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead className="text-slate-500 text-left">
                <tr>
                  <th className="py-1 pr-4">Key</th>
                  <th className="py-1 pr-4 text-right">Size</th>
                  <th className="py-1">Modified</th>
                </tr>
              </thead>
              <tbody className="text-slate-300">
                {items.map((o) => (
                  <tr key={o.key} className="border-t border-slate-800">
                    <td className="py-1 pr-4 break-all">{o.key}</td>
                    <td className="py-1 pr-4 text-right whitespace-nowrap">{formatBytes(o.size)}</td>
                    <td className="py-1 whitespace-nowrap">{o.modified || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {items.length === 0 && <p className="text-xs text-slate-500 py-2">No objects.</p>}
            {cursor && (
              <button
                onClick={() => browse.mutate({ prefix: applied, cursor })}
                className="mt-2 text-xs text-sky-400 hover:text-sky-300"
              >
                Load more
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

export function StoragePage() {
  const qc = useQueryClient()
  const { data: stores = [], isLoading, error } = useQuery({ queryKey: ['storage'], queryFn: listStores })
  const [selected, setSelected] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const current = stores.find((s) => s.name === selected) ?? stores[0] ?? null

  return (
    <div className="flex flex-col h-full min-h-0">
      <TopBar title="Storage" subtitle="blob stores" />
      <div className="flex flex-1 min-h-0">
        <aside className="w-64 shrink-0 border-r border-slate-800 flex flex-col">
          <SidebarHeader title="Storage" onNew={() => setAdding(true)} newLabel="New store" />
          <ul className="flex-1 overflow-y-auto">
            {isLoading && <li className="p-3 text-xs text-slate-500">Loading…</li>}
            {error && <li className="p-3 text-xs text-rose-400">{(error as Error).message}</li>}
            {!isLoading && stores.length === 0 && (
              <li className="p-3 text-xs text-slate-500">No storage declared. Add one to storage/.</li>
            )}
            {stores.map((s) => (
              <li key={s.name}>
                <button
                  onClick={() => {
                    setSelected(s.name)
                    setAdding(false)
                  }}
                  className={`w-full text-left px-3 py-2 border-b border-slate-800/60 hover:bg-slate-800/60 ${
                    current?.name === s.name ? 'bg-slate-800' : ''
                  }`}
                >
                  <div className="text-sm text-slate-100">{s.name}</div>
                  <div className="text-[11px] text-slate-500 font-mono">
                    {s.error ? <span className="text-rose-400">invalid</span> : PROVIDER_LABEL[s.provider ?? '']}
                    {s.missing.length > 0 && <span className="text-amber-400"> · env missing</span>}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <main className="flex-1 min-w-0 flex flex-col overflow-y-auto">
          {adding && (
            <NewStore
              onDone={() => {
                setAdding(false)
                qc.invalidateQueries({ queryKey: ['storage'] })
              }}
              onCancel={() => setAdding(false)}
            />
          )}
          {!adding && !isLoading && !error && stores.length === 0 && (
            <EmptyPanel
              icon="storage"
              title="No store declared"
              description="A store is where files live: S3, Azure Blob, Google Cloud Storage or a local folder. Workflows read and write it by name."
              actionLabel="New Store"
              onAction={() => setAdding(true)}
            />
          )}
          {!adding && current?.error && (
            <div className="p-6 text-sm">
              <p className="text-rose-400 font-mono break-words">{current.error}</p>
              <p className="text-xs text-slate-500 mt-2">Fix {current.file} in storage/.</p>
            </div>
          )}
          {!adding && current && !current.error && <StoreDetail key={current.name} store={current} />}
        </main>
      </div>
    </div>
  )
}
