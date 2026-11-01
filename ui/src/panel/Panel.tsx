import { useState } from 'react'
import { useResizablePanel } from '../hooks/useResizablePanel'
import { useScreen } from '../hooks/useScreen'
import { changeEngine, PRESETS, removeAgent, type AgentView, type WorkflowView } from '../canvas/model'
import type { AgentIssues } from '../overlays/issues'
import { AgentYamlTab } from './AgentYamlTab'
import { BudgetTab } from './BudgetTab'
import { ChangeCheck } from './ChangeCheck'
import { CodeAgentEditor } from './CodeAgentEditor'
import { ContractTab } from './ContractTab'
import { EngineTab } from './EngineTab'
import { GovernanceTab } from './GovernanceTab'
import { ProbeTab } from './ProbeTab'
import { RoutesTab } from './RoutesTab'
import { StartPanel } from './StartPanel'

const TABS = ['Code', 'Engine', 'Contract', 'Routes', 'Budget', 'Probe', 'YAML', 'Governance'] as const
type Tab = (typeof TABS)[number]

/** the Engine tab is named for what it holds */
const ENGINE_LABEL: Record<string, string> = { decide: 'Rules', llm: 'Prompt', loop: 'Loop', tool: 'Tool', human: 'Approval', code: 'Engine', pending: 'Engine' }

const PIN_KEY = 'tuvl.panelPinned'
const readPinned = () => { try { return localStorage.getItem(PIN_KEY) === '1' } catch { return false } }

export function Panel({ selected, view, models, issues, apply, onClose, onDeleted, saved, file, text, float = false }: {
  selected: string
  saved: boolean
  file: string
  text: string
  view: WorkflowView
  models: string[]
  issues: Record<string, AgentIssues>
  apply: (edit: (text: string) => string) => void
  onClose: () => void
  onDeleted: () => void
  /** float over the content whatever the screen (the split view has no room to dock) */
  float?: boolean
}) {
  const agent: AgentView | undefined = view.agents.find((a) => a.id === selected)
  const run = agent?.engine === 'code' ? (agent.raw.code as { run?: unknown } | undefined)?.run : undefined
  const hasCode = typeof run === 'string' && !run.startsWith('tuvl.')
  // a code agent opens on its Python (the panel is keyed by agent, so this resets per agent)
  const [tab, setTab] = useState<Tab>(hasCode ? 'Code' : 'Contract')
  const [confirm, setConfirm] = useState(false)
  const [more, setMore] = useState(false)
  const [showIssues, setShowIssues] = useState(false)
  const [pinned, setPinned] = useState(readPinned)
  const [sheetFull, setSheetFull] = useState(false)
  const screen = useScreen()
  const { width, handleMouseDown } = useResizablePanel(hasCode ? 600 : 400, 320, 1100)
  const tabs = TABS.filter((t) => t !== 'Code' || hasCode)
  const active = tabs.includes(tab) ? tab : 'Contract'
  // five tabs up front; the rest under More (a code agent's engine settings are rarely touched)
  const primary = tabs.filter((t) => t !== 'Governance' && !(t === 'Engine' && hasCode))
  const overflow = tabs.filter((t) => !primary.includes(t))
  const label = (t: Tab) => (t === 'Code' ? '</> Code' : t === 'Engine' ? ENGINE_LABEL[agent?.engine ?? 'pending'] ?? 'Engine' : t)
  const togglePin = () => setPinned((p) => { try { localStorage.setItem(PIN_KEY, p ? '0' : '1') } catch { /* storage unavailable */ } return !p })

  const docked = !float && (screen === 'wide' || (screen === 'mid' && pinned))
  const frame = screen === 'narrow'
    ? `fixed inset-x-0 bottom-0 z-40 ${sheetFull ? 'top-12' : 'h-[72vh]'} rounded-t-2xl border-t border-slate-700 shadow-[0_-18px_50px_rgba(0,0,0,0.55)]`
    : docked
      ? 'relative shrink-0 border-l border-slate-800'
      : 'absolute top-3 right-3 bottom-3 z-30 rounded-xl border border-slate-700 shadow-2xl shadow-black/60 overflow-hidden'
  const shell = (title: string, body: React.ReactNode, header?: React.ReactNode) => (
    <aside aria-label="Inspector" style={screen === 'narrow' ? undefined : { width: `min(${width}px, ${docked ? '60vw' : 'calc(100% - 1.5rem)'})` }}
      className={`${frame} bg-slate-900 flex flex-col min-h-0`}>
      {screen !== 'narrow' && (
        <div onMouseDown={handleMouseDown} role="separator" aria-label="Resize panel" aria-orientation="vertical"
          className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-indigo-500/40 z-10" />
      )}
      {screen === 'narrow' && <div aria-hidden="true" className="self-center w-11 h-1.5 rounded-full bg-slate-700 mt-2" />}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800">
        <span className="font-mono text-sm text-slate-100 truncate flex-1">{title}</span>
        {header}
        {screen === 'mid' && !float && (
          <button onClick={togglePin} className="w-7 h-7 rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200"
            aria-label={pinned ? 'Float the panel over the canvas' : 'Pin the panel beside the canvas'} title={pinned ? 'Float over the canvas' : 'Pin beside the canvas'}>
            {pinned ? '⇤' : '⇥'}
          </button>
        )}
        {screen === 'narrow' && (
          <button onClick={() => setSheetFull((f) => !f)} className="w-7 h-7 rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200"
            aria-label={sheetFull ? 'Shrink the panel' : 'Expand the panel'}>{sheetFull ? '⤡' : '⤢'}</button>
        )}
        <button onClick={onClose} className="w-7 h-7 rounded text-slate-500 hover:bg-slate-800 hover:text-slate-200" aria-label="Close panel">✕</button>
      </div>
      {body}
    </aside>
  )
  if (selected === '__start') {
    return shell(`${view.name} · start`, <div className="flex-1 overflow-auto p-3"><StartPanel view={view} models={models} apply={apply} /></div>)
  }
  if (!agent) return null
  const mine = issues[agent.id]?.messages ?? []
  const errs = mine.filter((m) => m.severity === 'error').length
  const warns = mine.length - errs
  // the agent's problems sit behind a badge so they never push the editor down
  const badge = mine.length > 0 && (
    <button onClick={() => setShowIssues((v) => !v)} aria-expanded={showIssues} aria-label={`${mine.length} problem${mine.length === 1 ? '' : 's'}`}
      className="flex items-center gap-1.5 text-[11px] rounded px-1.5 py-0.5 border border-slate-700 hover:border-slate-500">
      {errs > 0 && <span className="text-rose-300">✕ {errs}</span>}
      {warns > 0 && <span className="text-amber-300">⚠ {warns}</span>}
    </button>
  )
  return shell(agent.id, (
    <>
      <div className="relative flex gap-0.5 px-2 pt-2 border-b border-slate-800">
        {primary.map((t) => (
          <button key={t} onClick={() => setTab(t)} aria-label={t === 'YAML' ? 'Agent YAML' : undefined}
            title={t === 'YAML' ? 'This agent as YAML' : undefined}
            className={`px-2 py-1 text-[11px] rounded-t ${active === t ? 'bg-slate-800 text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}>{label(t)}</button>
        ))}
        {overflow.length > 0 && (
          <div className="relative">
            <button onClick={() => setMore((m) => !m)} aria-expanded={more} aria-haspopup="menu"
              className={`px-2 py-1 text-[11px] rounded-t ${overflow.includes(active) ? 'bg-slate-800 text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}>
              {overflow.includes(active) ? label(active) : 'More'} ▾
            </button>
            {more && (
              <div role="menu" className="absolute left-0 top-full z-20 mt-1 min-w-32 rounded border border-slate-700 bg-slate-900 py-1 shadow-xl">
                {overflow.map((t) => (
                  <button key={t} role="menuitem" onClick={() => { setTab(t); setMore(false) }}
                    className="block w-full text-left px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">{label(t)}</button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-3 space-y-3">
        {showIssues && mine.length > 0 && (
          <ul className="space-y-1 rounded border border-slate-800 bg-slate-950/60 p-2">
            {mine.map((m, i) => (
              <li key={i} className={`text-[11px] font-mono ${m.severity === 'error' ? 'text-rose-300' : 'text-amber-300'}`}>{m.message}</li>
            ))}
          </ul>
        )}
        {active === 'Code' && hasCode && <CodeAgentEditor key={run as string} run={run as string} agent={agent.raw} />}
        {active === 'Contract' && <ContractTab agent={agent} view={view} models={models} apply={apply} />}
        {active === 'Engine' && <EngineTab agent={agent} apply={apply} />}
        {active === 'Budget' && <BudgetTab agent={agent} apply={apply} />}
        {active === 'YAML' && <AgentYamlTab key={`${agent.id}-${agent.engine}`} agent={agent} apply={apply} />}
        {active === 'Governance' && <GovernanceTab agent={agent} view={view} apply={apply} />}
        {active === 'Routes' && <RoutesTab agent={agent} view={view} apply={apply} />}
        {active === 'Probe' && <ProbeTab key={agent.id} workflow={view.name} agent={agent} saved={saved} />}
      </div>
      <div className="px-3 pt-2 border-t border-slate-800"><ChangeCheck key={`${agent.id}-${agent.engine}`} file={file} text={text} agent={agent} saved={saved} /></div>
      <div className="flex items-center gap-2 px-3 py-2 text-xs">
        <select aria-label="Change engine" className="bg-slate-800 border border-slate-700 rounded px-1.5 py-1" value=""
          onChange={(e) => { if (e.target.value) apply((t) => changeEngine(t, agent.id, e.target.value)) }}>
          <option value="">Change engine…</option>
          {PRESETS.filter((p) => p.key !== 'pending' && !p.also).map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
        </select>
        <span className="flex-1" />
        {!confirm ? (
          <button className="text-rose-400 hover:text-rose-300" onClick={() => setConfirm(true)}>Delete</button>
        ) : (
          <>
            <button className="text-rose-300 font-medium" onClick={() => { apply((t) => removeAgent(t, agent.id)); setConfirm(false); onDeleted() }}>Delete {agent.id}</button>
            <button className="text-slate-400" onClick={() => setConfirm(false)}>Cancel</button>
          </>
        )}
      </div>
    </>
  ), badge)
}
