import { useCallback, useMemo, useRef, useState } from 'react'
import type { ReactNode, UIEvent } from 'react'

/**
 * Dependency-free row virtualization for large tables (agency cases hit tens of
 * thousands of rows). Fixed row height + spacer rows: only the visible window
 * (plus overscan) is mounted, so a 50k-row table renders ~40 DOM rows.
 *
 * Usage (inside a <table>):
 *   const v = useVirtualRows(rows.length, 34, 480)
 *   <div className="overflow-auto" style={{ maxHeight: 480 }} onScroll={v.onScroll}>
 *     <table>…
 *       <tbody>
 *         {v.topSpacer}
 *         {rows.slice(v.start, v.end).map(renderRow)}
 *         {v.bottomSpacer}
 *       </tbody>
 *     </table>
 *   </div>
 */
export function useVirtualRows(count: number, rowHeight = 34, viewportHeight = 480, overscan = 8) {
  const [scrollTop, setScrollTop] = useState(0)
  const raf = useRef<number | null>(null)

  const onScroll = useCallback((e: UIEvent<HTMLElement>) => {
    const top = (e.target as HTMLElement).scrollTop
    if (raf.current != null) cancelAnimationFrame(raf.current)
    raf.current = requestAnimationFrame(() => setScrollTop(top))
  }, [])

  return useMemo(() => {
    const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
    const visible = Math.ceil(viewportHeight / rowHeight) + overscan * 2
    const end = Math.min(count, start + visible)
    const topPad = start * rowHeight
    const bottomPad = Math.max(0, (count - end) * rowHeight)
    const spacer = (h: number, key: string): ReactNode =>
      h > 0 ? <tr key={key} aria-hidden style={{ height: h }} /> : null
    return {
      start,
      end,
      onScroll,
      rowHeight,
      topSpacer: spacer(topPad, 'vtop'),
      bottomSpacer: spacer(bottomPad, 'vbottom'),
      virtualized: true,
    }
  }, [count, rowHeight, viewportHeight, overscan, scrollTop, onScroll])
}

/** Middle-truncate long hashes/addresses for fixed-height virtual rows. */
export function midTrunc(value: string | undefined, keep = 10): string {
  if (!value) return '-'
  if (value.length <= keep * 2 + 1) return value
  return `${value.slice(0, keep)}…${value.slice(-keep)}`
}
