import { useEffect } from 'react'

export interface WorkflowEntry {
  file: string
  name: string
  group?: string
  agents?: number
  pending?: number
  unsaved: boolean
}

/** The current workflow as a button; ⌘K (or a click) opens the tile browser below the top bar. */
export function WorkflowSwitcher({ current, open, onToggle }: {
  current: WorkflowEntry | undefined
  open: boolean
  onToggle: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); onToggle() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onToggle])

  return (
    <button onClick={onToggle} aria-haspopup="dialog" aria-expanded={open} title="Browse workflows (⌘K)"
      className={`flex items-center gap-2 max-w-[20rem] rounded-md border px-2.5 py-1 ${open ? 'border-indigo-400 bg-slate-800' : 'border-slate-700 bg-slate-800/60 hover:border-slate-500'}`}>
      <span className="font-mono text-sm text-slate-100 truncate">{current?.name ?? 'Choose a workflow'}</span>
      {current?.group && <span className="hidden sm:inline shrink-0 rounded bg-slate-700 px-1.5 text-[10px] text-slate-300">{current.group}</span>}
      {current?.unsaved && <span className="text-amber-400">•</span>}
      {current?.agents != null && <span className="hidden xl:inline text-[11px] text-slate-500 shrink-0">{current.agents} agents</span>}
      <span className="text-slate-500" aria-hidden="true">{open ? '▴' : '▾'}</span>
      <kbd className="hidden lg:inline text-[10px] font-mono text-slate-500 border border-slate-700 rounded px-1">⌘K</kbd>
    </button>
  )
}
