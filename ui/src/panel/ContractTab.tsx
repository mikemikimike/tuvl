import { renameAgent, setField, type AgentView, type WorkflowView } from '../canvas/model'
import { FieldMapEditor, Row, TextField } from './fields'

/** Outputs that reach this agent: the trigger input (entry) and agents routing to it. */
function upstream(agent: AgentView, view: WorkflowView): Record<string, string> {
  const found: Record<string, string> = {}
  if (view.entry === agent.id) Object.assign(found, view.trigger.input)
  for (const a of view.agents) {
    if (Object.values(a.routes).includes(agent.id)) Object.assign(found, a.outputs)
  }
  return found
}

export function ContractTab({ agent, view, models, apply }: {
  agent: AgentView
  view: WorkflowView
  models: string[]
  apply: (edit: (text: string) => string) => void
}) {
  const offered = Object.entries(upstream(agent, view)).filter(([k]) => !(k in agent.inputs))
  return (
    <div className="space-y-3">
      <Row label="Id" hint="snake_case; renaming updates every route, tool and compensate reference">
        <TextField value={agent.id} mono ariaLabel="Agent id" onCommit={(v) => apply((t) => renameAgent(t, agent.id, v.trim()))} />
      </Row>
      <Row label="Description" hint="What it does — loop tools show this to the model">
        <TextField value={agent.description} ariaLabel="Description" onCommit={(v) => apply((t) => setField(t, agent.id, ['description'], v))} />
      </Row>
      <div>
        <p className="text-[11px] text-slate-400 mb-1">Inputs</p>
        <FieldMapEditor label="inputs" fields={agent.inputs} models={models}
          onChange={(next) => apply((t) => setField(t, agent.id, ['inputs'], next))} />
        {offered.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1 items-center">
            <span className="text-[10px] text-slate-500">from upstream:</span>
            {offered.map(([k, type]) => (
              <button key={k} className="rounded bg-slate-800 hover:bg-slate-700 px-1.5 text-[10px] font-mono text-slate-300"
                onClick={() => apply((t) => setField(t, agent.id, ['inputs'], { ...agent.inputs, [k]: type }))}>
                + {k}: {type}
              </button>
            ))}
          </div>
        )}
      </div>
      <div>
        <p className="text-[11px] text-slate-400 mb-1">Outputs</p>
        {agent.signalOutputs ? (
          <div className="space-y-1">
            {Object.entries(agent.signalOutputs).map(([signal, fields]) => (
              <div key={signal} className="text-[11px] font-mono">
                <span className="text-slate-400">on {signal}:</span>{' '}
                {Object.keys(fields).length === 0 ? <span className="text-slate-500">nothing</span>
                  : Object.entries(fields).map(([k, t]) => <span key={k} className="mr-2 text-slate-200">{k}<span className="text-slate-500">: {t}</span></span>)}
              </div>
            ))}
            <p className="text-[11px] text-slate-500">Per-signal outputs — edit them in the YAML tab.</p>
          </div>
        ) : (
          <FieldMapEditor label="outputs" fields={agent.outputs} models={models}
            onChange={(next) => apply((t) => setField(t, agent.id, ['outputs'], next))} />
        )}
      </div>
    </div>
  )
}
