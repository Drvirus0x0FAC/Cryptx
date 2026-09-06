/**
 * ─────────────────────────────────────────────────────────────────────────────
 * CryptX · Nexus Graph — Edge geometry toolkit
 * ─────────────────────────────────────────────────────────────────────────────
 * Pure, framework-free geometry + formatting helpers that power the
 * investigation graph edge layer (`components/nexus/NexusEdgeLayer.tsx`).
 * No React, no DOM, no side effects — every function is deterministic and
 * unit-testable.
 *
 * What lives here:
 *  • edgeCurve()          trimmed cubic Bézier paths (node-border → node-border),
 *                         bidirectional A→B / B→A fanning, self-loops
 *  • assignEdgeLanes()    deterministic lane assignment for parallel and
 *                         bidirectional bundles (spread its result into edgeCurve)
 *  • edgeWidthForValue()  logarithmic 1.5–6 px stroke-width scale
 *  • formatAmount()       compact "12.4M USDT" / "3.4K" amount labels
 *  • shortHash()          "0x1234abcd…cdef" transaction-hash shortening
 *
 * Coordinate space: SVG screen coordinates (y grows downward) — the same space
 * the d3-force simulation positions nodes in. All returned angles are degrees,
 * compatible with SVG `rotate(angle)`.
 *
 * Curvature convention
 * ────────────────────
 * Positive lane offsets bend a curve to the LEFT of its direction of travel
 * (source → target). Because the reverse edge's "left" is the opposite side of
 * the shared axis, a bidirectional pair A⇄B automatically fans into two tidy,
 * non-overlapping arcs when both edges receive a positive lane offset — that is
 * exactly what {@link assignEdgeLanes} produces.
 *
 * Quick example
 * ─────────────
 * ```ts
 * import { assignEdgeLanes, edgeCurve, edgeWidthForValue, formatAmount } from './edgeGeometry'
 *
 * const lanes = assignEdgeLanes(bundles)                    // one entry per bundle index
 * bundles.forEach((b, i) => {
 *   const geo = edgeCurve(srcNode, dstNode, {
 *     srcRadius: 22, dstRadius: 22, ...lanes[i],
 *   })
 *   // geo.d → <path d={geo.d} markerEnd="url(#arrow)" />
 *   // geo.labelPos → place the amount chip; geo.angle → rotate its arrow icon
 *   const w = edgeWidthForValue(b.value, maxValue)          // 1.5 – 6 px
 *   const chip = `${formatAmount(b.value, b.token)} · ${b.count} tx`
 * })
 * ```
 */

// ── Types ─────────────────────────────────────────────────────────────────────

/** A 2-D point in SVG screen coordinates (y grows downward). */
export interface XY {
  x: number
  y: number
}

/** Options accepted by {@link edgeCurve}. All fields are optional. */
export interface EdgeCurveOptions {
  /**
   * Lane spacing as a fraction of the (trimmed) edge length. One lane unit =
   * `curvature × distance`. Default `0.14`. Increase for wider fanning of
   * parallel edges, decrease for tighter, straighter arcs.
   */
  curvature?: number
  /**
   * Force self-loop rendering. Auto-detected when `src` and `dst` are the exact
   * same point (which is what happens naturally when `source === target`), so
   * you normally never need to set this. Note: two *distinct* nodes sharing
   * identical coordinates will also trigger the self-loop path — nudge one of
   * them if that can occur in your layout.
   */
  selfLoop?: boolean
  /**
   * 0-based index of this edge inside its fan group, as produced by
   * {@link assignEdgeLanes}. Used together with `pairCount` for centered
   * fanning when `laneOffset` is not given, and to stagger stacked self-loops.
   */
  pairIndex?: number
  /**
   * Total number of edges in this edge's fan group, as produced by
   * {@link assignEdgeLanes}. Default `1`.
   */
  pairCount?: number
  /**
   * Signed lane offset in lane units (positive = left of travel). When given it
   * takes precedence over the centered `pairIndex`/`pairCount` fanning. Values
   * from {@link assignEdgeLanes} guarantee that opposite directions of a
   * bidirectional pair land on opposite sides of the shared axis.
   */
  laneOffset?: number
  /**
   * Radius of the source node in px. The path starts at the node's border
   * (plus 1 px), not at its center. Default `18`.
   */
  srcRadius?: number
  /**
   * Radius of the target node in px. The path ends at the node's border (plus
   * `arrowGap`), leaving room for the arrowhead. Default `18`.
   */
  dstRadius?: number
  /**
   * Extra gap in px between the trimmed path end and the target node border,
   * so the arrowhead tip lands cleanly on the border. Default `3`.
   */
  arrowGap?: number
  /**
   * Absolute cap in px for the perpendicular bend of any lane. Prevents very
   * long edges from fanning excessively. Default `110`.
   */
  maxBend?: number
}

/** Geometry of a single rendered edge. */
export interface EdgeCurveResult {
  /** SVG path `d` attribute: `M… C… …` cubic Bézier, trimmed to node borders. */
  d: string
  /** Exact curve midpoint (t = 0.5) — the visual center of the arc. */
  mid: XY
  /**
   * Tangent angle at the curve midpoint, in degrees (0 = +x/right, 90 = +y/down
   * in screen coordinates). Suitable for `rotate(angle)` on glyphs that should
   * point along the direction of travel.
   */
  angle: number
  /**
   * Recommended anchor for the amount chip: the curve midpoint, i.e. the chip
   * sits centered *on* the curve (chips have an opaque background).
   */
  labelPos: XY
}

/**
 * Lane assignment for one edge, produced by {@link assignEdgeLanes}.
 * Spread it directly into {@link EdgeCurveOptions}:
 * `edgeCurve(a, b, { srcRadius: r, ...lanes[i] })`.
 */
export interface EdgeLaneAssignment {
  /** 0-based index of this edge inside its fan group. */
  pairIndex: number
  /** Total edges in this edge's fan group. */
  pairCount: number
  /**
   * Signed lane offset in lane units (positive = left of travel). Bidirectional
   * pairs receive offsets ≥ 1 in each direction's own travel frame, which
   * places the two directions on opposite sides of the shared axis.
   */
  laneOffset: number
}

// ── Constants ─────────────────────────────────────────────────────────────────

const DEFAULT_CURVATURE = 0.14
const DEFAULT_MAX_BEND = 110
const DEFAULT_RADIUS = 18
const DEFAULT_ARROW_GAP = 3
const MIN_DIST = 1

// ── Internal helpers ──────────────────────────────────────────────────────────

/** Round to 1 decimal for stable, compact path strings (avoids "-0"). */
function num(v: number): string {
  const r = Math.abs(v) < 1e-9 ? 0 : v
  return String(Number(r.toFixed(1)))
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v))
}

/** Exact point on a cubic Bézier at t = 0.5: (P0 + 3·C1 + 3·C2 + P3) / 8. */
function cubicMidpoint(p0: XY, c1: XY, c2: XY, p3: XY): XY {
  return {
    x: (p0.x + 3 * c1.x + 3 * c2.x + p3.x) / 8,
    y: (p0.y + 3 * c1.y + 3 * c2.y + p3.y) / 8,
  }
}

/** Tangent angle (degrees) of a cubic Bézier at t = 0.5. */
function cubicMidTangentAngle(p0: XY, c1: XY, c2: XY, p3: XY): number {
  const dx = 0.75 * (c1.x - p0.x) + 1.5 * (c2.x - c1.x) + 0.75 * (p3.x - c2.x)
  const dy = 0.75 * (c1.y - p0.y) + 1.5 * (c2.y - c1.y) + 0.75 * (p3.y - c2.y)
  if (Math.abs(dx) < 1e-9 && Math.abs(dy) < 1e-9) return 0
  return (Math.atan2(dy, dx) * 180) / Math.PI
}

function assembleCurve(p0: XY, c1: XY, c2: XY, p3: XY): EdgeCurveResult {
  const d = `M${num(p0.x)},${num(p0.y)} C${num(c1.x)},${num(c1.y)} ${num(c2.x)},${num(c2.y)} ${num(p3.x)},${num(p3.y)}`
  const mid = cubicMidpoint(p0, c1, c2, p3)
  return {
    d,
    mid,
    angle: cubicMidTangentAngle(p0, c1, c2, p3),
    labelPos: mid,
  }
}

// ── edgeCurve ─────────────────────────────────────────────────────────────────

/**
 * Build a trimmed cubic Bézier path for one edge.
 *
 * Behavior:
 *  • The path starts at the source node border and ends at the target node
 *    border (plus `arrowGap`), never underneath the node discs.
 *  • `laneOffset` (or centered `pairIndex`/`pairCount`) bends the curve
 *    perpendicular to the travel axis; positive offsets bend left of travel.
 *    Feed lanes from {@link assignEdgeLanes} so bidirectional pairs A⇄B fan
 *    into separate, opposite-curving arcs and same-direction parallels spread
 *    symmetrically.
 *  • A `laneOffset` of `0` yields a perfectly straight (but still border-
 *    trimmed) edge.
 *  • Self-transfers (src ≡ dst, or `selfLoop: true`) render as a tidy loop
 *    above the node; stacked self-loops grow outward via `pairIndex`.
 *
 * @param src   Source node center (screen coordinates).
 * @param dst   Target node center (screen coordinates).
 * @param opts  See {@link EdgeCurveOptions}.
 */
export function edgeCurve(src: XY, dst: XY, opts: EdgeCurveOptions = {}): EdgeCurveResult {
  const {
    curvature = DEFAULT_CURVATURE,
    selfLoop,
    pairIndex = 0,
    pairCount = 1,
    laneOffset,
    srcRadius = DEFAULT_RADIUS,
    dstRadius = DEFAULT_RADIUS,
    arrowGap = DEFAULT_ARROW_GAP,
    maxBend = DEFAULT_MAX_BEND,
  } = opts

  const isSelf = selfLoop ?? (src.x === dst.x && src.y === dst.y)
  if (isSelf) return selfLoopCurve(src, Math.max(6, srcRadius), pairIndex)

  const dx = dst.x - src.x
  const dy = dst.y - src.y
  const dist = Math.max(MIN_DIST, Math.hypot(dx, dy))
  const ux = dx / dist
  const uy = dy / dist
  // Left normal of the direction of travel (screen coordinates).
  const nx = -uy
  const ny = ux

  // Trim to node borders; cap each trim at 40% of the distance so heavily
  // overlapping nodes still produce a non-degenerate segment.
  const trimS = Math.min(srcRadius + 1, dist * 0.4)
  const trimD = Math.min(dstRadius + arrowGap, dist * 0.4)
  const p0: XY = { x: src.x + ux * trimS, y: src.y + uy * trimS }
  const p3: XY = { x: dst.x - ux * trimD, y: dst.y - uy * trimD }

  const lane = laneOffset ?? (pairIndex - (pairCount - 1) / 2)
  const bend = clamp(lane * curvature * dist, -maxBend, maxBend)

  const c1: XY = {
    x: p0.x + (p3.x - p0.x) / 3 + nx * bend,
    y: p0.y + (p3.y - p0.y) / 3 + ny * bend,
  }
  const c2: XY = {
    x: p0.x + (2 * (p3.x - p0.x)) / 3 + nx * bend,
    y: p0.y + (2 * (p3.y - p0.y)) / 3 + ny * bend,
  }

  return assembleCurve(p0, c1, c2, p3)
}

/**
 * Self-loop: an arc leaving the node's upper-right border, bowing above the
 * node, and re-entering at the upper-left border (arrowhead pointing back into
 * the node). `index` staggers stacked loops outward.
 */
function selfLoopCurve(center: XY, r: number, index: number): EdgeCurveResult {
  const a1 = (-35 * Math.PI) / 180 // start angle (upper-right)
  const a2 = (215 * Math.PI) / 180 // end angle   (upper-left)
  const grow = Math.max(0, index) * Math.max(10, r * 0.5)
  const border = r + 1
  const L = r * 2.6 + 14 + grow // control-arm length → loop height/width

  const p0: XY = { x: center.x + border * Math.cos(a1), y: center.y + border * Math.sin(a1) }
  const p3: XY = { x: center.x + border * Math.cos(a2), y: center.y + border * Math.sin(a2) }
  const c1: XY = { x: center.x + L * Math.cos(a1), y: center.y + L * Math.sin(a1) }
  const c2: XY = { x: center.x + L * Math.cos(a2), y: center.y + L * Math.sin(a2) }

  return assembleCurve(p0, c1, c2, p3)
}

// ── assignEdgeLanes ───────────────────────────────────────────────────────────

/**
 * Deterministically assign fan lanes to a list of edges/bundles so that:
 *
 *  • a lone edge between two nodes stays straight (lane 0);
 *  • parallel same-direction edges fan symmetrically around the straight line
 *    (lanes -0.5/+0.5, -1/0/+1, …);
 *  • bidirectional pairs (A→B *and* B→A) each move to their own side of the
 *    shared axis — offsets ≥ 1 lane in each direction's travel frame, which
 *    renders as opposite-curving, non-overlapping arcs;
 *  • self-loops on the same node stack outward (pairIndex 0, 1, 2, …).
 *
 * The result is index-aligned with the input array: `lanes[i]` belongs to
 * `edges[i]`. Input order is preserved within each direction group, so pass a
 * stably-sorted array (e.g. `bundleTxEdges()` output, sorted by value desc)
 * for reproducible layouts.
 *
 * @example
 * ```ts
 * const lanes = assignEdgeLanes(bundles)
 * bundles.map((b, i) => edgeCurve(src(b), dst(b), { srcRadius: 20, dstRadius: 20, ...lanes[i] }))
 * ```
 */
export function assignEdgeLanes<E extends { source: string; target: string }>(
  edges: readonly E[],
): EdgeLaneAssignment[] {
  // Group edge indices by unordered node pair (self-loops group per node).
  const groups = new Map<string, number[]>()
  edges.forEach((e, i) => {
    const key =
      e.source === e.target
        ? `self ${e.source}`
        : e.source < e.target
          ? `${e.source} ${e.target}`
          : `${e.target} ${e.source}`
    const list = groups.get(key)
    if (list) list.push(i)
    else groups.set(key, [i])
  })

  const out: EdgeLaneAssignment[] = []
  groups.forEach(indices => {
    const first = edges[indices[0]]
    if (!first) return

    // Self-loop group: stagger loops by position.
    if (first.source === first.target) {
      indices.forEach((edgeIdx, pos) => {
        out[edgeIdx] = { pairIndex: pos, pairCount: indices.length, laneOffset: pos }
      })
      return
    }

    // Split the group into the two travel directions.
    const fwd = indices.filter(i => edges[i].source < edges[i].target)
    const bwd = indices.filter(i => edges[i].source > edges[i].target)
    const bidirectional = fwd.length > 0 && bwd.length > 0

    fwd.forEach((edgeIdx, pos) => {
      out[edgeIdx] = bidirectional
        ? { pairIndex: pos, pairCount: fwd.length, laneOffset: 1 + pos }
        : { pairIndex: pos, pairCount: fwd.length, laneOffset: pos - (fwd.length - 1) / 2 }
    })
    bwd.forEach((edgeIdx, pos) => {
      out[edgeIdx] = bidirectional
        ? { pairIndex: pos, pairCount: bwd.length, laneOffset: 1 + pos }
        : { pairIndex: pos, pairCount: bwd.length, laneOffset: pos - (bwd.length - 1) / 2 }
    })
  })
  return out
}

// ── edgeWidthForValue ─────────────────────────────────────────────────────────

/**
 * Logarithmic stroke-width scale for transaction values, clamped to
 * 1.5–6 px. The largest value in view maps to 6 px; a zero/empty value maps
 * to 1.5 px.
 *
 * @param value     Bundled transfer value of this edge.
 * @param maxValue  Largest bundled value currently in view (pass the max over
 *                  all rendered bundles so widths are comparable across edges).
 */
export function edgeWidthForValue(value: number, maxValue: number): number {
  const v = Math.max(0, Number(value) || 0)
  const m = Math.max(0, Number(maxValue) || 0)
  if (m <= 0) return 1.5
  const t = Math.log1p(v) / Math.log1p(m)
  return clamp(1.5 + t * 4.5, 1.5, 6)
}

// ── shortHash / formatAmount ──────────────────────────────────────────────────

/**
 * Shorten a transaction hash (or address) for compact display:
 * `"0x8f3a…9c2d1"`. Matches the NexusGraph house style (8 head / 5 tail by
 * default). Strings already short enough are returned unchanged.
 */
export function shortHash(hash: string, head = 8, tail = 5): string {
  if (!hash) return ''
  const h = String(hash)
  return h.length > head + tail + 1 ? `${h.slice(0, head)}…${h.slice(-tail)}` : h
}

/** Round to 3 significant digits and strip trailing zeros. */
function trim3(n: number): string {
  if (n === 0) return '0'
  return String(parseFloat(n.toPrecision(3)))
}

/**
 * Compact amount formatting for edge chips: `12.4M USDT`, `3.4K`, `0.00123
 * ETH`. Uses K / M / B suffixes at thousands / millions / billions, at most 3
 * significant digits, and appends the token symbol when provided.
 *
 * @param value  Numeric amount (already bundled/summed).
 * @param token  Optional token symbol, e.g. `"USDT"`.
 */
export function formatAmount(value: number, token = ''): string {
  const v = Number(value) || 0
  const abs = Math.abs(v)
  const sign = v < 0 ? '-' : ''
  let body: string
  if (abs >= 1e9) body = `${trim3(abs / 1e9)}B`
  else if (abs >= 1e6) body = `${trim3(abs / 1e6)}M`
  else if (abs >= 1e3) body = `${trim3(abs / 1e3)}K`
  else body = trim3(abs)
  return `${sign}${body}${token ? ` ${token}` : ''}`
}
