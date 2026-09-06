/**
 * flowLayout.ts — Professional Sugiyama-style layered flow layout for the Nexus Graph.
 * =====================================================================================
 *
 * Pure TypeScript, zero dependencies. Renders money flow LEFT → RIGHT:
 *   · the seed (subject) node is pinned to rank 0 at the vertical centre,
 *   · downstream counterparties (funds leaving the seed) occupy ranks +1, +2, …
 *   · upstream sources (funds entering the seed) occupy ranks −1, −2, …
 *   · nodes unreachable from the seed are parked in a tidy column AFTER the
 *     rightmost flow rank (fallback ranking) so they never disturb the flow.
 *
 * Pipeline (classic Sugiyama steps, adapted for a centred seed):
 *   1. Cycle-safe rank assignment  — BFS from the seed in both directions with
 *      visited sets (can never infinite-loop), then DFS back-edge elimination
 *      per side (cycle removal) plus a bounded number of longest-path
 *      relaxation passes so each node sits one rank to the right of its
 *      predecessors where possible. Back edges and seed-incident edges are
 *      excluded, so relaxation always terminates on cyclic graphs and the
 *      seed's rank-0 anchor is immovable.
 *   2. Fallback ranking            — unreachable nodes → (maxRank + 1).
 *   3. Crossing reduction          — barycenter heuristic, alternating
 *      down/up sweeps (default 6, configurable 0–12). The seed never moves
 *      within its rank: it is excluded from sorting and re-inserted at its
 *      previous index, keeping it vertically centred.
 *   4. Coordinate assignment       — configurable rankGap / nodeGap, expanded
 *      by the per-node `radius` accessor so large nodes never overlap, and an
 *      `edgeLabelClearance` reserve so edge amount labels fit between columns.
 *      Every rank is centred vertically around the seed's y. The resulting
 *      canvas MAY exceed the viewport (W×H) — the caller is expected to run
 *      its fit-view logic afterwards (NexusGraph already does:
 *      `setTimeout(fitView, 300)`).
 *
 * Determinism: identical input → identical output. Adjacency lists are sorted
 * by node id, every ordering tie is broken by node id, and no randomness,
 * Date, or iteration-order-dependent logic is used anywhere.
 *
 * Complexity: roughly O((N + E) · sweeps) — comfortably interactive for the
 * graph sizes NexusGraph handles (hundreds of nodes).
 *
 * ────────────────────────────────────────────────────────────────────────────
 * INTEGRATION (NexusGraph.tsx)
 * ────────────────────────────────────────────────────────────────────────────
 * This module is a drop-in replacement for the legacy local `flowLayout()`
 * (NexusGraph.tsx line ~529) — the call signature is identical, options are
 * optional:
 *
 *   import { computeFlowLayout, relayoutSubset } from '../lib/nexus/flowLayout'
 *
 *   // Existing call sites (~lines 1273–1285 and 1291–1316):
 *   const pos = layout === 'flow'
 *     ? computeFlowLayout(nodes, graph.edges, graph.seed, W, H, {
 *         radius: n => nodeRadius(n, sizeMode),   // re-use existing sizing
 *       })
 *     : ...
 *   nodes.forEach(n => {
 *     const p = pos.get(n.id)
 *     if (p) { n.fx = p.x; n.fy = p.y }
 *   })
 *   sim.alpha(0.3).restart()
 *   setTimeout(fitView, 300)                       // canvas may exceed viewport
 *
 * Isolating a subgraph (SubgraphWorkspace):
 *
 *   // `positions`: current coordinates, e.g. new Map(nodesRef.current.map(n => [n.id, { x: n.x, y: n.y }]))
 *   const pos = relayoutSubset(
 *     positions, nodesRef.current, graph.edges, graph.seed,
 *     subgraph.ids, W, H,
 *     { radius: n => nodeRadius(n, sizeMode) },
 *   )
 *
 * Type compatibility: `NexusNode`/`SimNode` satisfy `FlowNodeLike`
 * (`{ id: string }`) structurally via the generic parameter, and `NexusEdge`
 * satisfies `FlowEdgeLike` — pass them directly, no mapping needed.
 */

// ── Public types ─────────────────────────────────────────────────────────────

/**
 * Minimal structural requirement for a layout node. Any object with a string
 * `id` works — `NexusNode` and the d3 `SimNode` both qualify. Additional
 * fields are only visible to the optional `radius` / `orderHint` accessors
 * through the generic parameter `N`.
 */
export interface FlowNodeLike {
  id: string
}

/**
 * Minimal structural requirement for a layout edge. `NexusEdge`
 * (`{ source, target, value, token, hash, time, type }`) is assignable
 * directly. Self-loops, duplicate (source,target) pairs, and edges referencing
 * unknown nodes are ignored by the layout.
 */
export interface FlowEdgeLike {
  source: string
  target: string
}

/** A 2D canvas coordinate (pixel space, same units as the SVG viewport). */
export interface FlowPoint {
  x: number
  y: number
}

/** Result of a layout computation: node id → canvas coordinate. */
export type FlowLayoutResult = Map<string, FlowPoint>

/**
 * Tunables for {@link computeFlowLayout} and {@link relayoutSubset}.
 * All fields are optional; defaults come from {@link FLOW_LAYOUT_DEFAULTS}.
 */
export interface FlowLayoutOptions<N extends FlowNodeLike = FlowNodeLike> {
  /**
   * Minimum horizontal distance between the centre columns of two adjacent
   * ranks (px). Effective spacing grows to
   * `maxRadius(rankA) + maxRadius(rankB) + edgeLabelClearance` when nodes are
   * large, so nodes never overlap horizontally and edge amount labels always
   * have room. Default 230 (sized so amount labels fit between columns).
   */
  rankGap?: number
  /**
   * Minimum vertical distance between the centres of two consecutive nodes in
   * the same rank (px). Effective spacing grows to
   * `radius(a) + radius(b) + nodeMargin` for large nodes, so nodes never
   * overlap vertically. Default 100.
   */
  nodeGap?: number
  /**
   * Extra vertical clearance (px) added on top of `radius(a) + radius(b)`
   * when that sum exceeds `nodeGap`. Default 28.
   */
  nodeMargin?: number
  /**
   * Extra horizontal clearance (px) reserved between the worst-case radii of
   * two adjacent ranks — this is the space edge amount/direction labels live
   * in. Default 120.
   */
  edgeLabelClearance?: number
  /**
   * Barycenter crossing-reduction sweeps (alternating down then up, starting
   * with down). Clamped to 0–12. Default 6. Use 0 to keep the raw
   * BFS-discovery ordering.
   */
  sweeps?: number
  /**
   * Longest-path layering relaxation passes after the initial BFS ranking and
   * back-edge elimination. Clamped to 0–24. Default 8. On the cycle-free side
   * graphs each pass only pushes nodes further from the seed (additionally
   * capped at ±N ranks), and the loop early-exits once stable — termination
   * is guaranteed even on cyclic input.
   */
  layeringPasses?: number
  /**
   * Per-node radius accessor (px). Factor it into spacing so big nodes never
   * overlap — integrators should pass the same sizing used for rendering,
   * e.g. `n => nodeRadius(n, sizeMode)`. Non-positive/NaN values fall back to
   * the default. Default: constant 25.
   */
  radius?: (node: N) => number
  /**
   * X coordinate of the seed's rank (px). Default `W / 2`.
   */
  centerX?: number
  /**
   * Y coordinate of the seed itself, and the vertical centre every other rank
   * is aligned around (px). Default `H / 2`.
   */
  centerY?: number
  /**
   * Initial within-rank ordering hint (smaller = higher up). Barycenter
   * sweeps refine this ordering, so it only seeds the starting configuration.
   * When omitted, BFS discovery order (adjacency-seeded) is used.
   * {@link relayoutSubset} uses this to preserve the user's current visual
   * order (current y coordinates) when isolating a subgraph.
   */
  orderHint?: (node: N) => number
}

/** Default spacing/iteration constants used by the flow layout. */
export const FLOW_LAYOUT_DEFAULTS = {
  /** See {@link FlowLayoutOptions.rankGap}. */
  rankGap: 230,
  /** See {@link FlowLayoutOptions.nodeGap}. */
  nodeGap: 100,
  /** See {@link FlowLayoutOptions.nodeMargin}. */
  nodeMargin: 28,
  /** See {@link FlowLayoutOptions.edgeLabelClearance}. */
  edgeLabelClearance: 120,
  /** See {@link FlowLayoutOptions.sweeps}. */
  sweeps: 6,
  /** See {@link FlowLayoutOptions.layeringPasses}. */
  layeringPasses: 8,
  /** Fallback node radius (px) when no `radius` accessor is supplied. */
  radius: 25,
} as const

// ── Internal helpers ─────────────────────────────────────────────────────────

/** Deterministic id comparator used for every tie-break. */
function compareIds(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0
}

/** `v` when it is a finite number, otherwise `fallback`. */
function finiteOr(v: number, fallback: number): number {
  return Number.isFinite(v) ? v : fallback
}

/** Positive finite `v`, otherwise `fallback`. */
function positiveOr(v: number | undefined, fallback: number): number {
  return v !== undefined && Number.isFinite(v) && v > 0 ? v : fallback
}

/** Integer `v` clamped to [lo, hi]. */
function clampInt(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, Math.round(v)))
}

/** Append helper for Map<string, string[]>. */
function pushMap<K, V>(map: Map<K, V[]>, key: K, value: V): void {
  const list = map.get(key)
  if (list) list.push(value)
  else map.set(key, [value])
}

/**
 * Deterministic substitute seed when the requested seed is not part of the
 * (sub)graph: highest combined in+out degree, ties broken by node id.
 * Callers must guarantee `nodes` is non-empty.
 */
function pickFallbackSeed<N extends FlowNodeLike>(
  nodes: readonly N[],
  edges: readonly FlowEdgeLike[],
): string {
  const degree = new Map<string, number>()
  for (const e of edges) {
    if (e.source === e.target) continue
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1)
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1)
  }
  let best = nodes[0].id
  for (const n of nodes) {
    const d = degree.get(n.id) ?? 0
    const bd = degree.get(best) ?? 0
    if (d > bd || (d === bd && compareIds(n.id, best) < 0)) best = n.id
  }
  return best
}

/**
 * Iterative three-colour DFS from the seed over ONE side of the graph,
 * recording back edges (edges pointing to a gray ancestor on the DFS stack)
 * into `ignored`. Removing exactly these edges breaks every cycle on that
 * side — the classic Sugiyama cycle-removal step — so the longest-path
 * relaxation afterwards runs on a DAG: it can neither infinite-loop, inflate
 * ranks through ping-ponging, nor push the seed off rank 0 (every edge from a
 * downstream node back into the seed is a back edge, because the seed stays
 * gray for the whole traversal).
 *
 * `direction` selects the layering graph walked:
 *   · 'down' — outgoing edges over nodes ranked ≥ 0 (seed + downstream),
 *   · 'up'   — incoming edges over nodes ranked < 0 (strictly upstream).
 * Edge keys are recorded in ORIGINAL edge direction (`source + ' ' + target`).
 * Deterministic: adjacency lists are id-sorted.
 */
function collectBackEdges(
  adj: Map<string, string[]>,
  seed: string,
  rank: ReadonlyMap<string, number>,
  direction: 'down' | 'up',
  ignored: Set<string>,
): void {
  const color = new Map<string, 1 | 2>() // absent = white, 1 = gray (on stack), 2 = black (done)
  const onSide = (id: string): boolean => {
    const r = rank.get(id)
    if (r === undefined) return false
    return direction === 'down' ? r >= 0 : r < 0
  }
  color.set(seed, 1)
  const stack: Array<{ id: string; next: number }> = [{ id: seed, next: 0 }]
  while (stack.length) {
    const top = stack[stack.length - 1]
    const nbrs = adj.get(top.id) ?? []
    if (top.next >= nbrs.length) {
      color.set(top.id, 2)
      stack.pop()
      continue
    }
    const nb = nbrs[top.next++]
    if (!onSide(nb)) continue // cross-side edges cannot violate layering
    const c = color.get(nb)
    if (c === 1) {
      // 'up' walks incoming edges, so the original edge is nb → top.id.
      ignored.add(direction === 'down' ? top.id + ' ' + nb : nb + ' ' + top.id)
    } else if (c === undefined) {
      color.set(nb, 1)
      stack.push({ id: nb, next: 0 })
    }
  }
}

// ── Main API ─────────────────────────────────────────────────────────────────

/**
 * Compute a professional left→right flow layout for the given graph.
 *
 * @param nodes  Graph nodes (`NexusNode[]` / `SimNode[]` compatible).
 * @param edges  Directed edges (`NexusEdge[]` compatible); duplicates,
 *               self-loops and dangling references are ignored.
 * @param seed   Id of the subject node. Pinned to rank 0 at
 *               `(centerX, centerY)`. If not present in `nodes`, a
 *               deterministic substitute (highest degree, then id) is used.
 * @param W      Viewport width (px) — used only to centre the canvas; the
 *               layout may extend beyond it (caller fits the view).
 * @param H      Viewport height (px) — same contract as `W`.
 * @param opts   Spacing / iteration / radius tunables (see
 *               {@link FlowLayoutOptions}).
 * @returns      Map of node id → coordinate. Contains exactly one entry per
 *               unique input node. Deterministic for identical input.
 */
export function computeFlowLayout<N extends FlowNodeLike>(
  nodes: readonly N[],
  edges: readonly FlowEdgeLike[],
  seed: string,
  W: number,
  H: number,
  opts: FlowLayoutOptions<N> = {},
): FlowLayoutResult {
  const out: FlowLayoutResult = new Map()

  // ── Sanitize nodes (dedupe by id, first occurrence wins) ──────────────────
  const seenIds = new Set<string>()
  const uniq: N[] = []
  for (const n of nodes) {
    if (!n || typeof n.id !== 'string' || seenIds.has(n.id)) continue
    seenIds.add(n.id)
    uniq.push(n)
  }
  if (!uniq.length) return out
  const ids = new Set(uniq.map(n => n.id))

  // ── Options ────────────────────────────────────────────────────────────────
  const rankGap = positiveOr(opts.rankGap, FLOW_LAYOUT_DEFAULTS.rankGap)
  const nodeGap = positiveOr(opts.nodeGap, FLOW_LAYOUT_DEFAULTS.nodeGap)
  const nodeMargin = positiveOr(opts.nodeMargin, FLOW_LAYOUT_DEFAULTS.nodeMargin)
  const edgeLabelClearance = positiveOr(opts.edgeLabelClearance, FLOW_LAYOUT_DEFAULTS.edgeLabelClearance)
  const sweeps = clampInt(finiteOr(opts.sweeps ?? NaN, FLOW_LAYOUT_DEFAULTS.sweeps), 0, 12)
  const layeringPasses = clampInt(finiteOr(opts.layeringPasses ?? NaN, FLOW_LAYOUT_DEFAULTS.layeringPasses), 0, 24)
  const centerX = finiteOr(opts.centerX ?? W / 2, 0)
  const centerY = finiteOr(opts.centerY ?? H / 2, 0)
  const radiusFn = opts.radius

  // Cache radii once (accessor may be non-trivial; caching also hardens
  // determinism against impure accessors).
  const radiusOf = new Map<string, number>()
  for (const n of uniq) {
    const raw = radiusFn ? radiusFn(n) : FLOW_LAYOUT_DEFAULTS.radius
    radiusOf.set(n.id, Number.isFinite(raw) && raw > 0 ? raw : FLOW_LAYOUT_DEFAULTS.radius)
  }

  // ── Sanitize edges (valid endpoints, no self-loops, deduped pairs) ────────
  const edgeSeen = new Set<string>()
  const cleanEdges: FlowEdgeLike[] = []
  for (const e of edges) {
    if (!e) continue
    const { source, target } = e
    if (typeof source !== 'string' || typeof target !== 'string') continue
    if (source === target) continue
    if (!ids.has(source) || !ids.has(target)) continue
    const key = source + ' ' + target
    if (edgeSeen.has(key)) continue
    edgeSeen.add(key)
    cleanEdges.push({ source, target })
  }

  // ── Adjacency (sorted by id → deterministic traversal) ────────────────────
  const outAdj = new Map<string, string[]>()
  const inAdj = new Map<string, string[]>()
  for (const e of cleanEdges) {
    pushMap(outAdj, e.source, e.target)
    pushMap(inAdj, e.target, e.source)
  }
  outAdj.forEach(list => list.sort(compareIds))
  inAdj.forEach(list => list.sort(compareIds))

  const effectiveSeed = ids.has(seed) ? seed : pickFallbackSeed(uniq, cleanEdges)

  // ══ Phase 1: rank assignment (cycle-safe BFS + bounded relaxation) ════════
  const rank = new Map<string, number>()
  const discovery = new Map<string, number>()
  let discoveryCounter = 0

  rank.set(effectiveSeed, 0)
  discovery.set(effectiveSeed, discoveryCounter++)

  // Downstream BFS: outgoing edges → positive ranks. The visited set makes
  // this immune to cycles.
  let frontier = [effectiveSeed]
  const seenDown = new Set([effectiveSeed])
  while (frontier.length) {
    const next: string[] = []
    for (const id of frontier) {
      const d = rank.get(id)!
      for (const t of outAdj.get(id) ?? []) {
        if (seenDown.has(t)) continue
        seenDown.add(t)
        rank.set(t, d + 1)
        discovery.set(t, discoveryCounter++)
        next.push(t)
      }
    }
    frontier = next
  }

  // Upstream BFS: incoming edges → negative ranks. Nodes already ranked by
  // the downstream pass (i.e. on a cycle through the seed) keep their
  // positive rank but still propagate, so secondary sources of downstream
  // nodes layer correctly.
  frontier = [effectiveSeed]
  const seenUp = new Set([effectiveSeed])
  while (frontier.length) {
    const next: string[] = []
    for (const id of frontier) {
      const d = rank.get(id)!
      for (const s of inAdj.get(id) ?? []) {
        if (seenUp.has(s)) continue
        seenUp.add(s)
        if (!rank.has(s)) {
          rank.set(s, d - 1)
          discovery.set(s, discoveryCounter++)
        }
        next.push(s)
      }
    }
    frontier = next
  }

  // Cycle removal (Sugiyama step 1): find back edges on each side of the seed
  // via DFS. Ignoring exactly those edges leaves a DAG per side, so the
  // relaxation below provably terminates and cannot corrupt the seed's rank.
  const ignoredEdges = new Set<string>()
  collectBackEdges(outAdj, effectiveSeed, rank, 'down', ignoredEdges)
  collectBackEdges(inAdj, effectiveSeed, rank, 'up', ignoredEdges)

  // Longest-path refinement: within each side of the seed, push every node at
  // least one rank beyond its predecessors. On the cycle-free side graphs this
  // converges in at most (longest chain) passes; ranks only ever move AWAY
  // from 0 and are additionally capped at ±N as a hard guarantee. Cross-side
  // edges (cycle edges through the seed region) and back edges are ignored,
  // and the seed itself is immovable (hard rank-0 anchor).
  const sortedEdges = [...cleanEdges].sort(
    (a, b) => compareIds(a.source, b.source) || compareIds(a.target, b.target),
  )
  const rankCap = uniq.length
  for (let pass = 0; pass < layeringPasses; pass++) {
    let changed = false
    for (const e of sortedEdges) {
      if (ignoredEdges.has(e.source + ' ' + e.target)) continue
      if (e.source === effectiveSeed || e.target === effectiveSeed) continue
      const ru = rank.get(e.source)
      const rv = rank.get(e.target)
      if (ru === undefined || rv === undefined) continue
      if (ru >= 0 && rv >= 0 && rv <= ru) {
        const nv = Math.min(rankCap, ru + 1)
        if (nv !== rv) {
          rank.set(e.target, nv)
          changed = true
        }
      } else if (ru < 0 && rv < 0 && ru >= rv) {
        const nu = Math.max(-rankCap, rv - 1)
        if (nu !== ru) {
          rank.set(e.source, nu)
          changed = true
        }
      }
    }
    if (!changed) break
  }

  // Fallback ranking: nodes unreachable from the seed form a tidy column
  // immediately after the rightmost flow rank.
  let maxRank = 0
  rank.forEach(r => {
    if (r > maxRank) maxRank = r
  })
  const fallbackRank = maxRank + 1
  const unreachable = uniq.filter(n => !rank.has(n.id)).sort((a, b) => compareIds(a.id, b.id))
  for (const n of unreachable) {
    rank.set(n.id, fallbackRank)
    discovery.set(n.id, discoveryCounter++)
  }

  // ══ Phase 2: compact ranks → columns ══════════════════════════════════════
  // Relaxation can leave empty rank values; compacting keeps column spacing
  // uniform (exactly one rankGap between occupied columns).
  const ranksPresent = [...new Set(rank.values())].sort((a, b) => a - b)
  const rankToIdx = new Map<number, number>()
  ranksPresent.forEach((r, i) => rankToIdx.set(r, i))
  const rankIndexOf = new Map<string, number>()
  rank.forEach((r, id) => rankIndexOf.set(id, rankToIdx.get(r)!))
  const SEED_RANK = 0 // effectiveSeed is always ranked 0
  const seedColIdx = rankToIdx.get(SEED_RANK)!

  const byRank = new Map<number, N[]>()
  for (const n of uniq) pushMap(byRank, rank.get(n.id)!, n)

  // ══ Phase 3: initial within-rank order (BFS discovery / order hint) ═══════
  const hint = opts.orderHint
  const order = new Map<number, string[]>()
  byRank.forEach((members, r) => {
    const sorted = [...members].sort((a, b) => {
      if (hint) {
        const ha = finiteOr(hint(a), 0)
        const hb = finiteOr(hint(b), 0)
        if (ha !== hb) return ha - hb
      } else {
        const da = discovery.get(a.id) ?? Number.MAX_SAFE_INTEGER
        const db = discovery.get(b.id) ?? Number.MAX_SAFE_INTEGER
        if (da !== db) return da - db
      }
      return compareIds(a.id, b.id)
    })
    order.set(
      r,
      sorted.map(n => n.id),
    )
  })

  // ══ Phase 4: crossing reduction (barycenter sweeps, seed pinned) ══════════
  const posOf = new Map<string, number>()
  const rebuildPositions = () => {
    posOf.clear()
    order.forEach(list => list.forEach((id, i) => posOf.set(id, i)))
  }
  rebuildPositions()

  for (let sweep = 0; sweep < sweeps; sweep++) {
    const downward = sweep % 2 === 0
    const seq = downward ? ranksPresent : [...ranksPresent].reverse()
    for (const r of seq) {
      const rIdx = rankToIdx.get(r)!
      const wantIdx = downward ? rIdx - 1 : rIdx + 1
      const list = order.get(r)!

      const barycenter = new Map<string, number>()
      for (const id of list) {
        if (id === effectiveSeed) continue // pinned — excluded from sorting
        let sum = 0
        let cnt = 0
        const nbrs = downward ? inAdj.get(id) : outAdj.get(id)
        if (nbrs) {
          for (const nb of nbrs) {
            if (rankIndexOf.get(nb) !== wantIdx) continue
            const p = posOf.get(nb)
            if (p === undefined) continue
            sum += p
            cnt++
          }
        }
        // Nodes without neighbours in the adjacent rank keep their slot.
        barycenter.set(id, cnt ? sum / cnt : posOf.get(id)!)
      }

      const seedIdx = list.indexOf(effectiveSeed)
      const sortable = list.filter(id => id !== effectiveSeed)
      sortable.sort((a, b) => barycenter.get(a)! - barycenter.get(b)! || compareIds(a, b))
      if (seedIdx >= 0) sortable.splice(Math.min(seedIdx, sortable.length), 0, effectiveSeed)
      order.set(r, sortable)
    }
    rebuildPositions()
  }

  // ══ Phase 5: coordinates ══════════════════════════════════════════════════
  // X: one column per compacted rank, centred on the seed's column. Spacing
  // widens beyond rankGap when large radii + label clearance demand it.
  const rankMaxRadius = new Map<number, number>()
  order.forEach((list, r) => {
    let mx = 0
    for (const id of list) mx = Math.max(mx, radiusOf.get(id)!)
    rankMaxRadius.set(r, mx)
  })

  const xOfRank = new Map<number, number>()
  xOfRank.set(SEED_RANK, centerX)
  for (let i = seedColIdx + 1; i < ranksPresent.length; i++) {
    const prev = ranksPresent[i - 1]
    const cur = ranksPresent[i]
    const gap = Math.max(rankGap, rankMaxRadius.get(prev)! + rankMaxRadius.get(cur)! + edgeLabelClearance)
    xOfRank.set(cur, xOfRank.get(prev)! + gap)
  }
  for (let i = seedColIdx - 1; i >= 0; i--) {
    const next = ranksPresent[i + 1]
    const cur = ranksPresent[i]
    const gap = Math.max(rankGap, rankMaxRadius.get(cur)! + rankMaxRadius.get(next)! + edgeLabelClearance)
    xOfRank.set(cur, xOfRank.get(next)! - gap)
  }

  // Y: within each rank, walk down accumulating per-pair gaps so large nodes
  // never overlap; centre the rank on the seed's y (the seed itself is pinned
  // exactly to centerY).
  order.forEach((list, r) => {
    const x = xOfRank.get(r)!
    if (!list.length) return
    const offsets: number[] = [0]
    for (let i = 1; i < list.length; i++) {
      const ra = radiusOf.get(list[i - 1])!
      const rb = radiusOf.get(list[i])!
      offsets.push(offsets[i - 1] + Math.max(nodeGap, ra + rb + nodeMargin))
    }
    const total = offsets[offsets.length - 1]
    let base: number
    if (r === SEED_RANK) {
      const sIdx = list.indexOf(effectiveSeed)
      base = sIdx >= 0 ? centerY - offsets[sIdx] : centerY - total / 2
    } else {
      base = centerY - total / 2
    }
    for (let i = 0; i < list.length; i++) {
      out.set(list[i], { x, y: base + offsets[i] })
    }
  })

  return out
}

/**
 * Re-layout an induced subgraph — used when a SubgraphWorkspace is isolated
 * (e.g. the user isolates a traced path or a set of selected transactions).
 *
 * Behaves exactly like {@link computeFlowLayout} on the subset, with two
 * subgraph-aware twists:
 *   · If `seed` is not part of the subset, a deterministic substitute seed
 *     (highest in-subgraph degree, ties by id) anchors the flow.
 *   · The current `positions` seed the initial within-rank ordering (via
 *     `orderHint`), so the isolated view preserves the vertical arrangement
 *     the user was looking at. An explicit `opts.orderHint` is overridden by
 *     this behaviour on purpose.
 *
 * @param positions  Current node coordinates (used only as an ordering hint;
 *                   entries may be missing — those nodes sort by id).
 * @param nodes      Full node list; only ids in `subsetIds` are laid out.
 * @param edges      Full edge list; only edges with both endpoints inside the
 *                   subset participate.
 * @param seed       Preferred seed/subject node id.
 * @param subsetIds  Ids to include (any iterable, e.g. `SubgraphWorkspace.ids`).
 * @param W          Viewport width (px).
 * @param H          Viewport height (px).
 * @param opts       Same tunables as {@link computeFlowLayout}.
 * @returns          Coordinates for exactly the subset ids (empty Map for an
 *                   empty subset).
 */
export function relayoutSubset<N extends FlowNodeLike>(
  positions: ReadonlyMap<string, FlowPoint>,
  nodes: readonly N[],
  edges: readonly FlowEdgeLike[],
  seed: string,
  subsetIds: Iterable<string>,
  W: number,
  H: number,
  opts: FlowLayoutOptions<N> = {},
): FlowLayoutResult {
  const idSet = new Set(subsetIds)
  const subNodes = nodes.filter(n => idSet.has(n.id))
  if (!subNodes.length) return new Map()
  const subEdges = edges.filter(e => idSet.has(e.source) && idSet.has(e.target))
  const effectiveSeed = idSet.has(seed) ? seed : pickFallbackSeed(subNodes, subEdges)
  return computeFlowLayout(subNodes, subEdges, effectiveSeed, W, H, {
    ...opts,
    orderHint: n => positions.get(n.id)?.y ?? 0,
  })
}
