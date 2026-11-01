import { useCallback, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { buildTask } from '../devApi'
import { JobOutput } from './JobOutput'

const NOTE =
  'Your coding agent builds this task on a feature branch (nothing is pushed). It spends tokens of your own account, ' +
  'and the first time it also records your consent to send the project files to your coding agent.'

/**
 * Runs `tuvl generate code --task` for an agent task with the developer's own coding agent, and shows what it prints.
 * Other task types are not the agent's work: models and workflows come from the scaffold (no tokens).
 */
export function RunWithAgent({ spec, id, type, blocked }: { spec: string; id: string; type: string; blocked?: string[] }) {
  const [asking, setAsking] = useState(false)
  const [job, setJob] = useState<string | null>(null)
  const [running, setRunning] = useState(false)

  const scaffoldOnly = type !== 'agent'
  const start = useMutation({
    mutationFn: () => buildTask(spec, id, scaffoldOnly),
    onSuccess: (r) => { setRunning(true); setJob(r.job); setAsking(false) },
  })

  const done = useCallback(() => setRunning(false), [])

  const btn = 'px-2.5 py-1 rounded text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-40'
  return (
    <div className="mt-4 border-t border-slate-700 pt-3 space-y-2">
      {scaffoldOnly && !running && (
        <>
          <p className="text-xs text-slate-400">
            A {type} task is not built by the coding agent: models and workflows come from the scaffold, tests from the spec&apos;s examples.
          </p>
          <button className={btn} disabled={start.isPending} onClick={() => start.mutate()}
            title="tuvl generate code --no-agent: models, workflows and tests from the spec; no tokens">
            Generate the scaffold (no tokens)
          </button>
        </>
      )}
      {!scaffoldOnly && !asking && !running && (
        <button className={`${btn} bg-indigo-700 hover:bg-indigo-600`} onClick={() => setAsking(true)} disabled={!!blocked}
          title={blocked ? `Blocked — ${blocked.join('; ')}` : 'tuvl generate code --task: your coding agent implements this task'}>
          Run with my agent ($)
        </button>
      )}
      {!scaffoldOnly && blocked && (
        <p role="status" className="text-xs text-rose-300">Blocked, so it cannot run yet: {blocked.join('; ')}</p>
      )}
      {asking && (
        <div className="rounded border border-amber-700/60 bg-amber-950/30 p-3 text-xs text-amber-100 space-y-2">
          <p>{NOTE}</p>
          <div className="flex gap-2">
            <button className={`${btn} bg-amber-700 hover:bg-amber-600`} disabled={start.isPending} onClick={() => start.mutate()}>Run it</button>
            <button className={btn} onClick={() => setAsking(false)}>Cancel</button>
          </div>
        </div>
      )}
      {start.error && <p className="text-xs text-rose-400">{(start.error as Error).message}</p>}
      {job && (
        <JobOutput job={job} label="Agent output" failedHint="see the output below, and “Why it failed” above"
          lostHint="check tuvl list tasks" onDone={done} />
      )}
    </div>
  )
}
