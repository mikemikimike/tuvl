/**
 * CollectionsPage — manage the models/collections.yaml registry.
 *
 * Displays all logical vector collections and lets developers create, edit,
 * or delete them.  The embedding dropdown is populated by the live
 * /api/_system/embeddings endpoint (reflects the loaded registry).
 */
import { dump } from 'js-yaml'
import { useState, useRef } from 'react'
import { TopBar } from '../components/TopBar'
import { ColorizedYaml } from '../components/ColorizedYaml'
import { parseYaml } from '../lib/yaml'
import { useSaveFile, useRegistryFile, useSystemEmbeddings, useVectorStatus, usePgDatasources } from '../queries'
import type { CollectionEntry, CollectionRegistryFile } from '../types'
import { SidebarHeader } from '../components/SidebarHeader'
import { EmptyPanel } from '../components/EmptyPanel'

// ── Empty form state ──────────────────────────────────────────────────────────

/** Shape of a single-entry collection YAML doc, as hand-edited in Advanced mode. */
interface CollectionYamlDoc {
  metadata?: { name?: string }
  spec?: { description?: string; embedding?: string; datasource?: string }
}

const EMPTY_ENTRY: CollectionEntry = { name: '', description: '', embedding: '', datasource: '' }

// ── Main page ─────────────────────────────────────────────────────────────────

export function CollectionsPage() {
  const { data: registryData, isLoading: loading } = useRegistryFile<CollectionRegistryFile | null>(
    'models',
    'collections.yaml',
  )
  const [entries, setEntries] = useState<CollectionEntry[]>([])
  const [selected, setSelected] = useState<CollectionEntry | null>(null)
  const [form, setForm] = useState<CollectionEntry>(EMPTY_ENTRY)
  const [isNew, setIsNew] = useState(false)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [toast, setToast] = useState<string | null>(null)

  const saveMutation = useSaveFile()
  const { data: vectorStatus } = useVectorStatus()
  const { data: embeddingsMap } = useSystemEmbeddings()
  const embeddingOptions = Object.keys(embeddingsMap ?? {})
  const { data: pgDsInfo } = usePgDatasources()

  // Sync the local list from the registry query — on initial load, and again
  // whenever a save/delete (here or elsewhere) invalidates the cache. Done
  // during render (React's documented "adjust state when a value changes"
  // pattern), not in an effect, so it settles in the same commit.
  const [seenRegistryData, setSeenRegistryData] = useState(registryData)
  const [hydrated, setHydrated] = useState(false)
  if (registryData !== seenRegistryData) {
    setSeenRegistryData(registryData)
    if (registryData !== undefined) {
      const list = registryData?.spec?.collections ?? []
      setEntries(list)
      if (!hydrated && list.length > 0) {
        setSelected(list[0])
        setForm(list[0])
      }
      setHydrated(true)
    }
  }

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }

  function buildEntryYaml(entry: CollectionEntry): object {
    const spec: Record<string, unknown> = {}
    if (entry.description?.trim()) spec.description = entry.description.trim()
    if (entry.embedding?.trim()) spec.embedding = entry.embedding.trim()
    if (entry.datasource?.trim()) spec.datasource = entry.datasource.trim()
    return {
      kind: 'CollectionConfig',
      version: 'v1',
      metadata: { name: entry.name || 'new-collection' },
      spec,
    }
  }

  function buildRegistryYaml(list: CollectionEntry[]): object {
    return {
      kind: 'CollectionRegistry',
      version: 'v1',
      metadata: { name: 'collections' },
      spec: {
        collections: list.map((e) => {
          const row: Record<string, unknown> = { name: e.name.trim() }
          if (e.description?.trim()) row.description = e.description.trim()
          if (e.embedding?.trim()) row.embedding = e.embedding.trim()
          if (e.datasource?.trim()) row.datasource = e.datasource.trim()
          return row
        }),
      },
    }
  }

  async function persistEntries(list: CollectionEntry[]) {
    setSaveState('saving')
    try {
      await saveMutation.mutateAsync({ kind: 'models', name: 'collections.yaml', body: buildRegistryYaml(list) })
      setSaveState('saved')
      setTimeout(() => setSaveState('idle'), 1500)
    } catch {
      setSaveState('error')
      setTimeout(() => setSaveState('idle'), 2000)
    }
  }

  function handleSelectEntry(entry: CollectionEntry) {
    setSelected(entry)
    setForm({ ...entry })
    setIsNew(false)
  }

  function handleNew() {
    setIsNew(true)
    setSelected(null)
    setForm({ ...EMPTY_ENTRY })
  }

  async function handleSave() {
    const trimmed: CollectionEntry = {
      name: form.name.trim(),
      description: form.description?.trim() || '',
      embedding: form.embedding?.trim() || '',
      datasource: form.datasource?.trim() || '',
    }
    if (!trimmed.name) { showToast('Name is required'); return }

    let updated: CollectionEntry[]
    if (isNew) {
      if (entries.some((e) => e.name === trimmed.name)) {
        showToast(`Collection '${trimmed.name}' already exists`)
        return
      }
      updated = [...entries, trimmed]
    } else {
      updated = entries.map((e) => (e.name === selected?.name ? trimmed : e))
    }

    setEntries(updated)
    setSelected(trimmed)
    setIsNew(false)
    await persistEntries(updated)
    showToast('Saved')
  }

  async function handleDelete() {
    if (!selected) return
    const updated = entries.filter((e) => e.name !== selected.name)
    setEntries(updated)
    setSelected(updated[0] ?? null)
    setForm(updated[0] ?? EMPTY_ENTRY)
    await persistEntries(updated)
    showToast(`Deleted '${selected.name}'`)
  }

  const previewYaml = dump(buildEntryYaml(form), { indent: 2 })

  // ── Advanced YAML editor state ──────────────────────────────────────────
  const [yamlAdvanced, setYamlAdvanced] = useState(false)
  const [advancedYaml, setAdvancedYaml] = useState('')
  const [yamlParseError, setYamlParseError] = useState<string | null>(null)
  const [yamlValidError, setYamlValidError] = useState<string | null>(null)
  const originalYamlRef = useRef('')

  function handleEnterAdvanced() {
    originalYamlRef.current = previewYaml
    setAdvancedYaml(previewYaml)
    setYamlParseError(null)
    setYamlValidError(null)
    setYamlAdvanced(true)
  }

  function handleAdvancedYamlChange(text: string) {
    setAdvancedYaml(text)
    setYamlValidError(null)
    try {
      const parsed = parseYaml<CollectionYamlDoc>(text)
      setForm({
        name: String(parsed?.metadata?.name ?? ''),
        description: String(parsed?.spec?.description ?? ''),
        embedding: String(parsed?.spec?.embedding ?? ''),
        datasource: String(parsed?.spec?.datasource ?? ''),
      })
      setYamlParseError(null)
    } catch (err: unknown) {
      setYamlParseError(err instanceof Error ? err.message : 'Invalid YAML')
    }
  }

  async function handleAdvancedSave() {
    if (yamlParseError) { setYamlValidError('Fix YAML syntax errors before saving.'); return }
    const trimmed: CollectionEntry = {
      name: form.name.trim(),
      description: form.description?.trim() || '',
      embedding: form.embedding?.trim() || '',
      datasource: form.datasource?.trim() || '',
    }
    if (!trimmed.name) { setYamlValidError('metadata.name is required.'); return }
    const updated = isNew
      ? [...entries, trimmed]
      : entries.map((e) => (e.name === selected?.name ? trimmed : e))
    setYamlValidError(null)
    await persistEntries(updated)
    setEntries(updated)
    setSelected(trimmed)
    setIsNew(false)
    setYamlAdvanced(false)
    showToast('Saved')
  }

  const inputCls = 'w-full rounded border border-slate-700 bg-slate-800/80 px-2 py-1.5 text-xs text-slate-100 outline-none focus:ring-1 focus:border-sky-500 focus:ring-sky-500/30'
  const labelCls = 'block text-[10px] font-medium text-slate-400 mb-0.5'

  return (
    <div className="flex flex-col h-full">
      <TopBar title="Collections" subtitle="models/collections.yaml" />

      {toast && (
        <div className="absolute top-14 right-6 z-50 rounded bg-slate-700 border border-slate-600 px-3 py-2 text-xs text-slate-200 shadow-lg">
          {toast}
        </div>
      )}

      {vectorStatus && !vectorStatus.ready && (
        <div className="shrink-0 flex items-start gap-2 px-4 py-2.5 bg-amber-950/60 border-b border-amber-800/60 text-xs text-amber-300">
          <span className="shrink-0 mt-0.5">⚠</span>
          <span>
            <strong>pgvector not available</strong> — {vectorStatus.reason ?? 'Vector features are disabled.'}{' '}
            Collections can still be configured here but the tuvl.data_ingest and tuvl.data_search steps will not run.
          </span>
        </div>
      )}

      {/* ── Vector storage datasource picker ───────────────────────────────── */}
      {pgDsInfo && pgDsInfo.datasources.length === 0 && (
        <div className="shrink-0 flex items-start gap-2 px-4 py-2.5 bg-red-950/60 border-b border-red-800/60 text-xs text-red-300">
          <span className="shrink-0 mt-0.5">✕</span>
          <span>
            <strong>No PostgreSQL datasource configured</strong> — vector storage is unavailable at runtime.
            Add a datasource YAML under <code className="text-red-200">datasources/</code> with{' '}
            <code className="text-red-200">spec.type: postgresql</code> to enable RAG features.
          </span>
        </div>
      )}

      {pgDsInfo && pgDsInfo.datasources.length > 0 && (
        <div className="shrink-0 flex items-center gap-2 px-4 py-2 bg-slate-800/60 border-b border-slate-700 text-xs text-slate-400">
          <span className="shrink-0">🗄</span>
          <span>Global vector datasource: <span className="text-slate-200 font-medium">{pgDsInfo.current_vector_datasource}</span>{' '}<span className="text-slate-600">— override per collection below</span></span>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* ── Left sidebar: listing ─────────────────────────────────── */}
        <aside className="w-56 shrink-0 border-r border-slate-700 bg-slate-900 flex flex-col">
          <SidebarHeader title="Collections" onNew={handleNew} newLabel="New collection" />

          {loading ? (
            <div className="px-3 py-4 text-xs text-slate-500">Loading…</div>
          ) : entries.length === 0 ? (
            <div className="px-3 py-4 text-xs text-slate-500 italic">No collections defined</div>
          ) : (
            <nav className="flex-1 overflow-y-auto py-1">
              {entries.map((e) => (
                <button
                  key={e.name}
                  onClick={() => handleSelectEntry(e)}
                  className={`w-full text-left px-3 py-2 text-xs transition-colors ${
                    (selected?.name === e.name && !isNew)
                      ? 'bg-sky-700/30 text-sky-300'
                      : 'text-slate-300 hover:bg-slate-800'
                  }`}
                >
                  <div className="font-medium truncate">{e.name}</div>
                  <div className="text-[10px] text-slate-500 truncate">
                    {e.embedding || 'global default'}
                  </div>
                </button>
              ))}
            </nav>
          )}
        </aside>

        {/* ── Centre: form ──────────────────────────────────────────── */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {(!selected && !isNew) ? (
            <EmptyPanel
              icon="collection"
              title="No collection selected"
              description="A collection is a searchable knowledge base: documents are embedded and stored so agents can search them."
              actionLabel="New Collection"
              onAction={handleNew}
            />
          ) : (
            <div className="flex flex-1 overflow-hidden">
              {/* Form */}
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                <div className="text-xs font-semibold text-slate-300 mb-2 uppercase tracking-wide">
                  {isNew ? 'New Collection' : `Edit: ${selected?.name}`}
                </div>

                {/* Name */}
                <div>
                  <label className={labelCls}>Name <span className="text-red-400">*</span></label>
                  <input
                    className={inputCls}
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                    placeholder="knowledge-base"
                    disabled={!isNew}
                  />
                  {!isNew && (
                    <p className="text-[10px] text-slate-500 mt-0.5">
                      Rename by deleting and re-creating this collection.
                    </p>
                  )}
                </div>

                {/* Description */}
                <div>
                  <label className={labelCls}>Description</label>
                  <input
                    className={inputCls}
                    value={form.description ?? ''}
                    onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                    placeholder="A short description of this collection"
                  />
                </div>

                {/* Embedding model dropdown */}
                <div>
                  <label className={labelCls}>Embedding Model</label>
                  <select
                    className={inputCls}
                    value={form.embedding ?? ''}
                    onChange={(e) => setForm((f) => ({ ...f, embedding: e.target.value }))}
                  >
                    <option value="">— Global default (TUVL_DEFAULT_EMBEDDING) —</option>
                    {embeddingOptions.map((name) => (
                      <option key={name} value={name}>{name}</option>
                    ))}
                  </select>
                  {embeddingOptions.length === 0 && (
                    <p className="text-[10px] text-amber-500 mt-0.5">
                      No named embeddings found. Define them in Embeddings first.
                    </p>
                  )}
                  <p className="text-[10px] text-slate-500 mt-0.5">
                    Leave blank to use the global default embedding from your .env.
                  </p>
                </div>

                {/* PostgreSQL datasource */}
                <div>
                  <label className={labelCls}>PostgreSQL Datasource</label>
                  <select
                    className={inputCls}
                    value={form.datasource ?? ''}
                    onChange={(e) => setForm((f) => ({ ...f, datasource: e.target.value }))}
                  >
                    <option value="">— Use global vector datasource —</option>
                    {(pgDsInfo?.datasources ?? []).map((ds) => (
                      <option key={ds} value={ds}>{ds}</option>
                    ))}
                  </select>
                  {!pgDsInfo?.datasources?.length && (
                    <p className="text-[10px] text-amber-500 mt-0.5">
                      No PostgreSQL datasources registered.
                    </p>
                  )}
                  <p className="text-[10px] text-slate-500 mt-0.5">
                    Leave blank to inherit the global vector datasource.
                  </p>
                </div>

                {/* Actions */}
                <div className="flex gap-2 pt-2">
                  <button
                    onClick={handleSave}
                    disabled={saveState === 'saving'}
                    className="px-3 py-1.5 text-xs rounded bg-sky-700 hover:bg-sky-600 text-white disabled:opacity-50"
                  >
                    {saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? '✓ Saved' : 'Save'}
                  </button>
                  {!isNew && selected && (
                    <button
                      onClick={handleDelete}
                      className="px-3 py-1.5 text-xs rounded bg-red-800 hover:bg-red-700 text-red-100"
                    >
                      Delete
                    </button>
                  )}
                  {isNew && (
                    <button
                      onClick={() => { setIsNew(false); setSelected(entries[0] ?? null); setForm(entries[0] ?? EMPTY_ENTRY) }}
                      className="px-3 py-1.5 text-xs rounded border border-slate-600 text-slate-300 hover:bg-slate-800"
                    >
                      Cancel
                    </button>
                  )}
                </div>

                {/* Usage hint */}
                {selected && !isNew && (
                  <div className="mt-4 rounded border border-slate-700 bg-slate-900/50 p-3 text-[11px] text-slate-400 space-y-1.5">
                    <div className="font-semibold text-slate-300 mb-1">Usage in a workflow YAML</div>
                    <pre className="text-sky-300 text-[10px] leading-5 whitespace-pre-wrap">{`- id: ingest
  kind: functional
  runner: DataIngest
  collection: ${selected.name}
  scope: global
  document: "{{text}}"

- id: search
  kind: functional
  runner: DataSearch
  collection: ${selected.name}
  scope: global
  query: "{{user_query}}"
  top_k: 5
  output_key: search_results`}</pre>
                  </div>
                )}
              </div>

              {/* YAML panel */}
              <div className="w-80 shrink-0 border-l border-slate-800 flex flex-col">
                <div className="px-4 py-3 border-b border-slate-800 flex-shrink-0 flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">YAML Preview</span>
                  <button
                    type="button"
                    onClick={yamlAdvanced ? () => { setYamlAdvanced(false); setYamlParseError(null); setYamlValidError(null) } : handleEnterAdvanced}
                    className={`text-xs px-2 py-1 rounded border transition-colors ${
                      yamlAdvanced
                        ? 'border-sky-600 text-sky-400 bg-sky-900/20 hover:bg-sky-900/40'
                        : 'border-slate-700 text-slate-500 hover:text-slate-300 hover:border-slate-600'
                    }`}
                  >
                    {yamlAdvanced ? '← Preview' : 'Advanced'}
                  </button>
                </div>
                {yamlAdvanced ? (
                  <div className="flex flex-col flex-1 min-h-0">
                    <textarea
                      value={advancedYaml}
                      onChange={(e) => handleAdvancedYamlChange(e.target.value)}
                      className="flex-1 min-h-0 w-full resize-none bg-transparent p-4 text-xs font-mono text-slate-200 outline-none leading-5 focus:ring-1 focus:ring-inset focus:ring-sky-800"
                      spellCheck={false}
                      autoComplete="off"
                    />
                    <div className="flex-shrink-0 border-t border-slate-800 px-4 py-3 flex flex-col gap-2">
                      {(yamlParseError || yamlValidError) && (
                        <p className="text-xs text-rose-400 font-mono break-all">{yamlParseError ?? yamlValidError}</p>
                      )}
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={handleAdvancedSave}
                          disabled={saveState === 'saving' || !!yamlParseError}
                          className="flex-1 px-3 py-2 rounded-lg bg-sky-600 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-40 transition-colors"
                        >
                          {saveState === 'saving' ? 'Saving…' : 'Validate & Save'}
                        </button>
                        <button
                          type="button"
                          onClick={() => { handleAdvancedYamlChange(originalYamlRef.current); setYamlAdvanced(false); setYamlParseError(null); setYamlValidError(null) }}
                          className="px-3 py-2 rounded-lg border border-slate-700 text-sm text-slate-300 hover:bg-slate-800 transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex-1 overflow-y-auto p-4">
                    <pre className="text-xs font-mono leading-5 select-all whitespace-pre">
                      <ColorizedYaml yaml={previewYaml} colorizeListItems={false} />
                    </pre>
                  </div>
                )}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
