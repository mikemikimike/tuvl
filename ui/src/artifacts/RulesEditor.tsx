import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { rulesTry, writeText } from '../devApi'
import { Row, TextField } from '../panel/fields'
import { inputClass } from '../panel/styles'
import { readArtifact, setIn, type Rule } from './doc'
import { useArtifactFile } from './useArtifactFile'

/** Rules artifact: an ordered decision table reused by `decide.rules: artifact://…`. */
export function RulesEditor({ name }: { name: string }) {
  const file = useArtifactFile(name)
  if (file.isLoading) return <p className="text-xs text-slate-500">Loading…</p>
  if (file.error) return <p className="text-xs text-rose-400">{(file.error as Error).message}</p>
  return <RulesForm key={file.data!.text} name={name} file={file.data!.file} saved={file.data!.text} />
}

function RulesForm({ name, file, saved }: { name: string; file: string; saved: string }) {
  const qc = useQueryClient()
  const [text, setText] = useState(saved)
  const [context, setContext] = useState('{\n  \n}')
  const rules = ((readArtifact(text)?.spec.rules ?? []) as Rule[])
  const dirty = text !== saved
  const put = (next: Rule[]) => setText((t) => setIn(t, ['rules'], next))
  const save = useMutation({
    mutationFn: () => writeText('artifacts', file, text),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['artifact-file', name] }) },
  })
  const parsed = (() => { try { return JSON.parse(context) as Record<string, unknown> } catch { return null } })()
  const tryIt = useMutation({ mutationFn: () => rulesTry(text, parsed ?? {}) })
  const hit = tryIt.data

  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[10px] text-slate-500">artifacts/{file}</span>
        <span className="ml-auto" />
        {dirty && <button className="text-slate-400 hover:text-slate-200" onClick={() => setText(saved)}>Discard</button>}
        <button className="rounded bg-sky-600 px-2 py-1 text-white disabled:opacity-40" disabled={!dirty || save.isPending}
          onClick={() => save.mutate()}>{save.isPending ? 'Saving…' : 'Save'}</button>
      </div>
      {save.error && <p className="text-rose-400">{(save.error as Error).message}</p>}
      <p className="text-[11px] text-slate-400">First match wins. <span className="font-mono">then</span> must be a value of the deciding agent's enum output.</p>
      <table className="w-full">
        <tbody>
          {rules.map((r, i) => (
            <tr key={i} className={`align-top ${hit?.rule === i + 1 ? 'bg-emerald-900/20' : ''}`}>
              <td className="pr-1 pt-1.5 font-mono text-[10px] text-slate-500">#{i + 1}</td>
              <td className="pr-1 w-2/3"><TextField value={r.when} mono ariaLabel={`Rule ${i + 1} condition`}
                onCommit={(v) => put(rules.map((x, k) => (k === i ? { ...x, when: v } : x)))} /></td>
              <td className="pr-1"><TextField value={r.then} mono ariaLabel={`Rule ${i + 1} result`}
                onCommit={(v) => put(rules.map((x, k) => (k === i ? { ...x, then: v } : x)))} /></td>
              <td className="whitespace-nowrap">
                <button className="px-0.5 text-slate-500 hover:text-slate-200" disabled={i === 0} aria-label="Move up"
                  onClick={() => put(rules.map((x, k) => (k === i - 1 ? rules[i] : k === i ? rules[i - 1] : x)))}>↑</button>
                <button className="px-0.5 text-slate-500 hover:text-rose-400" disabled={rules.length === 1} aria-label="Remove rule"
                  onClick={() => put(rules.filter((_, k) => k !== i))}>✕</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="text-[11px] text-indigo-300" onClick={() => put([...rules, { when: 'true', then: '' }])}>+ rule</button>
      <Row label="Try with a context (JSON)">
        <textarea aria-label="Rules context" className={`${inputClass} h-20 font-mono`} value={context} onChange={(e) => setContext(e.target.value)} />
      </Row>
      <button className="rounded bg-slate-700 px-2 py-1 hover:bg-slate-600 disabled:opacity-40" disabled={!parsed || tryIt.isPending}
        onClick={() => tryIt.mutate()}>Which rule matches?</button>
      {tryIt.error && <p className="text-rose-400">{(tryIt.error as Error).message}</p>}
      {hit && (
        <p className={hit.error ? 'text-rose-400' : hit.rule ? 'text-emerald-400' : 'text-amber-400'}>
          {hit.error ? `rule #${hit.rule}: ${hit.error}` : hit.rule ? `rule #${hit.rule} → ${hit.then}` : 'no rule matches — the decision model is asked, or the agent errors with no_rule_matched'}
        </p>
      )}
    </div>
  )
}
