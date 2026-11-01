import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { startRun } from '../runsApi'

export function StartRun({ workflows, onStarted }: { workflows: string[]; onStarted: (runId: string) => void }) {
  const [open, setOpen] = useState(false)
  const [workflow, setWorkflow] = useState('')
  const [input, setInput] = useState('{\n  \n}')
  const [error, setError] = useState<string | null>(null)
  const start = useMutation({
    mutationFn: () => startRun(workflow || workflows[0], JSON.parse(input) as Record<string, unknown>),
    onSuccess: (r) => { setOpen(false); setError(null); onStarted(r.run_id) },
    onError: (e: Error) => setError(e.message),
  })
  if (!open) {
    return <button onClick={() => setOpen(true)} disabled={!workflows.length} className="text-xs px-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40">▶ Start run</button>
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setOpen(false)}>
      <div className="w-[28rem] rounded-lg border border-slate-700 bg-slate-900 p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
        <p className="text-sm font-semibold">Start a run</p>
        <select aria-label="Workflow" value={workflow || workflows[0]} onChange={(e) => setWorkflow(e.target.value)}
          className="w-full bg-slate-800 border border-slate-700 rounded text-sm px-2 py-1">
          {workflows.map((w) => <option key={w}>{w}</option>)}
        </select>
        <textarea aria-label="Input JSON" rows={8} value={input} onChange={(e) => setInput(e.target.value)}
          className="w-full font-mono text-xs bg-slate-950 border border-slate-700 rounded p-2" />
        {error && <p className="text-xs text-rose-400">{error}</p>}
        <div className="flex justify-end gap-2">
          <button onClick={() => setOpen(false)} className="text-xs px-3 py-1 rounded bg-slate-700">Cancel</button>
          <button
            onClick={() => { try { JSON.parse(input) } catch { setError('input is not valid JSON'); return } start.mutate() }}
            disabled={start.isPending} className="text-xs px-3 py-1 rounded bg-indigo-600 hover:bg-indigo-500">Start</button>
        </div>
      </div>
    </div>
  )
}
