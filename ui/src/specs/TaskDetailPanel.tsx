import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { specStatus, specTask } from '../devApi'
import type { TaskStatus } from '../devApi'
import { FloatingPanel } from '../components/FloatingPanel'
import { Markdown } from '../components/Markdown'
import { openSpecEditor, openTaskWindow } from './channel'
import { RunWithAgent } from './RunWithAgent'
import { TaskTeamActivity } from './TeamActivity'
import { resultLink } from './resultLink'
import { taskMarkdown } from './taskMarkdown'

/** One task in full, as a readable document. Used in the floating panel and in the pop-out window. */
export function TaskDocument({ spec, id, status }: { spec: string; id: string; status?: TaskStatus }) {
  const navigate = useNavigate()
  const detail = useQuery({ queryKey: ['dev', 'specs', 'task', spec, id], queryFn: () => specTask(spec, id) })
  // the window has no card to take the status from: derive it (without running tests)
  const derived = useQuery({
    queryKey: ['dev', 'specs', 'status', `specs/${spec}`, 'no-tests'],
    queryFn: () => specStatus(`specs/${spec}`, false),
    enabled: !status,
  })
  const task = status ?? derived.data?.plans[0]?.tasks.find((t) => t.id === id)
  const to = resultLink(task?.target ?? detail.data?.target ?? {})
  const btn = 'px-2.5 py-1 rounded text-xs bg-slate-700 hover:bg-slate-600'

  if (detail.error) return <p className="text-sm text-rose-400">{(detail.error as Error).message}</p>
  if (!detail.data) return <p className="text-sm text-slate-500">Loading…</p>
  return (
    <div>
      <Markdown>{taskMarkdown(detail.data, task)}</Markdown>
      <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-700 pt-3">
        <button className={btn} onClick={() => openSpecEditor(spec)}>Open spec ↗</button>
        {to && <button className={btn} onClick={() => navigate(to)}>Open what it builds →</button>}
      </div>
      <TaskTeamActivity id={id} />
      {task && !task.obsolete && task.status !== 'done' && <RunWithAgent spec={spec} id={id} type={task.type} blocked={task.blocked ? (task.reasons.length > 0 ? task.reasons : ['it is blocked']) : undefined} />}
    </div>
  )
}

export function TaskDetailPanel({ spec, task, onClose }: { spec: string; task: TaskStatus; onClose: () => void }) {
  return (
    <FloatingPanel
      title={task.id}
      onClose={onClose}
      onPopOut={() => { openTaskWindow(spec, task.id); onClose() }}
    >
      <TaskDocument spec={spec} id={task.id} status={task} />
    </FloatingPanel>
  )
}
