import type { ReactNode } from 'react'

const ICONS: Record<string, ReactNode> = {
  model: (<><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5.5" /><circle cx="12" cy="12" r="2" /></>),
  embedding: (<><circle cx="6" cy="7" r="1.6" /><circle cx="17" cy="6" r="1.6" /><circle cx="9" cy="16" r="1.6" /><circle cx="18" cy="17" r="1.6" /><path d="M7.4 8l1.1 6.6M16 7.4l1.7 8M10.6 16.2l5.7.6M7.5 6.6l8 -.4" /></>),
  collection: (<><path d="M4 7l8-3.5L20 7l-8 3.5L4 7z" /><path d="M4 12l8 3.5 8-3.5" /><path d="M4 16.5l8 3.5 8-3.5" /></>),
  storage: (<><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6" /><path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></>),
}

/** What a page shows in its main area when nothing is selected: a short explanation and the button that adds the first item. */
export function EmptyPanel({ icon, title, description, actionLabel, onAction }: {
  icon: keyof typeof ICONS
  title: string
  description: string
  actionLabel: string
  onAction: () => void
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center h-full text-center px-6">
      <div className="mb-4 rounded-full border border-dashed border-slate-700 p-5">
        <svg className="h-9 w-9 text-slate-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
          {ICONS[icon]}
        </svg>
      </div>
      <p className="text-sm font-medium text-slate-400">{title}</p>
      <p className="mt-1 max-w-xs text-xs text-slate-600">{description}</p>
      <button
        onClick={onAction}
        className="mt-5 flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 transition-colors"
      >
        <span className="text-base font-light leading-none">+</span>
        {actionLabel}
      </button>
    </div>
  )
}
