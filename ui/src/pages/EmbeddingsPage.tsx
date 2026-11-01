import { useAdjustOnChange } from '../hooks/useAdjustOnChange'
/**
 * EmbeddingsPage — manage the models/embeddings.yaml registry.
 *
 * Displays all registered embedding configurations and lets developers
 * create, edit, or delete entries.  Saves the whole file as a single
 * EmbeddingRegistry YAML via the standard model file API.
 */
import { dump } from 'js-yaml'
import { useState, useRef } from 'react'
import { TopBar } from '../components/TopBar'
import { ColorizedYaml } from '../components/ColorizedYaml'
import { parseYaml } from '../lib/yaml'
import { useSaveFile, useRegistryFile, useVectorStatus, usePgDatasources, useUpdateVectorDatasource } from '../queries'
import type { EmbeddingEntry, EmbeddingRegistryFile } from '../types'
import { SidebarHeader } from '../components/SidebarHeader'
import { EmptyPanel } from '../components/EmptyPanel'

// ── Embedding provider presets ────────────────────────────────────────────────

interface Preset { label: string; model: string; dimensions: number }
const EMBEDDING_PRESETS: Preset[] = [
  // OpenAI
  { label: 'OpenAI text-embedding-3-large', model: 'openai/text-embedding-3-large', dimensions: 3072 },
  { label: 'OpenAI text-embedding-3-small', model: 'openai/text-embedding-3-small', dimensions: 1536 },
  { label: 'OpenAI text-embedding-ada-002', model: 'openai/text-embedding-ada-002', dimensions: 1536 },
  // Voyage AI
  { label: 'Voyage voyage-3-large', model: 'voyage/voyage-3-large', dimensions: 1024 },
  { label: 'Voyage voyage-3', model: 'voyage/voyage-3', dimensions: 1024 },
  { label: 'Voyage voyage-3-lite', model: 'voyage/voyage-3-lite', dimensions: 512 },
  { label: 'Voyage voyage-code-3', model: 'voyage/voyage-code-3', dimensions: 1024 },
  // Cohere
  { label: 'Cohere embed-v4.0', model: 'cohere/embed-v4.0', dimensions: 1536 },
  { label: 'Cohere embed-english-v3.0', model: 'cohere/embed-english-v3.0', dimensions: 1024 },
  { label: 'Cohere embed-multilingual-v3.0', model: 'cohere/embed-multilingual-v3.0', dimensions: 1024 },
  // Google
  { label: 'Gemini gemini-embedding-001', model: 'gemini/gemini-embedding-001', dimensions: 768 },
  // Mistral
  { label: 'Mistral mistral-embed', model: 'mistral/mistral-embed', dimensions: 1024 },
  // Ollama (local)
  { label: 'Ollama nomic-embed-text', model: 'ollama/nomic-embed-text', dimensions: 768 },
  { label: 'Ollama mxbai-embed-large', model: 'ollama/mxbai-embed-large', dimensions: 1024 },
  { label: 'Ollama bge-m3', model: 'ollama/bge-m3', dimensions: 1024 },
  { label: 'Ollama snowflake-arctic-embed', model: 'ollama/snowflake-arctic-embed', dimensions: 1024 },
  { label: 'Custom…', model: '', dimensions: 1536 },
]

// ── Empty form state ──────────────────────────────────────────────────────────

/** Shape of a single-entry embedding YAML doc, as hand-edited in Advanced mode. */
interface EmbeddingYamlDoc {
  metadata?: { name?: string }
  spec?: { provider?: string; model?: string; dimensions?: number; api_base?: string; api_key?: string }
}

const EMPTY_ENTRY: EmbeddingEntry = {
  name: '',
  provider: '',
  model: 'openai/text-embedding-3-small',
  dimensions: 1536,
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function EmbeddingsPage() {
  const { data: registryData, isLoading: loading } = useRegistryFile<EmbeddingRegistryFile | null>(
    'models',
    'embeddings.yaml',
  )
  const [entries, setEntries] = useState<EmbeddingEntry[]>([])
  const [selected, setSelected] = useState<EmbeddingEntry | null>(null)
  const [form, setForm] = useState<EmbeddingEntry>(EMPTY_ENTRY)
  const [isNew, setIsNew] = useState(false)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [toast, setToast] = useState<string | null>(null)

  const saveMutation = useSaveFile()
  const { data: vectorStatus } = useVectorStatus()
  const { data: pgDsInfo } = usePgDatasources()
  const updateVectorDs = useUpdateVectorDatasource()
  const [selectedVectorDs, setSelectedVectorDs] = useState<string>('')
  const [dsRestartHint, setDsRestartHint] = useState(false)

  // Keep selector in sync with the server-reported current datasource.
  const currentVectorDs = pgDsInfo?.current_vector_datasource
  useAdjustOnChange([currentVectorDs], () => {
    if (currentVectorDs && !selectedVectorDs) setSelectedVectorDs(currentVectorDs)
  })

  // Sync the local list from the registry query — on initial load, and again
  // whenever a save/delete (here or elsewhere) invalidates the cache. Done
  // during render (React's documented "adjust state when a value changes"
  // pattern), not in an effect, so it settles in the same commit.
  const [seenRegistryData, setSeenRegistryData] = useState(registryData)
  const [hydrated, setHydrated] = useState(false)
  if (registryData !== seenRegistryData) {
    setSeenRegistryData(registryData)
    if (registryData !== undefined) {
      const list = registryData?.spec?.embeddings ?? []
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

  function buildEntryYaml(entry: EmbeddingEntry): object {
    return {
      kind: 'EmbeddingConfig',
      version: 'v1',
      metadata: { name: entry.name || 'new-embedding' },
      spec: {
        provider: entry.provider,
        model: entry.model,
        dimensions: entry.dimensions,
        ...(entry.api_base ? { api_base: entry.api_base } : {}),
        ...(entry.api_key ? { api_key: entry.api_key } : {}),
      },
    }
  }

  function buildRegistryYaml(list: EmbeddingEntry[]): object {
    return {
      kind: 'EmbeddingRegistry',
      version: 'v1',
      metadata: { name: 'embeddings' },
      spec: {
        embeddings: list.map((e) => ({
          name: e.name.trim(),
          provider: e.provider.trim(),
          model: e.model.trim(),
          dimensions: Number(e.dimensions) || 1536,
          ...(e.api_base?.trim() ? { api_base: e.api_base.trim() } : {}),
          ...(e.api_key?.trim() ? { api_key: e.api_key.trim() } : {}),
        })),
      },
    }
  }

  async function persistEntries(list: EmbeddingEntry[]) {
    setSaveState('saving')
    try {
      await saveMutation.mutateAsync({ kind: 'models', name: 'embeddings.yaml', body: buildRegistryYaml(list) })
      setSaveState('saved')
      setTimeout(() => setSaveState('idle'), 1500)
    } catch {
      setSaveState('error')
      setTimeout(() => setSaveState('idle'), 2000)
    }
  }

  function handleSelectEntry(entry: EmbeddingEntry) {
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
    const trimmed = { ...form, name: form.name.trim(), model: form.model.trim(), provider: form.provider.trim() }
    if (!trimmed.name) { showToast('Name is required'); return }
    if (!trimmed.model) { showToast('Model string is required'); return }

    let updated: EmbeddingEntry[]
    if (isNew) {
      if (entries.some((e) => e.name === trimmed.name)) {
        showToast(`Embedding '${trimmed.name}' already exists`)
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

  function applyPreset(preset: Preset) {
    setForm((f) => ({
      ...f,
      model: preset.model,
      dimensions: preset.dimensions,
      provider: preset.model.split('/')[0] ?? '',
    }))
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
      const parsed = parseYaml<EmbeddingYamlDoc>(text)
      setForm({
        name: String(parsed?.metadata?.name ?? ''),
        provider: String(parsed?.spec?.provider ?? ''),
        model: String(parsed?.spec?.model ?? ''),
        dimensions: Number(parsed?.spec?.dimensions) || 1536,
        api_base: parsed?.spec?.api_base ? String(parsed.spec.api_base) : undefined,
        api_key: parsed?.spec?.api_key ? String(parsed.spec.api_key) : undefined,
      })
      setYamlParseError(null)
    } catch (err: unknown) {
      setYamlParseError(err instanceof Error ? err.message : 'Invalid YAML')
    }
  }

  async function handleAdvancedSave() {
    if (yamlParseError) { setYamlValidError('Fix YAML syntax errors before saving.'); return }
    const trimmed = { ...form, name: form.name.trim(), model: form.model.trim(), provider: form.provider.trim() }
    if (!trimmed.name) { setYamlValidError('metadata.name is required.'); return }
    if (!trimmed.model) { setYamlValidError('spec.model is required.'); return }
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

  // ── Input style helpers ───────────────────────────────────────────────────
  const inputCls = 'w-full rounded border border-slate-700 bg-slate-800/80 px-2 py-1.5 text-xs text-slate-100 outline-none focus:ring-1 focus:border-sky-500 focus:ring-sky-500/30'
  const labelCls = 'block text-[10px] font-medium text-slate-400 mb-0.5'

  return (
    <div className="flex flex-col h-full">
      <TopBar title="Embeddings" subtitle="models/embeddings.yaml" />

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
            Embeddings can still be configured here but the tuvl.data_ingest and tuvl.data_search steps will not run until pgvector is installed on the PostgreSQL server.
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

      {pgDsInfo && pgDsInfo.datasources.length === 1 && (
        <div className="shrink-0 flex items-center gap-2 px-4 py-2 bg-slate-800/60 border-b border-slate-700 text-xs text-slate-400">
          <span className="shrink-0">🗄</span>
          <span>Vector storage datasource: <span className="text-slate-200 font-medium">{pgDsInfo.current_vector_datasource}</span></span>
        </div>
      )}

      {pgDsInfo && pgDsInfo.datasources.length > 1 && (
        <div className="shrink-0 flex items-center gap-3 px-4 py-2 bg-slate-800/60 border-b border-slate-700 text-xs">
          <span className="text-slate-400 shrink-0">Vector storage datasource:</span>
          <select
            value={selectedVectorDs}
            onChange={(e) => { setSelectedVectorDs(e.target.value); setDsRestartHint(false) }}
            className="rounded border border-slate-600 bg-slate-900 px-2 py-1 text-xs text-slate-200 outline-none focus:border-sky-500"
          >
            {pgDsInfo.datasources.map((ds) => (
              <option key={ds} value={ds}>{ds}</option>
            ))}
          </select>
          <button
            disabled={updateVectorDs.isPending || selectedVectorDs === pgDsInfo.current_vector_datasource}
            onClick={async () => {
              await updateVectorDs.mutateAsync(selectedVectorDs)
              setDsRestartHint(true)
            }}
            className="px-2.5 py-1 rounded bg-sky-700 hover:bg-sky-600 text-white disabled:opacity-40 transition-colors"
          >
            {updateVectorDs.isPending ? 'Saving…' : 'Apply'}
          </button>
          {selectedVectorDs === pgDsInfo.current_vector_datasource && (
            <span className="text-slate-500 italic">current</span>
          )}
          {dsRestartHint && (
            <span className="text-amber-400">✓ Saved — restart the server to apply</span>
          )}
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* ── Left sidebar: listing ─────────────────────────────────────── */}
        <aside className="w-56 shrink-0 border-r border-slate-700 bg-slate-900 flex flex-col">
          <SidebarHeader title="Embeddings" onNew={handleNew} newLabel="New embedding" />

          {loading ? (
            <div className="px-3 py-4 text-xs text-slate-500">Loading…</div>
          ) : entries.length === 0 ? (
            <div className="px-3 py-4 text-xs text-slate-500 italic">No embeddings defined</div>
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
                  <div className="text-[10px] text-slate-500 truncate">{e.model}</div>
                </button>
              ))}
            </nav>
          )}
        </aside>

        {/* ── Centre: form ──────────────────────────────────────────────── */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {(!selected && !isNew) ? (
            <EmptyPanel
              icon="embedding"
              title="No embedding selected"
              description="An embedding turns text into vectors for search. Collections use one to index and find passages."
              actionLabel="New Embedding"
              onAction={handleNew}
            />
          ) : (
            <div className="flex flex-1 overflow-hidden">
              {/* Form */}
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                <div className="text-xs font-semibold text-slate-300 mb-2 uppercase tracking-wide">
                  {isNew ? 'New Embedding' : `Edit: ${selected?.name}`}
                </div>

                {/* Preset picker */}
                <div>
                  <label className={labelCls}>Quick Presets</label>
                  <div className="flex flex-wrap gap-1.5">
                    {EMBEDDING_PRESETS.map((p) => (
                      <button
                        key={p.label}
                        onClick={() => applyPreset(p)}
                        className="px-2 py-1 text-[10px] rounded border border-slate-600 bg-slate-800 text-slate-300 hover:bg-slate-700 truncate max-w-[160px]"
                        title={p.model || 'Custom'}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Name */}
                <div>
                  <label className={labelCls}>Name <span className="text-red-400">*</span></label>
                  <input
                    className={inputCls}
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                    placeholder="text-embedding-3-small"
                    disabled={!isNew}
                  />
                  {!isNew && (
                    <p className="text-[10px] text-slate-500 mt-0.5">
                      Rename by deleting and re-creating this entry.
                    </p>
                  )}
                </div>

                {/* Provider */}
                <div>
                  <label className={labelCls}>Provider</label>
                  <input
                    className={inputCls}
                    value={form.provider}
                    onChange={(e) => setForm((f) => ({ ...f, provider: e.target.value }))}
                    placeholder="openai"
                  />
                </div>

                {/* Model string */}
                <div>
                  <label className={labelCls}>Model (provider/model) <span className="text-red-400">*</span></label>
                  <input
                    className={inputCls}
                    value={form.model}
                    onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}
                    placeholder="openai/text-embedding-3-small"
                  />
                  <p className="text-[10px] text-slate-500 mt-0.5">
                    OpenAI, Gemini, Ollama, Cohere, Voyage or another OpenAI-compatible embeddings endpoint
                  </p>
                </div>

                {/* Endpoint */}
                <div>
                  <label className={labelCls}>API Base URL</label>
                  <input
                    className={inputCls}
                    value={form.api_base ?? ''}
                    onChange={(e) => setForm((f) => ({ ...f, api_base: e.target.value }))}
                    placeholder="https://gateway.example.com/v1"
                    spellCheck={false}
                  />
                  <p className="text-[10px] text-slate-500 mt-0.5">Optional — a gateway or proxy. Leave blank for the provider default.</p>
                </div>
                <div>
                  <label className={labelCls}>API Key</label>
                  <input
                    className={inputCls}
                    value={form.api_key ?? ''}
                    onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                    placeholder="${GATEWAY_API_KEY}"
                    spellCheck={false}
                  />
                  <p className="text-[10px] text-slate-500 mt-0.5">An {'${ENV_VAR}'} reference. Blank uses the provider's key variable.</p>
                </div>

                {/* Dimensions */}
                <div>
                  <label className={labelCls}>Dimensions <span className="text-red-400">*</span></label>
                  <input
                    type="number"
                    className={inputCls}
                    value={form.dimensions}
                    onChange={(e) => setForm((f) => ({ ...f, dimensions: parseInt(e.target.value, 10) || 1536 }))}
                    placeholder="1536"
                    min={1}
                  />
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
