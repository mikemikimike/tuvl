import { useEffect, useRef, useState } from 'react'
import { PRESETS, type Preset } from '../canvas/model'

const GROUPS = ['Deterministic · 0 LLM', 'AI · bounded', 'Control', 'Contract only'] as const

const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))

/** + Add step on the canvas (or A): a searchable picker; the step goes after the selected one. */
export function AddStep({ onAdd, after }: { onAdd: (preset: Preset) => void; after: string | null }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)

  const isOpen = useRef(false)
  const toggle = (next?: boolean) => {
    const opening = next ?? !isOpen.current
    if (opening && !isOpen.current) { setQuery(''); setActive(0); setTimeout(() => input.current?.focus(), 0) }
    isOpen.current = opening
    setOpen(opening)
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === 'a' && !e.metaKey && !e.ctrlKey && !e.altKey && !typing(e.target)) { e.preventDefault(); toggle(true) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const q = query.trim().toLowerCase()
  const matches = PRESETS.filter((p) => !q || `${p.label} ${p.hint} ${p.group}`.toLowerCase().includes(q))
  const add = (p: Preset) => { toggle(false); onAdd(p) }
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); toggle(false) }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, matches.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter' && matches[active]) { e.preventDefault(); add(matches[active]) }
  }

  return (
    <div className="absolute left-1/2 -translate-x-1/2 bottom-3 z-20">
      {open && (
        <>
          <div className="fixed inset-0" onClick={() => toggle(false)} aria-hidden="true" />
          <div role="dialog" aria-label="Add step" onKeyDown={onKeyDown}
            className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-[min(24rem,calc(100vw-2rem))] rounded-lg border border-slate-700 bg-slate-900 shadow-2xl shadow-black/60 overflow-hidden">
            <input ref={input} value={query} onChange={(e) => { setQuery(e.target.value); setActive(0) }} placeholder="Add a step…" aria-label="Find a step type"
              className="w-full bg-transparent border-b border-slate-800 px-3 py-2.5 text-sm outline-none" />
            <div className="max-h-[min(55vh,28rem)] overflow-auto py-1">
              {GROUPS.map((group) => {
                const items = matches.filter((p) => p.group === group)
                if (!items.length) return null
                return (
                  <div key={group}>
                    <p className="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wide text-slate-500">{group}</p>
                    {items.map((p) => {
                      const i = matches.indexOf(p)
                      return (
                        <button key={p.key} onClick={() => add(p)} onMouseEnter={() => setActive(i)} aria-label={`+ ${p.label}`}
                          className={`w-full text-left px-3 py-2 ${i === active ? 'bg-slate-800' : ''}`}>
                          <span className="block text-sm text-slate-100">{p.label}</span>
                          <span className="block text-[11px] text-slate-500">{p.hint}</span>
                        </button>
                      )
                    })}
                  </div>
                )
              })}
              {matches.length === 0 && <p className="px-3 py-2 text-xs text-slate-500">No step type matches.</p>}
            </div>
            <p className="px-3 py-2 border-t border-slate-800 text-[11px] text-slate-500">
              {after ? <>Linked after <span className="font-mono text-slate-300">{after}</span> where it ends</> : 'Select a step first to link the new one after it'}
            </p>
          </div>
        </>
      )}
      <button onClick={() => toggle()} aria-expanded={open} title="Add a step (A)"
        className="flex items-center gap-2 rounded-full border border-indigo-700 bg-indigo-950 hover:bg-indigo-900 text-indigo-100 text-sm px-4 py-2 shadow-lg shadow-black/40">
        <span className="text-base leading-none">+</span> Add step
        <kbd className="hidden lg:inline text-[10px] font-mono text-indigo-300 border border-indigo-700 rounded px-1">A</kbd>
      </button>
    </div>
  )
}
