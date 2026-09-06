/**
 * GraphMiniMap — reusable, INTERACTIVE minimap for every CrypTX graph.
 *
 * Shows nodes + edges + the current viewport rectangle in a small floating SVG.
 * Supports click-to-recenter and drag-to-pan (the NexusGraph minimap was
 * previously read-only). Selection is highlighted. Adapts to dark/light themes.
 *
 * The parent owns the world (node positions + viewport). This component is
 * presentational + emits pan intents via `onViewport(px, py)` where (px,py) is
 * the new top-left of the viewport in WORLD coordinates.
 */
import { useEffect, useMemo, useRef, useState } from 'react'

export interface MiniNode {
  id: string
  x: number
  y: number
  /** optional: high-risk → larger/dot colored */
  risk?: number
  selected?: boolean
}
export interface MiniEdge { x1: number; y1: number; x2: number; y2: number }

export interface ViewportRect { x: number; y: number; w: number; h: number }

export interface GraphMiniMapProps {
  nodes: MiniNode[]
  edges?: MiniEdge[]
  /** current viewport in WORLD coords (top-left + size) */
  viewport: ViewportRect
  width?: number
  height?: number
  onPan?: (worldX: number, worldY: number) => void
  /** anchor corner (default bottom-right) */
  position?: 'bottom-right' | 'bottom-left' | 'top-right'
}

function useIsLight(): boolean {
  const read = () => typeof document !== 'undefined' && document.documentElement.classList.contains('light')
  const [isLight, setIsLight] = useState(read)
  useEffect(() => {
    const el = document.documentElement
    const obs = new MutationObserver(() => setIsLight(el.classList.contains('light')))
    obs.observe(el, { attributes: true, attributeFilter: ['class'] })
    return () => obs.disconnect()
  }, [])
  return isLight
}

export function GraphMiniMap(props: GraphMiniMapProps) {
  const { nodes, edges = [], viewport, width = 168, height = 104, onPan, position = 'bottom-right' } = props
  const isLight = useIsLight()
  const svgRef = useRef<SVGSVGElement>(null)
  const [dragging, setDragging] = useState(false)

  // World bbox of all nodes + viewport (with padding)
  const bounds = useMemo(() => {
    if (!nodes.length && !viewport) return { minX: 0, minY: 0, maxX: width, maxY: height }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const n of nodes) { minX = Math.min(minX, n.x); minY = Math.min(minY, n.y); maxX = Math.max(maxX, n.x); maxY = Math.max(maxY, n.y) }
    // include viewport extremes
    minX = Math.min(minX, viewport.x); minY = Math.min(minY, viewport.y)
    maxX = Math.max(maxX, viewport.x + viewport.w); maxY = Math.max(maxY, viewport.y + viewport.h)
    const pad = Math.max(maxX - minX, maxY - minY) * 0.08 + 20
    return { minX: minX - pad, minY: minY - pad, maxX: maxX + pad, maxY: maxY + pad }
  }, [nodes, viewport, width, height])

  const worldW = Math.max(1, bounds.maxX - bounds.minX)
  const worldH = Math.max(1, bounds.maxY - bounds.minY)
  const scale = Math.min(width / worldW, height / worldH)
  // centre within the minimap box
  const offX = (width - worldW * scale) / 2 - bounds.minX * scale
  const offY = (height - worldH * scale) / 2 - bounds.minY * scale
  const w2m = (wx: number, wy: number) => ({ x: wx * scale + offX, y: wy * scale + offY })
  const m2w = (mx: number, my: number) => ({ x: (mx - offX) / scale, y: (my - offY) / scale })

  const handlePan = (clientX: number, clientY: number) => {
    if (!svgRef.current || !onPan) return
    const r = svgRef.current.getBoundingClientRect()
    const mx = ((clientX - r.left) / r.width) * width
    const my = ((clientY - r.top) / r.height) * height
    const w = m2w(mx, my)
    // recenter the viewport on the clicked world point
    onPan(w.x - viewport.w / 2, w.y - viewport.h / 2)
  }

  const vp = w2m(viewport.x, viewport.y)
  const vpW = viewport.w * scale
  const vpH = viewport.h * scale

  const cornerStyle = position === 'bottom-left'
    ? { bottom: 14, left: 14 }
    : position === 'top-right'
    ? { top: 14, right: 14 }
    : { bottom: 14, right: 14 }

  const bgFill = isLight ? 'rgba(248,250,252,0.92)' : 'rgba(8,10,15,0.82)'
  const borderColor = isLight ? 'rgba(148,163,184,0.5)' : 'rgba(71,85,105,0.5)'

  return (
    <svg
      ref={svgRef}
      width={width}
      height={height}
      className="cryptx-minimap"
      style={{
        position: 'absolute', ...cornerStyle, zIndex: 30, pointerEvents: 'auto',
        background: bgFill, border: `1px solid ${borderColor}`, borderRadius: 10,
        boxShadow: isLight ? '0 4px 14px rgba(15,23,42,0.10)' : '0 4px 14px rgba(0,0,0,0.45)',
        cursor: dragging ? 'grabbing' : (onPan ? 'grab' : 'default'),
      }}
      onMouseDown={e => { setDragging(true); handlePan(e.clientX, e.clientY) }}
      onMouseMove={e => { if (dragging) handlePan(e.clientX, e.clientY) }}
      onMouseUp={() => setDragging(false)}
      onMouseLeave={() => setDragging(false)}
    >
      {/* edges */}
      {edges.map((ed, i) => {
        const a = w2m(ed.x1, ed.y1); const b = w2m(ed.x2, ed.y2)
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={isLight ? 'rgba(100,116,139,0.30)' : 'rgba(148,163,184,0.22)'} strokeWidth={0.6} />
      })}
      {/* nodes */}
      {nodes.map(n => {
        const p = w2m(n.x, n.y)
        const r = n.selected ? 2.4 : (n.risk && n.risk >= 70 ? 2.0 : 1.5)
        const fill = n.selected ? '#0a84ff' : n.risk && n.risk >= 90 ? '#ff2d55' : n.risk && n.risk >= 70 ? '#ff9f0a' : isLight ? '#475569' : '#8e9db5'
        return <circle key={n.id} cx={p.x} cy={p.y} r={r} fill={fill} />
      })}
      {/* viewport rectangle */}
      <rect x={vp.x} y={vp.y} width={Math.max(6, vpW)} height={Math.max(6, vpH)}
        fill="rgba(10,132,255,0.08)" stroke="#0a84ff" strokeWidth={1} rx={2} />
    </svg>
  )
}

export default GraphMiniMap
