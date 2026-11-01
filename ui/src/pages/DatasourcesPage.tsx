import { useDisabledNames } from '../hooks/useAdjustOnChange'
import { type FormEvent, useState } from 'react'
import { TopBar } from '../components/TopBar'
import { YamlPanel } from '../components/YamlPanel'
import { useResizablePanel } from '../hooks/useResizablePanel'
import { useFilesIndex, useDatasource, useSaveFile } from '../queries'
import { useQueryClient } from '@tanstack/react-query'
import { keys } from '../queries'
import type { DatasourceConfig } from '../types'
import { useUIStore } from '../store'

/** Shape of a hand-edited Datasource YAML doc. */
interface DatasourceYamlDoc {
  enabled?: boolean
  metadata?: { name?: string; description?: string }
  spec?: { connection?: Record<string, unknown> }
}

const DS_KIND = 'datasources' as const

interface FormState {
  dsName: string
  description: string
  enabled: boolean
  host: string
  port: string
  database: string
  username: string
  password: string
}

const DEFAULT_FORM: FormState = {
  dsName: '',
  description: '',
  enabled: true,
  host: 'localhost',
  port: '5432',
  database: '',
  username: 'postgres',
  password: '',
}

function dsToForm(ds: DatasourceConfig): FormState {
  const conn = ds.spec.connection
  return {
    dsName: ds.metadata.name,
    description: ds.metadata.description ?? '',
    enabled: ds.enabled !== false,
    host: String(conn.host ?? 'localhost'),
    port: String(conn.port ?? '5432'),
    database: String(conn.database ?? ''),
    username: String(conn.username ?? ''),
    password: '', // never pre-fill password
  }
}

function buildYaml(form: FormState): object {
  return {
    kind: 'DataSource',
    version: 'v1',
    enabled: form.enabled,
    metadata: {
      name: form.dsName.trim() || 'datasource',
      ...(form.description.trim() && { description: form.description.trim() }),
    },
    spec: {
      type: 'postgresql',
      driver: 'asyncpg',
      connection: {
        host: form.host.trim(),
        port: parseInt(form.port, 10) || 5432,
        database: form.database.trim(),
        username: form.username.trim(),
        password: form.password,
      },
      pooling: { min_size: 5, max_size: 20 },
    },
  }
}

function yamlToDatasourceForm(doc: unknown): FormState {
  const parsed = doc as DatasourceYamlDoc
  const conn: Record<string, unknown> = parsed?.spec?.connection ?? {}
  return {
    dsName: String(parsed?.metadata?.name ?? ''),
    description: String(parsed?.metadata?.description ?? ''),
    enabled: parsed?.enabled !== false,
    host: String(conn.host ?? ''),
    port: String(conn.port ?? '5432'),
    database: String(conn.database ?? ''),
    username: String(conn.username ?? ''),
    password: String(conn.password ?? ''),
  }
}

function validateDatasourceYaml(doc: unknown): string | null {
  const conn: Record<string, unknown> = (doc as DatasourceYamlDoc)?.spec?.connection ?? {}
  for (const key of ['host', 'database', 'username']) {
    if (!String(conn[key] ?? '').trim()) return `${key} is required.`
  }
  return null
}

function Field({
  label,
  id,
  value,
  onChange,
  type = 'text',
  placeholder,
  hint,
}: {
  label: string
  id: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
  hint?: string
}) {
  const [show, setShow] = useState(false)
  const inputType = type === 'password' ? (show ? 'text' : 'password') : type
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-slate-400 mb-1.5">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={inputType}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 outline-none transition-colors focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30 font-mono"
        />
        {type === 'password' && (
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 text-xs"
          >
            {show ? 'hide' : 'show'}
          </button>
        )}
      </div>
      {hint && <p className="mt-1 text-xs text-slate-600">{hint}</p>}
    </div>
  )
}

const ENV_VAR_RE = /^\$\{[^}]+\}$/

function PasswordField({
  value,
  onChange,
  isEdit,
}: {
  value: string
  onChange: (v: string) => void
  isEdit: boolean
}) {
  const [useEnv, setUseEnv] = useState(() => ENV_VAR_RE.test(value))
  const [show, setShow] = useState(false)
  const isLight = useUIStore((s) => s.theme) === 'light'

  const handleToggleEnv = () => {
    const next = !useEnv
    setUseEnv(next)
    onChange(next ? '${POSTGRES_PASSWORD}' : '')
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label htmlFor="ds-pass" className="text-xs font-medium text-slate-400">
          Password
        </label>
        <button
          type="button"
          onClick={handleToggleEnv}
          className={`text-xs px-2 py-0.5 rounded border transition-colors ${
            useEnv
              ? (isLight ? 'border-emerald-500 text-emerald-700 bg-emerald-50' : 'border-emerald-700 text-emerald-400 bg-emerald-900/20')
              : 'border-slate-700 text-slate-500 hover:text-slate-300 hover:border-slate-600'
          }`}
        >
          {useEnv ? '✓ env var' : 'use .env var'}
        </button>
      </div>
      {useEnv ? (
        <div>
          <input
            id="ds-pass"
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            className={`w-full rounded-lg border px-3 py-2 text-sm outline-none transition-colors focus:ring-1 font-mono ${isLight ? 'border-emerald-400 bg-white text-emerald-800 focus:border-emerald-600 focus:ring-emerald-600/30' : 'border-emerald-800 bg-slate-800 text-emerald-300 focus:border-emerald-600 focus:ring-emerald-600/30'}`}
          />
          <p className="mt-1 text-xs text-slate-600">
            e.g.{' '}
            <span className="font-mono text-slate-500">{'${POSTGRES_PASSWORD}'}</span>
            {' '}— resolved from your .env at runtime.
          </p>
        </div>
      ) : (
        <div className="relative">
          <input
            id="ds-pass"
            type={show ? 'text' : 'password'}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 outline-none transition-colors focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30 font-mono"
          />
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 text-xs"
          >
            {show ? 'hide' : 'show'}
          </button>
          {isEdit && (
            <p className="mt-1 text-xs text-slate-600">Leave blank to keep existing password.</p>
          )}
        </div>
      )}
    </div>
  )
}

function DatasourceForm({
  form,
  onFormChange,
  onSaved,
  onCancel,
  hideActions,
  isEdit,
  existingDatasources,
}: {
  form: FormState
  onFormChange: (form: FormState) => void
  onSaved: () => void
  onCancel?: () => void
  hideActions?: boolean
  isEdit: boolean
  existingDatasources: string[]
}) {
  const [error, setError] = useState<string | null>(null)
  const save = useSaveFile()
  const qc = useQueryClient()

  const set = (field: keyof FormState) => (val: string) =>
    onFormChange({ ...form, [field]: val })

  const fileName = `${form.dsName.trim().toLowerCase().replace(/\s+/g, '_')}.yaml`

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!form.dsName.trim()) { setError('Datasource name is required.'); return }
    if (!isEdit && existingDatasources.includes(fileName)) {
      setError(`A datasource named "${fileName}" already exists.`)
      return
    }
    if (!form.host.trim() || !form.database.trim() || !form.username.trim()) {
      setError('Host, database and username are required.')
      return
    }
    try {
      await save.mutateAsync({ kind: DS_KIND, name: fileName, body: buildYaml(form) })
      await qc.invalidateQueries({ queryKey: keys.files() })
      await qc.invalidateQueries({ queryKey: keys.file(DS_KIND, fileName) })
      onSaved()
    } catch {
      setError('Failed to save. Is the engine running?')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 max-w-md">
      <div>
        <label htmlFor="ds-name" className="block text-xs font-medium text-slate-400 mb-1.5">
          Datasource Name <span className="text-rose-500">*</span>
        </label>
        <input
          id="ds-name"
          type="text"
          value={form.dsName}
          onChange={(e) => set('dsName')(e.target.value)}
          placeholder="main_postgres"
          disabled={isEdit}
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm font-mono text-slate-100 outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30 disabled:opacity-50 disabled:cursor-not-allowed"
        />
        {!isEdit && (
          <p className="mt-1 text-xs text-slate-600">
            Saved as <span className="font-mono">{fileName || '<name>.yaml'}</span> · referenced in model configs
          </p>
        )}
      </div>
      <div>
        <label htmlFor="ds-desc" className="block text-xs font-medium text-slate-400 mb-1.5">Description</label>
        <input
          id="ds-desc"
          type="text"
          value={form.description}
          onChange={(e) => set('description')(e.target.value)}
          placeholder="Optional description"
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-300 outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30"
        />
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={form.enabled}
          onClick={() => onFormChange({ ...form, enabled: !form.enabled })}
          className={`relative inline-flex h-4 w-7 rounded-full transition-colors ${form.enabled ? 'bg-emerald-500' : 'bg-rose-600/80'}`}
        >
          <span className={`absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform ${form.enabled ? 'translate-x-3' : 'translate-x-0'}`} />
        </button>
        <span className={`text-sm ${form.enabled ? 'text-slate-300' : 'text-rose-400'}`}>
          {form.enabled ? 'Enabled' : 'Disabled'}
        </span>
      </div>
      <Field label="Host" id="ds-host" value={form.host} onChange={set('host')} placeholder="localhost" />
      <Field label="Port" id="ds-port" value={form.port} onChange={set('port')} placeholder="5432" />
      <Field label="Database" id="ds-db" value={form.database} onChange={set('database')} placeholder="mydb" />
      <Field label="Username" id="ds-user" value={form.username} onChange={set('username')} placeholder="postgres" />
      <PasswordField
        value={form.password}
        onChange={set('password')}
        isEdit={isEdit}
      />
      {!hideActions && (
        <>
          {error && <p className="text-xs text-rose-400">{error}</p>}
          <div className="flex gap-3 pt-2">
            <button
              type="submit"
              disabled={save.isPending}
              className="px-4 py-2 rounded-lg bg-sky-600 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-40 transition-colors"
            >
              {save.isPending ? 'Saving…' : isEdit ? 'Save changes' : 'Create datasource'}
            </button>
            {onCancel && (
              <button
                type="button"
                onClick={onCancel}
                className="px-4 py-2 rounded-lg border border-slate-700 text-sm text-slate-300 hover:bg-slate-800 transition-colors"
              >
                Cancel
              </button>
            )}
          </div>
        </>
      )}
    </form>
  )
}

function DatasourceView({ ds, onEdit }: { ds: DatasourceConfig; onEdit: () => void }) {
  const isLight = useUIStore((s) => s.theme) === 'light'
  const conn = ds.spec.connection
  const rawPassword = String(conn.password ?? '')
  const passwordIsEnvVar = ENV_VAR_RE.test(rawPassword)

  const rows: [string, React.ReactNode][] = [
    ['host', String(conn.host ?? '')],
    ['port', String(conn.port ?? '')],
    ['database', String(conn.database ?? '')],
    ['username', String(conn.username ?? '')],
    [
      'password',
      passwordIsEnvVar ? (
        <span className="text-emerald-400">
          {rawPassword}
          <span className="ml-2 text-xs text-emerald-700 border border-emerald-800 rounded px-1 py-0.5 align-middle">.env</span>
        </span>
      ) : (
        '••••••••'
      ),
    ],
  ]
  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-slate-100 font-semibold text-lg">{ds.metadata.name}</h2>
          {ds.metadata.description && (
            <p className="text-slate-400 text-sm mt-0.5">{ds.metadata.description}</p>
          )}
          <span className={`inline-block mt-2 text-xs font-mono border rounded px-2 py-0.5 ${isLight ? 'text-sky-700 bg-sky-100 border-sky-300' : 'text-sky-400 bg-sky-900/30 border-sky-800'}`}>
            {ds.spec.driver ?? 'asyncpg'} · postgresql
          </span>
        </div>
        <button
          onClick={onEdit}
          className="px-3 py-1.5 rounded-lg border border-slate-700 text-sm text-slate-300 hover:bg-slate-800 transition-colors"
        >
          Edit
        </button>
      </div>
      <p className="text-xs text-slate-500 mb-3 uppercase tracking-wider">Connection</p>
      <table className="text-sm border-collapse w-full max-w-sm">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={String(k)} className="border-b border-slate-800">
              <td className="py-2 pr-8 text-slate-400 font-mono w-28">{k}</td>
              <td className="py-2 font-mono text-slate-300">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function DatasourcesPage() {
  const { data: index, isLoading } = useFilesIndex()
  const [selected, setSelected] = useState<string | null>(null)
  const [mode, setMode] = useState<'view' | 'edit' | 'create'>('view')
  const [advanced, setAdvanced] = useState(false)
  const [formState, setFormState] = useState<FormState>(DEFAULT_FORM)
  const { width: yamlWidth, handleMouseDown: yamlDragStart } = useResizablePanel(320)
  const [saveError, setSaveError] = useState<string | null>(null)

  const save = useSaveFile()
  const qc = useQueryClient()
  const datasources = index?.datasources ?? []

  const { data: ds, isLoading: loadingDs } = useDatasource(
    mode !== 'create' && selected ? selected : ''
  )

  const disabledNames = useDisabledNames(selected, ds)

  const handleSelectDs = (name: string) => {
    setSelected(name)
    setMode('view')
    setAdvanced(false)
    setSaveError(null)
  }

  const handleNewDs = () => {
    setSelected(null)
    setMode('create')
    setAdvanced(false)
    setFormState(DEFAULT_FORM)
    setSaveError(null)
  }

  const handleStartEdit = () => {
    if (ds) setFormState(dsToForm(ds))
    setMode('edit')
    setAdvanced(false)
    setSaveError(null)
  }

  const handleSaved = () => {
    if (mode === 'create') {
      setSelected(`${formState.dsName.trim().toLowerCase().replace(/\s+/g, '_')}.yaml`)
    }
    setMode('view')
    setAdvanced(false)
    setSaveError(null)
  }

  const handleCancel = () => {
    setMode('view')
    setAdvanced(false)
    setSaveError(null)
  }

  const handleAdvancedSave = async () => {
    setSaveError(null)
    if (!formState.dsName.trim()) { setSaveError('Datasource name is required.'); return }
    const fileName = `${formState.dsName.trim().toLowerCase().replace(/\s+/g, '_')}.yaml`
    if (mode === 'create' && datasources.includes(fileName)) {
      setSaveError(`A datasource named "${fileName}" already exists.`)
      return
    }
    try {
      await save.mutateAsync({ kind: DS_KIND, name: fileName, body: buildYaml(formState) })
      await qc.invalidateQueries({ queryKey: keys.files() })
      await qc.invalidateQueries({ queryKey: keys.file(DS_KIND, fileName) })
      handleSaved()
    } catch {
      setSaveError('Failed to save. Is the engine running?')
    }
  }

  const maskPassword = (pw: string) =>
    ENV_VAR_RE.test(pw) ? pw : pw ? '••••••••' : ''

  const showForm = mode === 'edit' || mode === 'create'

  const previewObj = showForm
    ? buildYaml({ ...formState, password: maskPassword(formState.password) })
    : ds
      ? buildYaml({ ...dsToForm(ds), password: maskPassword(String(ds.spec.connection.password ?? '')) })
      : null

  const rawSeedObj = showForm
    ? buildYaml(formState)
    : ds
      ? buildYaml(dsToForm(ds))
      : null

  return (
    <div className="flex flex-col h-full">
      <TopBar title="Datasources" />
      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <aside className="w-52 shrink-0 border-r border-slate-800 flex flex-col">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 shrink-0">
            <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">Datasources</span>
            <button onClick={handleNewDs} title="New datasource"
              className="flex h-7 w-7 items-center justify-center rounded-md text-sky-400 hover:bg-sky-900/30 hover:text-sky-300 transition-colors text-xl leading-none">
              +
            </button>
          </div>
          <div className="flex-1 overflow-y-auto py-1 px-2">
            {isLoading && <p className="text-slate-400 text-xs px-2 py-1">Loading…</p>}
            {datasources.length === 0 && !isLoading && (
              <p className="text-slate-500 text-xs px-2 py-1">No datasources yet.</p>
            )}
            {datasources.map((name) => (
              <button
                key={name}
                onClick={() => handleSelectDs(name)}
                className={`w-full text-left px-3 py-2 rounded text-sm font-mono transition-colors ${
                  selected === name && mode !== 'create'
                    ? 'bg-sky-700 text-white'
                    : `text-slate-300 hover:bg-slate-800${disabledNames.has(name) ? ' opacity-50' : ''}`
                }`}
              >
                <span className="flex items-center gap-1.5">
                  <span className="flex-1 truncate">{name}</span>
                  {disabledNames.has(name) && (
                    <span className="text-[9px] px-1 py-px rounded bg-rose-900/50 text-rose-400 border border-rose-800/50 leading-none">off</span>
                  )}
                </span>
              </button>
            ))}
          </div>
        </aside>

        {/* Content area */}
        <div className="flex flex-1 min-w-0">
          <main className="flex-1 basis-0 min-w-0 overflow-y-auto px-6 py-6">
            {mode === 'view' && !selected && (
              <div className="flex flex-col items-center justify-center h-full text-center px-6">
                <div className="mb-4 rounded-full border border-dashed border-slate-700 p-5">
                  <svg className="h-9 w-9 text-slate-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
                  </svg>
                </div>
                <p className="text-sm font-medium text-slate-400">No datasource selected</p>
                <p className="mt-1 max-w-xs text-xs text-slate-600">
                  Connect a PostgreSQL database to use as a datasource for your models and workflows.
                </p>
                <button
                  onClick={handleNewDs}
                  className="mt-5 flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 transition-colors"
                >
                  <span className="text-base font-light leading-none">+</span>
                  New Datasource
                </button>
              </div>
            )}
            {mode === 'view' && selected && loadingDs && (
              <p className="text-slate-400 text-sm">Loading…</p>
            )}
            {mode === 'view' && ds && !loadingDs && (
              <DatasourceView ds={ds} onEdit={handleStartEdit} />
            )}
            {showForm && (
              <div>
                <h2 className="text-slate-100 font-semibold text-lg mb-1">
                  {mode === 'create' ? 'New Datasource' : `Edit: ${formState.dsName}`}
                </h2>
                <p className="text-slate-400 text-sm mb-5">
                  {mode === 'create'
                    ? 'Configure a PostgreSQL connection for this datasource.'
                    : 'Update connection settings for this datasource.'}
                </p>
                <DatasourceForm
                  form={formState}
                  onFormChange={setFormState}
                  onSaved={handleSaved}
                  onCancel={mode === 'edit' ? handleCancel : undefined}
                  hideActions={advanced}
                  isEdit={mode === 'edit'}
                  existingDatasources={datasources}
                />
              </div>
            )}
          </main>

          {previewObj && rawSeedObj && (
            <aside style={{ width: yamlWidth }} className="shrink-0 relative flex flex-col bg-slate-950/40">
              <div
                onMouseDown={yamlDragStart}
                className="absolute left-0 top-0 h-full w-1 cursor-col-resize hover:bg-violet-500/40 transition-colors z-10"
              />
              <YamlPanel
                obj={previewObj}
                advanced={advanced}
                onAdvancedChange={setAdvanced}
                title="YAML Preview"
                seedObj={rawSeedObj}
                onParsed={(doc) => setFormState(yamlToDatasourceForm(doc))}
                validate={validateDatasourceYaml}
                saveLabel="Validate & Save"
                onSave={handleAdvancedSave}
                savePending={save.isPending}
                saveError={saveError}
              />
            </aside>
          )}
        </div>
      </div>
    </div>
  )
}
