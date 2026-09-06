/**
 * nodeShapes — pure SVG shape primitives for graph nodes.
 *
 * Every shape is authored inside a normalized box centred at (0,0) with a
 * nominal radius `r`, as a single `<path>` (so it is cheap to render, easy to
 * stroke, and trivially themable). The shapes are designed so the chain brand
 * glyph (rendered on top by GraphNodeKit) stays visually centred and legible.
 *
 * Shapes are how entity TYPE is encoded:
 *   circle  → wallet      square → contract    shield → exchange
 *   hexagon → mixer       diamond → bridge     rounded → dex
 *   triangle → scam       octagon → sanctioned
 *
 * Usage:
 *   <g transform="translate(x,y)">
 *     <NodeShape shape="hexagon" r={28} fill={...} stroke={...} strokeWidth={1.5} />
 *     <ChainGlyph .../>           // centred at 0,0
 *   </g>
 */
import type { ReactNode } from 'react'

export type NodeShape =
  | 'circle'
  | 'square'
  | 'diamond'
  | 'hexagon'
  | 'octagon'
  | 'shield'
  | 'triangle'
  | 'rounded'

export interface NodeShapeProps {
  shape: NodeShape
  /** nominal radius — the shape is inscribed in a 2r × 2r box centred at 0,0 */
  r: number
  fill?: string
  stroke?: string
  strokeWidth?: number
  strokeDasharray?: string
  opacity?: number
  filter?: string
  className?: string
}

// Pre-compute polygon vertex strings at radius r, rotated so the flat top is up.
function regularPolygon(r: number, sides: number, rotateDeg = 0): string {
  const pts: string[] = []
  const offset = (rotateDeg * Math.PI) / 180
  for (let i = 0; i < sides; i++) {
    const a = offset + (Math.PI * 2 * i) / sides - Math.PI / 2
    pts.push(`${(r * Math.cos(a)).toFixed(2)},${(r * Math.sin(a)).toFixed(2)}`)
  }
  return `M ${pts.join(' L ')} Z`
}

// Hexagon: flat-top, sides=6
function hexPath(r: number): string {
  return regularPolygon(r, 6, 0)
}
// Octagon: sides=8 (rotated 22.5° so a flat edge is on top)
function octPath(r: number): string {
  return regularPolygon(r, 8, 22.5)
}
// Triangle: pointing down (warning), sides=3 rotated 180°
function triPath(r: number): string {
  return regularPolygon(r * 1.12, 3, 180)
}
// Diamond: square rotated 45°
function diamondPath(r: number): string {
  const d = r * 1.18
  return `M 0,${-d} L ${d},0 L 0,${d} L ${-d},0 Z`
}
// Shield: exchange — rounded top, pointed bottom
function shieldPath(r: number): string {
  const w = r * 1.05
  const top = -r
  const bottom = r * 1.15
  const cornerR = r * 0.42
  return `M ${-w},${top + cornerR}
          Q ${-w},${top} ${-w + cornerR},${top}
          L ${w - cornerR},${top}
          Q ${w},${top} ${w},${top + cornerR}
          L ${w},${r * 0.15}
          Q ${w},${bottom} 0,${bottom}
          Q ${-w},${bottom} ${-w},${r * 0.15} Z`
}
// Square / rounded-square: contract / dex
function squarePath(r: number, rounded: boolean): string {
  const d = r * 0.96
  if (!rounded) return `M ${-d},${-d} L ${d},${-d} L ${d},${d} L ${-d},${d} Z`
  const c = r * 0.34
  return `M ${-d + c},${-d} L ${d - c},${-d} Q ${d},${-d} ${d},${-d + c}
          L ${d},${d - c} Q ${d},${d} ${d - c},${d} L ${-d + c},${d}
          Q ${-d},${d} ${-d},${d - c} L ${-d},${-d + c} Q ${-d},${-d} ${-d + c},${-d} Z`
}

const SHAPE_BUILDERS: Record<NodeShape, (r: number) => string> = {
  circle:   r => `M ${-r},0 a ${r},${r} 0 1,0 ${2 * r},0 a ${r},${r} 0 1,0 ${-2 * r},0 Z`,
  square:   r => squarePath(r, false),
  rounded:  r => squarePath(r, true),
  diamond:  diamondPath,
  hexagon:  hexPath,
  octagon:  octPath,
  shield:   shieldPath,
  triangle: triPath,
}

/** The SVG path `d` for a shape at radius r. Useful for hit-testing / minimaps. */
export function nodeShapePath(shape: NodeShape, r: number): string {
  return (SHAPE_BUILDERS[shape] || SHAPE_BUILDERS.circle)(r)
}

/** A rendered SVG shape. */
export function NodeShape(props: NodeShapeProps): ReactNode {
  const { shape, r, fill = 'none', stroke, strokeWidth = 1.5, strokeDasharray, opacity = 1, filter, className } = props
  const d = nodeShapePath(shape, r)
  return (
    <path
      d={d}
      fill={fill}
      stroke={stroke}
      strokeWidth={strokeWidth}
      strokeDasharray={strokeDasharray}
      strokeLinejoin="round"
      opacity={opacity}
      filter={filter}
      className={className}
    />
  )
}
