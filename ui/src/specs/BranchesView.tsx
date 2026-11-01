import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { devTelemetry, specBranches, teamEvents } from '../devApi'
import type { BranchNode, TaskStatus } from '../devApi'

const LOOK: Record<BranchNode['state'], { label: string; chip: string; dot: string }> = {
  merged: { label: 'merged', chip: 'bg-emerald-900/60 text-emerald-300', dot: 'border-emerald-500 bg-emerald-500' },
  open: { label: 'open, not merged', chip: 'bg-amber-900/60 text-amber-300', dot: 'border-amber-400 bg-amber-400' },
  none: { label: 'not built', chip: 'bg-slate-800 text-slate-400', dot: 'border-slate-600' },
}

const KIND: Record<BranchNode['kind'], string> = { spec: 'Spec', scaffold: 'Scaffold', task: 'Task' }

function copy(text: string) {
  try { void navigator.clipboard.writeText(text) } catch { /* the command is shown anyway */ }
}

function Commits({ node }: { node: BranchNode }) {
  if (node.commits.length === 0) return <p className="text-[11px] text-slate-500">No commits of its own to list.</p>
  return (
    <ul className="space-y-1.5" aria-label={`Commits of ${node.branch}`}>
      {node.commits.map((c) => (
        <li key={c.sha} className="rounded border border-slate-700/70 bg-slate-900/60 px-2 py-1.5">
          <p className="text-xs text-slate-100"><span className="font-mono text-cyan-400 mr-2">{c.sha}</span>{c.subject}</p>
          <p className="text-[10px] text-slate-500">{c.author}{c.when ? ` · ${new Date(c.when).toLocaleString()}` : ''}</p>
          {c.body && <pre className="mt-1 whitespace-pre-wrap font-sans text-[11px] text-slate-400">{c.body}</pre>}
        </li>
      ))}
    </ul>
  )
}

function Card({ node, status, open, onToggle, by }: { node: BranchNode; status?: TaskStatus['status']; open: boolean; onToggle: () => void; by?: string }) {
  // no branch, yet the project already has the work (written by hand or merged without a trace): say so
  const onBase = node.state === 'none' && (status === 'implemented' || status === 'tested' || status === 'done')
  const look = onBase ? { ...LOOK.merged, label: `${status}, no branch` } : LOOK[node.state]
  const command = node.state === 'open' && node.merge_first.length === 0 ? (node.pr ? '' : `git merge ${node.branch}`) : ''
  return (
    <div className="rounded border border-slate-700 bg-slate-800/60">
      <button onClick={onToggle} aria-expanded={open} className="w-full text-left p-2.5 space-y-1 hover:bg-slate-800">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className={`h-2.5 w-2.5 rounded-full border-2 ${look.dot}`} aria-hidden />
          <span className="uppercase tracking-wide text-slate-500">{KIND[node.kind]}</span>
          <span className="font-mono text-slate-100">{node.branch}</span>
          <span className={`rounded px-1.5 py-0.5 ${look.chip}`}>{look.label}</span>
          {node.state === 'open' && <span className="text-slate-400">{node.ahead} ahead{node.behind > 0 ? `, ${node.behind} behind` : ''}</span>}
          {node.parallel_with.length > 0 && (
            <span className="rounded bg-fuchsia-900/50 px-1.5 py-0.5 text-fuchsia-300" title={`built apart from ${node.parallel_with.join(', ')}`}>∥ parallel</span>
          )}
          {by && <span className="text-slate-400" title="from the team's collector">by {by}</span>}
          {node.deleted && <span className="text-slate-500">branch deleted after the merge</span>}
          <span className="flex-1" />
          <span className="text-slate-500">{node.commits.length} commit{node.commits.length === 1 ? '' : 's'} {open ? '▾' : '▸'}</span>
        </div>
        <p className="text-xs text-slate-300">{node.task ? `${node.task} · ` : ''}{node.title}</p>
      </button>
      {open && (
        <div className="border-t border-slate-700 p-2.5 space-y-2">
          {node.parallel_with.length > 0 && (
            <p className="text-[11px] text-fuchsia-300">Built apart from {node.parallel_with.join(', ')}: they may touch the same files, so merge one and check the other.</p>
          )}
          <Commits node={node} />
          {node.worktree && <p className="text-[11px] text-slate-500">worktree {node.worktree}</p>}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {node.pr && <a className="text-cyan-400 hover:underline" href={node.pr} target="_blank" rel="noreferrer">pull request ↗</a>}
            {node.state === 'open' && node.merge_first.length > 0 && (
              <span className="text-amber-300">Waiting: merge <span className="font-mono">{node.merge_first[node.merge_first.length - 1]}</span> first</span>
            )}
            {node.state === 'open' && node.merge_first.length === 0 && <span className="text-cyan-300">Next to merge</span>}
            {command && (
              <button className="px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 font-mono" onClick={() => copy(command)} title="Copy the command (tuvl never merges for you)">
                {command} ⧉
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Tree({ parent, nodes, status, openId, setOpenId, who }: {
  parent: string; nodes: BranchNode[]; status: (n: BranchNode) => TaskStatus['status'] | undefined; who: Record<string, string>
  openId: string | null; setOpenId: (id: string | null) => void
}) {
  const kids = nodes.filter((n) => n.ref && n.parent === parent)
  if (kids.length === 0) return null
  return (
    <ul className="ml-3 border-l border-slate-700 pl-4 space-y-3 pt-3">
      {kids.map((n) => (
        <li key={n.branch} className="relative">
          <span className="absolute -left-4 top-5 h-px w-4 bg-slate-700" aria-hidden />
          <Card node={n} status={status(n)} open={openId === n.branch} onToggle={() => setOpenId(openId === n.branch ? null : n.branch)} by={who[n.branch]} />
          <Tree parent={n.branch} nodes={nodes} status={status} openId={openId} setOpenId={setOpenId} who={who} />
        </li>
      ))}
    </ul>
  )
}

/** The branches of a spec's work as a tree of what grew from what: parallel work shows as siblings; click a branch for its commits. */
export function BranchesView({ spec, tasks }: { spec: string; tasks?: TaskStatus[] }) {
  const [openId, setOpenId] = useState<string | null>(null)
  const report = useQuery({ queryKey: ['dev', 'specs', 'branches', spec], queryFn: () => specBranches(`specs/${spec}`), refetchOnWindowFocus: true })
  // who built each branch, from the team's collector when this project shares its events
  const tel = useQuery({ queryKey: ['dev', 'dev-telemetry'], queryFn: devTelemetry, staleTime: 15000 })
  const shared = !!tel.data?.enabled && !!tel.data.token_set
  const made = useQuery({ queryKey: ['dev', 'team-events', 'branches'], queryFn: () => teamEvents({ kind: 'branch.created', limit: 200 }), enabled: shared, retry: false, refetchInterval: 15000 })
  const who: Record<string, string> = {}
  for (const e of made.data?.events ?? []) if (e.detail && !who[e.detail]) who[e.detail] = e.developer.name
  if (report.error) return <p className="text-sm text-rose-400">{(report.error as Error).message}</p>
  if (!report.data) return <p className="text-sm text-slate-500">Reading the branches…</p>
  const r = report.data
  if (!r.base) return <p className="text-sm text-slate-500">The project has no commits yet, so there are no branches to show.</p>
  const entry = r.specs[0]
  const status = (n: BranchNode) => tasks?.find((t) => t.id === n.task)?.status
  const landed = entry?.stack.filter((n) => n.deleted) ?? []
  const waiting = entry?.stack.filter((n) => n.state === 'none') ?? []
  return (
    <div className="space-y-3 max-w-4xl">
      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
        <span>base <span className="font-mono text-slate-100">{r.base}</span></span>
        <span>you are on <span className="font-mono text-slate-100">{r.current}</span></span>
        {r.dirty > 0 && <span className="text-amber-300">{r.dirty} uncommitted change(s)</span>}
        <span className="flex-1" />
        <button className="px-2.5 py-1 rounded bg-slate-700 hover:bg-slate-600" onClick={() => void report.refetch()} disabled={report.isFetching}>
          {report.isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {!entry ? (
        <p className="text-sm text-slate-500">This spec has no task list yet.</p>
      ) : (
        <>
          {entry.uncommitted.map((p) => (
            <p key={p} className="text-xs text-amber-300">! {p} is not committed anywhere yet; a build carries it on the scaffold branch.</p>
          ))}
          <p className="text-xs text-slate-500">
            Each branch hangs under the one it grew from; branches under the same parent were built apart from each other (parallel).
            Click a branch for its commits. tuvl opens the pull requests and never merges them.
          </p>
          <div>
            <div className="inline-flex items-center gap-2 rounded border border-slate-600 bg-slate-900 px-3 py-1.5 text-xs">
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" aria-hidden />
              <span className="font-mono text-slate-100">{r.base}</span>
              <span className="text-slate-500">base</span>
            </div>
            {landed.length > 0 && (
              <ul className="ml-3 border-l border-slate-700 pl-4 pt-2 space-y-1" aria-label="Landed on the base branch">
                {landed.map((n) => (
                  <li key={n.branch} className="text-xs text-slate-400">
                    <span className="text-emerald-400">✓ landed</span> <span className="font-mono">{n.branch}</span>
                    {n.last?.sha ? <> · <span className="font-mono">{n.last.sha}</span> {n.last.subject}</> : null}
                  </li>
                ))}
              </ul>
            )}
            <Tree parent={r.base} nodes={entry.stack} status={status} openId={openId} setOpenId={setOpenId} who={who} />
          </div>
          {waiting.length > 0 && (
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-500 mb-1">Not built yet</p>
              <ul className="space-y-1" aria-label="Branches not built yet">
                {waiting.map((n) => {
                  const s = status(n)
                  const onBase = s === 'implemented' || s === 'tested' || s === 'done'
                  return (
                    <li key={n.branch} className="text-xs text-slate-400">
                      <span className={onBase ? 'text-emerald-400' : 'text-slate-500'}>{onBase ? `✓ ${s}, no branch` : '○ not built'}</span>{' '}
                      <span className="font-mono">{n.branch}</span> · {n.task} {n.title}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
          {entry.merge_next ? (
            <p className="text-sm text-cyan-300">Merge next: <span className="font-mono">{entry.merge_next}</span></p>
          ) : (
            <p className="text-sm text-slate-500">Nothing waits to be merged.</p>
          )}
        </>
      )}
    </div>
  )
}
