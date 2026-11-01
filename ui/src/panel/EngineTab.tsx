import { useState } from 'react'
import { parse, stringify } from 'yaml'
import { CodeEditor } from '../components/CodeEditor'
import { isVectorStep, setField, type AgentView } from '../canvas/model'
import { Row, TextField } from './fields'
import { inputClass } from './styles'
import { HumanAccess } from './Access'
import { ModelPicker } from './ModelPicker'
import { ArtifactList, ArtifactSelect, WordsField } from './ArtifactPicker'
import { SITE_TYPES } from './artifactRefs'
import { McpServers } from './McpServers'
import { CollectionTools } from './CollectionTools'
import { VectorBlock } from './VectorBlock'
import { MemoryBlock } from './MemoryBlock'

const rec = (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})

/** decide: ordered rules (first match wins), optional model + threshold, shadow mode. */
function RulesTable({ agent, apply }: { agent: AgentView; apply: (e: (t: string) => string) => void }) {
  const d = rec(agent.raw.decide)
  const rules = (Array.isArray(d.rules) ? d.rules : []) as { when: string; then: string }[]
  const model = rec(d.model)
  const save = (next: { when: string; then: string }[]) => apply((t) => setField(t, agent.id, ['decide', 'rules'], next))
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-slate-400">Rules — first match wins; the model is asked only when none matches</p>
      <table className="w-full text-xs">
        <tbody>
          {rules.map((r, i) => (
            <tr key={i} className="align-top">
              <td className="pr-1 text-slate-500 font-mono text-[10px] pt-1.5">#{i + 1}</td>
              <td className="pr-1 w-2/3"><TextField value={r.when} mono ariaLabel={`Rule ${i + 1} condition`}
                onCommit={(v) => save(rules.map((x, k) => (k === i ? { ...x, when: v } : x)))} /></td>
              <td className="pr-1"><TextField value={r.then} mono ariaLabel={`Rule ${i + 1} result`}
                onCommit={(v) => save(rules.map((x, k) => (k === i ? { ...x, then: v } : x)))} /></td>
              <td className="whitespace-nowrap">
                <button className="text-slate-500 hover:text-slate-200 px-0.5" disabled={i === 0} aria-label="Move up"
                  onClick={() => save(rules.map((x, k) => (k === i - 1 ? rules[i] : k === i ? rules[i - 1] : x)))}>↑</button>
                <button className="text-slate-500 hover:text-rose-400 px-0.5" aria-label="Remove rule"
                  onClick={() => save(rules.filter((_, k) => k !== i))}>✕</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="text-[11px] text-indigo-300" onClick={() => save([...rules, { when: 'true', then: '' }])}>+ rule</button>
      <div className="grid grid-cols-2 gap-2 pt-1">
        <Row label="Decision model (AgentModel)">
          <ModelPicker kind="decision" label="Decision model" value={String(model.ref ?? '')}
            onChange={(v) => apply((t) => setField(t, agent.id, ['decide', 'model'], v ? { ref: v, min_confidence: model.min_confidence ?? 0.7 } : undefined))} />
        </Row>
        <Row label="Min confidence">
          <TextField value={model.min_confidence != null ? String(model.min_confidence) : ''} ariaLabel="Min confidence"
            onCommit={(v) => model.ref && apply((t) => setField(t, agent.id, ['decide', 'model', 'min_confidence'], Number(v)))} />
        </Row>
      </div>
      <label className="flex items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" checked={!!d.shadow} disabled={!model.ref}
          onChange={(e) => apply((t) => setField(t, agent.id, ['decide', 'shadow'], e.target.checked || undefined))} />
        Shadow mode — the model runs beside the rules and is journaled; the rules decide
      </label>
    </div>
  )
}

/** llm and loop: which configured AI model answers, the words it is given (written or stored), and the stored artifacts it uses. */
function ModelBlock({ agent, apply }: { agent: AgentView; apply: (e: (t: string) => string) => void }) {
  const key = agent.engine
  const block = rec(agent.raw[key])
  const text = (field: string) => (typeof block[field] === 'string' ? (block[field] as string) : '')
  const set = (path: string[], v: unknown) => apply((t) => setField(t, agent.id, [key, ...path], v))
  const words = key === 'loop' ? (['steering'] as const) : (['system', 'prompt'] as const)
  const skills = Array.isArray(block.skills) ? (block.skills as string[]) : []
  const judge = typeof rec(block.supervisor).judge === 'string' ? (rec(block.supervisor).judge as string) : ''
  return (
    <div className="space-y-2">
      <Row label="AI model">
        <ModelPicker label="AI model" value={text('model')} onChange={(v) => set(['model'], v)} />
      </Row>
      {words.map((field) => (
        <Row key={field} label={field === 'system' ? 'System prompt' : field === 'steering' ? 'Steering' : 'Prompt'}>
          <WordsField label={field} types={SITE_TYPES[field]} value={text(field)} onCommit={(v) => set([field], v)} />
        </Row>
      ))}
      <Row label="Skills" hint="Stored skill artifacts the model can draw on">
        <ArtifactList label="Skill" types={SITE_TYPES.skills} value={skills} onChange={(refs) => set(['skills'], refs)} />
      </Row>
      {key === 'loop' && (
        <>
          <CollectionTools tools={Array.isArray(block.tools) ? (block.tools as unknown[]) : []} onChange={(tools) => set(['tools'], tools)} />
          <McpServers tools={Array.isArray(block.tools) ? (block.tools as unknown[]) : []} onChange={(tools) => set(['tools'], tools)} />
          {block.supervisor != null && (
            <Row label="Supervisor judge" hint="A stored judge that reviews the loop as it runs">
              <ArtifactSelect label="Supervisor judge" types={SITE_TYPES.judge} value={judge}
                onChange={(ref) => set(['supervisor', 'judge'], ref || undefined)} />
            </Row>
          )}
        </>
      )}
    </div>
  )
}

/** Any engine block as YAML: the full contract is editable without a form per field. */
function BlockEditor({ agent, apply }: { agent: AgentView; apply: (e: (t: string) => string) => void }) {
  const key = agent.engine
  const original = stringify(agent.raw[key] ?? {}).trimEnd()
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const text = draft ?? original
  const commit = () => {
    if (draft === null || draft === original) return
    try {
      const value = parse(draft)
      apply((t) => setField(t, agent.id, [key], value))
      setDraft(null)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }
  return (
    <div className="space-y-1" onBlur={commit}>
      <p className="text-[11px] text-slate-400"><span className="font-mono">{key}:</span> block</p>
      <div className="h-56 rounded border border-slate-700 overflow-hidden">
        <CodeEditor value={text} onChange={setDraft} height="224px" />
      </div>
      {error && <p className="text-[11px] text-rose-400">{error}</p>}
      {draft !== null && draft !== original && <button className={`${inputClass} w-auto`} onClick={commit}>Apply</button>}
    </div>
  )
}

export function EngineTab({ agent, apply }: { agent: AgentView; apply: (e: (t: string) => string) => void }) {
  if (agent.engine === 'pending') {
    return <p className="text-xs text-slate-400">A contract only. Use <b>Change engine</b> on the card's menu (or the YAML tab) to implement it.</p>
  }
  return (
    <div className="space-y-4">
      {agent.engine === 'decide' && <RulesTable agent={agent} apply={apply} />}
      {(agent.engine === 'llm' || agent.engine === 'loop') && <ModelBlock agent={agent} apply={apply} />}
      {(agent.engine === 'llm' || agent.engine === 'loop') && <MemoryBlock agent={agent} apply={apply} />}
      {isVectorStep(agent) && <VectorBlock agent={agent} apply={apply} />}
      {agent.engine === 'human' && <HumanAccess agent={agent} apply={apply} />}
      <BlockEditor key={`${agent.id}-${agent.engine}`} agent={agent} apply={apply} />
    </div>
  )
}
