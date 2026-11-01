import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { jobState, stopJob } from '../devApi'
import type { JobState } from '../devApi'

/** Follows a command started from Insight (`/dev/jobs/<id>`): its output so far, and Stop while it runs. */
export function JobOutput({ job, label = 'Output', failedHint = 'see the output below', lostHint = 'check again in a moment', onDone }: {
  job: string
  label?: string
  failedHint?: string
  lostHint?: string
  onDone?: (status: JobState['status']) => void
}) {
  const qc = useQueryClient()
  const [lines, setLines] = useState<string[]>([])
  const [state, setState] = useState<JobState['status']>('running')
  const after = useRef(0)
  const log = useRef<HTMLPreElement>(null)

  useEffect(() => {
    after.current = 0
    setLines([])
    setState('running')
  }, [job])

  useEffect(() => {
    if (state !== 'running') return
    const timer = window.setInterval(async () => {
      try {
        const s = await jobState(job, after.current)
        after.current = s.next
        if (s.lines.length > 0) setLines((old) => [...old, ...s.lines])
        if (s.status !== 'running') {
          setState(s.status)
          void qc.invalidateQueries({ queryKey: ['dev'] })
          onDone?.(s.status)
        }
      } catch (e) {
        setLines((old) => [...old, `Lost contact with the dev server: ${(e as Error).message}. It may have restarted; the command may still have finished: ${lostHint}.`])
        setState('failed')
        onDone?.('failed')
      }
    }, 1000)
    return () => window.clearInterval(timer)
  }, [job, state, qc, onDone, lostHint])

  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight }) }, [lines])

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <span role="status">
          {state === 'running' ? '● running…' : state === 'ok' ? '✓ finished' : state === 'stopped' ? 'stopped' : `✗ failed — ${failedHint}`}
        </span>
        {state === 'running' && (
          <button className="px-2.5 py-1 rounded text-xs bg-slate-700 hover:bg-slate-600" onClick={() => void stopJob(job)}>Stop</button>
        )}
      </div>
      <pre ref={log} aria-label={label}
        className="max-h-64 overflow-auto whitespace-pre-wrap rounded border border-slate-700 bg-slate-950/70 p-3 font-mono text-xs text-slate-300">{lines.join('\n')}</pre>
    </div>
  )
}
