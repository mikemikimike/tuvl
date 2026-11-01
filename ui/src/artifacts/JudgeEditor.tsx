import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { judgeCalibrate, judgeLabel, judgeTry, writeText, type JudgeVerdict } from '../devApi'
import { Row, TextField } from '../panel/fields'
import { inputClass } from '../panel/styles'
import { addCalibration, readArtifact, removeCalibration, setIn, type Calibration } from './doc'
import { useArtifactFile } from './useArtifactFile'

const VERDICT_STYLE: Record<string, string> = {
  pass: 'text-emerald-400', fail: 'text-rose-400', uncertain: 'text-amber-400',
}

/** Judge artifact: rubric and thresholds, try it on a subject, mark verdicts into the calibration set. */
export function JudgeEditor({ name }: { name: string }) {
  const file = useArtifactFile(name)
  if (file.isLoading) return <p className="text-xs text-slate-500">Loading…</p>
  if (file.error) return <p className="text-xs text-rose-400">{(file.error as Error).message}</p>
  return <JudgeForm key={file.data!.text} name={name} file={file.data!.file} saved={file.data!.text} />
}

function JudgeForm({ name, file, saved }: { name: string; file: string; saved: string }) {
  const qc = useQueryClient()
  const [text, setText] = useState(saved)
  const [tab, setTab] = useState<'try' | 'calibration'>('try')
  const art = readArtifact(text)
  const spec = art?.spec ?? {}
  const calibration = (Array.isArray(spec.calibration) ? spec.calibration : []) as Calibration[]
  const dirty = text !== saved
  const save = useMutation({
    mutationFn: (next: string) => writeText('artifacts', file, next),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['artifact-file', name] }) },
  })
  const set = (path: (string | number)[], value: unknown) => setText((t) => setIn(t, path, value))

  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[10px] text-slate-500">artifacts/{file}</span>
        <span className="ml-auto" />
        {dirty && <button className="text-slate-400 hover:text-slate-200" onClick={() => setText(saved)}>Discard</button>}
        <button className="rounded bg-sky-600 px-2 py-1 text-white disabled:opacity-40" disabled={!dirty || save.isPending}
          onClick={() => save.mutate(text)}>{save.isPending ? 'Saving…' : 'Save'}</button>
      </div>
      {save.error && <p className="text-rose-400">{(save.error as Error).message}</p>}
      <Row label="Judge model (AgentModel or provider/model id)">
        <TextField value={String(spec.model ?? '')} mono ariaLabel="Judge model" onCommit={(v) => set(['model'], v)} />
      </Row>
      <Row label="Rubric" hint="What pass and fail mean. The judge answers {verdict, score, reasons}.">
        <textarea aria-label="Rubric" className={`${inputClass} h-28 font-mono`} defaultValue={String(spec.rubric ?? '')}
          onBlur={(e) => { if (e.target.value !== spec.rubric) set(['rubric'], e.target.value) }} />
      </Row>
      <div className="grid grid-cols-2 gap-2">
        <Row label="Min score" hint="A pass below it becomes fail">
          <TextField value={spec.min_score != null ? String(spec.min_score) : ''} ariaLabel="Min score" placeholder="0.5"
            onCommit={(v) => set(['min_score'], v === '' ? undefined : Number(v))} />
        </Row>
        <Row label="Min agreement" hint="Calibration needed to trust it">
          <TextField value={spec.min_agreement != null ? String(spec.min_agreement) : ''} ariaLabel="Min agreement" placeholder="0.9"
            onCommit={(v) => set(['min_agreement'], v === '' ? undefined : Number(v))} />
        </Row>
      </div>
      <div className="flex gap-1 border-b border-slate-800">
        {(['try', 'calibration'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-2 py-1 -mb-px border-b-2 ${tab === t ? 'border-sky-500 text-slate-100' : 'border-transparent text-slate-400'}`}>
            {t === 'try' ? 'Try' : `Calibration (${calibration.length})`}
          </button>
        ))}
      </div>
      {tab === 'try'
        ? <TryJudge name={name} text={text} onLabelled={(example) => { const next = addCalibration(text, example); setText(next); save.mutate(next) }} />
        : <CalibrationTab name={name} text={text} calibration={calibration} minAgreement={Number(spec.min_agreement ?? 0.9)}
            onRemove={(i) => setText((t) => removeCalibration(t, i))} />}
    </div>
  )
}

function TryJudge({ name, text, onLabelled }: { name: string; text: string; onLabelled: (c: Calibration) => void }) {
  const [subject, setSubject] = useState('{\n  \n}')
  const [label, setLabel] = useState('')
  const parsed = (() => { try { return { ok: true as const, value: JSON.parse(subject) as unknown } } catch (e) { return { ok: false as const, error: (e as Error).message } } })()
  const ask = useMutation({ mutationFn: () => judgeTry(name, text, parsed.ok ? parsed.value : null) })
  const mark = useMutation({
    mutationFn: async (expect: Calibration['expect']) => ({ ...(await judgeLabel(label, parsed.ok ? parsed.value : null)), expect }),
    onSuccess: ({ input, expect }) => { onLabelled({ input, expect }); setLabel('') },
  })
  const v: JudgeVerdict | undefined = ask.data
  const opposite = v?.verdict === 'pass' ? 'fail' : 'pass'
  return (
    <div className="space-y-2">
      <Row label="Subject (JSON) — what the judge sees">
        <textarea aria-label="Judge subject" className={`${inputClass} h-28 font-mono`} value={subject} onChange={(e) => setSubject(e.target.value)} />
      </Row>
      {!parsed.ok && <p className="text-amber-400">{parsed.error}</p>}
      <button className="rounded bg-slate-700 px-2 py-1 hover:bg-slate-600 disabled:opacity-40" disabled={!parsed.ok || ask.isPending}
        onClick={() => { mark.reset(); ask.mutate() }}>{ask.isPending ? 'Judging…' : '⚖ Ask the judge (live)'}</button>
      {ask.error && <p className="text-rose-400">{(ask.error as Error).message}</p>}
      {v && (
        <div className="rounded border border-slate-700 p-2 space-y-1.5">
          <p><span className={`font-semibold ${VERDICT_STYLE[v.verdict]}`}>{v.verdict}</span>
            <span className="text-slate-400"> · score {v.score.toFixed(2)}{v.cached ? ' · cached' : ''}</span></p>
          <ul className="list-disc pl-4 text-slate-300">{v.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          <div className="flex items-center gap-2 pt-1 border-t border-slate-800 whitespace-nowrap">
            <input aria-label="Calibration label" className={`${inputClass} font-mono w-40`} placeholder="label, e.g. ok-reply"
              value={label} onChange={(e) => setLabel(e.target.value)} />
            <button className="text-emerald-400 disabled:opacity-40" disabled={!label || mark.isPending}
              title={`Add to the calibration set expecting ${v.verdict}`}
              onClick={() => mark.mutate(v.verdict === 'uncertain' ? 'uncertain' : v.verdict)}>✓ right</button>
            <button className="text-rose-400 disabled:opacity-40" disabled={!label || mark.isPending}
              title={`Add to the calibration set expecting ${opposite}`} onClick={() => mark.mutate(opposite)}>✗ wrong</button>
          </div>
          {mark.error && <p className="text-rose-400">{(mark.error as Error).message}</p>}
          {mark.data && <p className="text-slate-400">Added {mark.data.input} expecting {mark.data.expect}.</p>}
        </div>
      )}
    </div>
  )
}

function CalibrationTab({ name, text, calibration, minAgreement, onRemove }: {
  name: string; text: string; calibration: Calibration[]; minAgreement: number; onRemove: (i: number) => void
}) {
  const run = useMutation({ mutationFn: () => judgeCalibrate(name, text) })
  const got = new Map((run.data?.results ?? []).map((r) => [r.input, r]))
  return (
    <div className="space-y-2">
      {calibration.length === 0
        ? <p className="text-slate-400">No labelled examples yet. Ask the judge on the Try tab and mark its verdict right or wrong.</p>
        : (
          <table className="w-full">
            <tbody>
              {calibration.map((c, i) => {
                const r = got.get(c.input)
                return (
                  <tr key={`${c.input}-${i}`}>
                    <td className="font-mono text-slate-300 pr-2 truncate max-w-[200px]" title={c.input}>{c.input.replace(/^fixtures\/judge\//, '')}</td>
                    <td className={`pr-2 ${VERDICT_STYLE[c.expect]}`}>{c.expect}</td>
                    <td className="pr-2">{r && <span className={r.agree ? 'text-emerald-400' : 'text-rose-400'}>{r.agree ? '✓' : `✗ ${r.got}`}</span>}</td>
                    <td><button className="text-slate-500 hover:text-rose-400" aria-label="Remove example" onClick={() => onRemove(i)}>✕</button></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      <button className="rounded bg-slate-700 px-2 py-1 hover:bg-slate-600 disabled:opacity-40" disabled={!calibration.length || run.isPending}
        onClick={() => run.mutate()}>{run.isPending ? 'Calibrating…' : '▶ Run calibration (live)'}</button>
      {run.error && <p className="text-rose-400">{(run.error as Error).message}</p>}
      {run.data && (
        <p className={run.data.trusted ? 'text-emerald-400' : 'text-rose-400'}>
          agreement {(run.data.agreement * 100).toFixed(0)}% (needs {(minAgreement * 100).toFixed(0)}%) — {run.data.trusted ? 'trusted' : 'untrusted: tuvl test --strict fails'}
        </p>
      )}
    </div>
  )
}
