import { useUIStore } from '../store'
import { useHealth } from '../queries'
import type { ReactNode } from 'react'

/** `children` replaces the title with page controls (the Workflows page puts its toolbar here). */
export function TopBar({ title, subtitle, children }: { title?: ReactNode; subtitle?: string; children?: ReactNode }) {
  const toggleSidebar = useUIStore((s) => s.toggleSidebar)
  const toggleTheme = useUIStore((s) => s.toggleTheme)
  const theme = useUIStore((s) => s.theme)
  const { data: health } = useHealth()

  return (
    <header className="min-h-12 shrink-0 bg-slate-900 border-b border-slate-700 flex items-center px-3 sm:px-4 gap-3">
      <button
        onClick={toggleSidebar}
        className="lg:hidden text-slate-400 hover:text-slate-100 transition-colors text-lg leading-none"
        aria-label="Toggle sidebar"
      >
        ☰
      </button>
      {children ?? <span className="text-slate-100 font-medium text-sm flex-1">{title}{subtitle && <span className="ml-2 text-[10px] font-mono text-slate-500">{subtitle}</span>}</span>}
      {health?.version && !children && (
        <span className="text-[10px] font-mono text-slate-500 select-none" title="tuvl version">v{health.version}</span>
      )}
      <button
        onClick={toggleTheme}
        title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        className="text-xs px-2.5 py-1 rounded border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-colors"
      >
        {theme === 'dark' ? '☀' : '☾'}
      </button>
    </header>
  )
}
