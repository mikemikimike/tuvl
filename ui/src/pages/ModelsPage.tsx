import { useDisabledNames } from '../hooks/useAdjustOnChange'
import React, { useState } from 'react'
import { TopBar } from '../components/TopBar'
import { YamlPanel } from '../components/YamlPanel'
import { useResizablePanel } from '../hooks/useResizablePanel'
import { useFilesIndex, useModel, useSaveFile, useAdminModels, useToggleModelVersion, useForkModelVersion } from '../queries'
import { useQueryClient } from '@tanstack/react-query'
import { keys } from '../queries'
import type { ModelConfig, ModelRelation, ModelVersionInfo } from '../types'
import { useUIStore } from '../store'
import { SidebarHeader } from '../components/SidebarHeader'
import { EmptyPanel } from '../components/EmptyPanel'

const MODEL_KIND = 'models' as const

// ── PostgreSQL type registry ───────────────────────────────────────────────────
const PG_NATIVE = ['string', 'integer', 'float', 'boolean', 'uuid', 'enum'] as const
const PG_EXTENDED = [
  'text', 'varchar', 'bigint', 'smallint', 'numeric',
  'date', 'timestamp', 'timestamptz', 'jsonb', 'bytea',
] as const

// ── Local state types ─────────────────────────────────────────────────────────
interface FieldRow {
  id: string
  name: string
  type: string
  /** Comma-separated enum values — only used when type === 'enum'. */
  enum_values: string
  primary_key: boolean
  required: boolean
  unique: boolean
  index: boolean
  default: string
  input: boolean
  secure: boolean
  description: string
}

interface RelationRow {
  id: string
  name: string
  model: string
  foreign_key: string
  type: 'many_to_one' | 'one_to_many'
}

interface ModelFormState {
  modelName: string
  description: string
  enabled: boolean
  tablename: string
  datasource: string
  generateSchema: boolean
  fields: FieldRow[]
  relations: RelationRow[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function newField(): FieldRow {
  return {
    id: crypto.randomUUID(),
    name: '',
    type: 'string',
    enum_values: '',
    primary_key: false,
    required: false,
    unique: false,
    index: false,
    default: '',
    input: true,
    secure: false,
    description: '',
  }
}

function newRelation(): RelationRow {
  return { id: crypto.randomUUID(), name: '', model: '', foreign_key: '', type: 'many_to_one' }
}

function emptyForm(): ModelFormState {
  return { modelName: '', description: '', enabled: true, tablename: '', datasource: 'main_postgres', generateSchema: true, fields: [newField()], relations: [] }
}

function configToForm(cfg: ModelConfig): ModelFormState {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const anyC = cfg as any
  const specFields = cfg.spec?.fields ?? cfg.fields ?? []
  const specRelations: ModelRelation[] = cfg.spec?.relations ?? []
  return {
    modelName: cfg.metadata?.name ?? anyC.name ?? '',
    description: cfg.metadata?.description ?? '',
    enabled: cfg.enabled !== false,
    tablename: cfg.spec?.tablename ?? anyC.table ?? '',
    datasource: cfg.spec?.datasource ?? 'main_postgres',
    generateSchema: cfg.spec?.schema !== false,
    fields: specFields.length > 0
      ? specFields.map((f) => ({
          id: crypto.randomUUID(),
          name: f.name,
          type: f.type,
          enum_values: Array.isArray(f.enum_values) ? f.enum_values.join(', ') : '',
          primary_key: f.primary_key ?? false,
          required: f.required ?? false,
          unique: f.unique ?? false,
          index: f.index ?? false,
          default: f.default !== undefined ? String(f.default) : '',
          input: f.input !== false,
          secure: f.secure ?? false,
          description: f.description ?? '',
        }))
      : [newField()],
    relations: specRelations.map((r) => ({
      id: crypto.randomUUID(),
      name: r.name,
      model: r.model,
      foreign_key: r.foreign_key,
      type: r.type,
    })),
  }
}

function buildYaml(form: ModelFormState): object {
  const validRelations = form.relations.filter(
    (r) => r.name.trim() && r.model.trim() && r.foreign_key.trim()
  )
  return {
    kind: 'ModelDefinition',
    version: 'v1',
    enabled: form.enabled,
    metadata: {
      name: form.modelName,
      ...(form.description.trim() && { description: form.description.trim() }),
    },
    spec: {
      tablename: form.tablename.trim() || `${form.modelName.toLowerCase()}s`,
      datasource: form.datasource || 'main_postgres',
      schema: form.generateSchema,
      fields: form.fields
        .filter((f) => f.name.trim())
        .map((f) => {
          const out: Record<string, unknown> = { name: f.name.trim(), type: f.type }
          if (f.type === 'enum') {
            const vals = f.enum_values.split(',').map((v) => v.trim()).filter(Boolean)
            if (vals.length > 0) out.enum_values = vals
          }
          if (f.primary_key) out.primary_key = true
          if (f.required) out.required = true
          if (f.unique) out.unique = true
          if (f.index) out.index = true
          if (f.default.trim()) out.default = f.default.trim()
          out.input = f.input
          if (f.secure) out.secure = true
          if (f.description.trim()) out.description = f.description.trim()
          return out
        }),
      ...(validRelations.length > 0 && {
        relations: validRelations.map((r) => ({
          name: r.name.trim(),
          model: r.model.trim(),
          foreign_key: r.foreign_key.trim(),
          type: r.type,
        })),
      }),
    },
  }
}

function yamlToForm(raw: unknown): ModelFormState {
  if (!raw || typeof raw !== 'object') return emptyForm()
  return configToForm(raw as ModelConfig)
}

// ── ForkDialog ────────────────────────────────────────────────────────────────
function ForkDialog({
  resourceLabel,
  sourceName,
  sourceVersion,
  onFork,
  onClose,
  isPending,
  error,
}: {
  resourceLabel: string
  sourceName: string
  sourceVersion: string
  onFork: (newVersion: string) => void
  onClose: () => void
  isPending: boolean
  error: string | null
}) {
  const [newVersion, setNewVersion] = useState('')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-80 rounded-xl border border-slate-700 bg-slate-900 shadow-2xl p-5 flex flex-col gap-4">
        <div>
          <p className="text-sm font-semibold text-slate-100">Fork {resourceLabel} version</p>
          <p className="mt-1 text-xs text-slate-400">
            Forking <span className="font-mono text-slate-300">{sourceName}@{sourceVersion}</span> — choose a new version tag.
          </p>
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">New version tag</label>
          <input
            type="text"
            value={newVersion}
            onChange={(e) => setNewVersion(e.target.value)}
            placeholder="e.g. v2"
            autoFocus
            onKeyDown={(e) => { if (e.key === 'Enter' && newVersion.trim()) onFork(newVersion.trim()) }}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm font-mono text-slate-100 outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30"
          />
        </div>
        {error && <p className="text-xs text-rose-400">{error}</p>}
        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg border border-slate-700 text-xs text-slate-300 hover:bg-slate-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => newVersion.trim() && onFork(newVersion.trim())}
            disabled={!newVersion.trim() || isPending}
            className="px-3 py-1.5 rounded-lg bg-sky-600 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-40 transition-colors"
          >
            {isPending ? 'Forking…' : 'Fork'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── ModelVersionsPanel ────────────────────────────────────────────────────────
function ModelVersionsPanel({ selectedName }: { selectedName: string | null }) {
  const { data: adminModels, isLoading, error } = useAdminModels()
  const toggle = useToggleModelVersion()
  const fork = useForkModelVersion()
  const [forkTarget, setForkTarget] = useState<{ name: string; version: string } | null>(null)
  const [forkError, setForkError] = useState<string | null>(null)

  if (isLoading) {
    return <p className="text-slate-500 text-xs px-4 py-3">Loading versions…</p>
  }
  if (error) {
    return (
      <p className="text-rose-400 text-xs px-4 py-3">
        Admin API unavailable — start tuvl with a database to manage versions.
      </p>
    )
  }
  if (!adminModels || Object.keys(adminModels).length === 0) {
    return <p className="text-slate-500 text-xs px-4 py-3">No versioned models in DB yet.</p>
  }

  // Strip .yaml suffix when matching against registry keys
  const needle = selectedName ? selectedName.replace(/\.yaml$/, '') : null
  const names = needle
    ? Object.keys(adminModels).filter((n) => n.toLowerCase() === needle.toLowerCase())
    : Object.keys(adminModels).sort()

  const handleFork = (newVersion: string) => {
    if (!forkTarget) return
    setForkError(null)
    fork.mutate(
      { name: forkTarget.name, version: forkTarget.version, newVersion },
      {
        onSuccess: () => setForkTarget(null),
        onError: (e) => setForkError(e instanceof Error ? e.message : 'Fork failed'),
      },
    )
  }

  return (
    <>
      {forkTarget && (
        <ForkDialog
          resourceLabel="model"
          sourceName={forkTarget.name}
          sourceVersion={forkTarget.version}
          onFork={handleFork}
          onClose={() => { setForkTarget(null); setForkError(null) }}
          isPending={fork.isPending}
          error={forkError}
        />
      )}
      <div className="flex-1 overflow-y-auto py-2 px-3 space-y-4">
        {names.map((name) => {
          const versions: ModelVersionInfo[] = adminModels[name] ?? []
          return (
            <div key={name}>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1 px-1">
                {name}
              </p>
              {versions.map((v) => (
                <div
                  key={v.schema_version}
                  className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-slate-800 transition-colors group"
                >
                  <span className="font-mono text-xs text-slate-300 w-8 shrink-0">{v.schema_version}</span>
                  {v.fields.length > 0 && (
                    <span className="text-[10px] text-slate-500 flex-1 truncate">
                      {v.fields.slice(0, 4).map((f) => f.name).join(', ')}
                      {v.fields.length > 4 ? ` +${v.fields.length - 4}` : ''}
                    </span>
                  )}
                  <button
                    title="Fork to new version"
                    onClick={() => setForkTarget({ name, version: v.schema_version })}
                    className="shrink-0 text-[10px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-500 hover:text-sky-400 hover:border-sky-700 transition-colors opacity-0 group-hover:opacity-100"
                  >
                    fork
                  </button>
                  <button
                    title={v.enabled ? 'Disable this version' : 'Enable this version'}
                    disabled={toggle.isPending}
                    onClick={() => toggle.mutate({ name, version: v.schema_version })}
                    className={`shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded border transition-colors disabled:opacity-50 ${
                      v.enabled
                        ? 'text-emerald-400 border-emerald-800 bg-emerald-900/20 hover:bg-rose-900/30 hover:text-rose-400 hover:border-rose-800'
                        : 'text-rose-400 border-rose-800 bg-rose-900/20 hover:bg-emerald-900/30 hover:text-emerald-400 hover:border-emerald-800'
                    }`}
                  >
                    {v.enabled ? 'on' : 'off'}
                  </button>
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </>
  )
}

function validateModelYaml(doc: unknown): string | null {
  const name = ((doc as Record<string, unknown> | null)?.metadata as Record<string, unknown> | undefined)?.name
  return String(name ?? '').trim() ? null : 'Model name is required.'
}

// ── FieldsEditor ──────────────────────────────────────────────────────────────
function FieldsEditor({
  fields,
  onChange,
}: {
  fields: FieldRow[]
  onChange: (fields: FieldRow[]) => void
}) {
  const isLight = useUIStore((s) => s.theme) === 'light'
  const update = (id: string, patch: Partial<FieldRow>) =>
    onChange(fields.map((f) => (f.id === id ? { ...f, ...patch } : f)))

  const remove = (id: string) => {
    if (fields.length === 1) return
    onChange(fields.filter((f) => f.id !== id))
  }

  const add = () => onChange([...fields, newField()])

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full text-xs border-collapse min-w-max">
          <thead>
            <tr className="text-slate-500 bg-slate-900/60">
              <th className="px-2 py-2 text-left font-medium w-32">Name</th>
              <th className="px-2 py-2 text-left font-medium w-32">Type</th>
              <th className="px-2 py-2 text-center font-medium w-8" title="Primary Key">PK</th>
              <th className="px-2 py-2 text-center font-medium w-10" title="Required">Req</th>
              <th className="px-2 py-2 text-center font-medium w-12" title="Unique">Uniq</th>
              <th className="px-2 py-2 text-center font-medium w-8" title="Index">Idx</th>
              <th className="px-2 py-2 text-left font-medium w-24">Default</th>
              <th className="px-2 py-2 text-center font-medium w-8" title="User Input">In</th>
              <th className="px-2 py-2 text-center font-medium w-10" title="Secure: redacted from traces, logs and model prompts">Sec</th>
              <th className="px-2 py-2 text-left font-medium">Description</th>
              <th className="px-2 py-2 w-6" />
            </tr>
          </thead>
          <tbody>
            {fields.map((f) => (
              <React.Fragment key={f.id}>
              <tr className="border-t border-slate-800 hover:bg-slate-800/20">
                <td className="px-2 py-1.5">
                  <input
                    type="text"
                    value={f.name}
                    onChange={(e) => update(f.id, { name: e.target.value })}
                    placeholder="field_name"
                    className="w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-xs text-slate-100 outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/20"
                  />
                </td>
                <td className="px-2 py-1.5">
                  <select
                    value={f.type}
                    onChange={(e) => update(f.id, { type: e.target.value, enum_values: e.target.value !== 'enum' ? '' : f.enum_values })}
                    className="w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-xs text-slate-100 outline-none focus:border-sky-500"
                  >
                    <optgroup label="Core">
                      {PG_NATIVE.map((t) => <option key={t} value={t}>{t}</option>)}
                    </optgroup>
                    <optgroup label="PostgreSQL">
                      {PG_EXTENDED.map((t) => <option key={t} value={t}>{t}</option>)}
                    </optgroup>
                  </select>
                </td>
                <td className="px-2 py-1.5 text-center">
                  <input type="checkbox" checked={f.primary_key}
                    onChange={(e) => update(f.id, { primary_key: e.target.checked })}
                    className="accent-sky-500 cursor-pointer" />
                </td>
                <td className="px-2 py-1.5 text-center">
                  <input type="checkbox" checked={f.required}
                    onChange={(e) => update(f.id, { required: e.target.checked })}
                    className="accent-sky-500 cursor-pointer" />
                </td>
                <td className="px-2 py-1.5 text-center">
                  <input type="checkbox" checked={f.unique}
                    onChange={(e) => update(f.id, { unique: e.target.checked })}
                    className="accent-sky-500 cursor-pointer" />
                </td>
                <td className="px-2 py-1.5 text-center">
                  <input type="checkbox" checked={f.index}
                    onChange={(e) => update(f.id, { index: e.target.checked })}
                    className="accent-sky-500 cursor-pointer" />
                </td>
                <td className="px-2 py-1.5">
                  <input
                    type="text"
                    value={f.default}
                    onChange={(e) => update(f.id, { default: e.target.value })}
                    placeholder="—"
                    className="w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-xs text-slate-300 outline-none focus:border-sky-500"
                  />
                </td>
                <td className="px-2 py-1.5 text-center">
                  <input type="checkbox" checked={f.input}
                    onChange={(e) => update(f.id, { input: e.target.checked })}
                    className="accent-sky-500 cursor-pointer" />
                </td>
                <td className="px-2 py-1.5 text-center">
                  <input type="checkbox" checked={f.secure} aria-label={`${f.name || 'field'} is secure`}
                    onChange={(e) => update(f.id, { secure: e.target.checked })}
                    className="accent-amber-500 cursor-pointer" />
                </td>
                <td className="px-2 py-1.5">
                  <input
                    type="text"
                    value={f.description}
                    onChange={(e) => update(f.id, { description: e.target.value })}
                    placeholder={f.type === 'enum' ? 'optional — enum values defined below' : 'optional description'}
                    className="w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-300 outline-none focus:border-sky-500"
                  />
                </td>
                <td className="px-2 py-1.5 text-center">
                  <button
                    type="button"
                    onClick={() => remove(f.id)}
                    disabled={fields.length === 1}
                    className="text-slate-600 hover:text-rose-400 disabled:opacity-20 transition-colors text-base leading-none"
                    title="Remove field"
                  >
                    ×
                  </button>
                </td>
              </tr>
              {f.type === 'enum' && (
                <tr key={f.id + '-enum'} className="border-t border-amber-900/30 bg-amber-900/5">
                  <td colSpan={10} className="px-3 py-1.5">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-amber-500/80 shrink-0">enum values</span>
                      <input
                        type="text"
                        value={f.enum_values}
                        onChange={(e) => update(f.id, { enum_values: e.target.value })}
                        placeholder="draft, active, terminated  (comma-separated)"
                        className="flex-1 rounded border border-amber-800/50 bg-amber-950/40 px-2 py-1 font-mono text-xs text-amber-200 placeholder-amber-700 outline-none focus:border-amber-600 focus:ring-1 focus:ring-amber-600/20"
                      />
                    </div>
                  </td>
                </tr>
              )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <button
        type="button"
        onClick={add}
        className={`text-xs border border-dashed rounded px-3 py-1.5 transition-colors ${isLight ? 'text-sky-600 hover:text-sky-700 border-sky-400 hover:border-sky-500 hover:bg-sky-50' : 'text-sky-400 hover:text-sky-300 border-sky-800 hover:border-sky-600'}`}
      >
        + Add field
      </button>
    </div>
  )
}

// ── RelationsEditor ───────────────────────────────────────────────────────────
function RelationsEditor({
  relations,
  availableModels,
  onChange,
}: {
  relations: RelationRow[]
  availableModels: string[]   // sidebar model file names e.g. ["candidate.yaml", ...]
  onChange: (relations: RelationRow[]) => void
}) {
  const isLight = useUIStore((s) => s.theme) === 'light'
  const update = (id: string, patch: Partial<RelationRow>) =>
    onChange(relations.map((r) => (r.id === id ? { ...r, ...patch } : r)))

  const remove = (id: string) => onChange(relations.filter((r) => r.id !== id))

  const add = () => onChange([...relations, newRelation()])

  // Convert file name → PascalCase model name for the dropdown options.
  const modelOptions = availableModels.map((f) => {
    const base = f.replace(/\.yaml$/, '')
    const pascal = base.replace(/(^|_)([a-z])/g, (_, __, c: string) => c.toUpperCase())
    return { label: pascal, value: pascal }
  })

  return (
    <div className="space-y-2">
      {relations.length === 0 ? (
        <p className="text-xs text-slate-600 italic">No relations defined.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full text-xs border-collapse min-w-max">
            <thead>
              <tr className="text-slate-500 bg-slate-900/60">
                <th className="px-2 py-2 text-left font-medium w-32">Name</th>
                <th className="px-2 py-2 text-left font-medium w-36">Related Model</th>
                <th className="px-2 py-2 text-left font-medium w-36">Foreign Key</th>
                <th className="px-2 py-2 text-left font-medium w-36">Type</th>
                <th className="px-2 py-2 w-6" />
              </tr>
            </thead>
            <tbody>
              {relations.map((r) => (
                <tr key={r.id} className="border-t border-slate-800 hover:bg-slate-800/20">
                  <td className="px-2 py-1.5">
                    <input
                      type="text"
                      value={r.name}
                      onChange={(e) => update(r.id, { name: e.target.value })}
                      placeholder="candidate"
                      className="w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-xs text-slate-100 outline-none focus:border-sky-500"
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      type="text"
                      value={r.model}
                      onChange={(e) => update(r.id, { model: e.target.value })}
                      placeholder="Candidate"
                      list={`model-list-${r.id}`}
                      className="w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-xs text-slate-100 outline-none focus:border-sky-500"
                    />
                    <datalist id={`model-list-${r.id}`}>
                      {modelOptions.map((o) => <option key={o.value} value={o.value} />)}
                    </datalist>
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      type="text"
                      value={r.foreign_key}
                      onChange={(e) => update(r.id, { foreign_key: e.target.value })}
                      placeholder="candidate_id"
                      className="w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-xs text-slate-100 outline-none focus:border-sky-500"
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <select
                      value={r.type}
                      onChange={(e) => update(r.id, { type: e.target.value as RelationRow['type'] })}
                      className="w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-100 outline-none focus:border-sky-500"
                    >
                      <option value="many_to_one">many_to_one  (FK on this model)</option>
                      <option value="one_to_many">one_to_many  (FK on related model)</option>
                    </select>
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    <button
                      type="button"
                      onClick={() => remove(r.id)}
                      className="text-slate-600 hover:text-rose-400 transition-colors text-base leading-none"
                      title="Remove relation"
                    >
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <button
        type="button"
        onClick={add}
        className={`text-xs border border-dashed rounded px-3 py-1.5 transition-colors ${isLight ? 'text-violet-600 hover:text-violet-700 border-violet-400 hover:border-violet-500 hover:bg-violet-50' : 'text-violet-400 hover:text-violet-300 border-violet-800 hover:border-violet-600'}`}
      >
        + Add relation
      </button>
    </div>
  )
}

// ── ModelForm ─────────────────────────────────────────────────────────────────
function ModelForm({
  form,
  onFormChange,
  onSaved,
  onCancel,
  isEdit,
  hideActions,
  datasources,
  existingModels,
  allModels,
  customSave,
}: {
  form: ModelFormState
  onFormChange: (f: ModelFormState) => void
  onSaved: () => void
  onCancel?: () => void
  isEdit: boolean
  hideActions?: boolean
  datasources: string[]
  existingModels: string[]
  allModels: string[]
  customSave?: (form: ModelFormState) => Promise<void>
}) {
  const [error, setError] = useState<string | null>(null)
  const save = useSaveFile()
  const qc = useQueryClient()

  const set = <K extends keyof ModelFormState>(k: K) => (val: ModelFormState[K]) =>
    onFormChange({ ...form, [k]: val })

  const fileName = `${form.modelName.trim().toLowerCase()}.yaml`

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!form.modelName.trim()) { setError('Model name is required.'); return }
    if (!isEdit && existingModels.includes(fileName)) {
      setError(`A model named "${fileName}" already exists.`)
      return
    }
    if (!form.fields.some((f) => f.name.trim())) {
      setError('At least one named field is required.')
      return
    }
    try {
      if (customSave) {
        await customSave(form)
      } else {
        await save.mutateAsync({ kind: MODEL_KIND, name: fileName, body: buildYaml(form) })
        await qc.invalidateQueries({ queryKey: keys.files() })
        await qc.invalidateQueries({ queryKey: keys.file(MODEL_KIND, fileName) })
      }
      onSaved()
    } catch {
      setError('Failed to save. Is the engine running?')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">
            Model Name <span className="text-rose-500">*</span>
          </label>
          <input
            type="text"
            value={form.modelName}
            onChange={(e) => set('modelName')(e.target.value)}
            placeholder="Candidate"
            disabled={isEdit}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30 disabled:opacity-50 disabled:cursor-not-allowed"
          />
          {!isEdit && (
            <p className="mt-1 text-xs text-slate-600">
              PascalCase · file saved as <span className="font-mono">{fileName || '<name>.yaml'}</span>
            </p>
          )}
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Table Name</label>
          <input
            type="text"
            value={form.tablename}
            onChange={(e) => set('tablename')(e.target.value)}
            placeholder={form.modelName ? `${form.modelName.toLowerCase()}s` : 'table_name'}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm font-mono text-slate-100 outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30"
          />
          <p className="mt-1 text-xs text-slate-600">Leave blank to auto-derive</p>
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-400 mb-1.5">Description</label>
        <input
          type="text"
          value={form.description}
          onChange={(e) => set('description')(e.target.value)}
          placeholder="Optional description"
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-300 outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30"
        />
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-400 mb-1.5">Datasource</label>
        <select
          value={form.datasource}
          onChange={(e) => set('datasource')(e.target.value)}
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30"
        >
          {datasources.length === 0 && (
            <option value="main_postgres">main_postgres (default)</option>
          )}
          {datasources.map((ds) => (
            <option key={ds} value={ds.replace(/\.yaml$/, '')}>
              {ds.replace(/\.yaml$/, '')}
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-slate-600">The datasource this model's table lives in</p>
      </div>

      <div className="flex items-center gap-6">
        <label className="flex items-center gap-2 cursor-pointer select-none text-sm">
          <input
            type="checkbox"
            checked={form.generateSchema}
            onChange={(e) => set('generateSchema')(e.target.checked)}
            className="accent-sky-500"
          />
          <span className="text-slate-300">Generate SQLModel schema</span>
        </label>

        <label className="flex items-center gap-2 cursor-pointer select-none text-sm">
          <button
            type="button"
            role="switch"
            aria-checked={form.enabled}
            onClick={() => set('enabled')(!form.enabled)}
            className={`relative inline-flex h-4 w-7 rounded-full transition-colors focus:outline-none ${form.enabled ? 'bg-emerald-500' : 'bg-rose-600/80'}`}
          >
            <span className={`absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform ${form.enabled ? 'translate-x-3' : 'translate-x-0'}`} />
          </button>
          <span className={`${form.enabled ? 'text-slate-300' : 'text-rose-400'}`}>
            {form.enabled ? 'Enabled' : 'Disabled'}
          </span>
        </label>
      </div>

      <div>
        <p className="text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">Fields</p>
        <FieldsEditor fields={form.fields} onChange={set('fields')} />
      </div>

      <div>
        <p className="text-xs font-medium text-slate-400 mb-1 uppercase tracking-wider">Relations</p>
        <p className="text-xs text-slate-600 mb-2">
          Declare FK links so API callers can use <span className="font-mono text-slate-500">?include=</span> to embed related records without N+1 queries.
        </p>
        <RelationsEditor
          relations={form.relations}
          availableModels={allModels}
          onChange={set('relations')}
        />
      </div>

      {!hideActions && (
        <div className="flex items-center gap-3 pt-1">
          {error && <p className="text-xs text-rose-400 flex-1">{error}</p>}
          <div className="flex gap-3 ml-auto">
            {onCancel && (
              <button
                type="button"
                onClick={onCancel}
                className="px-4 py-2 rounded-lg border border-slate-700 text-sm text-slate-300 hover:bg-slate-800 transition-colors"
              >
                Cancel
              </button>
            )}
            <button
              type="submit"
              disabled={save.isPending}
              className="px-4 py-2 rounded-lg bg-sky-600 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-40 transition-colors"
            >
              {save.isPending ? 'Saving…' : isEdit ? 'Save changes' : 'Create model'}
            </button>
          </div>
        </div>
      )}
    </form>
  )
}

// ── ModelDetailView ───────────────────────────────────────────────────────────
function ModelDetailView({ model, onEdit }: { model: ModelConfig; onEdit: () => void }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const anyM = model as any
  const fields = model.spec?.fields ?? model.fields ?? []
  const tablename = model.spec?.tablename ?? anyM.table
  const datasource = model.spec?.datasource ?? 'main_postgres'
  const isLight = useUIStore((s) => s.theme) === 'light'

  return (
    <div>
      <div className="flex items-start justify-between mb-6">
        <div>
          <h2 className="text-slate-100 font-semibold text-lg">{model.metadata?.name ?? (model as unknown as Record<string, string>).name ?? '(unnamed)'}</h2>
          {model.metadata?.description && (
            <p className="text-slate-400 text-sm mt-0.5">{model.metadata.description}</p>
          )}
          {tablename && (
            <span className={`inline-block mt-2 text-xs font-mono rounded px-2 py-0.5 border ${isLight ? 'text-sky-700 bg-sky-100 border-sky-300' : 'text-sky-400 bg-sky-900/30 border-sky-800'}`}>
              table: {tablename}
            </span>
          )}
          <span className={`inline-block mt-2 ml-2 text-xs font-mono rounded px-2 py-0.5 border ${isLight ? 'text-violet-700 bg-violet-100 border-violet-300' : 'text-violet-400 bg-violet-900/30 border-violet-800'}`}>
            datasource: {datasource}
          </span>
        </div>
        <button
          onClick={onEdit}
          className="shrink-0 px-3 py-1.5 rounded-lg border border-slate-700 text-sm text-slate-300 hover:bg-slate-800 transition-colors"
        >
          Edit
        </button>
      </div>

      {fields.length === 0 ? (
        <p className="text-slate-500 text-sm">No fields defined.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full text-xs border-collapse min-w-max">
            <thead>
              <tr className="text-slate-500 bg-slate-900/60">
                <th className="px-3 py-2 text-left font-medium">Name</th>
                <th className="px-3 py-2 text-left font-medium">Type</th>
                <th className="px-3 py-2 text-center font-medium w-8" title="Primary Key">PK</th>
                <th className="px-3 py-2 text-center font-medium w-10" title="Required">Req</th>
                <th className="px-3 py-2 text-center font-medium w-12" title="Unique">Uniq</th>
                <th className="px-3 py-2 text-center font-medium w-8" title="Index">Idx</th>
                <th className="px-3 py-2 text-left font-medium">Default</th>
                <th className="px-3 py-2 text-center font-medium w-12" title="User Input">Input</th>
                <th className="px-3 py-2 text-left font-medium">Description</th>
              </tr>
            </thead>
            <tbody>
              {fields.map((f) => (
                <tr key={f.name} className="border-t border-slate-800 hover:bg-slate-800/30 transition-colors">
                  <td className={`px-3 py-2 font-mono ${isLight ? 'text-sky-700' : 'text-sky-300'}`}>{f.name}</td>
                  <td className={`px-3 py-2 font-mono ${isLight ? 'text-violet-700' : 'text-violet-300'}`}>{f.type}</td>
                  <td className="px-3 py-2 text-center">{f.primary_key ? <span className={isLight ? 'text-sky-600' : 'text-sky-400'}>✓</span> : <span className="text-slate-700">—</span>}</td>
                  <td className="px-3 py-2 text-center">{f.required ? <span className={isLight ? 'text-emerald-600' : 'text-emerald-400'}>✓</span> : <span className="text-slate-700">—</span>}</td>
                  <td className="px-3 py-2 text-center">{f.unique ? <span className={isLight ? 'text-emerald-600' : 'text-emerald-400'}>✓</span> : <span className="text-slate-700">—</span>}</td>
                  <td className="px-3 py-2 text-center">{f.index ? <span className={isLight ? 'text-emerald-600' : 'text-emerald-400'}>✓</span> : <span className="text-slate-700">—</span>}</td>
                  <td className="px-3 py-2 font-mono text-slate-400">
                    {f.default !== undefined && String(f.default) !== '' ? String(f.default) : <span className="text-slate-700">—</span>}
                  </td>
                  <td className="px-3 py-2 text-center">{f.input !== false ? <span className={isLight ? 'text-emerald-600' : 'text-emerald-400'}>✓</span> : <span className="text-slate-700">—</span>}</td>
                  <td className="px-3 py-2 text-slate-400">{f.description || <span className="text-slate-700">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Relations */}
      {(() => {
        const relations = model.spec?.relations ?? []
        if (relations.length === 0) return null
        return (
          <div className="mt-6">
            <p className="text-xs font-medium text-slate-400 mb-2 uppercase tracking-wider">Relations</p>
            <div className="overflow-x-auto rounded-lg border border-slate-800">
              <table className="w-full text-xs border-collapse min-w-max">
                <thead>
                  <tr className="text-slate-500 bg-slate-900/60">
                    <th className="px-3 py-2 text-left font-medium">Name</th>
                    <th className="px-3 py-2 text-left font-medium">Related Model</th>
                    <th className="px-3 py-2 text-left font-medium">Foreign Key</th>
                    <th className="px-3 py-2 text-left font-medium">Type</th>
                  </tr>
                </thead>
                <tbody>
                  {relations.map((r) => (
                    <tr key={r.name} className="border-t border-slate-800 hover:bg-slate-800/30 transition-colors">
                      <td className={`px-3 py-2 font-mono ${isLight ? 'text-sky-700' : 'text-sky-300'}`}>{r.name}</td>
                      <td className={`px-3 py-2 font-mono ${isLight ? 'text-violet-700' : 'text-violet-300'}`}>{r.model}</td>
                      <td className="px-3 py-2 font-mono text-slate-300">{r.foreign_key}</td>
                      <td className="px-3 py-2">
                        <span className={`px-2 py-0.5 rounded text-xs font-mono ${
                          r.type === 'many_to_one'
                            ? 'bg-sky-900/40 text-sky-300 border border-sky-800'
                            : 'bg-violet-900/40 text-violet-300 border border-violet-800'
                        }`}>
                          {r.type}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      })()}
    </div>
  )
}

// ── ModelsPage ────────────────────────────────────────────────────────────────
export function ModelsPage() {
  const { data: index, isLoading } = useFilesIndex()
  const [selected, setSelected] = useState<string | null>(null)
  const [docIndex, setDocIndex] = useState<number>(0)
  const [mode, setMode] = useState<'view' | 'edit' | 'create'>('view')
  const [advanced, setAdvanced] = useState(false)
  const [sidebarTab, setSidebarTab] = useState<'files' | 'versions'>('files')
  const [formState, setFormState] = useState<ModelFormState>(emptyForm())
  const [saveError, setSaveError] = useState<string | null>(null)
  const { width: yamlWidth, handleMouseDown: yamlDragStart } = useResizablePanel(360)

  const save = useSaveFile()
  const qc = useQueryClient()
  const models = index?.models ?? []
  const datasources = index?.datasources ?? []

  const { data: modelData, isLoading: loadingModel } = useModel(
    mode !== 'create' && selected ? selected : ''
  )

  // Multi-document YAML support: server returns an array when the file contains
  // multiple documents separated by ---
  const rawModelData = modelData as unknown as ModelConfig | ModelConfig[] | undefined
  const isMultiDoc = Array.isArray(rawModelData)
  const allDocs: ModelConfig[] = isMultiDoc ? (rawModelData as ModelConfig[]) : rawModelData ? [rawModelData] : []
  const activeDoc: ModelConfig | undefined = allDocs[docIndex] ?? allDocs[0]

  // Track which filenames are known to be disabled (populated as configs are loaded)
  const disabledNames = useDisabledNames(selected, activeDoc as (ModelConfig & { enabled?: boolean }) | undefined)

  const handleSelectModel = (name: string) => {
    setSelected(name)
    setDocIndex(0)
    setMode('view')
    setAdvanced(false)
    setSaveError(null)
  }

  const handleNewModel = () => {
    setSelected(null)
    setMode('create')
    setAdvanced(false)
    setFormState(emptyForm())
    setSaveError(null)
  }

  const handleStartEdit = () => {
    if (activeDoc) setFormState(configToForm(activeDoc))
    setMode('edit')
    setAdvanced(false)
    setSaveError(null)
  }

  const handleSaved = () => {
    if (mode === 'create') {
      setSelected(`${formState.modelName.trim().toLowerCase()}.yaml`)
    }
    setMode('view')
    setAdvanced(false)
    setSaveError(null)
  }

  const handleCancel = () => {
    if (mode === 'create' && models.length > 0) {
      setSelected(models[0])
    }
    setMode(selected && mode !== 'create' ? 'view' : 'view')
    setAdvanced(false)
    setSaveError(null)
  }

  const handleAdvancedSave = async () => {
    setSaveError(null)
    if (!formState.modelName.trim()) { setSaveError('Model name is required.'); return }
    const fileName = `${formState.modelName.trim().toLowerCase()}.yaml`
    if (mode === 'create' && models.includes(fileName)) {
      setSaveError(`A model named "${fileName}" already exists.`)
      return
    }
    try {
      if (isMultiDoc && selected) {
        // Rebuild the full array, replacing only the doc at docIndex
        const newDocs = allDocs.map((d, i) => i === docIndex ? buildYaml(formState) : d)
        await save.mutateAsync({ kind: MODEL_KIND, name: selected, body: newDocs })
        await qc.invalidateQueries({ queryKey: keys.files() })
        await qc.invalidateQueries({ queryKey: keys.file(MODEL_KIND, selected) })
      } else {
        await save.mutateAsync({ kind: MODEL_KIND, name: fileName, body: buildYaml(formState) })
        await qc.invalidateQueries({ queryKey: keys.files() })
        await qc.invalidateQueries({ queryKey: keys.file(MODEL_KIND, fileName) })
      }
      handleSaved()
    } catch {
      setSaveError('Failed to save. Is the engine running?')
    }
  }

  // Save handler provided to ModelForm when editing within a multi-doc file
  const handleMultiDocSave = async (updatedForm: ModelFormState): Promise<void> => {
    if (!selected) return
    const newDocs = allDocs.map((d, i) => i === docIndex ? buildYaml(updatedForm) : d)
    await save.mutateAsync({ kind: MODEL_KIND, name: selected, body: newDocs })
    await qc.invalidateQueries({ queryKey: keys.files() })
    await qc.invalidateQueries({ queryKey: keys.file(MODEL_KIND, selected) })
  }

  const showForm = mode === 'edit' || mode === 'create'

  const previewObj = showForm
    ? buildYaml(formState)
    : activeDoc
      ? buildYaml(configToForm(activeDoc))
      : null

  return (
    <div className="flex flex-col h-full">
      <TopBar title="Models" />
      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <aside className="w-52 shrink-0 border-r border-slate-800 flex flex-col">
          {sidebarTab === 'files' ? (
            <SidebarHeader title="Models" onNew={handleNewModel} newLabel="New model" />
          ) : (
            <div className="flex items-center px-4 py-3 border-b border-slate-800 shrink-0">
              <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">Models</span>
            </div>
          )}
          {/* Sidebar tab strip */}
          <div className="flex border-b border-slate-800 shrink-0">
            {(['files', 'versions'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setSidebarTab(tab)}
                className={`flex-1 py-1.5 text-[10px] font-semibold uppercase tracking-wider transition-colors ${
                  sidebarTab === tab
                    ? 'text-sky-400 border-b-2 border-sky-500'
                    : 'text-slate-600 hover:text-slate-400'
                }`}
              >
                {tab === 'files' ? 'Files' : 'Versions'}
              </button>
            ))}
          </div>
          {sidebarTab === 'versions' ? (
            <ModelVersionsPanel selectedName={selected} />
          ) : (
          <div className="flex-1 overflow-y-auto py-1 px-2">
            {isLoading && <p className="text-slate-400 text-xs px-2 py-1">Loading…</p>}
            {models.length === 0 && !isLoading && (
              <p className="text-slate-500 text-xs px-2 py-1">No models yet.</p>
            )}
            {models.map((name) => (
              <button
                key={name}
                onClick={() => handleSelectModel(name)}
                className={`w-full text-left px-3 py-2 rounded text-sm font-mono transition-colors ${
                  selected === name && mode !== 'create'
                    ? 'bg-sky-700 text-white'
                    : 'text-slate-300 hover:bg-slate-800'
                } ${disabledNames.has(name) && !(selected === name && mode !== 'create') ? 'opacity-50' : ''}`}
              >
                <span className="flex items-center gap-1.5">
                  {name}
                  {disabledNames.has(name) && (
                    <span className="text-[9px] px-1 py-px rounded bg-rose-900/50 text-rose-400 border border-rose-800/50 leading-none">off</span>
                  )}
                </span>
              </button>
            ))}
          </div>
          )}
        </aside>

        {/* Content area */}
        <div className="flex flex-1 min-w-0">
          {/* Form / detail panel */}
          <main className="flex-1 basis-0 min-w-0 overflow-y-auto px-6 py-6">
            {mode === 'view' && !selected && (
              <EmptyPanel
                icon="model"
                title="No model selected"
                description="Define data models with fields, types, and PostgreSQL table mappings. Reference them in workflows and APIs."
                actionLabel="New Model"
                onAction={handleNewModel}
              />
            )}
            {mode === 'view' && selected && loadingModel && (
              <p className="text-slate-400 text-sm">Loading…</p>
            )}
            {/* Multi-document tab strip */}
            {mode === 'view' && isMultiDoc && !loadingModel && allDocs.length > 0 && (
              <div className="flex items-center gap-1 mb-5 pb-4 border-b border-slate-800 flex-wrap">
                <span className="text-xs text-slate-500 mr-1">Documents:</span>
                {allDocs.map((doc, i) => (
                  <button
                    key={i}
                    onClick={() => setDocIndex(i)}
                    className={`px-3 py-1 rounded-full text-xs font-mono transition-colors border ${
                      i === docIndex
                        ? 'bg-sky-700 border-sky-600 text-white'
                        : 'border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-200'
                    }`}
                  >
                    {doc.metadata?.name ?? `Document ${i + 1}`}
                    {doc.metadata?.schema_version ? (
                      <span className="ml-1 opacity-70">{doc.metadata.schema_version}</span>
                    ) : null}
                  </button>
                ))}
              </div>
            )}
            {mode === 'view' && activeDoc && !loadingModel && (
              <ModelDetailView model={activeDoc} onEdit={handleStartEdit} />
            )}
            {showForm && (
              <div>
                <h2 className="text-slate-100 font-semibold text-lg mb-1">
                  {mode === 'create' ? 'New Model' : `Edit: ${formState.modelName}`}
                </h2>
                <p className="text-slate-400 text-sm mb-5">
                  {mode === 'create'
                    ? 'Define your model fields and PostgreSQL mapping.'
                    : 'Update field definitions for this model.'}
                </p>
                <ModelForm
                  form={formState}
                  onFormChange={setFormState}
                  onSaved={handleSaved}
                  onCancel={handleCancel}
                  isEdit={mode === 'edit'}
                  hideActions={advanced}
                  datasources={datasources}
                  existingModels={models}
                  allModels={models}
                  customSave={isMultiDoc && mode === 'edit' ? handleMultiDocSave : undefined}
                />
              </div>
            )}
          </main>

          {/* YAML panel */}
          {previewObj && (
            <aside style={{ width: yamlWidth }} className="shrink-0 relative flex flex-col bg-slate-950/40">
              <div
                onMouseDown={yamlDragStart}
                className="absolute left-0 top-0 h-full w-1 cursor-col-resize hover:bg-violet-500/40 transition-colors z-10"
              />
              <YamlPanel
                obj={previewObj}
                title="YAML Preview"
                saveLabel="Validate & Save"
                validate={validateModelYaml}
                advanced={advanced}
                onAdvancedChange={setAdvanced}
                onParsed={(doc) => setFormState(yamlToForm(doc))}
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
