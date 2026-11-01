import { useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { TaskDocument } from './TaskDetailPanel'

/** One task in its own window (popped out of the Specs page). */
export function TaskWindow() {
  const { spec = '', id = '' } = useParams()
  useEffect(() => { document.title = `${id} — task` }, [id])
  return (
    <div className="h-screen overflow-auto bg-slate-950 p-6 text-slate-100">
      <div className="mx-auto max-w-3xl">
        <p className="mb-3 font-mono text-xs text-slate-500">{spec}</p>
        <TaskDocument spec={spec} id={id} />
      </div>
    </div>
  )
}
