/**
 * subgraph.ts — pure model layer for the Nexus Graph "Subgraph" (isolate) feature.
 *
 * This module is intentionally free of React, d3, and DOM dependencies so it can
 * be unit-tested and reused by the page, exporters, and future workers.
 *
 * ── Why it exists ────────────────────────────────────────────────────────────
 * The legacy implementation in `frontend/src/pages/NexusGraph.tsx` only supports
 * isolating a *node set* (`SubgraphWorkspace { ids, title, note }`, ~line 1104).
 * It cannot isolate selected transactions / edge bundles, recompute layout for
 * the isolated subset, or restore the previous camera on return. This module
 * provides the data model for the fixed feature:
 *
 *   1. `buildSubgraph(graph, selection)` — core selector. Select by node ids,
 *      by directed edge pair keys (`'source|target'`, e.g. a transaction
 *      bundle), or both; always returns nodes + edges + correlations + stats.
 *   2. `subgraphFromBundles(graph, bundles)` — isolate one or more selected
 *      transaction bundles ("Isolate these flows").
 *   3. `subgraphFromPath(graph, path)` — isolate a marked BFS path.
 *   4. `toSubgraphWorkspace(result, meta)` — produce a `SubgraphWorkspace`-
 *      compatible object the existing page state can hold directly.
 *   5. `toNexusGraphResult(graph, result)` — narrow a full graph to the
 *      subgraph for re-layout (pass `.nodes`/`.edges` to the flow layout) and
 *      for export (`exportSubgraphJSON` replacement).
 *
 * ── Integrator contract (NexusGraph.tsx) ─────────────────────────────────────
 * - Keep page state as `SubgraphWorkspace | null`, but build it via
 *   `toSubgraphWorkspace(...)`. The model adds an OPTIONAL `edgeKeys` field;
 *   a `SubgraphWorkspaceModel` is structurally assignable to the legacy
 *   `{ ids: Set<string>; title: string; note: string }` shape.
 * - When `workspace.edgeKeys` is present and non-empty, the visible tx edges
 *   are the subgraph edges (directed pair match), NOT "all edges among ids".
 * - Use `result.nodes` / `result.edges` to re-run the flow layout on the
 *   isolated subset before fitting the camera (see docs/nexus-graph-revamp/
 *   subgraph-fix-plan.md for the animated dim → re-layout → fit sequence).
 * - `stats.volume` is FLOW volume (Σ selected edge values). `stats.nodeVolume`
 *   is the legacy node-volume sum kept for parity with the old stats panel.
 */

import type {
  NexusCorrelation,
  NexusEdge,
  NexusGraphResult,
  NexusNode,
} from '../../types'

// ── Constants ────────────────────────────────────────────────────────────────

/**
 * Minimum `bridge_score` at which a node is counted as a bridge wallet.
 * Matches the legacy stats memo in NexusGraph.tsx (`bridge_score >= 5`).
 */
export const BRIDGE_SCORE_THRESHOLD = 5

// ── Key helpers ──────────────────────────────────────────────────────────────

/**
 * Directed pair key for a wallet→wallet link, identical to the `edgePairKey`
 * helper local to NexusGraph.tsx (line ~99): `${source}|${target}`.
 *
 * Tx bundles produced by `bundleTxEdges()` use this exact key format, so a
 * selected bundle's `key` can be passed straight into `buildSubgraph` via
 * `selection.edgeKeys` (in 'bundled' edge mode) — for 'detail' mode strip the
 * `|hash` suffix or use the bundle's `source`/`target` fields.
 */
export function edgePairKey(source: string, target: string): string {
  return `${source}|${target}`
}

// ── Types ────────────────────────────────────────────────────────────────────

/**
 * Selection input for {@link buildSubgraph}.
 *
 * - `nodeIds` — restrict to these nodes (unknown ids are ignored). When given,
 *   only edges whose BOTH endpoints are in the set survive.
 * - `edgeKeys` — restrict to tx edges whose DIRECTED pair key
 *   (`edgePairKey(source, target)`) is listed. For undirected matching, pass
 *   both directions (see {@link subgraphFromPath}, which does this for you).
 * - `includeCorrelations` — include behavioral correlation links between
 *   member nodes (default `true`, matching legacy subgraph stats/export).
 *
 * When only `edgeKeys` is given, member nodes are inferred as the union of
 * the surviving edges' endpoints. When neither is given the result is empty
 * (check with {@link subgraphIsEmpty}) — callers should treat that as
 * "nothing to isolate" and keep the full graph.
 */
export interface SubgraphSelection {
  nodeIds?: Iterable<string>
  edgeKeys?: Iterable<string>
  includeCorrelations?: boolean
}

/** Aggregate metrics for a built subgraph. */
export interface SubgraphStats {
  /** Number of member nodes. */
  nodeCount: number
  /** Number of member transaction edges ("flows" in the UI). */
  flowCount: number
  /** Number of member behavioral correlations ("links" in the UI). */
  linkCount: number
  /** Σ `value` over the selected edges — actual flow volume in the subgraph. */
  volume: number
  /** Σ `total_volume` over member nodes (legacy panel metric; double-counts
   *  internal flows, kept only for backward parity). */
  nodeVolume: number
  /** Highest `risk_score` among member nodes (0 when empty). */
  maxRisk: number
  /** Member nodes with `bridge_score >= BRIDGE_SCORE_THRESHOLD`. */
  bridgeCount: number
}

/** Result of building a subgraph: members, member links, and stats. */
export interface SubgraphResult {
  /** Member node ids. Feed to visibility filters (`visNodes`, `fitView`). */
  ids: Set<string>
  /** Directed pair keys of the surviving tx edges. Present so the renderer
   *  can highlight / export exactly the isolated flows. Empty only when the
   *  subgraph has no edges. NOTE: when the selection was node-only, this
   *  contains the keys of ALL edges among member nodes. */
  edgeKeys: Set<string>
  /** Member nodes (references into `graph.nodes`, no copies). */
  nodes: NexusNode[]
  /** Member transaction edges (references into `graph.edges`). */
  edges: NexusEdge[]
  /** Member correlations (empty when `includeCorrelations: false`). */
  correlations: NexusCorrelation[]
  stats: SubgraphStats
}

/** What kind of investigation slice a subgraph represents (drives titles). */
export type SubgraphKind =
  | 'neighborhood'
  | 'path'
  | 'flows'
  | 'trace'
  | 'custom'

/**
 * Drop-in replacement for the page-local
 * `type SubgraphWorkspace = { ids: Set<string>; title: string; note: string }`
 * (NexusGraph.tsx line ~50 / state line ~1104).
 *
 * `edgeKeys` is optional: when absent the page renders all edges among
 * member nodes (legacy behavior); when present the page should render only
 * edges whose directed pair key is listed.
 */
export interface SubgraphWorkspaceModel {
  ids: Set<string>
  title: string
  note: string
  /** Directed pair keys of isolated flows (present for 'flows'/'path' kinds). */
  edgeKeys?: Set<string>
  /** Provenance for breadcrumbs, notes, and analytics. */
  kind?: SubgraphKind
  /** Full model result, kept so the panel/export needn't recompute. */
  result?: SubgraphResult
}

// ── Core builder ─────────────────────────────────────────────────────────────

/**
 * Build a subgraph from a full Nexus graph and a selection.
 *
 * Pure: never mutates `graph`. Returns fresh `Set`s but reuses the graph's
 * node/edge/correlation object references (cheap; treat them as read-only).
 */
export function buildSubgraph(
  graph: NexusGraphResult,
  sel: SubgraphSelection,
): SubgraphResult {
  const includeCorrelations = sel.includeCorrelations !== false

  // Neither selector given → empty result (callers treat as "nothing to
  // isolate"). Never silently select the whole graph.
  if (sel.nodeIds == null && sel.edgeKeys == null) {
    return {
      ids: new Set(),
      edgeKeys: new Set(),
      nodes: [],
      edges: [],
      correlations: [],
      stats: { nodeCount: 0, flowCount: 0, linkCount: 0, volume: 0, nodeVolume: 0, maxRisk: 0, bridgeCount: 0 },
    }
  }

  const validId = new Set(graph.nodes.map(n => n.id))
  const nodeIds = sel.nodeIds
    ? new Set(Array.from(sel.nodeIds).filter(id => validId.has(id)))
    : null
  const edgeKeys = sel.edgeKeys ? new Set(sel.edgeKeys) : null

  const edges = graph.edges.filter(e => {
    if (nodeIds && (!nodeIds.has(e.source) || !nodeIds.has(e.target))) return false
    if (edgeKeys && !edgeKeys.has(edgePairKey(e.source, e.target))) return false
    return true
  })

  // Member ids: explicit node set, otherwise inferred from surviving edges.
  const ids = new Set<string>(nodeIds ?? [])
  if (!nodeIds) {
    edges.forEach(e => {
      ids.add(e.source)
      ids.add(e.target)
    })
  }

  const nodes = graph.nodes.filter(n => ids.has(n.id))
  const correlations = includeCorrelations
    ? graph.correlations.filter(c => ids.has(c.source) && ids.has(c.target))
    : []

  const resultEdgeKeys = new Set<string>()
  let volume = 0
  edges.forEach(e => {
    resultEdgeKeys.add(edgePairKey(e.source, e.target))
    volume += Number(e.value || 0)
  })

  let maxRisk = 0
  let nodeVolume = 0
  let bridgeCount = 0
  nodes.forEach(n => {
    if ((n.risk_score || 0) > maxRisk) maxRisk = n.risk_score || 0
    nodeVolume += Number(n.total_volume || 0)
    if ((n.bridge_score || 0) >= BRIDGE_SCORE_THRESHOLD) bridgeCount += 1
  })

  return {
    ids,
    edgeKeys: resultEdgeKeys,
    nodes,
    edges,
    correlations,
    stats: {
      nodeCount: nodes.length,
      flowCount: edges.length,
      linkCount: correlations.length,
      volume,
      nodeVolume,
      maxRisk,
      bridgeCount,
    },
  }
}

// ── Convenience constructors ─────────────────────────────────────────────────

/**
 * Isolate one or more selected transaction bundles ("Isolate these flows").
 *
 * `bundles` accepts anything shaped like `{ source, target }` — the page's
 * `TxBundle` type qualifies directly. Members are exactly the bundles'
 * endpoints; edges are exactly the tx edges matching the bundles' directed
 * pair keys (all individual transactions inside the bundles survive, because
 * they share the same pair key).
 *
 * @example
 *   const sub = subgraphFromBundles(graph, [selectedBundle])
 *   if (!subgraphIsEmpty(sub)) openSubgraphSession(sub, 'flows')
 */
export function subgraphFromBundles(
  graph: NexusGraphResult,
  bundles: Array<{ source: string; target: string }>,
  opts?: { includeCorrelations?: boolean },
): SubgraphResult {
  const edgeKeys = bundles.map(b => edgePairKey(b.source, b.target))
  return buildSubgraph(graph, { edgeKeys, includeCorrelations: opts?.includeCorrelations })
}

/**
 * Isolate a marked BFS path (as produced by `doFindPath` / `pathOrder`).
 *
 * - Members: the nodes on `path` (consecutive duplicates removed; ids not
 *   present in the graph are dropped).
 * - Edges: by default only the tx edges along consecutive path hops. Because
 *   real transaction direction along a hop can run either way, BOTH directed
 *   pair keys for each hop are matched. Pass `includeInternalEdges: true` to
 *   instead keep every edge among path members (e.g. shortcut edges between
 *   non-consecutive hops).
 *
 * A path of length < 2 still yields a valid single-node / empty subgraph;
 * check {@link subgraphIsEmpty} before opening a workspace.
 */
export function subgraphFromPath(
  graph: NexusGraphResult,
  path: string[],
  opts?: { includeInternalEdges?: boolean; includeCorrelations?: boolean },
): SubgraphResult {
  const validId = new Set(graph.nodes.map(n => n.id))
  const nodes: string[] = []
  path.forEach(id => {
    if (validId.has(id) && nodes[nodes.length - 1] !== id) nodes.push(id)
  })

  if (opts?.includeInternalEdges || nodes.length < 2) {
    return buildSubgraph(graph, {
      nodeIds: nodes,
      includeCorrelations: opts?.includeCorrelations,
    })
  }

  const edgeKeys: string[] = []
  for (let i = 0; i < nodes.length - 1; i++) {
    edgeKeys.push(edgePairKey(nodes[i], nodes[i + 1]))
    edgeKeys.push(edgePairKey(nodes[i + 1], nodes[i]))
  }
  return buildSubgraph(graph, {
    nodeIds: nodes,
    edgeKeys,
    includeCorrelations: opts?.includeCorrelations,
  })
}

// ── Workspace helpers ────────────────────────────────────────────────────────

/** True when a built subgraph has no member nodes (nothing to isolate). */
export function subgraphIsEmpty(result: SubgraphResult): boolean {
  return result.ids.size === 0
}

/**
 * Human-readable note line for the workspace banner / breadcrumb tooltip,
 * e.g. `12 nodes · 18 flows · 3 links`.
 */
export function subgraphNote(stats: SubgraphStats): string {
  return `${stats.nodeCount} nodes · ${stats.flowCount} flows · ${stats.linkCount} links`
}

/**
 * Default title for a subgraph kind, e.g. `Isolated flows · 2 bundles`.
 * The page may override with investigation-specific titles.
 */
export function subgraphTitle(
  kind: SubgraphKind,
  detail: string | number,
): string {
  const suffix = typeof detail === 'number' ? `${detail}` : detail
  switch (kind) {
    case 'neighborhood': return `Neighborhood · ${suffix}`
    case 'path': return `Path · ${suffix}`
    case 'flows': return `Isolated flows · ${suffix}`
    case 'trace': return `Trace expansion · ${suffix}`
    default: return `Subgraph · ${suffix}`
  }
}

/**
 * Convert a model result into a `SubgraphWorkspace`-compatible object for the
 * existing page state (`useState<SubgraphWorkspace | null>`).
 *
 * The returned object carries `edgeKeys` whenever the selection was
 * edge-restricted (flows/path), which the visibility filter uses to render
 * exactly the isolated flows instead of all intra-member edges.
 */
export function toSubgraphWorkspace(
  result: SubgraphResult,
  meta: { title: string; note?: string; kind?: SubgraphKind },
): SubgraphWorkspaceModel {
  return {
    ids: result.ids,
    title: meta.title,
    note: meta.note ?? subgraphNote(result.stats),
    edgeKeys: result.edgeKeys.size ? result.edgeKeys : undefined,
    kind: meta.kind,
    result,
  }
}

// ── Graph narrowing (re-layout & export) ─────────────────────────────────────

/**
 * Narrow a full `NexusGraphResult` down to the subgraph's members.
 *
 * Use the returned object's `nodes` / `edges` to re-run the flow layout on
 * the isolated subset (e.g. `computeFlowLayout(narrowed.nodes,
 * narrowed.edges, narrowed.seed, W, H)`), and the whole object as the payload
 * of the JSON export (replacing the inline filtering in
 * `exportSubgraphJSON`, NexusGraph.tsx lines ~698–722).
 *
 * Communities, bridge_wallets, pivot_queue, and paths_from_seed are filtered
 * to members; summary counts are recomputed.
 */
export function toNexusGraphResult(
  graph: NexusGraphResult,
  sub: SubgraphResult,
): NexusGraphResult {
  const communities = graph.communities
    .map(c => ({ ...c, members: c.members.filter(m => sub.ids.has(m)) }))
    .filter(c => c.members.length > 0)
    .map(c => ({ ...c, size: c.members.length }))

  return {
    ...graph,
    summary: {
      node_count: sub.stats.nodeCount,
      edge_count: sub.stats.flowCount,
      correlation_count: sub.stats.linkCount,
      community_count: communities.length,
      bridge_wallet_count: sub.stats.bridgeCount,
      highest_risk: sub.stats.maxRisk,
    },
    nodes: sub.nodes,
    edges: sub.edges,
    correlations: sub.correlations,
    communities,
    bridge_wallets: graph.bridge_wallets.filter(n => sub.ids.has(n.id)),
    pivot_queue: graph.pivot_queue.filter(n => sub.ids.has(n.id)),
    paths_from_seed: graph.paths_from_seed.filter(p =>
      p.path.every(id => sub.ids.has(id)),
    ),
  }
}
