import { useDisabledNames } from '../hooks/useAdjustOnChange'
import { dump } from 'js-yaml'
import { useEffect, useRef, useState } from 'react'
import { TopBar } from '../components/TopBar'
import { ColorizedYaml } from '../components/ColorizedYaml'
import { parseYaml } from '../lib/yaml'
import { useResizablePanel } from '../hooks/useResizablePanel'
import { useFilesIndex, useAgentModel, useSaveFile, useDeleteFile } from '../queries'
import type { AgentModelConfig } from '../types'

// ── Common model presets ─────────────────────────────────────────────────────

const MODEL_PRESETS = [
  // Anthropic (newest first)
  'anthropic/claude-opus-4-7',
  'anthropic/claude-opus-4-6',
  'anthropic/claude-opus-4-5',
  'anthropic/claude-sonnet-4-6',
  'anthropic/claude-sonnet-4-5',
  'anthropic/claude-haiku-4-5-20251001',
  'anthropic/claude-3-7-sonnet-20250219',
  'anthropic/claude-3-5-sonnet-20241022',
  'anthropic/claude-3-5-haiku-20241022',
  'anthropic/claude-3-haiku-20240307',
  // OpenAI
  'openai/gpt-5',
  'openai/gpt-5-mini',
  'openai/gpt-5-nano',
  'openai/gpt-4.1',
  'openai/gpt-4.1-mini',
  'openai/gpt-4.1-nano',
  'openai/gpt-4o',
  'openai/gpt-4o-mini',
  'openai/o3',
  'openai/o3-mini',
  'openai/o4-mini',
  'openai/gpt-3.5-turbo',
  // Google Gemini (newest first)
  'gemini/gemini-3.5-pro',
  'gemini/gemini-3.5-flash',
  'gemini/gemini-3.5-flash-lite',
  'gemini/gemini-3.1-flash-lite',
  'gemini/gemini-3-pro',
  'gemini/gemini-2.5-pro',
  'gemini/gemini-2.5-flash-lite',
  'gemini/gemini-2.0-flash',
  'gemini/gemini-2.0-flash-lite',
  'gemini/gemini-1.5-pro',
  'gemini/gemini-1.5-flash',
  // xAI (Grok)
  'xai/grok-4',
  'xai/grok-3',
  'xai/grok-3-mini',
  'xai/grok-2',
  // Groq (fast inference)
  'groq/llama-3.3-70b-versatile',
  'groq/llama-3.1-8b-instant',
  'groq/deepseek-r1-distill-llama-70b',
  'groq/qwen-2.5-32b',
  'groq/llama-3.1-70b-versatile',
  // DeepSeek
  'deepseek/deepseek-chat',
  'deepseek/deepseek-reasoner',
  // Mistral
  'mistral/mistral-large-latest',
  'mistral/mistral-small-latest',
  'mistral/codestral-latest',
  // Ollama (local — newest first)
  'ollama/llama3.3',
  'ollama/llama3.2',
  'ollama/llama3.1',
  'ollama/llama3',
  'ollama/qwen2.5',
  'ollama/qwen2.5-coder',
  'ollama/deepseek-r1',
  'ollama/phi4',
  'ollama/phi3',
  'ollama/gemma3',
  'ollama/gemma2',
  'ollama/mistral',
  'ollama/codellama',
]

// ── Provider hints ────────────────────────────────────────────────────────────

function getProviderHint(model: string): { apiBasePlaceholder: string; apiKeyPlaceholder: string } {
  if (model.startsWith('ollama/') || model.startsWith('ollama_chat/')) {
    return { apiBasePlaceholder: 'http://localhost:11434', apiKeyPlaceholder: '' }
  }
  if (model.startsWith('openai/')) {
    return { apiBasePlaceholder: '', apiKeyPlaceholder: '${OPENAI_API_KEY}' }
  }
  if (model.startsWith('anthropic/')) {
    return { apiBasePlaceholder: '', apiKeyPlaceholder: '${ANTHROPIC_API_KEY}' }
  }
  if (model.startsWith('groq/')) {
    return { apiBasePlaceholder: '', apiKeyPlaceholder: '${GROQ_API_KEY}' }
  }
  if (model.startsWith('gemini/')) {
    return { apiBasePlaceholder: '', apiKeyPlaceholder: '${GEMINI_API_KEY}' }
  }
  if (model.startsWith('xai/')) {
    return { apiBasePlaceholder: '', apiKeyPlaceholder: '${XAI_API_KEY}' }
  }
  if (model.startsWith('deepseek/')) {
    return { apiBasePlaceholder: '', apiKeyPlaceholder: '${DEEPSEEK_API_KEY}' }
  }
  if (model.startsWith('cohere/')) {
    return { apiBasePlaceholder: '', apiKeyPlaceholder: '${COHERE_API_KEY}' }
  }
  if (model.startsWith('azure/')) {
    return { apiBasePlaceholder: 'https://<resource>.openai.azure.com/openai/v1', apiKeyPlaceholder: '${AZURE_OPENAI_API_KEY}' }
  }
  if (model.startsWith('bedrock/')) {
    return { apiBasePlaceholder: 'https://bedrock-runtime.<region>.amazonaws.com/openai/v1', apiKeyPlaceholder: '${AWS_BEARER_TOKEN_BEDROCK}' }
  }
  if (model.startsWith('vertex_ai/')) {
    return { apiBasePlaceholder: '', apiKeyPlaceholder: '${VERTEX_ACCESS_TOKEN}' }
  }
  if (model.startsWith('mistral/')) {
    return { apiBasePlaceholder: '', apiKeyPlaceholder: '${MISTRAL_API_KEY}' }
  }
  return { apiBasePlaceholder: '', apiKeyPlaceholder: '' }
}

// ── Form state ────────────────────────────────────────────────────────────────

/** Shape of a hand-edited AgentModel YAML doc. Accepts both the current
 *  spec-nested format and the legacy flat format (mirrors AgentModelConfig). */
interface AgentModelYamlDoc {
  enabled?: boolean
  metadata?: { name?: string; description?: string }
  spec?: {
    type?: string
    provider?: string
    model?: string
    api_base?: string
    api_key?: string
    temperature?: number
    max_tokens?: number
    timeout?: number
  }
  type?: string
  provider?: string
  model?: string
  api_base?: string
  api_key?: string
  temperature?: number
  max_tokens?: number
  timeout?: number
}

type ModelType = 'llm' | 'decision'
type DecisionProvider = 'laya' | 'jev' | 'llm'

const DECISION_PROVIDERS: { key: DecisionProvider; hint: string; placeholder: string }[] = [
  { key: 'laya', hint: 'Self-hosted Laya (laya-serve container). Model: auto, english, multilingual or typed-decisions; set the API base.', placeholder: 'auto' },
  { key: 'jev', hint: 'TypeSafe Jev (hosted). Pin a version, never "latest"; set the API base.', placeholder: 'jev-1.13.0' },
  { key: 'llm', hint: 'Any LLM, or a hosted decision model behind an OpenAI-compatible endpoint (openai/<name> + API base). It returns the decision and its confidence.', placeholder: 'gemini/gemini-3.1-flash-lite' },
]

interface FormState {
  type: ModelType
  provider: DecisionProvider
  name: string
  description: string
  enabled: boolean
  model: string
  apiBase: string
  apiKey: string
  temperature: string   // keep as string to allow empty
  maxTokens: string
  timeout: string
}

const DEFAULT_FORM: FormState = {
  type: 'llm',
  provider: 'laya',
  name: '',
  description: '',
  enabled: true,
  model: 'ollama/llama3',
  apiBase: '',
  apiKey: '',
  temperature: '0.7',
  maxTokens: '',
  timeout: '60',
}

function configToForm(cfg: AgentModelConfig): FormState {
  // Support both new format (spec block) and legacy flat format
  const s = cfg.spec ?? cfg as Partial<AgentModelConfig>
  return {
    type: cfg.spec?.type === 'decision' ? 'decision' : 'llm',
    provider: cfg.spec?.provider === 'litellm' ? 'llm' : ((cfg.spec?.provider as DecisionProvider | undefined) ?? 'laya'),
    name: cfg.metadata.name,
    description: cfg.metadata.description ?? '',
    enabled: cfg.enabled !== false,
    model: s.model ?? '',
    apiBase: s.api_base ?? '',
    apiKey: s.api_key ?? '',
    temperature: s.temperature != null ? String(s.temperature) : '',
    maxTokens: s.max_tokens != null ? String(s.max_tokens) : '',
    timeout: s.timeout != null ? String(s.timeout) : '60',
  }
}

function formToYaml(f: FormState): object {
  const spec: Record<string, unknown> = f.type === 'decision'
    ? { type: 'decision', provider: f.provider, model: f.model }
    : { model: f.model || 'ollama/llama3' }
  if (f.type === 'decision') {
    if (f.apiBase) spec.api_base = f.apiBase
    if (f.apiKey) spec.api_key = f.apiKey
    return {
      kind: 'AgentModel',
      enabled: f.enabled,
      metadata: { name: f.name || 'my_model', ...(f.description ? { description: f.description } : {}) },
      spec,
    }
  }
  if (f.apiBase) spec.api_base = f.apiBase
  if (f.apiKey) spec.api_key = f.apiKey
  if (f.temperature !== '') spec.temperature = parseFloat(f.temperature)
  if (f.maxTokens !== '') spec.max_tokens = parseInt(f.maxTokens, 10)
  if (f.timeout !== '' && f.timeout !== '60') spec.timeout = parseInt(f.timeout, 10)
  return {
    kind: 'AgentModel',
    version: 'v1',
    enabled: f.enabled,
    metadata: {
      name: f.name || 'my_model',
      ...(f.description ? { description: f.description } : {}),
    },
    spec,
  }
}

// ── AgentModelForm ────────────────────────────────────────────────────────────

function AgentModelForm({
  initialData,
  existingFileName,
  onSaved,
  onDeleted,
  onCancel,
}: {
  initialData?: AgentModelConfig
  existingFileName?: string
  onSaved: (filename: string) => void
  onDeleted: () => void
  onCancel: () => void
}) {
  const save = useSaveFile()
  const del = useDeleteFile()
  const [form, setForm] = useState<FormState>(
    initialData ? configToForm(initialData) : DEFAULT_FORM,
  )
  const [savedForm, setSavedForm] = useState<FormState>(
    initialData ? configToForm(initialData) : DEFAULT_FORM,
  )
  const [error, setError] = useState<string | null>(null)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved'>('idle')
  const [advanced, setAdvanced] = useState(false)
  const [rawYaml, setRawYaml] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)
  const { width: yamlWidth, handleMouseDown: yamlDragStart } = useResizablePanel(288)
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const originalYamlRef = useRef('')

  const isDirty = JSON.stringify(form) !== JSON.stringify(savedForm)

  useEffect(() => () => { if (savedTimerRef.current) clearTimeout(savedTimerRef.current) }, [])

  const set = <K extends keyof FormState>(k: K) =>
    (val: FormState[K]) => setForm((f) => ({ ...f, [k]: val }))

  const hint = getProviderHint(form.model)
  const yamlObj = formToYaml(form)
  const yamlStr = dump(yamlObj, { lineWidth: -1 })

  const handleSave = async () => {
    setError(null)
    if (!form.name.trim()) { setError('Name is required.'); return }
    if (!form.model.trim()) { setError('Model is required.'); return }
    const filename = `${form.name.trim().replace(/\s+/g, '_').toLowerCase()}.yaml`
    try {
      await save.mutateAsync({ kind: 'llms', name: filename, body: yamlObj })
      setSavedForm(form)
      setSaveStatus('saved')
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current)
      savedTimerRef.current = setTimeout(() => setSaveStatus('idle'), 2500)
      onSaved(filename)
    } catch {
      setError('Failed to save. Is the engine running?')
    }
  }

  const handleDelete = async () => {
    if (!existingFileName) return
    if (!confirm(`Delete ${existingFileName}?`)) return
    try {
      await del.mutateAsync({ kind: 'llms', name: existingFileName })
      onDeleted()
    } catch {
      setError('Failed to delete.')
    }
  }

  const handleEnterAdvanced = () => {
    originalYamlRef.current = yamlStr
    setRawYaml(yamlStr)
    setParseError(null)
    setAdvanced(true)
  }

  const handleYamlChange = (text: string) => {
    setRawYaml(text)
    setParseError(null)
    try {
      const parsed = parseYaml<AgentModelYamlDoc>(text)
      if (parsed && typeof parsed === 'object') {
        // Support both new format (spec block) and legacy flat format
        const s = parsed?.spec ?? parsed
        setForm({
          type: s?.type === 'decision' ? 'decision' : 'llm',
          provider: s?.provider === 'litellm' ? 'llm' : ((s?.provider as DecisionProvider | undefined) ?? form.provider),
          name: String(parsed?.metadata?.name ?? form.name),
          description: String(parsed?.metadata?.description ?? ''),
          enabled: parsed?.enabled !== false,
          model: String(s?.model ?? form.model),
          apiBase: String(s?.api_base ?? ''),
          apiKey: String(s?.api_key ?? ''),
          temperature: s?.temperature != null ? String(s.temperature) : '',
          maxTokens: s?.max_tokens != null ? String(s.max_tokens) : '',
          timeout: s?.timeout != null ? String(s.timeout) : '60',
        })
      }
    } catch (e: unknown) {
      setParseError(e instanceof Error ? e.message : 'Invalid YAML')
    }
  }

  const handleAdvancedSave = async () => {
    if (parseError) return
    setError(null)
    try {
      const parsed = parseYaml<AgentModelYamlDoc>(rawYaml)
      const name = String(parsed?.metadata?.name ?? '').trim()
      if (!name) { setError('metadata.name is required.'); return }
      const filename = `${name.replace(/\s+/g, '_').toLowerCase()}.yaml`
      await save.mutateAsync({ kind: 'llms', name: filename, body: parsed })
      setSavedForm(form)
      setSaveStatus('saved')
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current)
      savedTimerRef.current = setTimeout(() => setSaveStatus('idle'), 2500)
      onSaved(filename)
    } catch {
      setError('Failed to save. Check YAML is valid and engine is running.')
    }
  }

  const inputCls =
    'w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500/30'
  const monoInputCls = inputCls + ' font-mono'
  const labelCls = 'block text-xs font-medium text-slate-400 mb-1.5'

  return (
    <div className="flex flex-1 min-h-0">
      {/* ── Form ── */}
      <div className="flex-1 min-w-0 overflow-y-auto p-6">
        <div className="max-w-xl space-y-6">

          {/* Identity */}
          <section>
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-3">Identity</h3>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelCls}>Name <span className="text-rose-500">*</span></label>
                  <input
                    type="text"
                    value={form.name}
                    onChange={(e) => set('name')(e.target.value)}
                    placeholder="llama3_local"
                    className={monoInputCls}
                    disabled={!!existingFileName}
                    spellCheck={false}
                  />
                  <p className="mt-1 text-[10px] text-slate-600">snake_case · used as filename</p>
                </div>
                <div>
                  <label className={labelCls}>Description</label>
                  <input
                    type="text"
                    value={form.description}
                    onChange={(e) => set('description')(e.target.value)}
                    placeholder="Local Llama 3 via Ollama"
                    className={inputCls}
                  />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  role="switch"
                  aria-checked={form.enabled}
                  onClick={() => set('enabled')(!form.enabled)}
                  className={`relative inline-flex h-4 w-7 rounded-full transition-colors ${form.enabled ? 'bg-emerald-500' : 'bg-rose-600/80'}`}
                >
                  <span className={`absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform ${form.enabled ? 'translate-x-3' : 'translate-x-0'}`} />
                </button>
                <span className={`text-sm ${form.enabled ? 'text-slate-300' : 'text-rose-400'}`}>
                  {form.enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
            </div>
          </section>

          {/* Model */}
          <section>
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-3">Model</h3>
            <div className="mb-3 inline-flex rounded-lg border border-slate-700 p-0.5 text-xs" role="radiogroup" aria-label="Model type">
              {(['llm', 'decision'] as const).map((t) => (
                <button key={t} type="button" role="radio" aria-checked={form.type === t}
                  onClick={() => setForm((f) => ({ ...f, type: t, model: f.model === DEFAULT_FORM.model && t === 'decision' ? '' : f.model }))}
                  className={`rounded-md px-3 py-1 ${form.type === t ? 'bg-violet-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}>
                  {t === 'llm' ? 'LLM' : 'Decision'}
                </button>
              ))}
            </div>
            {form.type === 'decision' ? (
              <div className="space-y-3">
                <p className="text-[11px] text-slate-500">
                  A typed-decision model for <span className="font-mono">decide.model.ref</span>: it picks one value of the
                  agent's enum output with a confidence. No prompt, no free text.
                </p>
                <div>
                  <label className={labelCls}>Provider <span className="text-rose-500">*</span></label>
                  <select value={form.provider} onChange={(e) => set('provider')(e.target.value as DecisionProvider)} className={monoInputCls}>
                    {DECISION_PROVIDERS.map((p) => <option key={p.key} value={p.key}>{p.key}</option>)}
                  </select>
                  <p className="mt-1 text-[10px] text-slate-600">{DECISION_PROVIDERS.find((p) => p.key === form.provider)?.hint}</p>
                </div>
                <div>
                  <label className={labelCls}>Model <span className="text-rose-500">*</span></label>
                  <input type="text" value={form.model} onChange={(e) => set('model')(e.target.value)}
                    placeholder={DECISION_PROVIDERS.find((p) => p.key === form.provider)?.placeholder}
                    className={monoInputCls} spellCheck={false} />
                  <p className="mt-1 text-[10px] text-slate-600">Pinned in tuvl.lock</p>
                </div>
                <div>
                  <label className={labelCls}>API Base URL</label>
                  <input type="text" value={form.apiBase} onChange={(e) => set('apiBase')(e.target.value)}
                    placeholder={form.provider === 'laya' ? '${LAYA_API_BASE:http://localhost:8000}' : 'https://decisions.example.com/v1'} className={monoInputCls} spellCheck={false} />
                  <p className="mt-1 text-[10px] text-slate-600">Required for laya and jev (the System One server); optional for llm.</p>
                </div>
                <div>
                  <label className={labelCls}>API Key</label>
                  <input type="text" value={form.apiKey} onChange={(e) => set('apiKey')(e.target.value)}
                    placeholder={'${DECISION_API_KEY}'} className={monoInputCls} spellCheck={false} />
                  <p className="mt-1 text-[10px] text-slate-600">
                    Must be an <span className="font-mono text-slate-500">{'${ENV_VAR}'}</span> reference — a literal key is refused.
                  </p>
                </div>
              </div>
            ) : (
            <div className="space-y-3">
              <div>
                <label className={labelCls}>LLM Model string <span className="text-rose-500">*</span></label>
                <input
                  type="text"
                  list="model-presets"
                  value={form.model}
                  onChange={(e) => set('model')(e.target.value)}
                  placeholder="ollama/llama3"
                  className={monoInputCls}
                  spellCheck={false}
                />
                <datalist id="model-presets">
                  {MODEL_PRESETS.map((m) => <option key={m} value={m} />)}
                </datalist>
                <p className="mt-1 text-[10px] text-slate-600">
                  model id — format: <span className="font-mono text-slate-500">provider/model-name</span>
                </p>
              </div>

              <div>
                <label className={labelCls}>API Base URL</label>
                <input
                  type="text"
                  value={form.apiBase}
                  onChange={(e) => set('apiBase')(e.target.value)}
                  placeholder={hint.apiBasePlaceholder || 'http://localhost:11434 (Ollama) or proxy URL'}
                  className={monoInputCls}
                  spellCheck={false}
                />
                <p className="mt-1 text-[10px] text-slate-600">
                  Required for Ollama and other self-hosted or gateway endpoints. Leave blank to use provider default.
                </p>
              </div>

              <div>
                <label className={labelCls}>API Key</label>
                <input
                  type="text"
                  value={form.apiKey}
                  onChange={(e) => set('apiKey')(e.target.value)}
                  placeholder={hint.apiKeyPlaceholder || '${YOUR_API_KEY}'}
                  className={monoInputCls}
                  spellCheck={false}
                />
                <p className="mt-1 text-[10px] text-slate-600">
                  Use <span className="font-mono text-slate-500">{'${ENV_VAR_NAME}'}</span> to reference environment variables.
                </p>
              </div>
            </div>
            )}
          </section>

          {/* Parameters */}
          {form.type === 'llm' && <section>
            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-3">Parameters</h3>
            <div className="space-y-3">
              <div>
                <label className={labelCls}>
                  Temperature{' '}
                  <span className="text-slate-500 font-normal">
                    {form.temperature !== '' ? parseFloat(form.temperature).toFixed(1) : '—'}
                  </span>
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min="0"
                    max="2"
                    step="0.1"
                    value={form.temperature !== '' ? form.temperature : '0.7'}
                    onChange={(e) => set('temperature')(e.target.value)}
                    className="flex-1 accent-violet-500"
                  />
                  <input
                    type="number"
                    min="0"
                    max="2"
                    step="0.1"
                    value={form.temperature}
                    onChange={(e) => set('temperature')(e.target.value)}
                    placeholder="0.7"
                    className="w-20 rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-100 outline-none focus:border-violet-500 text-center"
                  />
                </div>
                <div className="flex justify-between text-[10px] text-slate-600 mt-0.5 px-0.5">
                  <span>0 · Deterministic</span>
                  <span>2 · Creative</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelCls}>Max Tokens</label>
                  <input
                    type="number"
                    min="1"
                    value={form.maxTokens}
                    onChange={(e) => set('maxTokens')(e.target.value)}
                    placeholder="2048 (model default)"
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className={labelCls}>Timeout (seconds)</label>
                  <input
                    type="number"
                    min="1"
                    value={form.timeout}
                    onChange={(e) => set('timeout')(e.target.value)}
                    placeholder="60"
                    className={inputCls}
                  />
                </div>
              </div>
            </div>
          </section>}

          {/* Actions */}
          {error && <p className="text-xs text-rose-400">{error}</p>}
          <div className="flex items-center gap-3 pt-2">
            <button
              type="button"
              onClick={handleSave}
              disabled={save.isPending || !isDirty}
              className={`px-5 py-2 rounded-lg text-sm font-semibold transition-colors ${
                saveStatus === 'saved'
                  ? 'bg-emerald-700 text-emerald-100 cursor-default'
                  : isDirty
                  ? 'bg-violet-600 text-slate-100 hover:bg-violet-500 disabled:opacity-40'
                  : 'bg-slate-700 text-slate-500 cursor-not-allowed'
              }`}
            >
              {save.isPending ? 'Saving…' : saveStatus === 'saved' ? '✓ Saved' : 'Save'}
            </button>
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2 rounded-lg border border-slate-700 text-sm text-slate-300 hover:bg-slate-800 transition-colors"
            >
              Cancel
            </button>
            {existingFileName && (
              <button
                type="button"
                onClick={handleDelete}
                disabled={del.isPending}
                className="ml-auto px-4 py-2 rounded-lg text-sm text-rose-400 hover:text-rose-300 border border-rose-900 hover:border-rose-700 transition-colors"
              >
                {del.isPending ? 'Deleting…' : 'Delete'}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── YAML Panel ── */}
      <div style={{ width: yamlWidth }} className="shrink-0 relative border-l border-slate-800 flex flex-col">
        <div
          onMouseDown={yamlDragStart}
          className="absolute left-0 top-0 h-full w-1 cursor-col-resize hover:bg-violet-500/40 transition-colors z-10"
        />
        <div className="px-4 py-3 border-b border-slate-800 shrink-0 flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">YAML</span>
          <button
            type="button"
            onClick={advanced ? () => { setAdvanced(false); setError(null) } : handleEnterAdvanced}
            className={`text-xs px-2 py-1 rounded border transition-colors ${
              advanced
                ? 'border-sky-600 text-sky-400 bg-sky-900/20 hover:bg-sky-900/40'
                : 'border-slate-700 text-slate-500 hover:text-slate-300 hover:border-slate-600'
            }`}
          >
            {advanced ? '← Preview' : 'Advanced'}
          </button>
        </div>

        {advanced ? (
          <div className="flex flex-col flex-1 min-h-0">
            <textarea
              value={rawYaml}
              onChange={(e) => handleYamlChange(e.target.value)}
              className="flex-1 min-h-0 w-full resize-none bg-transparent p-4 text-xs font-mono text-slate-200 outline-none leading-5 focus:ring-1 focus:ring-inset focus:ring-sky-800"
              spellCheck={false}
              autoComplete="off"
            />
            <div className="flex-shrink-0 border-t border-slate-800 px-4 py-3 flex flex-col gap-2">
              {(parseError || error) && (
                <p className="text-xs text-rose-400 font-mono break-all">{parseError || error}</p>
              )}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleAdvancedSave}
                  disabled={save.isPending || !!parseError}
                  className="flex-1 px-3 py-2 rounded-lg bg-sky-600 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-40 transition-colors"
                >
                  {save.isPending ? 'Saving…' : 'Validate & Save'}
                </button>
                <button
                  type="button"
                  onClick={() => { handleYamlChange(originalYamlRef.current); setAdvanced(false); setError(null) }}
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
              <ColorizedYaml yaml={yamlStr} colorizeListItems={false} />
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}

// ── AgentModelsPage ───────────────────────────────────────────────────────────

export function AgentModelsPage() {
  const { data: index, isLoading } = useFilesIndex()
  const [selected, setSelected] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const { data: agentModel, isLoading: loadingModel } = useAgentModel(
    !creating && selected ? selected : '',
  )

  const disabledNames = useDisabledNames(selected, agentModel)

  const agentModels = index?.llms ?? []

  const handleSaved = (filename: string) => {
    setCreating(false)
    setSelected(filename)
  }

  const handleDeleted = () => {
    setSelected(null)
    setCreating(false)
  }

  const handleCancel = () => {
    if (creating) setCreating(false)
  }

  return (
    <div className="flex flex-col h-full">
      <TopBar title="AI Models" />
      <div className="flex flex-1 min-h-0">

        {/* Sidebar */}
        <aside className="w-52 shrink-0 border-r border-slate-800 flex flex-col">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 shrink-0">
            <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">AI Models</span>
            <button onClick={() => { setSelected(null); setCreating(true) }} title="New AI model"
              className="flex h-7 w-7 items-center justify-center rounded-md text-sky-400 hover:bg-sky-900/30 hover:text-sky-300 transition-colors text-xl leading-none">
              +
            </button>
          </div>
          <div className="flex-1 overflow-y-auto py-1 px-2">
            {isLoading && <p className="text-slate-400 text-xs px-2 py-1">Loading…</p>}
            {agentModels.length === 0 && !isLoading && (
              <p className="text-slate-500 text-xs px-2 py-2 leading-relaxed">
                No LLM configs yet.
              </p>
            )}
            {agentModels.map((name) => (
              <button
                key={name}
                onClick={() => { setSelected(name); setCreating(false) }}
                className={`w-full text-left px-3 py-2 rounded text-sm font-mono transition-colors ${
                  selected === name && !creating
                    ? 'bg-violet-700 text-slate-100'
                    : `text-slate-300 hover:bg-slate-800${disabledNames.has(name) ? ' opacity-50' : ''}`
                }`}
              >
                <span className="flex items-center gap-1.5">
                  <span className="flex-1 truncate">{name.replace('.yaml', '')}</span>
                  {disabledNames.has(name) && (
                    <span className="text-[9px] px-1 py-px rounded bg-rose-900/50 text-rose-400 border border-rose-800/50 leading-none">off</span>
                  )}
                </span>
              </button>
            ))}
          </div>
        </aside>

        {/* Main */}
        <main className="flex-1 min-w-0 flex flex-col">
          {!selected && !creating && (
            <div className="flex flex-col items-center justify-center h-full text-center px-6">
              <div className="mb-4 rounded-full border border-dashed border-slate-700 p-5">
                <svg className="h-9 w-9 text-slate-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z" />
                </svg>
              </div>
              <p className="text-sm font-medium text-slate-400">No AI model selected</p>
              <p className="mt-1 max-w-xs text-xs text-slate-600">
                Configure named LLM providers — Ollama, OpenAI, Anthropic, and more. Reference them by name in workflow agent steps.
              </p>
              <button
                onClick={() => { setSelected(null); setCreating(true) }}
                className="mt-5 flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 transition-colors"
              >
                <span className="text-base font-light leading-none">+</span>
                New AI Model
              </button>
            </div>
          )}

          {selected && (loadingModel || !agentModel) && !creating && (
            <div className="flex items-center justify-center h-full text-slate-400 text-sm">
              Loading…
            </div>
          )}

          {creating && (
            <AgentModelForm
              key="__new__"
              onSaved={handleSaved}
              onDeleted={handleDeleted}
              onCancel={handleCancel}
            />
          )}

          {!creating && selected && agentModel && !loadingModel && (
            <AgentModelForm
              key={selected}
              initialData={agentModel}
              existingFileName={selected}
              onSaved={handleSaved}
              onDeleted={handleDeleted}
              onCancel={handleCancel}
            />
          )}
        </main>
      </div>
    </div>
  )
}
