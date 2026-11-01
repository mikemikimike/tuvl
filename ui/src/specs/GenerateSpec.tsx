import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { generateSpec } from '../devApi'
import type { IdeasMe } from '../devApi'
import { JobOutput } from './JobOutput'

/** Asks your coding agent to draft a spec from an idea (`tuvl generate spec --idea`), and shows what it prints. */
export function GenerateSpec({ idea, me }: { idea: string; me: IdeasMe }) {
  const [asking, setAsking] = useState(false)
  const [where, setWhere] = useState<'here' | 'branch'>('here')
  const [title, setTitle] = useState('')
  const [job, setJob] = useState<string | null>(null)
  const start = useMutation({
    mutationFn: () => generateSpec(idea, where, title),
    onSuccess: (r) => { setJob(r.job); setAsking(false) },
  })
  const btn = 'px-2.5 py-1 rounded text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-40'
  const noAgent = me.agent === 'none'
  return (
    <div className="space-y-2">
      {noAgent ? (
        <p className="text-xs text-slate-500">
          To have your coding agent draft a spec from this idea, choose it first: <code>tuvl use agent &lt;agent&gt;</code> (<code>tuvl list agents</code> shows what is installed).
        </p>
      ) : (
        !asking && !job && (
          <button className={`${btn} bg-indigo-700 hover:bg-indigo-600`} onClick={() => setAsking(true)}
            title={`tuvl generate spec --idea ${idea}: ${me.agent} writes a draft spec from this idea`}>
            Generate a spec with my agent ($)
          </button>
        )
      )}
      {asking && (
        <div className="rounded border border-amber-700/60 bg-amber-950/30 p-3 text-xs text-amber-100 space-y-3" role="group" aria-label="Generate a spec">
          <p>
            {me.agent} reads this idea and writes a draft spec. It spends tokens of your own account{me.consent ? '' : ', and the first time it records your consent to send the idea’s files to your coding agent'}.
            It may change only the spec file.
          </p>
          <fieldset className="space-y-1">
            <legend className="sr-only">Where the draft goes</legend>
            <label className="flex items-start gap-2">
              <input type="radio" name="where" checked={where === 'here'} onChange={() => setWhere('here')} />
              <span>Into this project, uncommitted. The Specs page shows it at once; review it, then approve.</span>
            </label>
            <label className="flex items-start gap-2">
              <input type="radio" name="where" checked={where === 'branch'} onChange={() => setWhere('branch')} />
              <span>On a <code>spec/&lt;id&gt;</code> branch, nothing pushed. The idea must be committed.</span>
            </label>
          </fieldset>
          <input aria-label="Spec title" className="w-full rounded border border-amber-800/60 bg-slate-950 px-2 py-1 text-xs text-slate-100 placeholder-slate-600"
            value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Spec title (optional: the idea's)" />
          <div className="flex gap-2">
            <button className={`${btn} bg-amber-700 hover:bg-amber-600`} disabled={start.isPending} onClick={() => start.mutate()}>Run it</button>
            <button className={btn} onClick={() => setAsking(false)}>Cancel</button>
          </div>
        </div>
      )}
      {start.error && <p role="alert" className="text-xs text-rose-400">{(start.error as Error).message}</p>}
      {job && (
        <>
          <JobOutput job={job} label="Spec generation output" />
          <button className={btn} onClick={() => setJob(null)}>Done</button>
        </>
      )}
    </div>
  )
}
