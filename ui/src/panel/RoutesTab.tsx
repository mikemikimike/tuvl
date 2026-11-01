import { useState } from 'react'
import { addEnd, setRoute, type AgentView, type WorkflowView } from '../canvas/model'
import { outletsOf, requiredSignals } from '../canvas/outlets'
import { inputClass } from './styles'

export function RoutesTab({ agent, view, apply }: { agent: AgentView; view: WorkflowView; apply: (e: (t: string) => string) => void }) {
  const [signal, setSignal] = useState('')
  const [end, setEnd] = useState('')
  const required = new Set(requiredSignals(agent))
  const targets = [
    ...view.agents.filter((a) => a.id !== agent.id && a.role === 'spine').map((a) => a.id),
    ...Object.keys(view.ends).map((e) => (e === 'default' ? 'END' : `END.${e}`)),
  ]
  return (
    <div className="space-y-2">
      <table className="w-full text-xs">
        <tbody>
          {outletsOf(agent).map((s) => (
            <tr key={s}>
              <td className="py-0.5 pr-2 font-mono text-slate-300 whitespace-nowrap">
                {s}{required.has(s) && !agent.routes[s] && <span className="ml-1 text-rose-400" title="required">*</span>}
              </td>
              <td className="py-0.5 w-full">
                <select aria-label={`Route ${s}`} className={inputClass} value={agent.routes[s] ?? ''}
                  onChange={(e) => apply((t) => setRoute(t, agent.id, s, e.target.value || null))}>
                  <option value="">— unrouted —</option>
                  {targets.map((x) => <option key={x}>{x}</option>)}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); if (signal.trim()) { apply((t) => setRoute(t, agent.id, signal.trim(), 'END')); setSignal('') } }}>
        <input value={signal} onChange={(e) => setSignal(e.target.value)} placeholder="new signal" aria-label="New signal" className={`${inputClass} font-mono`} />
        <button className="text-xs px-2 rounded bg-slate-700">Add</button>
      </form>
      <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); if (end.trim()) { apply((t) => addEnd(t, end.trim(), 200)); setEnd('') } }}>
        <input value={end} onChange={(e) => setEnd(e.target.value)} placeholder="new end (e.g. rejected)" aria-label="New end" className={`${inputClass} font-mono`} />
        <button className="text-xs px-2 rounded bg-slate-700">Add end</button>
      </form>
    </div>
  )
}
