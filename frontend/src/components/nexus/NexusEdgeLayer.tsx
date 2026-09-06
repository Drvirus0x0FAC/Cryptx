/**
 * ─────────────────────────────────────────────────────────────────────────────
 * CryptX · Nexus Graph — Professional edge layer (presentational)
 * ─────────────────────────────────────────────────────────────────────────────
 * Reusable, props-driven SVG edge rendering for the Nexus investigation graph.
 * Components hold NO state of their own — hover/selection/path state is owned
 * by the parent (NexusGraph.tsx) and passed in; interactions are emitted via
 * callbacks.
 *
 * Exports
 * ───────
 *  • `<NexusEdgeLayer>`  drop-in layer: maps TxBundles → positioned FlowEdges,
 *                        computes bidirectional lanes, direction colors,
 *                        dimming, and renders its own marker defs.
 *  • `<FlowEdge>`        one bundled edge: invisible fat hit-path, trimmed
 *                        curved path with rounded caps, crisp arrowhead,
 *                        animated flow particles (SVG animateMotion) traveling
 *                        source → target, and an amount chip centered on the
 *                        curve ("12.4K USDT · 7 tx") with a direction arrow.
 *  • `<EdgeMarkerDefs>`  SVG <defs> with per-direction arrowhead markers.
 *                        Required once per <svg> when using <FlowEdge>
 *                        standalone (NexusEdgeLayer includes it automatically,
 *                        disable with `includeDefs={false}`).
 *  • Theme system        `darkEdgeTheme` / `lightEdgeTheme` /
 *                        `mergeEdgeTheme()` / `NexusEdgeTheme`.
 *  • Geometry re-exports everything from `lib/nexus/edgeGeometry` so this file
 *                        is a one-stop import for the integrator.
 *
 * Direction semantics (restrained corporate palette)
 * ──────────────────────────────────────────────────
 *  • `in`    — funds flowing INTO the focus/seed node   → emerald #10b981
 *  • `out`   — funds flowing OUT of the focus/seed node → amber   #f59e0b
 *              (prefer rose? `mergeEdgeTheme(darkEdgeTheme, { out: { stroke: '#f43f5e', … } })`)
 *  • `route` — transit edge between non-focus nodes     → sky/slate #38bdf8
 *
 * State precedence (highest wins): `selected` / `onPath` → `hovered` → `dimmed`
 * → base. Dimmed edges render at `theme.dimOpacity` (0.08) with chip and
 * particles hidden; hovering a dimmed edge temporarily revives it so analysts
 * can peek without losing the active trace.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * INTEGRATION EXAMPLE (inside NexusGraph.tsx)
 * ─────────────────────────────────────────────────────────────────────────────
 * The layer is structurally compatible with NexusGraph's local `TxBundle`
 * type (lines 51–62) — pass `renderTxBundles` straight in. Node anchors come
 * from the sim nodes in `nodesRef`.
 *
 * ```tsx
 * import { NexusEdgeLayer } from '../components/nexus/NexusEdgeLayer'
 *
 * const nodeAnchor = (id: string) => {
 *   const n = nodesRef.current.find(x => x.id === id)
 *   return n ? { x: n.x, y: n.y, r: nodeRadius(n, sizeMode) } : undefined
 * }
 *
 * // …inside the <svg>, AFTER flow-lane guides and BEFORE the node <g> so
 * // nodes paint on top of edge ends/arrowheads:
 * <g transform={`translate(${vx},${vy}) scale(${vz})`}>
 *   <NexusEdgeLayer
 *     bundles={renderTxBundles}
 *     resolveNode={nodeAnchor}
 *     focusId={selected ?? graph.seed}
 *     hoveredKey={hoveredEdge}
 *     selectedKey={selectedBundleKey}
 *     pathEdgeKeys={pathEdgeSet}            // Set<"source|target">; either direction matches
 *     showLabels="active"                   // chips on hover/selected/path only
 *     showParticles                         // particles on active edges
 *     mode={pal.isLight ? 'light' : 'dark'}
 *     onHover={setHoveredEdge}
 *     onClick={(key) => {
 *       const b = renderTxBundles.find(x => x.key === key)
 *       if (b) selectBundleFor(b)           // reuse the existing selectBundle logic
 *     }}
 *   />
 *   …nodes…
 * </g>
 * ```
 *
 * Standalone FlowEdge usage (custom layer):
 *
 * ```tsx
 * import { FlowEdge, EdgeMarkerDefs, edgeCurve, assignEdgeLanes } from '../components/nexus/NexusEdgeLayer'
 *
 * <svg>
 *   <EdgeMarkerDefs mode="dark" />          // once per svg (or per idPrefix)
 *   <FlowEdge
 *     bundle={bundle}
 *     src={{ x: a.x, y: a.y }}
 *     dst={{ x: b.x, y: b.y }}
 *     srcRadius={22}
 *     dstRadius={22}
 *     direction={bundle.target === seed ? 'in' : 'out'}
 *     hovered={hoveredEdge === bundle.key}
 *     onHover={setHoveredEdge}
 *     onClick={(key) => inspect(key)}
 *   />
 * </svg>
 * ```
 */

import type { MouseEvent as ReactMouseEvent } from 'react'
import {
  assignEdgeLanes,
  edgeCurve,
  edgeWidthForValue,
  formatAmount,
  shortHash,
} from '../../lib/nexus/edgeGeometry'
import type { EdgeLaneAssignment, XY } from '../../lib/nexus/edgeGeometry'

// Re-export the full geometry toolkit so integrators can import everything
// edge-related from this one module.
export {
  assignEdgeLanes,
  edgeCurve,
  edgeWidthForValue,
  formatAmount,
  shortHash,
}
export type {
  EdgeCurveOptions,
  EdgeCurveResult,
  EdgeLaneAssignment,
  XY,
} from '../../lib/nexus/edgeGeometry'

// ── Public types ──────────────────────────────────────────────────────────────

/**
 * Flow direction of an edge relative to the focus/seed node:
 *  • `in`    — funds flowing INTO the focus node  (target === focus)
 *  • `out`   — funds flowing OUT of the focus node (source === focus)
 *  • `route` — transit edge between two non-focus nodes
 */
export type EdgeDirection = 'in' | 'out' | 'route'

/**
 * Structural subset of NexusGraph's `TxBundle` (NexusGraph.tsx lines 51–62).
 * The real `TxBundle` is assignable to this interface — pass bundles directly,
 * no mapping needed.
 */
export interface TxBundleLike {
  /** Unique bundle key (NexusGraph uses `"source|target"`). */
  key: string
  /** Source node id. */
  source: string
  /** Target node id. */
  target: string
  /** Summed transfer value across the bundle. */
  value: number
  /** Number of raw transactions in the bundle. */
  count: number
  /** Dominant token symbol (may be ''). */
  token?: string
  /** Bundle type label, e.g. "transaction". Unused visually, kept for parity. */
  type?: string
  /** Latest tx timestamp (ISO string). Unused visually, kept for parity. */
  latestTime?: string
  /** Up to a few representative tx hashes; the first is shown in the tooltip. */
  hashes?: string[]
  /** Raw edges in the bundle. Unused visually, kept for parity. */
  edges?: ReadonlyArray<unknown>
}

/** Node anchor resolved by the integrator: sim position + rendered radius. */
export interface NexusEdgeNodeAnchor {
  x: number
  y: number
  /** Rendered node radius in px (defaults to 18 inside FlowEdge). */
  r?: number
}

// ── Theme ─────────────────────────────────────────────────────────────────────

/** Colors for one direction state of an edge. */
export interface EdgeDirectionColors {
  /** Visible curve stroke + arrowhead fill. */
  stroke: string
  /** Amount-chip background (should be near-opaque so the chip reads on top of the curve). */
  chipBg: string
  /** Amount-chip border. */
  chipBorder: string
  /** Amount-chip primary text. */
  chipText: string
  /** Flow-particle fill. */
  particle: string
}

/** Full edge-layer theme. Use {@link mergeEdgeTheme} to customize a default. */
export interface NexusEdgeTheme {
  in: EdgeDirectionColors
  out: EdgeDirectionColors
  route: EdgeDirectionColors
  /** Monospace font stack for chip text. */
  fontFamily: string
  /** Opacity for dimmed edges (default 0.08). */
  dimOpacity: number
  /** Opacity for idle (non-active, non-dimmed) edges. */
  baseOpacity: number
  /** Width in px of the invisible pointer hit-path (min; grows with stroke). */
  hitWidth: number
}

/** Partial theme accepted by {@link mergeEdgeTheme} and `themeOverride`. */
export interface EdgeThemeOverride {
  in?: Partial<EdgeDirectionColors>
  out?: Partial<EdgeDirectionColors>
  route?: Partial<EdgeDirectionColors>
  fontFamily?: string
  dimOpacity?: number
  baseOpacity?: number
  hitWidth?: number
}

const MONO_FONT =
  "'Roboto Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"

/**
 * Default dark-theme palette (matches the CryptX cyber theme):
 * inbound emerald #10b981, outbound amber #f59e0b, route sky #38bdf8.
 */
export const darkEdgeTheme: NexusEdgeTheme = {
  in: {
    stroke: '#10b981',
    chipBg: 'rgba(6, 18, 14, 0.94)',
    chipBorder: 'rgba(16, 185, 129, 0.5)',
    chipText: '#6ee7b7',
    particle: '#a7f3d0',
  },
  out: {
    stroke: '#f59e0b',
    chipBg: 'rgba(20, 14, 4, 0.94)',
    chipBorder: 'rgba(245, 158, 11, 0.5)',
    chipText: '#fcd34d',
    particle: '#fde68a',
  },
  route: {
    stroke: '#38bdf8',
    chipBg: 'rgba(6, 14, 20, 0.94)',
    chipBorder: 'rgba(56, 189, 248, 0.45)',
    chipText: '#7dd3fc',
    particle: '#bae6fd',
  },
  fontFamily: MONO_FONT,
  dimOpacity: 0.08,
  baseOpacity: 0.62,
  hitWidth: 18,
}

/** Default light-theme palette (same hues, deepened for contrast on white). */
export const lightEdgeTheme: NexusEdgeTheme = {
  in: {
    stroke: '#059669',
    chipBg: 'rgba(255, 255, 255, 0.96)',
    chipBorder: 'rgba(5, 150, 105, 0.42)',
    chipText: '#047857',
    particle: '#059669',
  },
  out: {
    stroke: '#d97706',
    chipBg: 'rgba(255, 255, 255, 0.96)',
    chipBorder: 'rgba(217, 119, 6, 0.42)',
    chipText: '#b45309',
    particle: '#d97706',
  },
  route: {
    stroke: '#0284c7',
    chipBg: 'rgba(255, 255, 255, 0.96)',
    chipBorder: 'rgba(2, 132, 199, 0.4)',
    chipText: '#0369a1',
    particle: '#0284c7',
  },
  fontFamily: MONO_FONT,
  dimOpacity: 0.08,
  baseOpacity: 0.55,
  hitWidth: 18,
}

/**
 * Shallow-merge a theme override onto a base theme (per direction + scalars).
 *
 * @example
 * ```ts
 * const theme = mergeEdgeTheme(darkEdgeTheme, {
 *   out: { stroke: '#f43f5e', chipBorder: 'rgba(244,63,94,.5)', chipText: '#fda4af' },
 * })
 * ```
 */
export function mergeEdgeTheme(base: NexusEdgeTheme, override: EdgeThemeOverride = {}): NexusEdgeTheme {
  return {
    in: { ...base.in, ...override.in },
    out: { ...base.out, ...override.out },
    route: { ...base.route, ...override.route },
    fontFamily: override.fontFamily ?? base.fontFamily,
    dimOpacity: override.dimOpacity ?? base.dimOpacity,
    baseOpacity: override.baseOpacity ?? base.baseOpacity,
    hitWidth: override.hitWidth ?? base.hitWidth,
  }
}

// ── Markers ───────────────────────────────────────────────────────────────────

/** Default id namespace for arrowhead markers. */
export const DEFAULT_MARKER_PREFIX = 'nxe'

/**
 * Marker id for a direction. Pass the same `idPrefix` to `<EdgeMarkerDefs>`
 * and `<FlowEdge>` when running multiple edge layers in one document.
 */
export function edgeMarkerId(direction: EdgeDirection, prefix: string = DEFAULT_MARKER_PREFIX): string {
  return `${prefix}-arrow-${direction}`
}

export interface EdgeMarkerDefsProps {
  /** Full theme; when omitted, `mode` selects the dark/light default. */
  theme?: NexusEdgeTheme
  /** Selects the default palette when `theme` is not given. Default 'dark'. */
  mode?: 'dark' | 'light'
  /** Id namespace; must match the `idPrefix` given to FlowEdge. Default 'nxe'. */
  idPrefix?: string
}

/**
 * SVG `<defs>` containing one crisp arrowhead marker per direction
 * (`in` / `out` / `route`). Markers use `markerUnits="strokeWidth"` so the
 * arrowhead scales proportionally with the edge's emphasis width, and
 * `orient="auto"` so it follows the curve tangent — always pointing in the
 * source → target direction of travel.
 *
 * Render exactly once per `<svg>` (per `idPrefix`) before any `<FlowEdge>`
 * that references it. `<NexusEdgeLayer>` renders it automatically.
 */
export function EdgeMarkerDefs({ theme, mode = 'dark', idPrefix = DEFAULT_MARKER_PREFIX }: EdgeMarkerDefsProps) {
  const t = theme ?? (mode === 'light' ? lightEdgeTheme : darkEdgeTheme)
  const directions: EdgeDirection[] = ['in', 'out', 'route']
  return (
    <defs>
      {directions.map(dir => (
        <marker
          key={dir}
          id={edgeMarkerId(dir, idPrefix)}
          viewBox="0 0 7 6"
          markerWidth="7"
          markerHeight="6"
          refX="5.9"
          refY="3"
          orient="auto"
          markerUnits="strokeWidth"
        >
          {/* chevron with a concave back — crisp at small sizes */}
          <path d="M0.2,0.4 L6.6,3 L0.2,5.6 L1.7,3 z" fill={t[dir].stroke} />
        </marker>
      ))}
    </defs>
  )
}

// ── Direction helper ──────────────────────────────────────────────────────────

/**
 * Default direction derivation used by `<NexusEdgeLayer>`:
 * `target === focus` → 'in', `source === focus` → 'out', otherwise 'route'.
 * A self-loop on the focus node counts as 'in' (funds return to the focus).
 * Exported so integrators can reuse or wrap it in a custom `directionFor`.
 */
export function defaultEdgeDirection(
  bundle: { source: string; target: string },
  focusId: string | null,
): EdgeDirection {
  if (!focusId) return 'route'
  if (bundle.target === focusId) return 'in'
  if (bundle.source === focusId) return 'out'
  return 'route'
}

// ── FlowEdge ──────────────────────────────────────────────────────────────────

export interface FlowEdgeProps {
  /** The bundled transaction edge to render (NexusGraph `TxBundle` fits). */
  bundle: TxBundleLike
  /** Source node center (screen coordinates). */
  src: XY
  /** Target node center (screen coordinates). */
  dst: XY
  /** Source node rendered radius (px). Default 18. */
  srcRadius?: number
  /** Target node rendered radius (px). Default 18. */
  dstRadius?: number
  /** Lane fan index — take from `assignEdgeLanes`. */
  pairIndex?: number
  /** Lane fan size — take from `assignEdgeLanes`. */
  pairCount?: number
  /** Signed lane offset — take from `assignEdgeLanes` (wins over pairIndex/pairCount). */
  laneOffset?: number
  /** Lane spacing as fraction of edge length. Default 0.14 (see edgeCurve). */
  curvature?: number
  /** Flow direction; drives the color family. Default 'route'. */
  direction?: EdgeDirection
  /** Largest bundle value in view, for the logarithmic width scale. Default: this bundle's value. */
  maxValue?: number
  /** Explicit stroke width (px); overrides the value-based scale. */
  width?: number
  /** De-emphasized (another trace/selection is active). Default false. */
  dimmed?: boolean
  /** Pointer is over this edge. Default false. */
  hovered?: boolean
  /** This bundle is the inspector's current selection. Default false. */
  selected?: boolean
  /** Edge belongs to the traced path / subgraph highlight. Default false. */
  onPath?: boolean
  /**
   * Chip visibility override. Default: shown when hovered/selected/onPath,
   * hidden while dimmed (unless hovered).
   */
  showLabel?: boolean
  /** Master switch for flow particles. Default true. */
  showParticles?: boolean
  /** Animate particles even when the edge is idle. Default false. */
  alwaysFlow?: boolean
  /** Particle count. Default 2 (3 when selected/onPath). */
  particleCount?: number
  /** Seconds per particle traversal. Default 1.8 (1.05 when selected/onPath). */
  particleDuration?: number
  /** Full chip text override. Default `"<formatAmount(value, token)> · <count> tx"`. */
  label?: string
  /** Full theme; when omitted, `mode` selects the dark/light default. */
  theme?: NexusEdgeTheme
  /** Selects the default palette when `theme` is not given. Default 'dark'. */
  mode?: 'dark' | 'light'
  /** Marker id namespace; must match EdgeMarkerDefs. Default 'nxe'. */
  idPrefix?: string
  /** Called with the bundle key on pointer enter, `null` on leave. */
  onHover?: (key: string | null) => void
  /**
   * Called on click with the bundle key. The click is `stopPropagation()`-ed
   * so it never reaches the canvas background (which would clear selection).
   */
  onClick?: (key: string, event: ReactMouseEvent<SVGGElement>) => void
}

/**
 * One professionally rendered transaction-bundle edge:
 *
 *  • invisible fat hit-path (easy to hover/click, even for 1.5 px edges)
 *  • visible cubic curve, trimmed to node borders, rounded caps, width scaled
 *    logarithmically by bundled value (1.5–6 px via `edgeWidthForValue`)
 *  • crisp arrowhead (see `<EdgeMarkerDefs>`) pointing source → target
 *  • animated flow particles traveling in the transaction direction
 *  • amount chip centered on the curve: `"12.4K USDT · 7 tx"` plus a small
 *    arrow icon rotated to the curve tangent (points along the flow)
 *  • native `<title>` tooltip with the full-precision amount and first tx hash
 *
 * Hover raises opacity/width slightly and enlarges the chip (~7 %); `dimmed`
 * drops the edge to `theme.dimOpacity` (0.08). All transitions are 160 ms.
 *
 * Must be rendered inside an `<svg>` that also contains a matching
 * `<EdgeMarkerDefs>` (automatic inside `<NexusEdgeLayer>`).
 */
export function FlowEdge({
  bundle,
  src,
  dst,
  srcRadius = 18,
  dstRadius = 18,
  pairIndex,
  pairCount,
  laneOffset,
  curvature,
  direction = 'route',
  maxValue,
  width: widthProp,
  dimmed = false,
  hovered = false,
  selected = false,
  onPath = false,
  showLabel,
  showParticles = true,
  alwaysFlow = false,
  particleCount,
  particleDuration,
  label,
  theme,
  mode = 'dark',
  idPrefix = DEFAULT_MARKER_PREFIX,
  onHover,
  onClick,
}: FlowEdgeProps) {
  const t = theme ?? (mode === 'light' ? lightEdgeTheme : darkEdgeTheme)
  const colors = t[direction]
  const active = hovered || selected || onPath

  const geo = edgeCurve(src, dst, {
    curvature,
    pairIndex,
    pairCount,
    laneOffset,
    srcRadius,
    dstRadius,
  })

  const baseWidth = widthProp ?? edgeWidthForValue(bundle.value, maxValue ?? bundle.value)
  const width = selected || onPath ? baseWidth + 1.2 : hovered ? baseWidth + 0.8 : baseWidth
  const opacity =
    dimmed && !hovered
      ? t.dimOpacity
      : selected || onPath
        ? 0.98
        : hovered
          ? 0.95
          : t.baseOpacity

  const chipVisible = (showLabel ?? active) && !(dimmed && !hovered)
  const particlesOn = showParticles && (alwaysFlow || active) && !(dimmed && !hovered)
  const pCount = Math.max(1, particleCount ?? (selected || onPath ? 3 : 2))
  const pDur = particleDuration ?? (selected || onPath ? 1.05 : 1.8)

  const token = bundle.token || ''
  const chipText = label ?? `${formatAmount(bundle.value, token)} · ${bundle.count} tx`
  const dirWord = direction === 'in' ? 'Inbound' : direction === 'out' ? 'Outbound' : 'Transit'
  const fullAmount = (Number(bundle.value) || 0).toLocaleString(undefined, {
    maximumFractionDigits: 6,
  })
  const firstHash = bundle.hashes && bundle.hashes.length > 0 ? bundle.hashes[0] : ''
  const markerUrl = `url(#${edgeMarkerId(direction, idPrefix)})`

  // Amount-chip geometry (estimated monospace metrics; chip is pointer-transparent).
  const chipPadX = 9
  const chipIconW = 15
  const chipCharW = 6.2
  const chipH = 20
  const chipTextW = chipText.length * chipCharW
  const chipW = Math.ceil(chipPadX * 2 + chipIconW + chipTextW)
  const chipIconX = -chipW / 2 + chipPadX + chipIconW / 2
  const chipTextX = -chipW / 2 + chipPadX + chipIconW + chipTextW / 2

  return (
    <g
      className={
        `nx-flow-edge nx-flow-edge--${direction}` +
        (selected ? ' is-selected' : '') +
        (onPath ? ' is-on-path' : '') +
        (hovered ? ' is-hovered' : '') +
        (dimmed ? ' is-dimmed' : '')
      }
      style={{ cursor: 'pointer' }}
      onMouseEnter={() => onHover?.(bundle.key)}
      onMouseLeave={() => onHover?.(null)}
      onClick={event => {
        event.stopPropagation()
        onClick?.(bundle.key, event)
      }}
    >
      <title>{`${dirWord} · ${fullAmount}${token ? ` ${token}` : ''} · ${bundle.count} tx${firstHash ? ` · ${shortHash(firstHash)}` : ''}`}</title>

      {/* soft halo behind emphasized edges */}
      {active && !dimmed && (
        <path
          d={geo.d}
          fill="none"
          stroke={colors.stroke}
          strokeWidth={width + 6}
          strokeLinecap="round"
          opacity={0.15}
          pointerEvents="none"
        />
      )}

      {/* invisible fat hit area — the only painted event target in this <g> */}
      <path
        d={geo.d}
        fill="none"
        stroke="transparent"
        strokeWidth={Math.max(t.hitWidth, width + 6)}
        strokeLinecap="round"
      />

      {/* visible curve with directional arrowhead */}
      <path
        d={geo.d}
        fill="none"
        stroke={colors.stroke}
        strokeWidth={width}
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={opacity}
        markerEnd={markerUrl}
        pointerEvents="none"
        style={{ transition: 'stroke-width 160ms ease, opacity 160ms ease' }}
      />

      {/* flow particles traveling source → target */}
      {particlesOn &&
        Array.from({ length: pCount }).map((_, i) => (
          <circle
            key={i}
            r={Math.max(1.8, Math.min(3.4, width * 0.5))}
            fill={colors.particle}
            opacity={0.95}
            pointerEvents="none"
          >
            <animateMotion
              dur={`${pDur}s`}
              begin={`${(-i * pDur) / pCount}s`}
              repeatCount="indefinite"
              path={geo.d}
            />
          </circle>
        ))}

      {/* amount chip, centered on the curve */}
      {chipVisible && (
        <g transform={`translate(${geo.labelPos.x},${geo.labelPos.y})`} pointerEvents="none">
          <g
            style={{
              transform: hovered ? 'scale(1.07)' : 'scale(1)',
              transformBox: 'fill-box',
              transformOrigin: 'center',
              transition: 'transform 160ms ease',
            }}
          >
            <rect
              x={-chipW / 2}
              y={-chipH / 2}
              width={chipW}
              height={chipH}
              rx={6}
              fill={colors.chipBg}
              stroke={colors.chipBorder}
              strokeWidth={1}
            />
            {/* direction arrow, rotated to the curve tangent at the midpoint */}
            <g transform={`translate(${chipIconX},0) rotate(${geo.angle})`}>
              <path d="M-3.4,-3.2 L3.8,0 L-3.4,3.2 z" fill={colors.stroke} />
            </g>
            <text
              x={chipTextX}
              y={3.5}
              textAnchor="middle"
              fill={colors.chipText}
              fontSize={10}
              fontWeight={700}
              letterSpacing={0.2}
              fontFamily={t.fontFamily}
            >
              {chipText}
            </text>
          </g>
        </g>
      )}
    </g>
  )
}

// ── NexusEdgeLayer ────────────────────────────────────────────────────────────

export interface NexusEdgeLayerProps {
  /** Bundled transaction edges (NexusGraph `TxBundle[]` fits directly). */
  bundles: readonly TxBundleLike[]
  /**
   * Resolve a node id to its current sim position + rendered radius.
   * Return `undefined` for hidden/missing nodes — those edges are skipped.
   */
  resolveNode: (id: string) => NexusEdgeNodeAnchor | undefined
  /**
   * Focus node id (usually `selected ?? graph.seed`). Drives the default
   * in/out/route direction coloring. Pass `null` to color everything 'route'.
   */
  focusId?: string | null
  /** Currently hovered bundle key (parent-owned state). */
  hoveredKey?: string | null
  /** Currently selected bundle key (parent-owned state). */
  selectedKey?: string | null
  /**
   * Set of `"source|target"` pair keys (NexusGraph's `edgePairKey` format)
   * that belong to the traced path / subgraph. Matches either direction.
   */
  pathEdgeKeys?: ReadonlySet<string>
  /**
   * When a trace/selection is active, dim every edge not part of it to
   * `theme.dimOpacity`. Default true.
   */
  dimWhenInactive?: boolean
  /**
   * Custom direction derivation. Default: {@link defaultEdgeDirection}
   * (target === focus → 'in', source === focus → 'out', else 'route').
   */
  directionFor?: (bundle: TxBundleLike, focusId: string | null) => EdgeDirection
  /** Explicit max value for the width scale. Default: max over `bundles`. */
  maxValue?: number
  /** Lane spacing as fraction of edge length (see `edgeCurve`). Default 0.14. */
  curvature?: number
  /** Selects the default palette when `theme` is not given. Default 'dark'. */
  mode?: 'dark' | 'light'
  /** Full theme replacement (wins over `mode` and `themeOverride`). */
  theme?: NexusEdgeTheme
  /** Partial override merged onto the `mode` default (ignored when `theme` is set). */
  themeOverride?: EdgeThemeOverride
  /** Master switch for flow particles. Default true. */
  showParticles?: boolean
  /** Animate particles on ALL edges, not just active ones. Default false. */
  alwaysFlow?: boolean
  /**
   * Chip visibility policy: 'active' (hover/selected/path only — default),
   * 'always' (every edge), or 'never'.
   */
  showLabels?: 'active' | 'always' | 'never'
  /** Marker id namespace. Default 'nxe'. */
  idPrefix?: string
  /**
   * Render `<EdgeMarkerDefs>` inside this layer. Default true. Set false only
   * if you render matching defs yourself elsewhere in the same <svg>.
   */
  includeDefs?: boolean
  /** Called with the bundle key on pointer enter, `null` on leave. */
  onHover?: (key: string | null) => void
  /** Called on edge click (already stopPropagation-ed). */
  onClick?: (key: string, event: ReactMouseEvent<SVGGElement>) => void
}

/**
 * Drop-in edge layer for the Nexus investigation graph. Renders:
 * `<EdgeMarkerDefs>` + one `<FlowEdge>` per resolvable bundle.
 *
 * Purely presentational — no internal state. Wire `hoveredKey`,
 * `selectedKey`, `pathEdgeKeys`, `onHover` and `onClick` to NexusGraph's
 * existing `hoveredEdge` / `selectedBundleKey` / `pathEdgeSet` state.
 *
 * Render order: place this layer BEFORE the node layer so node discs paint
 * over trimmed edge ends and arrowheads.
 */
export function NexusEdgeLayer({
  bundles,
  resolveNode,
  focusId = null,
  hoveredKey = null,
  selectedKey = null,
  pathEdgeKeys,
  dimWhenInactive = true,
  directionFor,
  maxValue: maxValueProp,
  curvature,
  mode = 'dark',
  theme,
  themeOverride,
  showParticles = true,
  alwaysFlow = false,
  showLabels = 'active',
  idPrefix = DEFAULT_MARKER_PREFIX,
  includeDefs = true,
  onHover,
  onClick,
}: NexusEdgeLayerProps) {
  const t = theme ?? mergeEdgeTheme(mode === 'light' ? lightEdgeTheme : darkEdgeTheme, themeOverride)
  const lanes = assignEdgeLanes(bundles)
  const maxValue = maxValueProp ?? bundles.reduce((m, b) => Math.max(m, Number(b.value) || 0), 0)
  const traceActive = !!selectedKey || (!!pathEdgeKeys && pathEdgeKeys.size > 0)

  return (
    <g className="nexus-edge-layer" data-mode={mode}>
      {includeDefs && <EdgeMarkerDefs theme={t} idPrefix={idPrefix} />}
      {bundles.map((bundle, i) => {
        const s = resolveNode(bundle.source)
        const d = resolveNode(bundle.target)
        if (!s || !d) return null

        const lane: EdgeLaneAssignment | undefined = lanes[i]
        const pairFwd = `${bundle.source}|${bundle.target}`
        const pairRev = `${bundle.target}|${bundle.source}`
        const onPath = !!pathEdgeKeys && (pathEdgeKeys.has(pairFwd) || pathEdgeKeys.has(pairRev))
        const selected = selectedKey === bundle.key
        const hovered = hoveredKey === bundle.key
        const dimmed = dimWhenInactive && traceActive && !selected && !onPath
        const direction = directionFor ? directionFor(bundle, focusId) : defaultEdgeDirection(bundle, focusId)

        return (
          <FlowEdge
            key={bundle.key}
            bundle={bundle}
            src={s}
            dst={d}
            srcRadius={s.r ?? 18}
            dstRadius={d.r ?? 18}
            pairIndex={lane?.pairIndex}
            pairCount={lane?.pairCount}
            laneOffset={lane?.laneOffset}
            curvature={curvature}
            direction={direction}
            maxValue={maxValue}
            dimmed={dimmed}
            hovered={hovered}
            selected={selected}
            onPath={onPath}
            showLabel={showLabels === 'always' ? true : showLabels === 'never' ? false : undefined}
            showParticles={showParticles}
            alwaysFlow={alwaysFlow}
            theme={t}
            idPrefix={idPrefix}
            onHover={onHover}
            onClick={onClick}
          />
        )
      })}
    </g>
  )
}
