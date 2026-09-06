/**
 * GraphNodeKit — the unified, theme-aware graph node renderer for CrypTX.
 *
 * One component, used by NexusGraph / TraceGraph / BoardCanvas, that layers:
 *   1. Pulse aura      — for high-risk / sanctioned (animated)
 *   2. Selection ring  — neon cyan when selected
 *   3. Risk-arc gauge  — arc length = risk_score/100, color = risk tier
 *   4. Type-shape body — entity type → shape (wallet circle, mixer hexagon…)
 *                        filled with a soft tier tint
 *   5. Chain brand glyph (ChainGlyph) centred in the body
 *   6. Type badge      — top-right pictogram (TypeGlyph) in the type accent color
 *   7. Chips           — risk score (bottom), hop (top-right), motif count, etc.
 *
 * It is purely presentational: state (selected/hovered/dimmed) is passed in,
 * interactions are emitted via callbacks. It reads the `.light` class on
 * <html> so dark and light themes both render correctly (consistent with the
 * recent UI/theme fix).
 *
 * The shape system means an analyst can tell an exchange (shield) from a
 * mixer (hexagon) from a bridge (diamond) at a glance — even in a printout —
 * which was impossible before (every node was a circle).
 */
import { useEffect, useState } from 'react'
import { ChainGlyph, glyphKey } from '../chainGlyphs'
import { NodeShape, type NodeShape as Shape } from './nodeShapes'
import { classifyEntity, ENTITY_META, type EntityInput } from './entityTypes'
import { riskStyle, riskArc, isHighRisk } from './riskPalette'
import { TypeGlyph } from './TypeGlyph'

export interface GraphNodeKitProps {
  /** node centre in graph coordinates (the parent places this in a translated <g>) */
  x?: number
  y?: number
  /** nominal body radius (default 26) */
  r?: number
  /** entity-classification inputs — passed straight to classifyEntity() */
  entity: EntityInput & { chain?: string | null }
  riskScore?: number | null
  riskLevel?: string | null
  sanctioned?: boolean
  chain?: string | null
  /** short label shown under the node (address short / role) */
  label?: string
  /** hop distance from the seed (0 = seed). Shows a hop chip when > 0. */
  hop?: number
  /** motif count (behavioral patterns) — shows an "M×n" chip when > 0 */
  motifCount?: number
  /** true for the seed / subject node — renders a distinct accent ring */
  isSeed?: boolean
  /** selection / hover / dim state */
  selected?: boolean
  hovered?: boolean
  dimmed?: boolean
  /** highlight as part of an active fund-path */
  onPath?: boolean
  /** show text labels at all (LOD: callers turn off when zoomed out) */
  showLabel?: boolean
  /** show the corner type badge (LOD: off when tiny) */
  showTypeBadge?: boolean
  /** accent color override for the seed ring (defaults to a cyan) */
  seedColor?: string
  /** click + hover handlers */
  onClick?: () => void
  onDoubleClick?: () => void
  onHoverEnter?: () => void
  onHoverLeave?: () => void
  /** native SVG <title> tooltip text (full address + role) */
  tooltip?: string
  className?: string
  style?: React.CSSProperties
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

export function GraphNodeKit(props: GraphNodeKitProps) {
  const {
    x = 0, y = 0, r = 26, entity, riskScore, riskLevel, sanctioned,
    chain, label, hop, motifCount, isSeed,
    selected, hovered, dimmed, onPath, showLabel = true, showTypeBadge = true,
    seedColor = '#64d2ff', onClick, onDoubleClick, onHoverEnter, onHoverLeave,
    tooltip, className, style,
  } = props

  const isLight = useIsLight()
  const type = classifyEntity(entity)
  const meta = ENTITY_META[type]
  const rs = riskStyle(riskScore, riskLevel, sanctioned)
  const high = isHighRisk(riskScore, riskLevel, sanctioned)
  const chainKey = glyphKey(chain || entity.chain || '')
  const arc = riskArc(riskScore, r + 5)
  const opacity = dimmed ? 0.16 : 1

  // Body fill: a soft tint of the risk tier (so type shape + risk read together).
  const bodyFill = rs.soft
  const bodyStroke = rs.color
  // selection / hover emphasis
  const emphasis = selected || hovered
  const strokeW = selected ? 2.8 : hovered ? 2.3 : isSeed ? 2.2 : 1.5
  const seedRing = isSeed ? seedColor : null

  return (
    <g
      transform={`translate(${x},${y})`}
      className={className}
      style={{ cursor: onClick ? 'pointer' : 'default', opacity, transition: 'opacity 280ms ease', ...style }}
      onClick={e => { if (onClick) { e.stopPropagation(); onClick() } }}
      onDoubleClick={e => { if (onDoubleClick) { e.stopPropagation(); onDoubleClick() } }}
      onMouseEnter={onHoverEnter}
      onMouseLeave={onHoverLeave}
    >
      {tooltip && <title>{tooltip}</title>}

      {/* 1. Pulse aura for sanctioned / critical */}
      {high && !dimmed && (
        <circle r={r + 12} fill={rs.color} opacity={isLight ? 0.10 : 0.13}>
          <animate attributeName="r" values={`${r + 8};${r + 16};${r + 8}`} dur="2.6s" repeatCount="indefinite" />
          <animate attributeName="opacity" values={isLight ? '0.06;0.14;0.06' : '0.08;0.18;0.08'} dur="2.6s" repeatCount="indefinite" />
        </circle>
      )}

      {/* 2. Selection / path / seed ring (outside the risk arc) */}
      {selected && (
        <circle r={r + 8} fill="none" stroke="#0a84ff" strokeWidth={2} opacity={0.9} />
      )}
      {onPath && !selected && (
        <circle r={r + 8} fill="none" stroke="#ffd60a" strokeWidth={2} opacity={0.85}>
          <animate attributeName="opacity" values="0.5;0.95;0.5" dur="1.6s" repeatCount="indefinite" />
        </circle>
      )}
      {seedRing && !selected && (
        <circle r={r + 8} fill="none" stroke={seedRing} strokeWidth={1.8} opacity={0.65} strokeDasharray="3 3" />
      )}

      {/* 3. Risk-arc gauge ring (arc length = risk %) */}
      <circle r={r + 5} fill="none" stroke={isLight ? 'rgba(148,163,184,0.30)' : 'rgba(148,163,184,0.18)'} strokeWidth={2.5} />
      <circle
        r={r + 5}
        fill="none"
        stroke={rs.color}
        strokeWidth={2.5}
        strokeLinecap="round"
        strokeDasharray={arc.dash}
        transform="rotate(-90)"
        opacity={emphasis ? 1 : 0.92}
      />

      {/* 4 + 5. Type-shape body + chain glyph */}
      <NodeShape shape={meta.shape as Shape} r={r} fill={bodyFill} stroke={bodyStroke} strokeWidth={strokeW} />
      {/* ChainGlyph self-centres at (0,0) — do NOT wrap in a translate; that
          causes an off-centre shift. The r factor controls glyph diameter. */}
      <ChainGlyph chain={chainKey} r={r * 0.82} />

      {/* 6. Type badge (top-right pictogram) */}
      {showTypeBadge && (
        <g transform={`translate(${r * 0.72},${-r * 0.92})`}>
          <circle r={7.5} fill={isLight ? '#ffffff' : '#0a0c12'} stroke={meta.color} strokeWidth={1.4} />
          <g transform="translate(-6,-6)" color={meta.color}>
            <TypeGlyph type={type} size={12} />
          </g>
        </g>
      )}

      {/* 7a. Hop chip (top-left) — only when hop > 0 */}
      {typeof hop === 'number' && hop > 0 && showLabel && (
        <g transform={`translate(${-r * 0.95},${-r * 0.95})`}>
          <circle r={7} fill={isLight ? '#ffffff' : '#0a0c12'} stroke={isLight ? '#94a3b8' : '#475569'} strokeWidth={1} />
          <text textAnchor="middle" dy="3" fontSize="8.5" fontWeight={700} fill={isLight ? '#334155' : '#cbd5e1'}>{hop}</text>
        </g>
      )}

      {/* 7b. Risk-score chip (bottom) */}
      {typeof riskScore === 'number' && riskScore > 0 && showLabel && (
        <g transform={`translate(0,${r + 16})`}>
          <rect x={-15} y={-8} width={30} height={15} rx={7.5} fill={rs.color} />
          <text textAnchor="middle" dy="2.5" fontSize="9.5" fontWeight={800} fill="#ffffff">{riskScore}</text>
        </g>
      )}

      {/* 7c. Motif-count chip (right of risk chip) */}
      {typeof motifCount === 'number' && motifCount > 0 && showLabel && (
        <g transform={`translate(${label ? 22 : 0},${r + 16})`}>
          <rect x={-13} y={-8} width={26} height={15} rx={7.5} fill={isLight ? '#ffffff' : '#0a0c12'} stroke="#bf5af2" strokeWidth={1} />
          <text textAnchor="middle" dy="2.5" fontSize="8.5" fontWeight={700} fill="#bf5af2">M×{motifCount}</text>
        </g>
      )}

      {/* 7d. Label chip with left accent bar (entity role / short address) */}
      {label && showLabel && (
        <g transform={`translate(0,${r + (typeof riskScore === 'number' && riskScore > 0 ? 30 : 16)})`}>
          <rect x={-Math.min(70, label.length * 3.6 + 8)} y={-8} width={Math.min(140, label.length * 7.2 + 16)} height={16} rx={8}
            fill={isLight ? 'rgba(255,255,255,0.92)' : 'rgba(10,12,18,0.86)'}
            stroke={isLight ? 'rgba(148,163,184,0.45)' : 'rgba(100,116,139,0.35)'} strokeWidth={0.8} />
          <rect x={-Math.min(70, label.length * 3.6 + 8)} y={-8} width={2.5} height={16} rx={1.25} fill={meta.color} />
          <text textAnchor="middle" dy="3.5" fontSize="9.5" fontWeight={600}
            fill={isLight ? '#1e293b' : '#e2e8f0'}>{label.length > 18 ? label.slice(0, 16) + '…' : label}</text>
        </g>
      )}
    </g>
  )
}

export default GraphNodeKit
