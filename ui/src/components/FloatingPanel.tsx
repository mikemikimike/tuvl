import { useCallback, useEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react'

interface Place { x: number; y: number }

const KEY = 'tuvl.floatingPanel'
const WIDTH = 560

function remembered(): Place | null {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Place | null
    return v && Number.isFinite(v.x) && Number.isFinite(v.y) ? v : null
  } catch {
    return null
  }
}

const within = (p: Place): Place => ({
  x: Math.min(Math.max(p.x, 80 - WIDTH), window.innerWidth - 80),
  y: Math.min(Math.max(p.y, 0), window.innerHeight - 40),
})

/** A panel that floats over the page: drag it by its title, resize it from the corner, or pop it out into its own window. */
export function FloatingPanel({ title, onClose, onPopOut, children }: {
  title: ReactNode
  onClose: () => void
  onPopOut?: () => void
  children: ReactNode
}) {
  const [place, setPlace] = useState<Place>(() => within(remembered() ?? { x: window.innerWidth - WIDTH - 24, y: 72 }))
  const drag = useRef<{ dx: number; dy: number } | null>(null)

  const move = useCallback((e: PointerEvent<HTMLElement>) => {
    if (drag.current) setPlace(within({ x: e.clientX - drag.current.dx, y: e.clientY - drag.current.dy }))
  }, [])
  const release = useCallback((e: PointerEvent<HTMLElement>) => {
    if (!drag.current) return
    drag.current = null
    e.currentTarget.releasePointerCapture(e.pointerId)
    try { localStorage.setItem(KEY, JSON.stringify(place)) } catch { /* a remembered position is a convenience */ }
  }, [place])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const onResize = () => setPlace((p) => within(p))
    window.addEventListener('keydown', onKey)
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', onResize)
    }
  }, [onClose])

  const btn = 'px-2 py-0.5 rounded text-xs bg-slate-700 hover:bg-slate-600'
  return (
    <div
      role="dialog"
      style={{ left: place.x, top: place.y, width: WIDTH, height: '70vh', minWidth: 320, minHeight: 200, maxWidth: '95vw', maxHeight: '95vh' }}
      className="fixed z-30 flex resize flex-col overflow-hidden rounded-lg border border-slate-600 bg-slate-900 shadow-2xl"
    >
      <header
        onPointerDown={(e) => {
          if ((e.target as HTMLElement).closest('button')) return
          drag.current = { dx: e.clientX - place.x, dy: e.clientY - place.y }
          e.currentTarget.setPointerCapture(e.pointerId)
        }}
        onPointerMove={move}
        onPointerUp={release}
        className="flex cursor-move touch-none select-none items-center gap-2 border-b border-slate-700 bg-slate-800 px-3 py-1.5 text-xs"
      >
        <span className="flex-1 truncate font-mono text-slate-300">{title}</span>
        {onPopOut && <button className={btn} onClick={onPopOut} title="Open in its own window">Pop out ↗</button>}
        <button className={btn} onClick={onClose} aria-label="Close" title="Close (Esc)">✕</button>
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-4">{children}</div>
    </div>
  )
}
