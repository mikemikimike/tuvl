import { dump } from 'js-yaml'
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from 'react'
import { TopBar } from '../components/TopBar'
import { ColorizedYaml } from '../components/ColorizedYaml'
import { parseYaml } from '../lib/yaml'
import { useResizablePanel } from '../hooks/useResizablePanel'
import {
  useFederationProviders,
  useFederationProvider,
  useSaveFederationProvider,
  useDeleteFederationProvider,
} from '../queries'
import type { FederationProviderConfig } from '../types'

// ── Provider presets ──────────────────────────────────────────────────────────

const PRESETS: Record<string, Partial<FederationProviderConfig['spec']> & { label: string; color: string; icon: string }> = {
  google: {
    label: 'Google',
    color: 'border-rose-700/40 bg-rose-900/10',
    icon: 'G',
    provider: 'google',
    scope: 'openid email profile',
  },
  github: {
    label: 'GitHub',
    color: 'border-slate-600/50 bg-slate-800/30',
    icon: '⌥',
    provider: 'github',
    scope: 'read:user user:email',
  },
  microsoft: {
    label: 'Microsoft',
    color: 'border-sky-700/40 bg-sky-900/10',
    icon: 'M',
    provider: 'microsoft',
    scope: 'openid email profile User.Read',
  },
}

// ── Styles ────────────────────────────────────────────────────────────────────

const inputCls =
  'w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none font-mono focus:border-violet-500 focus:ring-1 focus:ring-violet-500/20 transition-colors'
const labelCls = 'block text-xs font-medium text-slate-400 mb-1.5'

// ── YAML Panel ────────────────────────────────────────────────────────────────

/** Shape of a hand-edited Federation provider YAML doc. */
interface FederationYamlDoc {
  enabled?: boolean
  metadata?: { name?: string; description?: string }
  spec?: {
    provider?: string
    client_id?: string
    client_secret?: string
    scope?: string
    auth_url?: string
    token_url?: string
    userinfo_url?: string
    tenant_id?: string
    allowed_domains?: string[]
  }
}

interface YamlPanelProps {
  obj: object
  advanced: boolean
  onAdvancedChange: (v: boolean) => void
  onFormChange: (f: FormState) => void
  onSave: () => Promise<void>
  savePending: boolean
  saveError: string | null
}

function YamlPanel({ obj, advanced, onAdvancedChange, onFormChange, onSave, savePending, saveError }: YamlPanelProps) {
  const [rawYaml, setRawYaml] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const originalYamlRef = useRef('')

  const handleEnterAdvanced = () => {
    const _seed = dump(obj, { lineWidth: -1 })
    originalYamlRef.current = _seed
    setRawYaml(_seed)
    setParseError(null)
    setValidationError(null)
    onAdvancedChange(true)
  }

  const handleYamlChange = (text: string) => {
    setRawYaml(text)
    setValidationError(null)
    try {
      const parsed = parseYaml<FederationYamlDoc>(text)
      if (parsed && typeof parsed === 'object') {
        onFormChange({
          name: String(parsed?.metadata?.name ?? ''),
          description: String(parsed?.metadata?.description ?? ''),
          enabled: parsed?.enabled !== false,
          provider: String(parsed?.spec?.provider ?? 'google'),
          clientId: String(parsed?.spec?.client_id ?? ''),
          clientSecret: String(parsed?.spec?.client_secret ?? ''),
          scope: String(parsed?.spec?.scope ?? ''),
          authUrl: String(parsed?.spec?.auth_url ?? ''),
          tokenUrl: String(parsed?.spec?.token_url ?? ''),
          userinfoUrl: String(parsed?.spec?.userinfo_url ?? ''),
          tenantId: String(parsed?.spec?.tenant_id ?? ''),
          allowedDomains: Array.isArray(parsed?.spec?.allowed_domains)
            ? (parsed.spec?.allowed_domains as string[])
            : [],
        })
      }
      setParseError(null)
    } catch (e: unknown) {
      setParseError(e instanceof Error ? e.message : 'Invalid YAML')
    }
  }

  const handleValidateAndSave = async () => {
    if (parseError) { setValidationError('Fix YAML syntax errors before saving.'); return }
    try {
      const parsed = parseYaml<FederationYamlDoc>(rawYaml)
      const spec: NonNullable<FederationYamlDoc['spec']> = parsed?.spec ?? {}
      if (!String(spec.provider ?? '').trim()) { setValidationError('spec.provider is required.'); return }
      if (!String(spec.client_id ?? '').trim()) { setValidationError('spec.client_id is required.'); return }
      if (!String(spec.client_secret ?? '').trim()) { setValidationError('spec.client_secret is required.'); return }
    } catch {
      setValidationError('Invalid YAML — cannot parse.')
      return
    }
    setValidationError(null)
    await onSave()
  }

  const previewYaml = advanced ? rawYaml : dump(obj, { lineWidth: -1 })
  const displayError = parseError || validationError || saveError

  return (
    <div className="flex flex-col h-full w-full bg-slate-950/50">
      <div className="px-4 py-3 border-b border-slate-800 flex-shrink-0 flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">YAML</span>
        <button
          type="button"
          onClick={advanced ? () => onAdvancedChange(false) : handleEnterAdvanced}
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
            {displayError && <p className="text-xs text-rose-400 font-mono break-all">{displayError}</p>}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleValidateAndSave}
                disabled={savePending || !!parseError}
                className="flex-1 px-3 py-2 rounded-lg bg-sky-600 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-40 transition-colors"
              >
                {savePending ? 'Saving\u2026' : 'Validate & Save'}
              </button>
              <button
                type="button"
                onClick={() => { handleYamlChange(originalYamlRef.current); onAdvancedChange(false) }}
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
            <ColorizedYaml yaml={previewYaml} />
          </pre>
        </div>
      )}
    </div>
  )
}

// ── Form state ────────────────────────────────────────────────────────────────

interface FormState {
  name: string
  description: string
  enabled: boolean
  provider: string
  clientId: string
  clientSecret: string
  scope: string
  authUrl: string
  tokenUrl: string
  userinfoUrl: string
  tenantId: string
  allowedDomains: string[]
}

const DEFAULT_FORM: FormState = {
  name: '',
  description: '',
  enabled: true,
  provider: 'google',
  clientId: '',
  clientSecret: '',
  scope: '',
  authUrl: '',
  tokenUrl: '',
  userinfoUrl: '',
  tenantId: '',
  allowedDomains: [],
}

function configToForm(cfg: FederationProviderConfig): FormState {
  return {
    name: cfg.metadata.name,
    description: cfg.metadata.description ?? '',
    enabled: cfg.enabled !== false,
    provider: cfg.spec.provider,
    clientId: cfg.spec.client_id,
    clientSecret: cfg.spec.client_secret,
    scope: cfg.spec.scope ?? '',
    authUrl: cfg.spec.auth_url ?? '',
    tokenUrl: cfg.spec.token_url ?? '',
    userinfoUrl: cfg.spec.userinfo_url ?? '',
    tenantId: cfg.spec.tenant_id ?? '',
    allowedDomains: cfg.spec.allowed_domains ?? [],
  }
}

function formToConfig(f: FormState): FederationProviderConfig {
  const spec: FederationProviderConfig['spec'] = {
    provider: f.provider,
    client_id: f.clientId,
    client_secret: f.clientSecret,
  }
  if (f.scope) spec.scope = f.scope
  if (f.authUrl) spec.auth_url = f.authUrl
  if (f.tokenUrl) spec.token_url = f.tokenUrl
  if (f.userinfoUrl) spec.userinfo_url = f.userinfoUrl
  if (f.tenantId) spec.tenant_id = f.tenantId
  if (f.allowedDomains.length) spec.allowed_domains = f.allowedDomains
  return {
    kind: 'FederationProvider',
    version: 'v1',
    enabled: f.enabled,
    metadata: {
      name: f.name.trim().replace(/\s+/g, '_').toLowerCase(),
      ...(f.description ? { description: f.description } : {}),
    },
    spec,
  }
}

// ── Domain tag input ──────────────────────────────────────────────────────────

function DomainTagInput({ domains, onChange }: { domains: string[]; onChange: (d: string[]) => void }) {
  const [input, setInput] = useState('')

  const addDomain = () => {
    const d = input.trim().toLowerCase().replace(/^@/, '')
    if (d && !domains.includes(d)) onChange([...domains, d])
    setInput('')
  }

  const handleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addDomain() }
    if (e.key === 'Backspace' && !input && domains.length) onChange(domains.slice(0, -1))
  }

  return (
    <div>
      {domains.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {domains.map((d) => (
            <span key={d} className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-violet-900/30 border border-violet-700/40 text-xs text-violet-300 font-mono">
              {d}
              <button
                type="button"
                onClick={() => onChange(domains.filter((x) => x !== d))}
                className="text-violet-500 hover:text-rose-400 leading-none ml-0.5"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <input
        type="text"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKey}
        onBlur={addDomain}
        placeholder="example.com"
        className={inputCls}
        spellCheck={false}
      />
      <p className="mt-1 text-[10px] text-slate-600">
        Press Enter or , to add. Leave empty to allow any domain.
      </p>
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ onNew }: { onNew: () => void }) {
  return (
    <div className="flex flex-col items-center text-center px-6">
      <div className="mb-4 rounded-full border border-dashed border-slate-700 p-5">
        <svg className="h-9 w-9 text-slate-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round"
            d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
        </svg>
      </div>
      <p className="text-sm font-medium text-slate-400">No federation providers yet</p>
      <p className="mt-1 max-w-xs text-xs text-slate-600">
        Add a provider to let users sign in with Google, GitHub, Microsoft, or any OAuth2-compatible service.
      </p>
      <button onClick={onNew}
        className="mt-5 flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 transition-colors">
        <span className="text-base font-light leading-none">+</span>
        New Provider
      </button>
    </div>
  )
}

// ── Provider form ─────────────────────────────────────────────────────────────

function ProviderForm({
  existingName,
  onSaved,
  onDeleted,
  onCancel,
}: {
  existingName?: string
  onSaved: (name: string) => void
  onDeleted: () => void
  onCancel: () => void
}) {
  const { data: existing } = useFederationProvider(existingName ?? '')
  const save = useSaveFederationProvider()
  const del = useDeleteFederationProvider()

  const [form, setForm] = useState<FormState>(DEFAULT_FORM)
  const [savedForm, setSavedForm] = useState<FormState>(DEFAULT_FORM)
  const [error, setError] = useState<string | null>(null)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved'>('idle')
  const [yamlAdvanced, setYamlAdvanced] = useState(false)
  const { width: yamlWidth, handleMouseDown: yamlDragStart } = useResizablePanel(320)
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (existing) {
      const f = configToForm(existing)
      setForm(f)
      setSavedForm(f)
    }
  }, [existing])

  useEffect(() => {
    if (existingName) return
    const preset = PRESETS[form.provider]
    if (!preset) return
    setForm((f) => ({
      ...f,
      scope: f.scope || preset.scope || '',
      name: f.name || form.provider,
    }))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.provider])

  useEffect(() => () => { if (savedTimerRef.current) clearTimeout(savedTimerRef.current) }, [])

  const set = <K extends keyof FormState>(k: K) => (val: FormState[K]) =>
    setForm((f) => ({ ...f, [k]: val }))

  const isDirty = JSON.stringify(form) !== JSON.stringify(savedForm)

  const doSave = async () => {
    setError(null)
    if (!form.name.trim()) { setError('Name is required.'); return }
    if (!form.provider.trim()) { setError('Provider type is required.'); return }
    if (!form.clientId.trim()) { setError('Client ID is required.'); return }
    if (!form.clientSecret.trim()) { setError('Client secret is required.'); return }

    const cfg = formToConfig(form)
    const filename = `${cfg.metadata.name}.yaml`
    try {
      await save.mutateAsync({ name: filename, body: cfg })
      setSavedForm(form)
      setSaveStatus('saved')
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current)
      savedTimerRef.current = setTimeout(() => setSaveStatus('idle'), 2500)
      onSaved(filename)
    } catch {
      setError('Failed to save. Is the engine running?')
    }
  }

  const handleFormSubmit = (e: FormEvent) => { e.preventDefault(); doSave() }

  const handleDelete = async () => {
    if (!existingName) return
    if (!confirm(`Delete provider "${existingName}"?`)) return
    try {
      await del.mutateAsync(existingName)
      onDeleted()
    } catch {
      setError('Failed to delete.')
    }
  }

  const isMicrosoft = form.provider === 'microsoft'
  const previewObj = formToConfig(form)

  return (
    <form onSubmit={handleFormSubmit} className="flex flex-1 min-h-0 overflow-hidden">
      {/* ── Scrollable form fields ── */}
      <div className="flex-1 overflow-y-auto p-6 min-w-0">
        <div className="max-w-lg space-y-6">

          {/* Identity */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-500">Identity</h3>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelCls}>Name <span className="text-rose-500">*</span></label>
                  <input type="text" value={form.name} onChange={(e) => set('name')(e.target.value)}
                    className={inputCls} placeholder="google" disabled={!!existingName} spellCheck={false} />
                  <p className="mt-1 text-[10px] text-slate-600">snake_case · used in the OAuth redirect URL</p>
                </div>
                <div>
                  <label className={labelCls}>Description</label>
                  <input type="text" value={form.description} onChange={(e) => set('description')(e.target.value)}
                    className={inputCls} placeholder="Google Sign-In" />
                </div>
              </div>

              <div>
                <label className={labelCls}>Provider type <span className="text-rose-500">*</span></label>
                <select value={form.provider} onChange={(e) => set('provider')(e.target.value)}
                  className={inputCls} disabled={!!existingName}>
                  <option value="google">Google</option>
                  <option value="github">GitHub</option>
                  <option value="microsoft">Microsoft / Azure AD</option>
                  <option value="custom">Custom OAuth2</option>
                </select>
              </div>

              <div className="flex items-center gap-3">
                <button type="button" role="switch" aria-checked={form.enabled}
                  onClick={() => set('enabled')(!form.enabled)}
                  className={`relative inline-flex h-4 w-7 rounded-full transition-colors ${form.enabled ? 'bg-emerald-500' : 'bg-rose-600/80'}`}>
                  <span className={`absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform ${form.enabled ? 'translate-x-3' : 'translate-x-0'}`} />
                </button>
                <span className={`text-sm ${form.enabled ? 'text-slate-300' : 'text-rose-400'}`}>
                  {form.enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
            </div>
          </section>

          {/* Credentials */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-500">Credentials</h3>
            <div className="space-y-3">
              <div>
                <label className={labelCls}>Client ID <span className="text-rose-500">*</span></label>
                <input type="text" value={form.clientId} onChange={(e) => set('clientId')(e.target.value)}
                  className={inputCls} placeholder="${GOOGLE_CLIENT_ID}" spellCheck={false} />
                <p className="mt-1 text-[10px] text-slate-600">
                  Use <span className="font-mono text-slate-500">{'${ENV_VAR_NAME}'}</span> to reference environment variables.
                </p>
              </div>
              <div>
                <label className={labelCls}>Client secret <span className="text-rose-500">*</span></label>
                <input type="text" value={form.clientSecret} onChange={(e) => set('clientSecret')(e.target.value)}
                  className={inputCls} placeholder="${GOOGLE_CLIENT_SECRET}" spellCheck={false} />
              </div>
            </div>
          </section>

          {/* Access Control */}
          <section>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-widest text-slate-500">Access Control</h3>
            <p className="mb-3 text-[11px] text-slate-500">
              Restrict sign-in to users whose email belongs to specific domains.
            </p>
            <DomainTagInput domains={form.allowedDomains} onChange={set('allowedDomains')} />
          </section>

          {/* Scope & overrides */}
          <section>
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-widest text-slate-500">Scope &amp; URL overrides</h3>
            <p className="mb-3 text-[11px] text-slate-500">
              Leave blank to use built-in defaults for <span className="text-slate-400">{form.provider}</span>.
            </p>
            <div className="space-y-3">
              <div>
                <label className={labelCls}>Scope</label>
                <input type="text" value={form.scope} onChange={(e) => set('scope')(e.target.value)}
                  className={inputCls} placeholder={PRESETS[form.provider]?.scope ?? 'openid email profile'} spellCheck={false} />
              </div>
              {isMicrosoft && (
                <div>
                  <label className={labelCls}>Tenant ID</label>
                  <input type="text" value={form.tenantId} onChange={(e) => set('tenantId')(e.target.value)}
                    className={inputCls} placeholder="common" spellCheck={false} />
                  <p className="mt-1 text-[10px] text-slate-600">"common", "organizations", or a specific tenant UUID</p>
                </div>
              )}
              <div>
                <label className={labelCls}>Auth URL override</label>
                <input type="text" value={form.authUrl} onChange={(e) => set('authUrl')(e.target.value)}
                  className={inputCls} placeholder="https://…" spellCheck={false} />
              </div>
              <div>
                <label className={labelCls}>Token URL override</label>
                <input type="text" value={form.tokenUrl} onChange={(e) => set('tokenUrl')(e.target.value)}
                  className={inputCls} placeholder="https://…" spellCheck={false} />
              </div>
              <div>
                <label className={labelCls}>Userinfo URL override</label>
                <input type="text" value={form.userinfoUrl} onChange={(e) => set('userinfoUrl')(e.target.value)}
                  className={inputCls} placeholder="https://…" spellCheck={false} />
              </div>
            </div>
          </section>

          {/* Redirect URI hint */}
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <p className="mb-1 text-xs font-semibold text-slate-400">Redirect URI to register with provider</p>
            <p className="font-mono text-xs text-violet-300 break-all">
              {`<your-server>/auth/oauth/${form.name || '{name}'}/callback`}
            </p>
            <p className="mt-1.5 text-[10px] text-slate-600">
              Copy this into your OAuth app's "Authorized redirect URIs" / "Callback URL" field.
            </p>
          </section>

          {error && !yamlAdvanced && <p className="text-xs text-red-400">{error}</p>}

          {/* Actions */}
          <div className="flex items-center gap-3 pb-6">
            <button type="submit" disabled={save.isPending || !isDirty}
              className="rounded-lg bg-violet-600 px-5 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-40 transition-colors">
              {save.isPending ? 'Saving…' : saveStatus === 'saved' ? '✓ Saved' : 'Save'}
            </button>
            <button type="button" onClick={onCancel}
              className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-400 hover:border-slate-600 hover:text-slate-200 transition-colors">
              Cancel
            </button>
            {existingName && (
              <button type="button" onClick={handleDelete} disabled={del.isPending}
                className="ml-auto rounded-lg border border-red-900/50 px-4 py-2 text-sm text-red-500 hover:bg-red-900/20 hover:text-red-400 disabled:opacity-40 transition-colors">
                {del.isPending ? 'Deleting…' : 'Delete'}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── YAML panel ── */}
      <div style={{ width: yamlWidth }} className="shrink-0 relative border-l border-slate-800">
        <div
          onMouseDown={yamlDragStart}
          className="absolute left-0 top-0 h-full w-1 cursor-col-resize hover:bg-violet-500/40 transition-colors z-10"
        />
        <YamlPanel
          obj={previewObj}
          advanced={yamlAdvanced}
          onAdvancedChange={(v) => { setYamlAdvanced(v); if (!v) setError(null) }}
          onFormChange={(f) => setForm(f)}
          onSave={doSave}
          savePending={save.isPending}
          saveError={yamlAdvanced ? error : null}
        />
      </div>
    </form>
  )
}

// ── Provider card ─────────────────────────────────────────────────────────────

function ProviderCard({
  name,
  selected,
  onClick,
}: {
  name: string
  selected: boolean
  onClick: () => void
}) {
  const { data: cfg } = useFederationProvider(name)
  const preset = PRESETS[cfg?.spec.provider ?? name]
  const enabled = cfg?.enabled !== false
  const hasDomains = (cfg?.spec.allowed_domains?.length ?? 0) > 0

  return (
    <button type="button" onClick={onClick}
      className={`w-full rounded-xl border p-4 text-left transition-all ${
        selected
          ? 'border-violet-600/60 bg-violet-900/20 ring-1 ring-violet-600/30'
          : `${preset?.color ?? 'border-slate-700 bg-slate-900/40'} hover:border-slate-600`
      }`}>
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-slate-700 bg-slate-800 text-sm font-bold text-slate-300">
          {preset?.icon ?? name[0].toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-200">
            {preset?.label ?? cfg?.metadata.name ?? name}
          </p>
          {hasDomains ? (
            <p className="truncate text-[10px] text-violet-400 font-mono">
              {cfg!.spec.allowed_domains!.join(', ')}
            </p>
          ) : cfg?.metadata.description ? (
            <p className="truncate text-xs text-slate-500">{cfg.metadata.description}</p>
          ) : null}
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
          enabled ? 'bg-emerald-900/50 text-emerald-400' : 'bg-slate-700/60 text-slate-500'
        }`}>
          {enabled ? 'on' : 'off'}
        </span>
      </div>
    </button>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function FederationPage() {
  const { data: providers = [], isLoading } = useFederationProviders()
  const [selected, setSelected] = useState<string | null>(null)
  const [isNew, setIsNew] = useState(false)

  const handleNew = () => {
    setSelected(null)
    setIsNew(true)
  }

  const handleSaved = (filename: string) => {
    const name = filename.replace(/\.yaml$/, '')
    setIsNew(false)
    setSelected(name)
  }

  const handleDeleted = () => {
    setSelected(null)
    setIsNew(false)
  }

  const showForm = isNew || selected !== null

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TopBar title="Federation" />

      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Sidebar list */}
        <div className="flex w-64 shrink-0 flex-col border-r border-slate-800">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
            <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">Providers</span>
            <button onClick={handleNew} title="Add provider"
              className="flex h-7 w-7 items-center justify-center rounded-md text-sky-400 hover:bg-sky-900/30 hover:text-sky-300 transition-colors text-xl leading-none">
              +
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {isLoading && (
              <>
                {[1, 2].map((i) => (
                  <div key={i} className="h-16 animate-pulse rounded-xl border border-slate-800 bg-slate-800/40" />
                ))}
              </>
            )}

            {!isLoading && providers.length === 0 && !isNew && (
              <p className="px-2 py-4 text-center text-xs text-slate-600">No providers configured yet.</p>
            )}

            {providers.map((name) => (
              <ProviderCard
                key={name}
                name={name.replace(/\.yaml$/, '')}
                selected={selected === name.replace(/\.yaml$/, '')}
                onClick={() => { setSelected(name.replace(/\.yaml$/, '')); setIsNew(false) }}
              />
            ))}

            {isNew && (
              <div className="rounded-xl border border-dashed border-violet-700/50 bg-violet-900/10 p-4 text-center text-xs text-violet-400">
                New provider…
              </div>
            )}
          </div>
        </div>

        {/* Detail panel */}
        <div className="flex flex-1 min-w-0 flex-col overflow-hidden">
          {!showForm && (
            <div className="flex flex-1 items-center justify-center h-full">
              <EmptyState onNew={handleNew} />
            </div>
          )}
          {showForm && (
            <ProviderForm
              existingName={selected ? `${selected}.yaml` : undefined}
              onSaved={handleSaved}
              onDeleted={handleDeleted}
              onCancel={() => { setIsNew(false); if (!selected) setSelected(null) }}
            />
          )}
        </div>
      </div>
    </div>
  )
}
