import { useEffect, useRef, useState, type ReactNode } from 'react'

interface Box { x: number; y: number; w: number; h: number }

const MIN_W = 480
const MIN_H = 320
const EDGES = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'] as const
type Edge = (typeof EDGES)[number]

const EDGE_CLASS: Record<Edge, string> = {
  n: 'top-0 left-2 right-2 h-1.5 cursor-ns-resize',
  s: 'bottom-0 left-2 right-2 h-1.5 cursor-ns-resize',
  e: 'right-0 top-2 bottom-2 w-1.5 cursor-ew-resize',
  w: 'left-0 top-2 bottom-2 w-1.5 cursor-ew-resize',
  ne: 'top-0 right-0 w-3 h-3 cursor-nesw-resize',
  sw: 'bottom-0 left-0 w-3 h-3 cursor-nesw-resize',
  nw: 'top-0 left-0 w-3 h-3 cursor-nwse-resize',
  se: 'bottom-0 right-0 w-4 h-4 cursor-nwse-resize',
}

function initial(storageKey: string): Box {
  const vw = window.innerWidth
  const vh = window.innerHeight
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? 'null') as Box | null
    if (saved && saved.w >= MIN_W && saved.h >= MIN_H) return clamp(saved)
  } catch { /* storage unavailable */ }
  const w = Math.min(1180, vw - 48)
  const h = Math.min(760, vh - 48)
  return { x: Math.round((vw - w) / 2), y: Math.round((vh - h) / 2), w, h }
}

/** keep the title bar reachable whatever the viewport did since */
function clamp(b: Box): Box {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const w = Math.min(Math.max(b.w, MIN_W), vw)
  const h = Math.min(Math.max(b.h, MIN_H), vh)
  return { w, h, x: Math.min(Math.max(b.x, 0), vw - Math.min(w, 120)), y: Math.min(Math.max(b.y, 0), vh - 40) }
}

/**
 * A non-modal window over the page: drag it by its title bar, resize it from any edge or corner,
 * maximize it (button or double-click on the title). Its size and place are remembered per `storageKey`.
 */
export function FloatingWindow({ title, label, storageKey, onClose, actions, children }: {
  title: ReactNode
  label: string
  storageKey: string
  onClose: () => void
  actions?: ReactNode
  children: ReactNode
}) {
  const [box, setBox] = useState<Box>(() => initial(storageKey))
  const [maximized, setMaximized] = useState(false)
  const drag = useRef<{ edge: Edge | 'move'; x: number; y: number; start: Box } | null>(null)

  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify(box)) } catch { /* storage unavailable */ }
  }, [box, storageKey])

  useEffect(() => {
    const onResize = () => setBox((b) => clamp(b))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const begin = (edge: Edge | 'move') => (e: React.PointerEvent) => {
    if (maximized || e.button !== 0) return
    if (edge === 'move' && (e.target as HTMLElement).closest('button, select, input, a')) return
    e.preventDefault()
    drag.current = { edge, x: e.clientX, y: e.clientY, start: box }
    document.body.style.userSelect = 'none'
    const onMove = (ev: PointerEvent) => {
      const d = drag.current
      if (!d) return
      const dx = ev.clientX - d.x
      const dy = ev.clientY - d.y
      const s = d.start
      if (d.edge === 'move') { setBox(clamp({ ...s, x: s.x + dx, y: s.y + dy })); return }
      let { x, y, w, h } = s
      if (d.edge.includes('e')) w = s.w + dx
      if (d.edge.includes('s')) h = s.h + dy
      if (d.edge.includes('w')) { w = Math.max(MIN_W, s.w - dx); x = s.x + s.w - w }
      if (d.edge.includes('n')) { h = Math.max(MIN_H, s.h - dy); y = s.y + s.h - h }
      setBox(clamp({ x, y, w, h }))
    }
    const onUp = () => {
      drag.current = null
      document.body.style.userSelect = ''
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const style = maximized ? { left: 0, top: 0, width: '100vw', height: '100vh' } : { left: box.x, top: box.y, width: box.w, height: box.h }
  return (
    <div role="dialog" aria-label={label} style={style}
      className={`fixed z-50 flex flex-col bg-slate-950 border border-slate-700 shadow-2xl shadow-black/60 ${maximized ? '' : 'rounded-lg'}`}>
      <div onPointerDown={begin('move')} onDoubleClick={(e) => { if (!(e.target as HTMLElement).closest('button')) setMaximized((m) => !m) }}
        className={`flex items-center gap-2 px-3 h-10 shrink-0 border-b border-slate-800 bg-slate-900 select-none ${maximized ? '' : 'rounded-t-lg cursor-move'}`}>
        <div className="flex-1 min-w-0 flex items-center gap-2 text-xs">{title}</div>
        {actions}
        <button aria-label={maximized ? 'Restore window' : 'Maximize window'} title={maximized ? 'Restore' : 'Maximize'}
          onClick={() => setMaximized((m) => !m)} className="w-7 h-7 rounded text-slate-400 hover:bg-slate-800 hover:text-slate-100">
          {maximized ? '❐' : '□'}
        </button>
        <button aria-label="Close window" title="Back to the panel (Esc)" onClick={onClose}
          className="w-7 h-7 rounded text-slate-400 hover:bg-slate-800 hover:text-slate-100">✕</button>
      </div>
      <div className="flex-1 min-h-0">{children}</div>
      {!maximized && EDGES.map((edge) => (
        <div key={edge} aria-hidden="true" onPointerDown={begin(edge)} className={`absolute ${EDGE_CLASS[edge]}`} />
      ))}
    </div>
  )
}
