import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { TopBar } from '../components/TopBar'
import { CodeEditor, type LineIssue } from '../components/CodeEditor'
import { CanvasView } from '../canvas/CanvasView'
import type { Positions } from '../canvas/layout'
import { accessSummary, addAgent, fileInputs, parseWorkflow, setRoute, setWorkflowField, START, type Preset } from '../canvas/model'
import { issuesByAgent } from '../overlays/issues'
import { SummaryBar } from '../overlays/SummaryBar'
import { AddStep } from '../palette/AddStep'
import { Panel } from '../panel/Panel'
import { ProblemsBar } from '../workflows/ProblemsBar'
import { rememberWorkflow } from '../workflows/recent'
import { WorkflowSwitcher } from '../workflows/WorkflowSwitcher'
import { WorkflowTiles } from '../workflows/WorkflowTiles'
import { useScreen } from '../hooks/useScreen'
import { apiFetch, toApiError } from '../api'
import { useFilesIndex, useHealth } from '../queries'
import { fetchProject, getBreakpoints, getLayout, listText, putBreakpoints, putLayout, readText, specVerify, startDevRun, uploadForRun, validateProject, writeText } from '../devApi'
import type { ValidationIssue, ValidationResult } from '../types'

const NEW_WORKFLOW = (name: string) => `kind: Workflow
version: tuvl/v2
metadata:
  name: ${name}
  description: What this workflow does.
spec:
  trigger:
    http: { path: /${name.replace(/_/g, '-')}, method: POST }
    input: { text: str }
  agents:
    - id: first_step
      description: The first agent — a typed contract until it is implemented.
      engine: pending
      inputs: { text: str }
      routes: { default: END, error: END.failed }
  outputs:
    default: {}
    failed: { status: 500 }
`

async function validateDraft(name: string, text: string): Promise<ValidationResult> {
  const res = await apiFetch('/dev/validate/draft', { method: 'POST', body: JSON.stringify({ name, text }) })
  if (!res.ok) throw await toApiError(res)
  return res.json() as Promise<ValidationResult>
}

/** `value`, once it has stopped changing for `ms`. */
function useSettled<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return settled
}

function lineOf(issue: ValidationIssue, file: string): number | null {
  const [path, line] = issue.file.split(':')
  if (!path.endsWith(`workflows/${file}`) && path !== file) return null
  return line ? Number(line) : issue.line ?? 1
}

export function WorkflowsPage() {
  const qc = useQueryClient()
  const files = useQuery({ queryKey: ['dev', 'text', 'workflows'], queryFn: () => listText('workflows') })
  const project = useQuery({ queryKey: ['dev', 'project-summary'], queryFn: fetchProject })
  const [params] = useSearchParams()
  const linked = params.get('wf')
  const fromLink = linked ? files.data?.find((f) => f.replace(/\.ya?ml$/, '') === linked) : undefined
  const [chosen, setChosen] = useState<string | null>(null)
  const selected = chosen ?? fromLink ?? files.data?.[0] ?? null
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [mode, setMode] = useState<'canvas' | 'split' | 'yaml'>('canvas')
  const [menu, setMenu] = useState(false)
  const [browsing, setBrowsing] = useState(false)
  const toggleBrowsing = useCallback(() => setBrowsing((b) => !b), [])
  const index = useFilesIndex()
  const screen = useScreen()
  useEffect(() => { if (selected) rememberWorkflow(selected) }, [selected])
  const [node, setNode] = useState<string | null>(params.get('agent'))
  const [dataFlow, setDataFlow] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const text = useQuery({
    queryKey: ['dev', 'text', 'workflows', selected],
    queryFn: () => readText('workflows', selected!),
    enabled: !!selected,
  })
  const loaded = text.data ?? ''
  const draft = (selected && drafts[selected]) ?? loaded
  const dirty = !!selected && drafts[selected] !== undefined && drafts[selected] !== loaded
  const setDraft = (value: string) => { if (selected) setDrafts((d) => ({ ...d, [selected]: value })) }

  const saved = useQuery({ queryKey: ['dev', 'validate'], queryFn: validateProject })
  const settledDraft = useSettled(draft, 700)
  const draftReport = useQuery({
    queryKey: ['dev', 'validate', 'draft', selected, settledDraft],
    queryFn: () => validateDraft(selected!, settledDraft),
    enabled: !!selected && dirty && settledDraft === draft,
    staleTime: Infinity,
  })
  const report = dirty ? draftReport.data ?? saved.data : saved.data

  const parsed = useMemo(() => parseWorkflow(draft), [draft])
  const layoutName = parsed.ok ? parsed.view.name : ''
  const layoutQuery = useQuery({ queryKey: ['dev', 'layout', layoutName], queryFn: () => getLayout(layoutName), enabled: !!layoutName })
  const [moved, setMoved] = useState<Record<string, Positions>>({})
  const positions = moved[layoutName] ?? layoutQuery.data ?? {}
  const breakpoints = useQuery({ queryKey: ['dev', 'breakpoints', layoutName], queryFn: () => getBreakpoints(layoutName), enabled: !!layoutName })
  const toggleBreakpoint = (agentId: string) => {
    const current = breakpoints.data ?? []
    const next = current.includes(agentId) ? current.filter((a) => a !== agentId) : [...current, agentId]
    qc.setQueryData(['dev', 'breakpoints', layoutName], next)
    void putBreakpoints(layoutName, next)
  }
  const navigate = useNavigate()
  const health = useHealth()
  // Live runs call models: refuse up front when one this workflow uses isn't configured.
  const unready = Object.entries(health.data?.models ?? {})
    .filter(([, m]) => !m.configured && (m.used_by ?? []).some((u) => u.startsWith(`${layoutName}.`)))
    .map(([name, m]) => `${name}${m.missing?.length ? ` needs ${m.missing.join(', ')}` : ' is not configured'}`)
  const runBlock = dirty ? 'Save first' : unready.length ? `${unready.join('; ')} — see tuvl doctor` : null
  const trace = useQuery({ queryKey: ['dev', 'specs', 'verify', 'all'], queryFn: () => specVerify(undefined, false), enabled: !!node })
  const specLine = (() => {
    for (const sp of trace.data?.specs ?? []) {
      const step = sp.flows.find((f) => f.flow === layoutName)?.steps.find((st) => st.step === node)
      if (step) return { path: sp.path, line: step.line }
    }
    return null
  })()
  const [runForm, setRunForm] = useState<{ step: boolean; input: string } | null>(null)
  const startRun = useMutation({
    mutationFn: (f: { step: boolean; input: string }) => startDevRun(layoutName, JSON.parse(f.input) as Record<string, unknown>, f.step),
    onSuccess: (r) => { setRunForm(null); navigate(`/runs?run=${r.run_id}`) },
    onError: (e: Error) => setError(e.message),
  })
  const uploads = parsed.ok ? fileInputs(parsed.view.trigger.input) : []
  const attach = async (name: string, many: boolean, files: FileList | null) => {
    if (!files || !runForm) return
    try {
      const refs = await Promise.all([...files].map((f) => uploadForRun(layoutName, f)))
      const current = JSON.parse(runForm.input) as Record<string, unknown>
      setRunForm({ ...runForm, input: JSON.stringify({ ...current, [name]: many ? refs : refs[0] }, null, 2) })
      setError(null)
    } catch (e) { setError((e as Error).message) }
  }
  const openRunForm = (step: boolean) => {
    const sample = parsed.ok ? Object.fromEntries(Object.entries(parsed.view.trigger.input).map(([k, t]) => [k, /^list\[file\]/.test(t.trim()) ? [] : t.trim().startsWith('file') ? null : ''])) : {}
    setRunForm({ step, input: JSON.stringify(sample, null, 2) })
  }

  const apply = (edit: (t: string) => string) => {
    try { setDraft(edit(draft)); setError(null) } catch (e) { setError((e as Error).message) }
  }
  const save = useMutation({
    mutationFn: () => writeText('workflows', selected!, draft),
    onSuccess: () => {
      setError(null)
      qc.setQueryData(['dev', 'text', 'workflows', selected], draft)
      setDrafts((d) => { const rest = { ...d }; delete rest[selected!]; return rest })
      void qc.invalidateQueries({ queryKey: ['dev'] }) // validation and the project refresh in the background
    },
    onError: (e: Error) => setError(e.message),
  })
  const saveLayout = (p: Positions) => {
    if (!layoutName) return
    setMoved((m) => ({ ...m, [layoutName]: p }))
    void putLayout(layoutName, p)
  }

  const addFromPalette = (preset: Preset) => {
    if (!parsed.ok) return
    const taken = new Set(parsed.view.agents.map((a) => a.id))
    const free = (name: string) => !taken.has(name) && !preset.also?.(name).some((a) => taken.has(String(a.id)))
    let id = preset.key
    for (let n = 2; !free(id); n += 1) id = `${preset.key}_${n}`
    apply((t) => {
      let next = addAgent(t, preset.make(id))
      for (const more of preset.also?.(id) ?? []) next = addAgent(next, more)
      const from = node && parsed.view.agents.find((a) => a.id === node)
      // Insert it where the selected agent currently ends; never cut an existing link.
      const signal = from && Object.entries(from.routes).find(([, target]) => target === 'END')?.[0]
      if (from && signal) next = setRoute(next, from.id, signal, id)
      return next
    })
    setNode(id)
  }

  const models = project.data?.models ?? []
  const issues = useMemo(() => (selected ? issuesByAgent(report, selected) : { agents: {}, workflow: [] }), [report, selected])
  const lineIssues: LineIssue[] = useMemo(() => {
    if (!report || !selected) return []
    return [...report.errors, ...report.warnings]
      .map((i) => ({ i, at: lineOf(i, selected) }))
      .filter((x): x is { i: ValidationIssue; at: number } => x.at !== null && x.at > 0)
      .map(({ i, at }) => ({ line: at, message: i.message, severity: i.severity }))
  }, [report, selected])
  const counts = (name: string) => project.data?.workflows.find((w) => `${w.name}.yaml` === name || name.startsWith(`${w.name}.`))

  const create = async (raw: string, group: string | null = null) => {
    const name = raw.trim()
    if (!/^[a-z][a-z0-9_]*$/.test(name)) { setError('workflow names are snake_case: letters, digits, _'); return }
    if (files.data?.includes(`${name}.yaml`)) { setError(`${name} already exists`); return }
    await writeText('workflows', `${name}.yaml`, group ? setWorkflowField(NEW_WORKFLOW(name), ['metadata', 'group'], group) : NEW_WORKFLOW(name))
    await qc.invalidateQueries({ queryKey: ['dev'] })
    setChosen(`${name}.yaml`)
    setNode(null)
    setBrowsing(false)
  }
  const groupOf = useMemo(() => {
    const m = new Map<string, string>()
    for (const [g, fs] of Object.entries(index.data?.workflow_groups ?? {})) for (const f of fs) m.set(f, g)
    return m
  }, [index.data])
  const entries = (files.data ?? []).map((file) => {
    const c = counts(file)
    // the open draft wins over the saved file, so a group edit moves the tile at once
    const group = file === selected && parsed.ok ? parsed.view.group ?? undefined : groupOf.get(file)
    return { file, name: file.replace(/\.ya?ml$/, ''), group, agents: c?.agents, pending: c?.pending, unsaved: drafts[file] !== undefined }
  })
  const view = screen === 'narrow' && mode === 'split' ? 'canvas' : mode
  const unavailable = (selected && counts(selected)?.unavailable) || []

  const tab = (m: 'canvas' | 'split' | 'yaml', label: string) => (
    <button onClick={() => setMode(m)} aria-pressed={view === m}
      className={`px-2.5 py-1 rounded ${view === m ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}>{label}</button>
  )
  const canRun = view !== 'yaml' && parsed.ok
  const discard = () => setDrafts((d) => { const r = { ...d }; delete r[selected!]; return r })
  const goSpec = () => specLine && navigate(`/specs?spec=${encodeURIComponent(specLine.path.replace(/^specs\//, ''))}&view=trace`)
  const btn = 'px-2.5 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40'

  const canvas = parsed.ok && (
    <div className="flex-1 min-w-0 relative">
      <CanvasView view={parsed.view} saved={positions} issues={issues.agents} selected={node} dataFlow={dataFlow}
        apply={apply} onSelect={setNode} onMoved={saveLayout}
        breakpoints={breakpoints.data ?? []} onToggleBreakpoint={toggleBreakpoint} />
      <label className="absolute left-3 top-3 z-10 flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-900/90 px-2 py-1 text-xs text-slate-400">
        <input type="checkbox" checked={dataFlow} onChange={(e) => setDataFlow(e.target.checked)} /> data flow
      </label>
      <AddStep onAdd={addFromPalette} after={node && node !== '__start' ? node : null} />
      {runForm && (
        <form className="absolute left-1/2 -translate-x-1/2 top-3 z-40 w-[min(20rem,calc(100%-1.5rem))] space-y-2 rounded-lg border border-slate-700 bg-slate-900 p-3 shadow-xl"
          onSubmit={(e) => { e.preventDefault(); try { JSON.parse(runForm.input) } catch { setError('input is not valid JSON'); return } startRun.mutate(runForm) }}>
          <p className="text-xs font-medium text-slate-200">{runForm.step ? 'Step through' : 'Run'} {parsed.view.name}</p>
          {uploads.map(([name, many]) => (
            <label key={name} className="block text-[11px] text-slate-400">
              {name} (file{many ? 's' : ''})
              <input type="file" aria-label={`Attach ${name}`} multiple={many} className="block w-full text-xs"
                onChange={(e) => void attach(name, many, e.target.files)} />
            </label>
          ))}
          <textarea aria-label="Run input" rows={6} value={runForm.input} onChange={(e) => setRunForm({ ...runForm, input: e.target.value })}
            className="w-full font-mono text-xs bg-slate-950 border border-slate-700 rounded p-2" />
          <div className="flex justify-end gap-2">
            <button type="button" className="text-xs px-2 py-1 rounded bg-slate-700" onClick={() => setRunForm(null)}>Cancel</button>
            <button type="submit" className="text-xs px-2 py-1 rounded bg-indigo-600" disabled={startRun.isPending}>Start</button>
          </div>
        </form>
      )}
    </div>
  )
  const yaml = (
    <div className="flex-1 min-w-0 min-h-0 flex flex-col">
      {unavailable.length > 0 && (
        <p role="alert" className="px-4 py-2 text-xs text-amber-300 border-b border-amber-900/40 bg-amber-950/20">
          This workflow cannot run: {unavailable.join('; ')}
        </p>
      )}
      {!parsed.ok && view !== 'yaml' && <p className="px-4 py-2 text-xs text-rose-400">The canvas needs valid YAML: {parsed.error}</p>}
      <div className="flex-1 min-h-0 overflow-hidden"><CodeEditor value={draft} onChange={setDraft} issues={lineIssues} /></div>
    </div>
  )

  return (
    <div className="flex flex-col h-full">
      <TopBar>
        <div className="flex flex-1 min-w-0 flex-wrap items-center gap-2 py-1.5 text-xs">
          <WorkflowSwitcher current={entries.find((e) => e.file === selected)} open={browsing} onToggle={toggleBrowsing} />
          {selected && parsed.ok && (
            <button onClick={() => { setNode(START); setBrowsing(false) }} title="Who may run this workflow — opens the Start panel"
              className="flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-800/40 px-2 py-1 text-slate-300 hover:border-slate-500">
              <span aria-hidden="true">{accessSummary(parsed.view.access).kind === 'public' ? '○' : '🔒'}</span>
              <span className="max-w-[12rem] truncate">{accessSummary(parsed.view.access).label}</span>
            </button>
          )}
          {selected && (
            <div role="group" aria-label="View" className="flex rounded-md border border-slate-700 bg-slate-800/40 p-0.5">
              {tab('canvas', 'Canvas')}
              {screen !== 'narrow' && tab('split', 'Split')}
              {tab('yaml', 'YAML')}
            </div>
          )}
          {selected && <SummaryBar report={report} file={selected} pending={dirty ? draftReport.isFetching : saved.isFetching} dirty={dirty} />}
          <span className="flex-1" />
          {error && <span className="text-rose-400 truncate max-w-xs" title={error}>{error}</span>}
          {canRun && specLine && <button className="hidden lg:inline text-indigo-300 hover:underline" title="The spec step this agent implements" onClick={goSpec}>spec :{specLine.line}</button>}
          {canRun && unready.length > 0 && !dirty && <span className="hidden lg:inline text-amber-400" title={runBlock ?? undefined}>model not configured</span>}
          {canRun && <button className={btn} disabled={!!runBlock} title={runBlock ?? 'Start a dev run (pauses at breakpoints)'} onClick={() => openRunForm(false)}>▶ Run</button>}
          {canRun && <button className={`hidden lg:inline ${btn}`} disabled={!!runBlock} title={runBlock ?? 'Start a dev run that pauses before every agent and tool call'} onClick={() => openRunForm(true)}>⏯ Step</button>}
          {dirty && <button className="hidden lg:inline text-slate-400 hover:text-slate-200" onClick={discard}>Discard</button>}
          {selected && (
            <div className="relative lg:hidden">
              <button className={btn} aria-label="More actions" aria-expanded={menu} onClick={() => setMenu((m) => !m)}>⋯</button>
              {menu && (
                <div role="menu" className="absolute right-0 top-full mt-1 z-50 min-w-40 rounded border border-slate-700 bg-slate-900 py-1 shadow-xl" onClick={() => setMenu(false)}>
                  {canRun && <button role="menuitem" disabled={!!runBlock} className="block w-full text-left px-3 py-2 hover:bg-slate-800 disabled:opacity-40" onClick={() => openRunForm(true)}>⏯ Step through</button>}
                  {canRun && specLine && <button role="menuitem" className="block w-full text-left px-3 py-2 hover:bg-slate-800" onClick={goSpec}>Spec :{specLine.line}</button>}
                  {dirty && <button role="menuitem" className="block w-full text-left px-3 py-2 hover:bg-slate-800" onClick={discard}>Discard changes</button>}
                  {!canRun && !dirty && <p className="px-3 py-2 text-slate-500">Nothing else here</p>}
                </div>
              )}
            </div>
          )}
          <button onClick={() => save.mutate()} disabled={!selected || !dirty || save.isPending}
            className="px-3 py-1 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white">
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </TopBar>
      {browsing && (
        <WorkflowTiles entries={entries} selected={selected} onClose={() => setBrowsing(false)}
          onPick={(f) => { setChosen(f); setNode(null); setBrowsing(false) }}
          onCreate={(n, g) => void create(n, g)} />
      )}
      {!selected ? (
        <p className="p-6 text-sm text-slate-500">Create a workflow (⌘K → + New workflow) — or let your coding agent build one from a checked spec.</p>
      ) : (
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="relative flex flex-1 min-h-0">
            {view === 'yaml' || !parsed.ok ? yaml : (
              <>
                {canvas}
                {view === 'split' && <div className="w-[38%] min-w-80 border-l border-slate-800 flex">{yaml}</div>}
                {node && (
                  <Panel key={node} selected={node} view={parsed.view} models={models} issues={issues.agents} apply={apply} saved={!dirty} file={selected} text={draft}
                    float={view === 'split'} onClose={() => setNode(null)} onDeleted={() => setNode(null)} />
                )}
              </>
            )}
          </div>
          <ProblemsBar key={selected} report={report} file={selected} onPick={(a) => { setMode((m) => (m === 'yaml' ? 'canvas' : m)); setNode(a) }} />
        </div>
      )}
    </div>
  )
}
