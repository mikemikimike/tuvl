import { useEffect, useMemo, useRef, useState } from 'react'
import { recent } from './recent'
import { groupNames, initials, sections } from './groups'
import type { WorkflowEntry } from './WorkflowSwitcher'

// static class names so Tailwind keeps them
const HUES = [
  'bg-sky-900/60 text-sky-200', 'bg-emerald-900/60 text-emerald-200', 'bg-violet-900/60 text-violet-200',
  'bg-amber-900/50 text-amber-200', 'bg-rose-900/50 text-rose-200', 'bg-indigo-900/60 text-indigo-200',
]
const hue = (key: string) => HUES[[...key].reduce((n, c) => n + c.charCodeAt(0), 0) % HUES.length]

/**
 * The workflow picker: small tiles, grouped by `metadata.group`. It sits in the page flow, so opening it
 * pushes the canvas down; picking a tile (or Esc) closes it.
 */
export function WorkflowTiles({ entries, selected, onPick, onCreate, onClose }: {
  entries: WorkflowEntry[]
  selected: string | null
  onPick: (file: string) => void
  onCreate: (name: string, group: string | null) => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newGroup, setNewGroup] = useState('')
  const search = useRef<HTMLInputElement>(null)
  useEffect(() => { search.current?.focus() }, [])

  const shown = useMemo(() => sections(entries, query, recent()), [entries, query])
  const first = shown.flatMap((s) => s.items)[0]
  const groups = useMemo(() => groupNames(entries), [entries])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); onClose() }
    else if (e.key === 'Enter' && !creating && first && document.activeElement === search.current) { e.preventDefault(); onPick(first.file) }
  }

  return (
    <section role="dialog" aria-label="Choose a workflow" onKeyDown={onKeyDown}
      className="shrink-0 max-h-[52vh] overflow-auto border-b border-slate-700 bg-slate-900/95 px-3 sm:px-4 py-3">
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <input ref={search} value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Find a workflow"
          placeholder="Find a workflow or a group…"
          className="w-full sm:w-72 rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-sm outline-none focus:border-indigo-400" />
        <span className="text-[11px] text-slate-500">{entries.length} workflow{entries.length === 1 ? '' : 's'}{groups.length ? ` · ${groups.length} group${groups.length === 1 ? '' : 's'}` : ''}</span>
        <span className="ml-auto text-[11px] text-slate-500">↵ open first match · esc close</span>
        <button onClick={onClose} aria-label="Close the workflow list" className="text-slate-400 hover:text-slate-100 text-sm px-1">✕</button>
      </div>

      <div className="columns-1 md:columns-2 2xl:columns-3 gap-x-8">
        {shown.map((s) => (
          <div key={s.title} className="break-inside-avoid mb-4">
            <p className="mb-1.5 text-[10px] uppercase tracking-wide text-slate-500">
              {s.title}<span className="ml-1.5 normal-case text-slate-600">{s.items.length}</span>
            </p>
            <ul className="grid grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))] gap-2">
              {s.items.map((e) => (
                <li key={`${s.kind}:${e.file}`}>
                  <button onClick={() => onPick(e.file)} title={e.name}
                    aria-current={e.file === selected ? 'true' : undefined}
                    className={`w-full text-left rounded-lg border px-2.5 py-2 flex items-center gap-2.5 transition-colors ${
                      e.file === selected ? 'border-indigo-400 bg-indigo-950/40' : 'border-slate-700 bg-slate-800/50 hover:border-slate-500 hover:bg-slate-800'}`}>
                    <span aria-hidden="true" className={`grid h-8 w-8 shrink-0 place-items-center rounded-md text-[11px] font-semibold ${hue(e.group ?? e.name)}`}>
                      {initials(e.name)}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate font-mono text-[13px] text-slate-100">{e.name}</span>
                      <span className="block truncate text-[10px] text-slate-500">
                        {e.agents != null ? `${e.agents} agent${e.agents === 1 ? '' : 's'}` : ' '}
                        {!!e.pending && <span className="text-amber-400"> · {e.pending} pending</span>}
                        {e.unsaved && <span className="text-amber-400"> · unsaved</span>}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
        {shown.every((s) => s.items.length === 0) && <p className="text-xs text-slate-500">No workflow matches “{query}”.</p>}

        <div className="break-inside-avoid">
          {!creating ? (
            <button onClick={() => { setCreating(true); setNewGroup(''); }}
              className="rounded-lg border border-dashed border-slate-600 px-3 py-2 text-xs text-slate-300 hover:border-indigo-400 hover:text-indigo-200">
              + New workflow
            </button>
          ) : (
            <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => {
              e.preventDefault()
              if (newName.trim()) onCreate(newName.trim(), newGroup.trim() || null)
            }}>
              <input autoFocus value={newName} onChange={(e) => setNewName(e.target.value)} aria-label="New workflow name"
                placeholder="snake_case_name" className="w-48 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs font-mono outline-none focus:border-indigo-400" />
              <input value={newGroup} onChange={(e) => setNewGroup(e.target.value)} aria-label="Group (optional)" list="workflow-groups"
                placeholder="group (optional)" className="w-44 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs outline-none focus:border-indigo-400" />
              <datalist id="workflow-groups">{groups.map((g) => <option key={g} value={g} />)}</datalist>
              <button type="submit" className="rounded-md bg-indigo-600 px-2.5 py-1.5 text-xs text-white">Create</button>
              <button type="button" onClick={() => setCreating(false)} className="rounded-md bg-slate-700 px-2.5 py-1.5 text-xs">Cancel</button>
            </form>
          )}
        </div>
      </div>
    </section>
  )
}
