/** The title row of a list sidebar, with the "+" that starts a new item (the pattern of the Models page). */
export function SidebarHeader({ title, onNew, newLabel }: { title: string; onNew: () => void; newLabel: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 shrink-0">
      <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</span>
      <button
        onClick={onNew}
        title={newLabel}
        aria-label={newLabel}
        className="flex h-7 w-7 items-center justify-center rounded-md text-sky-400 hover:bg-sky-900/30 hover:text-sky-300 transition-colors text-xl leading-none"
      >
        +
      </button>
    </div>
  )
}
