import { Handle, Position, type NodeProps } from '@xyflow/react'
import { accessSummary, apiOn, type WorkflowView } from '../canvas/model'

export function StartNode({ data, selected }: NodeProps) {
  const { trigger, access } = data as { trigger: WorkflowView['trigger']; access: WorkflowView['access'] }
  const who = accessSummary(access)
  return (
    <div className={`w-52 rounded-lg border border-emerald-600/70 bg-emerald-950/40 px-2 py-1.5 ${selected ? 'outline outline-2 outline-indigo-400' : ''}`}>
      <p className="text-[10px] uppercase tracking-wide text-emerald-300">Start</p>
      {trigger.http && (
        <p className={`text-xs font-mono ${apiOn(trigger) ? 'text-slate-200' : 'text-slate-500 line-through'}`}>{trigger.http.method ?? 'POST'} {trigger.http.path}</p>
      )}
      {trigger.schedule && (
        <p className={`text-xs font-mono ${trigger.schedule.enabled ? 'text-slate-200' : 'text-slate-500 line-through'}`}>⏰ {trigger.schedule.cron}</p>
      )}
      {!apiOn(trigger) && !trigger.schedule?.enabled && <p className="text-xs text-slate-400">no trigger enabled</p>}
      <p className={`mt-0.5 text-[10px] font-mono truncate ${who.kind === 'public' ? 'text-amber-300' : who.kind === 'signed-in' ? 'text-slate-400' : 'text-sky-300'}`}
        title="Who may run this workflow — click to change">
        {who.kind === 'public' ? '○' : '🔒'} {who.label}
      </p>
      {Object.keys(trigger.input).length > 0 && (
        <p className="text-[10px] text-slate-400 truncate">{Object.entries(trigger.input).map(([k, t]) => `${k}:${t}`).join(' ')}</p>
      )}
      <Handle id="out" type="source" position={Position.Right} className="!bg-emerald-400" />
    </div>
  )
}

export function EndNode({ data, selected }: NodeProps) {
  const { name, status } = data as { name: string; status?: number }
  return (
    <div className={`rounded-full border border-slate-500 bg-slate-900 px-3 py-1 text-xs ${selected ? 'outline outline-2 outline-indigo-400' : ''}`}>
      <Handle type="target" position={Position.Left} className="!bg-slate-400" />
      <span className="font-mono text-slate-200">{name === 'default' ? 'END' : `END.${name}`}</span>
      <span className="ml-1 text-slate-500">{status ?? 200}</span>
    </div>
  )
}
