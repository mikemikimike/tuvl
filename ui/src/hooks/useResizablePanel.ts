import { useCallback, useRef, useState } from 'react'

/**
 * Provides drag-to-resize behaviour for a side panel.
 *
 * Place a thin `<div onMouseDown={handleMouseDown} />` on the *left* edge of
 * the panel.  Dragging it left widens the panel; dragging right narrows it.
 *
 * Usage:
 *   const { width, handleMouseDown } = useResizablePanel(320)
 *   // In JSX:
 *   <div style={{ width }} className="shrink-0 relative ...">
 *     <div onMouseDown={handleMouseDown} className="absolute left-0 top-0 h-full w-1 cursor-col-resize ..." />
 *     // ...panel content...
 *   </div>
 */
export function useResizablePanel(defaultWidth: number, min = 200, max = 900) {
  const [width, setWidth] = useState(defaultWidth)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(0)

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      dragging.current = true
      startX.current = e.clientX
      startWidth.current = width
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'

      const onMove = (ev: MouseEvent) => {
        if (!dragging.current) return
        // panel is on the right → dragging the left edge leftward expands it
        const delta = startX.current - ev.clientX
        const newW = Math.max(min, Math.min(max, startWidth.current + delta))
        setWidth(newW)
      }

      const onUp = () => {
        dragging.current = false
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
      }

      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    },
    [width, min, max],
  )

  return { width, handleMouseDown }
}

/**
 * Like useResizablePanel but for a panel on the LEFT side of the screen.
 * Place the drag handle on the panel's *right* edge.
 * Dragging rightward widens the panel; dragging leftward narrows it.
 */
export function useResizablePanelLeft(defaultWidth: number, min = 160, max = 600) {
  const [width, setWidth] = useState(defaultWidth)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(0)

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      dragging.current = true
      startX.current = e.clientX
      startWidth.current = width
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'

      const onMove = (ev: MouseEvent) => {
        if (!dragging.current) return
        // panel is on the left → dragging the right edge rightward expands it
        const delta = ev.clientX - startX.current
        const newW = Math.max(min, Math.min(max, startWidth.current + delta))
        setWidth(newW)
      }

      const onUp = () => {
        dragging.current = false
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
      }

      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    },
    [width, min, max],
  )

  return { width, handleMouseDown }
}
