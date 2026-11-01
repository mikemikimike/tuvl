import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { TopBar } from '../components/TopBar'
import { listArtifacts, getArtifact, createArtifact, deleteArtifact } from '../api'
import { writeText } from '../devApi'
import { JudgeEditor } from '../artifacts/JudgeEditor'
import { RulesEditor } from '../artifacts/RulesEditor'
import { judgeTemplate, rulesTemplate } from '../artifacts/doc'
import type { ArtifactSummary, ArtifactType } from '../types'
import { PROSE_ARTIFACT_TYPES } from '../types'

// Closed set of artifact types. prompt/steering/skill are prose; judge and rules
// have editors here; guardrail/hook/mcp are structured YAML managed on disk.
const ALL_TYPES: ArtifactType[] = ['prompt', 'steering', 'skill', 'guardrail', 'hook', 'mcp', 'judge', 'rules']
const STRUCTURED_TYPES: ArtifactType[] = ['guardrail', 'hook', 'mcp', 'judge', 'rules']
type CreatableType = 'prompt' | 'steering' | 'skill' | 'judge' | 'rules'
const EDITED_TYPES = ['judge', 'rules']

const TYPE_BADGE: Record<ArtifactType, string> = {
  prompt: 'text-violet-400 border-violet-800/60 bg-violet-900/20',
  steering: 'text-indigo-400 border-indigo-800/60 bg-indigo-900/20',
  skill: 'text-sky-400 border-sky-800/60 bg-sky-900/20',
  guardrail: 'text-amber-400 border-amber-800/60 bg-amber-900/20',
  hook: 'text-emerald-400 border-emerald-800/60 bg-emerald-900/20',
  mcp: 'text-pink-400 border-pink-800/60 bg-pink-900/20',
  judge: 'text-rose-400 border-rose-800/60 bg-rose-900/20',
  rules: 'text-teal-400 border-teal-800/60 bg-teal-900/20',
}

function TypeBadge({ type }: { type: ArtifactType }) {
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-mono ${TYPE_BADGE[type] ?? 'text-slate-400 border-slate-700 bg-slate-800'}`}>
      {type}
    </span>
  )
}

// ── Detail panel: content viewer with version picker ─────────────────────────

function ArtifactDetailPanel({ artifact, onClose, onDeleted }: {
  artifact: ArtifactSummary
  onClose: () => void
  onDeleted: () => void
}) {
  const [version, setVersion] = useState<number>(artifact.latest)
  const isStructured = STRUCTURED_TYPES.includes(artifact.type)
  const { data: detail, isLoading, isError, error } = useQuery({
    queryKey: ['artifact', artifact.name, version],
    queryFn: () => getArtifact(artifact.name, version),
  })

  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border border-slate-800 bg-slate-900/40">
      <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-2.5 shrink-0">
        <span className="font-mono text-sm text-slate-100 truncate">{artifact.name}</span>
        <TypeBadge type={artifact.type} />
        <select
          value={version}
          onChange={(e) => setVersion(Number(e.target.value))}
          className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 text-[11px] font-mono text-slate-300 outline-none focus:border-sky-500"
          title="Version"
        >
          {[...artifact.versions].sort((a, b) => b - a).map((v) => (
            <option key={v} value={v}>v{v}{v === artifact.latest ? ' (latest)' : ''}</option>
          ))}
        </select>
        <span className="ml-auto" />
        <button
          type="button"
          onClick={async () => {
            if (!window.confirm(`Delete artifact "${artifact.name}" (all versions)?`)) return
            try { await deleteArtifact(artifact.name); onDeleted() }
            catch (e) { alert(e instanceof Error ? e.message : String(e)) }
          }}
          className="rounded border border-rose-900 px-2 py-1 text-[11px] text-rose-400 hover:border-rose-700 hover:text-rose-300 transition-colors"
        >
          Delete
        </button>
        <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-300 px-1" title="Close">✕</button>
      </div>
      <div className="px-4 py-2 border-b border-slate-800 shrink-0 space-y-1">
        {artifact.description && <p className="text-xs text-slate-400">{artifact.description}</p>}
        <p className="text-[10px] font-mono text-slate-600 truncate" title={artifact.source}>{artifact.source}</p>
        <p className="text-[10px] text-slate-500">
          Referenced by:{' '}
          {artifact.referenced_by.length
            ? artifact.referenced_by.map((r) => (
                <code key={r} className="mr-1.5 text-sky-400 font-mono">{r}</code>
              ))
            : <span className="text-slate-600">nothing</span>}
        </p>
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-4">
        {artifact.type === 'judge' && artifact.source === 'file' && <JudgeEditor name={artifact.name} />}
        {artifact.type === 'rules' && artifact.source === 'file' && <RulesEditor name={artifact.name} />}
        {!(EDITED_TYPES.includes(artifact.type) && artifact.source === 'file') && <>
        {isLoading && <p className="text-xs text-slate-500">Loading…</p>}
        {isError && <p className="text-xs text-rose-400">{error instanceof Error ? error.message : 'Failed to load content'}</p>}
        {detail && (
          <>
            <p className="mb-2 text-[10px] font-mono text-slate-600">
              v{detail.version} · {detail.content_hash.slice(0, 12)}{isStructured ? ` · ${artifact.type} (structured)` : ''}
            </p>
            <pre className="whitespace-pre-wrap break-words rounded border border-slate-800 bg-slate-950/60 p-3 text-xs font-mono leading-5 text-slate-200">
              {typeof detail.content === 'string'
                ? detail.content
                : JSON.stringify(detail.content, null, 2)}
            </pre>
          </>
        )}
        </>}
      </div>
    </div>
  )
}

// ── Create form (prose types only) ───────────────────────────────────────────

function CreateArtifactForm({ onDone, onCancel }: { onDone: (name: string) => void; onCancel: () => void }) {
  const [name, setName] = useState('')
  const [type, setType] = useState<CreatableType>('prompt')
  const structured = type === 'judge' || type === 'rules'
  const [description, setDescription] = useState('')
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async () => {
    setErr(null)
    if (!name.trim()) { setErr('Name is required.'); return }
    if (!structured && !content.trim()) { setErr('Content is required.'); return }
    setSaving(true)
    try {
      if (structured) {
        const n = name.trim()
        if (!/^[a-z0-9][a-z0-9_-]*$/.test(n)) throw new Error('Name: lowercase letters, digits, - and _')
        const template = type === 'judge' ? judgeTemplate(n, description.trim()) : rulesTemplate(n, description.trim())
        await writeText('artifacts', `${n}.yaml`, template)
        onDone(n)
        return
      }
      const res = await createArtifact({
        name: name.trim(),
        type,
        content,
        ...(description.trim() ? { description: description.trim() } : {}),
      })
      onDone(res.name)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4 space-y-3">
      <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">New artifact</p>
      <div className="grid grid-cols-[1fr_140px] gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1">Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="triage-steering"
            spellCheck={false}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm font-mono text-slate-100 outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1">Type</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value as CreatableType)}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-2 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"
          >
            {[...PROSE_ARTIFACT_TYPES, 'judge', 'rules'].map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-slate-400 mb-1">Description <span className="text-slate-600 font-normal">(optional)</span></label>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What this artifact is for"
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500/30"
        />
      </div>
      {structured ? (
        <p className="text-[11px] text-slate-400">
          Creates <span className="font-mono">artifacts/{name.trim() || '<name>'}.yaml</span> from a template; edit its {type === 'judge' ? 'rubric and calibration set' : 'rules'} once it is listed (the dev server reloads on save).
        </p>
      ) : <div>
        <label className="block text-xs font-medium text-slate-400 mb-1">Content <span className="text-slate-600 font-normal">(markdown / prose)</span></label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={10}
          spellCheck={false}
          placeholder={'# Steering\n\nAlways confirm the order id before acting…'}
          className="w-full rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 font-mono text-xs text-slate-200 outline-none focus:border-sky-500 resize-y"
        />
      </div>}
      {err && <p className="text-xs text-rose-400">{err}</p>}
      <div className="flex items-center justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 transition-colors">Cancel</button>
        <button
          type="button"
          onClick={submit}
          disabled={saving}
          className="rounded-lg bg-sky-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-40 transition-colors"
        >
          {saving ? 'Saving…' : 'Create artifact'}
        </button>
      </div>
      <p className="text-[10px] text-slate-600">
        Guardrail / hook / mcp artifacts are YAML files managed in the project&apos;s artifacts directory — they can be viewed and deleted here but not created.
      </p>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function ArtifactsPage() {
  const qc = useQueryClient()
  const [typeFilter, setTypeFilter] = useState<ArtifactType | ''>('')
  const [selected, setSelected] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const { data: artifacts = [], isLoading, isError, error } = useQuery({
    queryKey: ['artifacts', typeFilter || 'all'],
    queryFn: () => listArtifacts(typeFilter || undefined),
    // a new YAML artifact appears once the dev server has reloaded
    refetchInterval: (q) => (selected && !(q.state.data ?? []).some((a) => a.name === selected) ? 1000 : false),
    refetchIntervalInBackground: true,
  })

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['artifacts'] })
    void qc.invalidateQueries({ queryKey: ['artifact'] })
  }

  const selectedArtifact = artifacts.find((a) => a.name === selected) ?? null

  return (
    <div className="flex h-full flex-col">
      <TopBar title="Artifacts" subtitle="versioned prompts · steering · skills · guardrails · hooks · mcp · judges · rules" />
      <div className="flex flex-1 min-h-0 gap-4 p-6">
        {/* List */}
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <div className="flex items-center gap-2 shrink-0">
            <select
              value={typeFilter}
              onChange={(e) => { setTypeFilter(e.target.value as ArtifactType | ''); setSelected(null) }}
              className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-sky-500"
            >
              <option value="">All types</option>
              {ALL_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <span className="text-[11px] text-slate-500">{artifacts.length} artifact{artifacts.length === 1 ? '' : 's'}</span>
            <button
              type="button"
              onClick={() => setCreating((v) => !v)}
              className="ml-auto rounded-lg bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500 transition-colors"
            >
              {creating ? '× Close' : '+ New artifact'}
            </button>
          </div>

          {creating && (
            <CreateArtifactForm
              onCancel={() => setCreating(false)}
              onDone={(name) => { setCreating(false); invalidate(); setSelected(name) }}
            />
          )}

          {isError && (
            <p className="text-xs text-rose-400">{error instanceof Error ? error.message : 'Failed to load artifacts'}</p>
          )}

          <div className="flex-1 min-h-0 overflow-auto rounded-lg border border-slate-800">
            {isLoading ? (
              <p className="p-6 text-center text-sm text-slate-500">Loading…</p>
            ) : artifacts.length === 0 ? (
              <p className="p-8 text-center text-sm text-slate-500">
                No artifacts{typeFilter ? ` of type ${typeFilter}` : ''} yet. Prose artifacts (prompt / steering / skill) can be created here; structured ones live in the project&apos;s artifacts directory.
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-slate-900/60 text-[10px] uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Name</th>
                    <th className="px-3 py-2 text-left font-medium">Type</th>
                    <th className="px-3 py-2 text-left font-medium">Description</th>
                    <th className="px-3 py-2 text-left font-medium">Latest</th>
                    <th className="px-3 py-2 text-left font-medium">Referenced by</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {artifacts.map((a) => (
                    <tr
                      key={a.name}
                      onClick={() => setSelected(a.name === selected ? null : a.name)}
                      className={`cursor-pointer transition-colors ${selected === a.name ? 'bg-sky-900/20' : 'hover:bg-slate-800/40'}`}
                    >
                      <td className="px-3 py-2 font-mono text-xs text-slate-100">{a.name}</td>
                      <td className="px-3 py-2"><TypeBadge type={a.type} /></td>
                      <td className="px-3 py-2 text-xs text-slate-400 max-w-[280px] truncate" title={a.description}>{a.description || '—'}</td>
                      <td className="px-3 py-2 font-mono text-xs text-slate-400">v{a.latest} <span className="text-slate-600">({a.versions.length})</span></td>
                      <td className="px-3 py-2 text-xs">
                        {a.referenced_by.length
                          ? <span className="font-mono text-sky-400" title={a.referenced_by.join(', ')}>{a.referenced_by.length} ref{a.referenced_by.length === 1 ? '' : 's'}</span>
                          : <span className="text-slate-600">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Detail */}
        {selectedArtifact && (
          <div className={`${selectedArtifact.type === 'judge' || selectedArtifact.type === 'rules' ? 'w-[520px]' : 'w-[420px]'} shrink-0 min-h-0`}>
            <ArtifactDetailPanel
              artifact={selectedArtifact}
              onClose={() => setSelected(null)}
              onDeleted={() => { setSelected(null); invalidate() }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
