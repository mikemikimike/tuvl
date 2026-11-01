import { useMutation } from '@tanstack/react-query'
import { changeCheck, runCodegen } from '../devApi'
import type { AgentView } from '../canvas/model'

/** After an engine change: replay the pinned fixtures with this agent executing, and compare cost. */
export function ChangeCheck({ file, text, agent, saved }: { file: string; text: string; agent: AgentView; saved: boolean }) {
  const check = useMutation({ mutationFn: () => changeCheck(file, text, agent.id) })
  const stub = useMutation({ mutationFn: () => runCodegen(true) })
  const r = check.data
  return (
    <div className="space-y-1.5 text-xs">
      <div className="flex gap-2">
        <button className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40" disabled={check.isPending}
          title="Replay pinned runs of this workflow with this agent executing; the rest comes from the recording"
          onClick={() => check.mutate()}>
          {check.isPending ? 'Checking…' : '⇄ Check vs fixtures'}
        </button>
        {agent.engine === 'code' && (
          <button className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40" disabled={!saved || stub.isPending}
            title={saved ? 'tuvl codegen: create or update the agent stub' : 'Save first'} onClick={() => stub.mutate()}>
            {stub.isPending ? 'Generating…' : '⌘ Generate stub'}
          </button>
        )}
      </div>
      {stub.data && <p className="text-slate-400">codegen: {(stub.data.written ?? []).map((w) => w.path).join(', ') || 'up to date'}</p>}
      {check.error && <p className="text-rose-400">{(check.error as Error).message}</p>}
      {r && (
        <div className="rounded border border-slate-700 p-2 space-y-1">
          {r.fixtures === 0 ? (
            <p className="text-slate-400">No pinned fixtures for this workflow yet — pin a run on the Runs page first.</p>
          ) : (
            <ul className="space-y-0.5">
              {r.replays.map((x) => (
                <li key={x.name}>
                  <span className={x.passed ? 'text-emerald-400' : 'text-rose-400'}>{x.passed ? 'SAME' : 'DIFF'}</span>{' '}
                  <span className="font-mono">{x.name.replace(/^replay-/, '').replace(/\.journal$/, '')}</span>
                  {x.failures.map((f, i) => <span key={i} className="block pl-10 text-rose-300">{f}</span>)}
                </li>
              ))}
            </ul>
          )}
          <p className="text-slate-400">before: {r.before ?? '—'}</p>
          <p className="text-slate-300">after: {r.after ?? '—'}</p>
        </div>
      )}
    </div>
  )
}
