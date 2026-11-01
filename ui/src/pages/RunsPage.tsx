import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { TopBar } from '../components/TopBar'
import { fetchProject } from '../devApi'
import { listApprovals } from '../runsApi'
import { ApprovalCard } from '../runs/ApprovalCard'
import { RunDetail } from '../runs/RunDetail'
import { RunList } from '../runs/RunList'
import { StartRun } from '../runs/StartRun'

export function RunsPage() {
  const [params, setParams] = useSearchParams()
  const selected = params.get('run')
  const [filters, setFilters] = useState({ workflow: '', status: '' })
  const [tab, setTab] = useState<'runs' | 'approvals'>('runs')
  const project = useQuery({ queryKey: ['dev', 'project-summary'], queryFn: fetchProject })
  const approvals = useQuery({ queryKey: ['approvals'], queryFn: listApprovals, refetchInterval: 4000 })
  const workflows = project.data?.workflows.map((w) => w.name) ?? []
  const select = (id: string) => { setParams({ run: id }); setTab('runs') }
  const pending = approvals.data?.length ?? 0

  return (
    <div className="flex flex-col h-full">
      <TopBar title="Runs" />
      <div className="flex items-center gap-1 px-3 py-1.5 border-b border-slate-800 text-xs">
        {(['runs', 'approvals'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-2.5 py-1 rounded ${tab === t ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200'}`}>
            {t === 'runs' ? 'Runs' : `Approvals${pending ? ` (${pending})` : ''}`}
          </button>
        ))}
        <span className="flex-1" />
        <StartRun workflows={workflows} onStarted={select} />
      </div>
      {tab === 'runs' ? (
        <div className="flex flex-1 min-h-0">
          <aside className="w-80 shrink-0 border-r border-slate-700 bg-slate-900/60">
            <RunList workflows={workflows} workflow={filters.workflow} status={filters.status} selected={selected}
              onFilter={setFilters} onSelect={select} />
          </aside>
          <main className="flex-1 min-w-0">
            {selected ? <RunDetail key={selected} runId={selected} /> : <p className="p-6 text-sm text-slate-500">Select a run to see its journal.</p>}
          </main>
        </div>
      ) : (
        <div className="flex-1 overflow-auto p-4 space-y-3 max-w-3xl">
          {approvals.data?.map((a) => (
            <div key={a.approval_id} className="space-y-1">
              <button onClick={() => select(a.run_id)} className="text-xs text-slate-400 hover:text-slate-200 font-mono">
                run {a.run_id.slice(0, 8)} · {a.agent_id} · {a.kind}
              </button>
              <ApprovalCard approval={a} />
            </div>
          ))}
          {pending === 0 && <p className="text-sm text-slate-500">Nothing is waiting for a decision.</p>}
        </div>
      )}
    </div>
  )
}
