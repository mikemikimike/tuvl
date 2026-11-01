import { useState } from 'react'
import { parse, stringify } from 'yaml'
import { CodeEditor } from '../components/CodeEditor'
import { checkAgent, replaceAgent, type AgentView } from '../canvas/model'
import { inputClass } from './styles'

/** The whole agent as YAML: what the other tabs edit one field at a time. */
export function AgentYamlTab({ agent, apply }: { agent: AgentView; apply: (e: (t: string) => string) => void }) {
  const original = stringify(agent.raw, { lineWidth: 0 }).trimEnd()
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const text = draft ?? original
  const dirty = draft !== null && draft !== original
  const commit = () => {
    if (!dirty || draft === null) return
    try {
      const value = parse(draft)
      checkAgent(agent.id, value)
      apply((t) => replaceAgent(t, agent.id, value))
      setDraft(null)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }
  return (
    <div className="space-y-2" onBlur={commit}>
      <p className="text-[11px] text-slate-400">
        <span className="font-mono">{agent.id}</span> as it is in the workflow file. Edit it and click outside (or Apply); the id cannot change here.
      </p>
      <div className="h-80 rounded border border-slate-700 overflow-hidden" aria-label="Agent YAML">
        <CodeEditor value={text} onChange={(v) => { setDraft(v); setError(null) }} height="320px" />
      </div>
      {error && <p role="alert" className="text-[11px] text-rose-400">{error}</p>}
      {dirty && (
        <div className="flex gap-2">
          <button className={`${inputClass} w-auto`} onClick={commit}>Apply</button>
          <button className={`${inputClass} w-auto`} onClick={() => { setDraft(null); setError(null) }}>Discard</button>
        </div>
      )}
    </div>
  )
}
