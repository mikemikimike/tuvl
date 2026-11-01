import { setWorkflowField, type WorkflowView } from '../canvas/model'
import { FieldMapEditor, Row, TextField } from './fields'
import { WorkflowAccess } from './Access'
import { TriggerPanel } from './TriggerPanel'

export function StartPanel({ view, models, apply }: { view: WorkflowView; models: string[]; apply: (e: (t: string) => string) => void }) {
  const set = (path: (string | number)[], value: unknown) => apply((t) => setWorkflowField(t, path, value))
  return (
    <div className="space-y-3">
      <Row label="Description"><TextField value={view.description} ariaLabel="Workflow description" onCommit={(v) => set(['metadata', 'description'], v)} /></Row>
      <Row label="Group" hint="Organises the workflow picker; leave empty for none">
        <TextField value={view.group ?? ''} ariaLabel="Workflow group" placeholder="e.g. payments"
          onCommit={(v) => set(['metadata', 'group'], v.trim() || undefined)} />
      </Row>
      <TriggerPanel view={view} apply={apply} />
      <WorkflowAccess view={view} apply={apply} />
      <div>
        <p className="text-[11px] text-slate-400 mb-1">Input</p>
        <FieldMapEditor label="trigger" fields={view.trigger.input} models={models} onChange={(next) => set(['spec', 'trigger', 'input'], next)} />
      </div>
      <div>
        <p className="text-[11px] text-slate-400 mb-1">Ends</p>
        <ul className="text-xs space-y-0.5">
          {Object.entries(view.ends).map(([name, e]) => (
            <li key={name} className="flex gap-2 items-center">
              <span className="font-mono text-slate-300 w-28">{name === 'default' ? 'END' : `END.${name}`}</span>
              <TextField value={String(e.status ?? 200)} ariaLabel={`Status of ${name}`}
                onCommit={(v) => set(['spec', 'outputs', name, 'status'], Number(v) === 200 ? undefined : Number(v))} />
            </li>
          ))}
        </ul>
        <p className="text-[10px] text-slate-500 mt-1">Response bodies and rollback flags: YAML tab.</p>
      </div>
    </div>
  )
}
