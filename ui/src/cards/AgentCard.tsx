import { Handle, Position, type NodeProps } from '@xyflow/react'
import { determinism, type AgentView } from '../canvas/model'
import type { ValidationIssue } from '../types'
import { EngineIcon } from './EngineIcon'
import { HoverInfo } from './NodeInfo'
import { ENGINE_LABEL, FRAME, HEADER } from './style'

export interface AgentCardData extends Record<string, unknown> {
  agent: AgentView
  issues: { errors: number; warnings: number; first?: string; messages?: ValidationIssue[] }
  outlets: string[]
  missingInputs: string[]
  breakpoint: boolean
  onToggleBreakpoint: () => void
}

const rec = (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})

function Chips({ agent }: { agent: AgentView }) {
  const budget = rec(agent.raw.budget)
  const chips: string[] = []
  if (budget.timeout) chips.push(`⏱ ${String(budget.timeout)}`)
  if (budget.max_tokens) chips.push(`${String(budget.max_tokens)} tok`)
  if (budget.max_iterations) chips.push(`≤${String(budget.max_iterations)} turns`)
  if (rec(budget.retry).attempts) chips.push(`retry ×${String(rec(budget.retry).attempts)}`)
  const guards = rec(agent.raw.guardrails)
  const n = ['input', 'output', 'tools'].reduce((k, g) => k + ((guards[g] as unknown[] | undefined)?.length ?? 0), 0)
  if (n) chips.push(`🛡 ${n}`)
  if (agent.raw.effect) chips.push(String(agent.raw.effect))
  if (agent.raw.compensate) chips.push('↶ compensate')
  return chips.length ? (
    <div className="flex flex-wrap gap-1">{chips.map((c) => <span key={c} className="rounded bg-slate-900/70 px-1 text-[10px] text-slate-400">{c}</span>)}</div>
  ) : null
}

function EngineSummary({ agent }: { agent: AgentView }) {
  if (agent.engine === 'decide') {
    const d = rec(agent.raw.decide)
    const rules = Array.isArray(d.rules) ? d.rules.length : 0
    const model = rec(d.model)
    return (
      <p className="text-[10px] text-sky-300">
        {rules} rule{rules === 1 ? '' : 's'}{model.ref ? ` · ${String(model.ref)} ≥ ${String(model.min_confidence)}` : ''}{d.shadow ? ' · shadow' : ''}
      </p>
    )
  }
  if (agent.engine === 'loop') {
    const tools = (rec(agent.raw.loop).tools as Record<string, unknown>[] | undefined) ?? []
    return (
      <ul className="space-y-0.5">
        {tools.map((t, i) => {
          const name = String(t.agent ?? t.workflow ?? t.mcp ?? '?')
          const kind = t.agent ? 'agent' : t.workflow ? 'workflow' : 'mcp'
          return (
            <li key={i} className="flex items-center gap-1 text-[10px] text-slate-300">
              <span className="text-slate-500">{kind === 'mcp' ? 'MCP' : kind === 'workflow' ? 'W' : 'A'}</span>
              <span className="font-mono truncate">{name.replace('artifact://', '')}</span>
              {t.approval ? <span title="needs approval">🔒</span> : null}
              {t.max_calls ? <span className="text-slate-500">×{String(t.max_calls)}</span> : null}
            </li>
          )
        })}
        {tools.length === 0 && <li className="text-[10px] text-rose-300">no tools yet</li>}
      </ul>
    )
  }
  if (agent.engine === 'tool') {
    const t = rec(agent.raw.tool)
    const what =
      t.use === 'db'
        ? `${String(t.op)} ${String(t.model)}`
        : t.use === 'http'
          ? `${String(t.method)} ${String(t.url)}`
          : t.use === 'storage'
            ? `${String(t.op)} ${String(t.store)}${t.key ? `/${String(t.key)}` : ''}`
            : `${String(t.name)}`
    return <p className="text-[10px] font-mono text-slate-400 truncate">{String(t.use)} · {what}</p>
  }
  if (agent.engine === 'parallel') {
    const branches = rec(agent.raw.parallel).branches
    const ids = Array.isArray(branches) ? branches.map((b) => String(rec(b).id)) : []
    return <p className="text-[10px] font-mono text-slate-400 truncate">{ids.length} at once: {ids.join(' · ')}</p>
  }
  if (agent.engine === 'map') {
    const m = rec(agent.raw.map)
    return <p className="text-[10px] font-mono text-slate-400 truncate">each of {String(m.over)} → {String(m.workflow)}</p>
  }
  if (agent.engine === 'code') return <p className="text-[10px] font-mono text-slate-400 truncate">{String(rec(agent.raw.code).run)}</p>
  if (agent.engine === 'llm') return <p className="text-[10px] text-slate-400 truncate">{String(rec(agent.raw.llm).model)}</p>
  return null
}

const OUTLET_GAP = 18

export function AgentCard({ data, selected }: NodeProps) {
  const { agent, issues, outlets, missingInputs, breakpoint, onToggleBreakpoint } = data as AgentCardData
  const det = determinism(agent)
  const errorRing = issues.errors ? 'ring-2 ring-rose-500/80' : issues.warnings ? 'ring-1 ring-amber-400/60' : ''
  const height = Math.max(96, 46 + outlets.length * OUTLET_GAP)
  return (
    <HoverInfo
      agent={agent}
      messages={issues.messages ?? []}
      className={`group w-60 rounded-lg border ${FRAME[det]} ${errorRing} ${selected ? 'outline outline-2 outline-indigo-400' : ''} shadow-lg`}
      style={{ minHeight: height }}
    >
      <Handle type="target" position={Position.Left} className={missingInputs.length ? '!bg-rose-500' : '!bg-slate-400'} />
      <div className={`flex items-center gap-1.5 px-2 pt-1.5 text-[10px] uppercase tracking-wide ${HEADER[det]}`}>
        <EngineIcon engine={agent.engine} />
        <span>{ENGINE_LABEL[agent.engine]}</span>
        {det !== agent.engine && <span className="text-slate-500 normal-case">{det}</span>}
        <span className="flex-1" />
        <button
          className={`nodrag h-2.5 w-2.5 rounded-full border ${breakpoint ? 'bg-rose-500 border-rose-400' : 'border-slate-500 opacity-0 group-hover:opacity-100 hover:border-rose-400'}`}
          title={breakpoint ? 'Breakpoint: dev runs pause before this agent' : 'Set a breakpoint'}
          aria-label={breakpoint ? `Remove breakpoint on ${agent.id}` : `Set breakpoint on ${agent.id}`}
          onClick={(e) => { e.stopPropagation(); onToggleBreakpoint() }}
        />
        {issues.errors > 0 && <span className="rounded bg-rose-600 px-1 text-white">{issues.errors}</span>}
        {issues.errors === 0 && issues.warnings > 0 && <span className="rounded bg-amber-600/80 px-1 text-white">{issues.warnings}</span>}
      </div>
      <div className="px-2 pb-2 pr-14 space-y-1">
        <p className="font-mono text-sm text-slate-100 truncate">{agent.id}</p>
        <p className="text-[11px] text-slate-400 leading-snug line-clamp-2">{agent.description}</p>
        <EngineSummary agent={agent} />
        {Object.keys(agent.inputs).length > 0 && (
          <p className="text-[10px] text-slate-500 truncate">
            in {Object.entries(agent.inputs).map(([k, t]) => (
              <span key={k} className={missingInputs.includes(k) ? 'text-rose-400' : ''}>{k}:{t} </span>
            ))}
          </p>
        )}
        {Object.keys(agent.outputs).length > 0 && (
          <p className="text-[10px] text-slate-500 truncate">out {Object.entries(agent.outputs).map(([k, t]) => `${k}:${t}`).join(' ')}</p>
        )}
        <Chips agent={agent} />
      </div>
      {outlets.map((signal, i) => (
        <div key={signal} className="absolute right-0 flex items-center" style={{ top: 30 + i * OUTLET_GAP }}>
          <span className={`mr-2 text-[10px] ${agent.routes[signal] ? 'text-slate-400' : 'text-rose-400'}`}>{signal}</span>
          <Handle id={signal} type="source" position={Position.Right} className={agent.routes[signal] ? '!bg-slate-300' : '!bg-rose-500'} style={{ top: 'auto', position: 'relative', transform: 'none' }} />
        </div>
      ))}
      <Handle id="__tools" type="source" position={Position.Bottom} className="!bg-transparent !border-0" isConnectable={false} />
    </HoverInfo>
  )
}
