import type { ReactNode } from 'react'
import type { RunEvent } from '../runsApi'
import { groupSteps } from './steps'

const ENGINE_COLOUR: Record<string, string> = {
  code: 'border-slate-500', tool: 'border-amber-500', decide: 'border-sky-500', llm: 'border-violet-500',
  loop: 'border-violet-400', parallel: 'border-teal-500', human: 'border-emerald-500', pending: 'border-slate-600 border-dashed',
}

const short = (v: unknown, n = 140) => {
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  return s && s.length > n ? `${s.slice(0, n)}…` : s
}

function Detail({ e }: { e: RunEvent }): ReactNode {
  const p = e.payload
  switch (e.type) {
    case 'decision':
      return (
        <span>
          decided <b className="text-sky-300">{String(p.decision)}</b> by{' '}
          <span className="font-mono">{String(p.source)}</span>
          {typeof p.confidence === 'number' && <> · confidence {p.confidence.toFixed(2)}</>}
          {p.shadow ? <> · shadow {short(p.shadow, 60)}</> : null}
        </span>
      )
    case 'llm_turn':
      return (
        <span>
          {p.iteration != null ? <>turn {String(p.iteration)} · </> : null}
          {String(p.model ?? '')}
          {Array.isArray(p.tool_calls) && p.tool_calls.length > 0 && <> → {p.tool_calls.join(', ')}</>}
        </span>
      )
    case 'tool_call':
      return (
        <span>
          <span className="font-mono text-amber-300">{String(p.tool ?? p.name ?? p.use)}</span>
          {p.effect ? <span className="ml-1 text-[10px] uppercase text-slate-500">{String(p.effect)}</span> : null}
          {p.args ? <span className="ml-1 font-mono text-slate-400">{short(p.args)}</span> : null}
          {p.url ? <span className="ml-1 font-mono text-slate-400">{String(p.method)} {String(p.url)}</span> : null}
          {p.approved ? <span className="ml-1 text-emerald-400">approved</span> : null}
        </span>
      )
    case 'tool_result':
      return <span className={p.ok === false ? 'text-rose-400' : ''}>{p.ok === false ? `failed ${short(p.error ?? '')}` : `ok ${p.status ?? ''}`}</span>
    case 'map_started':
      return <span>{String(p.items)} item{p.items === 1 ? '' : 's'} → <span className="font-mono">{String(p.workflow)}</span>, {String(p.concurrency)} at a time</span>
    case 'map_item':
      return (
        <span className={p.ok ? '' : 'text-rose-400'}>
          item {String(p.index)} {p.ok ? 'ok' : `failed: ${short(p.reason ?? '', 200)}`}
          {p.run_id ? <span className="ml-1 font-mono text-slate-500">{String(p.run_id).slice(0, 8)}</span> : null}
        </span>
      )
    case 'map_finished':
      return <span className={Number(p.failed) ? 'text-rose-400' : ''}>{String(p.items)} items, {String(p.failed)} failed{Number(p.skipped) ? `, ${String(p.skipped)} not started` : ''}</span>
    case 'parallel_started':
      return <span>{(p.branches as string[]).length} branches at once: <span className="font-mono">{(p.branches as string[]).join(', ')}</span> · on error {String(p.on_error)}</span>
    case 'parallel_branch':
      return (
        <span className={p.ok ? '' : 'text-rose-400'}>
          <span className="font-mono">{String(p.branch)}</span> {p.ok ? 'ok' : `failed: ${short(p.reason ?? '', 200)}`} · {String(p.ms)} ms{Number(p.tokens) ? ` · ${String(p.tokens)} tok` : ''}
        </span>
      )
    case 'parallel_finished':
      return <span className={(p.failed as string[]).length ? 'text-rose-400' : ''}>{String(p.branches)} branches, {(p.failed as string[]).length} failed</span>
    case 'judge_verdict':
      return <span>{String(p.judge)} → {p.error ? <span className="text-rose-400">{String(p.error)}</span> : String(p.verdict)}</span>
    case 'supervisor':
      return <span>{String(p.source)}: <b>{String(p.action)}</b>{p.why ? <> — {String(p.why)}</> : null}</span>
    case 'approval_requested':
      return <span className="text-amber-300">{String(p.title ?? `approve ${p.tool}`)}{p.args ? <span className="font-mono ml-1 text-slate-400">{short(p.args)}</span> : null}</span>
    case 'approval_decided':
      return <span>{String(p.decision ?? '')} by {String(p.reviewer ?? p.decided_by ?? '?')}</span>
    case 'run_completed':
      return <span className="text-emerald-300">END.{String(p.end)} ({String(p.status)})</span>
    case 'run_failed':
    case 'run_aborted':
      return <span className="text-rose-400">{String(p.error_type ?? '')} {short(p.message ?? '', 300)}</span>
    default:
      return Object.keys(p).length ? <span className="font-mono text-slate-500">{short(p)}</span> : null
  }
}

function Line({ e }: { e: RunEvent }) {
  return (
    <li className="flex gap-2 text-xs leading-5">
      <span className="w-8 shrink-0 text-right font-mono text-slate-600">{e.seq}</span>
      <span className="w-36 shrink-0 text-slate-400">
        {e.type.replace(/_/g, ' ')}
        {typeof e.payload.branch === 'string' && e.type !== 'parallel_branch' && (
          <span className="ml-1 rounded bg-teal-950 px-1 font-mono text-[10px] text-teal-300">{e.payload.branch}</span>
        )}
      </span>
      <span className="flex-1 min-w-0 break-words text-slate-300"><Detail e={e} /></span>
      <span className="shrink-0 text-[11px] text-slate-500">
        {e.tokens ? `${e.tokens} tok ` : ''}{e.latency_ms != null ? `${e.latency_ms} ms` : ''}
      </span>
    </li>
  )
}

export function RunTimeline({ events, drafts = {} }: { events: RunEvent[]; drafts?: Record<string, string> }) {
  return (
    <ol className="space-y-2">
      {groupSteps(events).map((step, i) => {
        const done = step.completed?.payload
        const failed = done && done.error_type
        return (
          <li key={i} className={`border-l-2 pl-3 ${step.agent ? ENGINE_COLOUR[step.engine ?? ''] ?? 'border-slate-600' : 'border-transparent'}`}>
            {step.agent && (
              <div className="flex items-center gap-2 text-sm mb-1">
                <span className="font-mono text-slate-100">{step.agent}</span>
                {step.engine && <span className="text-[10px] uppercase tracking-wide text-slate-500">{step.engine}</span>}
                {done && (
                  <span className={`text-xs ${failed ? 'text-rose-400' : 'text-slate-400'}`}>
                    → {String(done.signal)}{failed ? ` (${String(done.error_type)})` : ''}
                  </span>
                )}
              </div>
            )}
            {step.agent && !step.completed && drafts[step.agent] && (
              <p aria-label={`Live draft of ${step.agent}`} aria-live="polite"
                className="my-1 whitespace-pre-wrap break-words rounded border border-violet-900/60 bg-violet-950/20 px-2 py-1 text-xs text-slate-200">
                {drafts[step.agent]}
                <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-violet-400 align-middle" aria-hidden="true" />
              </p>
            )}
            <ul className="space-y-0.5">
              {step.events.filter((e) => e.type !== 'agent_started' && e.type !== 'agent_completed').map((e) => <Line key={e.seq} e={e} />)}
            </ul>
          </li>
        )
      })}
    </ol>
  )
}
