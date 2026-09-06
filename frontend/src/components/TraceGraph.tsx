/**
 * TraceGraph — Elite fund-flow visualization for investigators.
 *
 * Rebuilt from the hierarchical hop-column renderer into a living force-directed
 * canvas. Designed for maximum investigative visibility:
 *
 *  • d3-force layout (link / charge / collide / radial-by-hop) with smooth settle
 *  • Chain logos on every node (ChainLogo from lib/chainGlyphs) — air-gap safe
 *  • Risk shown as a glow ring AROUND the logo (chain + risk visible at once)
 *  • Animated value particles along edges, colored by source chain
 *  • Relation emphasis: hover/click dims the rest of the graph, highlighting
 *    the selected node's connected subgraph or the seed→node fund path
 *  • Mini-map with live viewport rectangle (click-to-pan)
 *  • Smooth camera tweens (fitView / reset / zoom-to-node) via graphAnim
 *  • LOD: text + particle culling when zoomed out or graph is large
 *  • Layout toggle: Force / Flow / Radial — animated transitions
 *
 * Keeps the `Props { graph, patterns }` contract from the prior version so
 * FundTracer.tsx needs no change to swap in this component.
 */
import { useRef, useState, useMemo, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import {
  ZoomIn, ZoomOut, Maximize2, Minimize2, RotateCcw, Copy, ExternalLink,
  X, Shield, AlertTriangle, Info, Search, Download, Play, Pause, Crosshair,
  Share2, Network, GitBranch,
} from 'lucide-react'
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, forceX, forceY, type Simulation } from 'd3-force'
import { ChainLogo, ChainGlyph, brandColor, glyphKey } from '../lib/chainGlyphs'
import { GraphNodeKit } from '../lib/graphkit'
import { useTweenView, fitViewTransform, HOME_VIEW, useReducedMotion, easeInOutCubic, LAYOUT_MS } from '../lib/nexus/graphAnim'
import type { TraceGraph as GraphData, GraphNode, GraphEdge, TracePattern } from '../types'

// ── Layout constants ────────────────────────────────────────────────────────
const NODE_R = 26          // node circle radius (logo sits inside)
const COL_W = 360          // flow-layout column width
const V_GAP = 92           // flow-layout sibling gap
const PAD = 60
const LOD_TEXT_Z = 0.55    // below this zoom, hide text labels
const LOD_PARTICLE_NODES = 140  // above this node count, drop particle animations

// ── Risk styles ─────────────────────────────────────────────────────────────
// Risk is now rendered as a GLOW RING around the chain-logo node body, so the
// investigator sees BOTH the chain AND the risk simultaneously.
const RISK_GLOW: Record<string, { color: string; glow: boolean; label: string }> = {
  sanctioned:  { color: '#f0356b', glow: true,  label: 'Sanctioned'  },
  mixer:       { color: '#a855f7', glow: true,  label: 'Mixer'       },
  scam:        { color: '#f97316', glow: false, label: 'Scam'        },
  bridge_swap: { color: '#f59e0b', glow: false, label: 'Bridge/Swap' },
  entity:      { color: '#ff5a6e', glow: false, label: 'Entity'      },
  clean:       { color: '#22c55e', glow: false, label: 'Clean'       },
  error:       { color: '#475569', glow: false, label: 'Unknown'     },
}

function riskCfg(level: string) {
  return RISK_GLOW[level] ?? RISK_GLOW.error
}
function isHighRisk(level: string) {
  return level === 'sanctioned' || level === 'mixer'
}

// Coarse risk bucket from a numeric risk_score (backend may emit SANCTIONED/
// CRITICAL/HIGH/MEDIUM/LOW/CLEAN strings OR a 0-100 int).
function riskBucket(score: number, level: string): string {
  if (level === 'sanctioned' || score >= 90) return 'sanctioned'
  if (level === 'mixer' || score >= 75) return 'mixer'
  if (score >= 55) return 'scam'
  if (score >= 35) return 'bridge_swap'
  if (score >= 15) return 'entity'
  if (score > 0) return 'clean'
  return level || 'error'
}

// ── Position type for the force sim ─────────────────────────────────────────
interface SimNode extends GraphNode {
  x: number
  y: number
  vx?: number
  vy?: number
  fx?: number | null
  fy?: number | null
}
interface SimLink {
  source: string | SimNode
  target: string | SimNode
}

// ── Layouts ─────────────────────────────────────────────────────────────────
type LayoutKind = 'force' | 'flow' | 'radial'

function flowLayout(nodes: GraphNode[], edges: GraphEdge[], _seed: string): Map<string, { x: number; y: number }> {
  const byHop = new Map<number, GraphNode[]>()
  for (const n of nodes) {
    const h = n.hop ?? 0
    if (!byHop.has(h)) byHop.set(h, [])
    byHop.get(h)!.push(n)
  }
  // parents[id] = wallets that flow INTO it. Ordering each column by the mean
  // position of its parents keeps flows straight and minimizes edge crossings.
  const parents = new Map<string, string[]>()
  for (const e of edges) {
    if (!parents.has(e.target)) parents.set(e.target, [])
    parents.get(e.target)!.push(e.source)
  }
  const out = new Map<string, { x: number; y: number }>()
  const yOf = new Map<string, number>()
  const hops = [...byHop.keys()].sort((a, b) => a - b)
  hops.forEach((h, hi) => {
    let group = byHop.get(h)!
    if (hi > 0) {
      const bary = (n: GraphNode) => {
        const ys = (parents.get(n.id) || []).map(pp => yOf.get(pp)).filter((y): y is number => y != null)
        return ys.length ? ys.reduce((a, y) => a + y, 0) / ys.length : 1e9
      }
      group = group.slice().sort((a, b) => bary(a) - bary(b))
    }
    const cx = PAD + hi * COL_W
    const th = (group.length - 1) * V_GAP
    group.forEach((n, i) => {
      const y = -th / 2 + i * V_GAP
      out.set(n.id, { x: cx, y })
      yOf.set(n.id, y)
    })
  })
  return out
}

function radialLayout(nodes: GraphNode[], seed: string): Map<string, { x: number; y: number }> {
  const out = new Map<string, { x: number; y: number }>()
  const cx = 500, cy = 350
  const seedNode = nodes.find(n => n.id === seed || n.address === seed) || nodes[0]
  if (seedNode) out.set(seedNode.id, { x: cx, y: cy })
  const rest = nodes.filter(n => !(n.id === (seedNode?.id)))
  const maxHop = Math.max(1, ...nodes.map(n => n.hop ?? 1))
  rest.forEach((n, i) => {
    const ring = Math.max(1, n.hop ?? 1)
    const radius = 120 + (ring / maxHop) * 280
    const angle = (i / Math.max(1, rest.length)) * Math.PI * 2
    out.set(n.id, { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius })
  })
  return out
}

function fmtAmt(amount: number, token: string): string {
  if (!amount) return ''
  const v = amount >= 1000 ? amount.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
    : amount >= 1 ? amount.toFixed(4).replace(/\.?0+$/, '')
    : amount.toFixed(8).replace(/\.?0+$/, '')
  return token ? `${v} ${token}` : v
}

// ── Path-finding for "Highlight fund path" ──────────────────────────────────
function bfsPath(edges: GraphEdge[], seed: string, targetId: string): Set<string> {
  if (seed === targetId) return new Set([seed])
  const adj = new Map<string, string[]>()
  for (const e of edges) {
    if (!adj.has(e.source)) adj.set(e.source, [])
    adj.get(e.source)!.push(e.target)
  }
  const prev = new Map<string, string>()
  const seen = new Set<string>([seed])
  const queue: string[] = [seed]
  while (queue.length) {
    const cur = queue.shift()!
    if (cur === targetId) break
    for (const nxt of adj.get(cur) || []) {
      if (!seen.has(nxt)) {
        seen.add(nxt)
        prev.set(nxt, cur)
        queue.push(nxt)
      }
    }
  }
  const path = new Set<string>()
  let cur: string | undefined = targetId
  while (cur && cur !== seed) {
    path.add(cur)
    cur = prev.get(cur)
  }
  if (cur === seed || cur === undefined) path.add(seed)
  return path
}

function connectedSubgraph(edges: GraphEdge[], nodeId: string): Set<string> {
  const out = new Set<string>([nodeId])
  for (const e of edges) {
    if (e.source === nodeId) out.add(e.target)
    if (e.target === nodeId) out.add(e.source)
  }
  return out
}

// ── Sub-components ────────────────────────────────────────────────────────────
function ArrowDefs() {
  return (
    <defs>
      <filter id="tg-glow-red" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="4" result="blur" />
        <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
      <filter id="tg-glow-purple" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="4" result="blur" />
        <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
      <filter id="tg-glow-soft" x="-30%" y="-30%" width="160%" height="160%">
        <feGaussianBlur stdDeviation="2" result="blur" />
        <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
      <radialGradient id="tg-seed-grad" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stopColor="#ff5a6e" stopOpacity="0.3" />
        <stop offset="100%" stopColor="#ff5a6e" stopOpacity="0" />
      </radialGradient>
    </defs>
  )
}

interface NodeElProps {
  n: SimNode
  selected: boolean
  dimmed: boolean        // outside the current emphasis set
  highlighted: boolean   // search match
  inPath: boolean        // part of the highlighted fund path
  lod: { showText: boolean; showParticles: boolean }
  onSelect: (n: SimNode) => void
  onHover: (n: SimNode, e: React.MouseEvent) => void
  onLeave: () => void
  onDragStart: (n: SimNode, e: React.MouseEvent) => void
}

function NodeEl({ n, selected, dimmed, highlighted, inPath, lod, onSelect, onHover, onLeave, onDragStart }: NodeElProps) {
  const isSeed = n.hop === 0
  const opacity = dimmed ? 0.18 : 1

  return (
    <g
      className="tg-node"
      transform={`translate(${n.x},${n.y})`}
      style={{ cursor: 'pointer', opacity, transition: 'opacity 320ms ease' }}
      onClick={(e) => { e.stopPropagation(); onSelect(n) }}
      onMouseEnter={(e) => onHover(n, e)}
      onMouseLeave={onLeave}
      onMouseDown={(e) => onDragStart(n, e)}
      role="button"
      aria-label={n.address}
    >
      <title>{`${n.address}${n.entity ? '  ·  ' + n.entity : ''}  ·  risk ${n.risk_score}  ·  hop ${n.hop}`}</title>

      {/* Seed accent glow (kept — the kit's seedColor ring complements it) */}
      {isSeed && (
        <circle r={NODE_R + 16} fill="url(#tg-seed-grad)" />
      )}

      {/* ── GraphNodeKit body ──
          Type-aware shape (mixer hexagon, exchange shield, bridge diamond, etc.)
          + unified risk-arc ring + chain glyph + type badge + hop + risk chip.
          Replaces the old ChainLogo-disc + RISK_GLOW ring so entity TYPE is now
          visible at a glance, and the risk palette is consistent with NexusGraph. */}
      <GraphNodeKit
        r={NODE_R}
        entity={{ roleHint: n.entity, riskLabels: n.risk_labels, isSuspicious: n.is_suspicious, chain: n.chain }}
        riskScore={n.risk_score}
        riskLevel={n.risk_level as string}
        sanctioned={n.risk_labels?.some(l => /sanction|ofac/i.test(l))}
        chain={n.chain}
        label={lod.showText ? (n.entity || n.short_address) : undefined}
        hop={n.hop}
        isSeed={isSeed}
        selected={selected}
        hovered={highlighted}
        dimmed={dimmed}
        onPath={inPath}
        showLabel={lod.showText}
        showTypeBadge={lod.showText}
        seedColor="#5e9eff"
      />
    </g>
  )
}

interface EdgeElProps {
  edge: GraphEdge
  sNode: SimNode
  tNode: SimNode
  dimmed: boolean
  inPath: boolean
  showParticles: boolean
  showLabel: boolean
  onEdgeClick: (edge: GraphEdge) => void
}

function EdgeEl({ edge, sNode, tNode, dimmed, inPath, showParticles, showLabel, onEdgeClick }: EdgeElProps) {
  // Cubic bezier between node centers (offset by radius so it starts at the rim).
  const dx = tNode.x - sNode.x
  const dy = tNode.y - sNode.y
  const dist = Math.hypot(dx, dy) || 1
  const ux = dx / dist, uy = dy / dist
  const sx = sNode.x + ux * NODE_R, sy = sNode.y + uy * NODE_R
  const tx = tNode.x - ux * NODE_R, ty = tNode.y - uy * NODE_R
  const mx = (sx + tx) / 2, my = (sy + ty) / 2
  // Curve perpendicular offset for a gentle arc.
  const cx = mx - uy * Math.min(40, dist * 0.15)
  const cy = my + ux * Math.min(40, dist * 0.15)
  const pathD = `M ${sx} ${sy} Q ${cx} ${cy} ${tx} ${ty}`

  const srcBucket = riskBucket(sNode.risk_score, sNode.risk_level as string)
  const color = brandColor(sNode.chain, riskCfg(srcBucket).color)
  const label = fmtAmt(edge.amount, edge.token)
  const highRisk = isHighRisk(srcBucket)
  const flowDur = highRisk ? '1.2s' : edge.amount > 10 ? '1.5s' : '2.5s'
  const opacity = dimmed ? 0.06 : inPath ? 0.95 : highRisk ? 0.7 : 0.4

  return (
    <g onClick={() => onEdgeClick(edge)} style={{ cursor: 'pointer', opacity, transition: 'opacity 320ms ease' }}>
      {/* Invisible wide hit-area */}
      <path d={pathD} stroke="transparent" strokeWidth={12} fill="none" />

      {/* Edge line — CSS dash flow (no SMIL, so React never hits the
          "removeChild is not a child" crash when edges mount/unmount). */}
      <path
        id={`tg-edge-${edge.source}-${edge.target}`}
        d={pathD}
        stroke={color}
        strokeWidth={inPath ? 3 : highRisk ? 2.2 : 1.3}
        fill="none"
        strokeDasharray={inPath ? '10 4' : showParticles ? '7 7' : undefined}
        style={showParticles ? { animation: `tg-dash ${flowDur} linear infinite` } : undefined}
        markerEnd={`url(#tg-arr-${srcBucket})`}
      />

      {/* Cinematic value "comet" flowing source → target via CSS offset-path. */}
      {showParticles && (
        <circle
          r={inPath ? 4.5 : highRisk ? 3.6 : 2.6}
          fill="#ffffff"
          stroke={color}
          strokeWidth={inPath ? 6 : 3.5}
          strokeOpacity={0.45}
          style={{ offsetPath: `path("${pathD}")`, offsetRotate: '0deg', animation: `tg-comet ${flowDur} linear infinite` } as any}
        />
      )}

      {/* Amount label with token glyph (LOD-gated for performance) */}
      {label && showLabel && (
        <g transform={`translate(${cx},${cy})`} pointerEvents="none">
          <rect x={-((label.length * 4.6) + 14)} y={-9} width={(label.length * 4.6) + 28} height={18}
            fill="#0a0608" stroke={color} strokeWidth={0.5} rx={4} opacity={0.92} />
          {edge.token && (
            <g transform="translate(-((label.length * 4.6) + 8), 0)">
              <ChainGlyph chain={edge.token} r={6} color={color} />
            </g>
          )}
          <text x={2} y={4} textAnchor="middle" fill={color} fontSize={8.5}
            fontFamily="monospace" fontWeight={600}>{label.slice(0, 18)}</text>
        </g>
      )}
    </g>
  )
}

// ── Node detail panel ────────────────────────────────────────────────────────
function NodePanel({ node, patterns, onClose, onHighlightPath, seed }: {
  node: SimNode
  patterns: TracePattern[]
  onClose: () => void
  onHighlightPath: (targetId: string) => void
  seed: string
}) {
  const bucket = riskBucket(node.risk_score, node.risk_level as string)
  const cfg = riskCfg(bucket)
  const [copied, setCopied] = useState(false)
  const nodePatterns = patterns.filter(p => p.node_id === node.id || p.address === node.address)

  function copy(text: string) {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const riskBg = { backgroundColor: `${cfg.color}14`, borderColor: `${cfg.color}44` }

  return (
    <div className="absolute top-0 right-0 h-full w-80 flex flex-col z-30 shadow-2xl overflow-y-auto text-sm"
      style={{ background: 'rgba(4,13,26,0.98)', borderLeft: '1px solid #160a0e', backdropFilter: 'blur(8px)' }}>
      {/* Header with chain logo */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-bg-border shrink-0">
        <div className="flex items-center gap-2">
          <ChainLogo chain={node.chain} size={22} />
          <span className="text-display text-[11px] font-bold tracking-widest text-text-bright">Wallet Details</span>
        </div>
        <button onClick={onClose} className="text-text-muted hover:text-neon-cyan transition-colors"><X size={15} /></button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Risk level */}
        <div className="flex items-center justify-between rounded-lg px-3 py-2 border" style={riskBg}>
          <span className="text-[10px] text-text-muted uppercase tracking-widest font-bold text-tech">Risk Level</span>
          <span className="text-display text-xs font-bold" style={{ color: cfg.color, textShadow: `0 0 8px ${cfg.color}88` }}>
            {cfg.label.toUpperCase()}
          </span>
        </div>

        {/* Risk score gauge */}
        {node.risk_score > 0 && (
          <div className="flex items-center gap-3 bg-bg-surface rounded-lg px-3 py-2 border border-bg-border">
            <div className="text-display text-2xl font-bold" style={{ color: cfg.color, textShadow: `0 0 12px ${cfg.color}66` }}>
              {node.risk_score}
            </div>
            <div className="text-[11px] text-text-muted text-tech">Risk Score<br /><span className="text-text-dim">/ 100</span></div>
          </div>
        )}

        {/* Address */}
        <div>
          <p className="field-label">Address</p>
          <div className="flex items-start gap-2 bg-bg-surface rounded-lg p-2 border border-bg-border">
            <span className="text-tech text-[11px] text-neon-cyan break-all flex-1 select-all">{node.address}</span>
            <button onClick={() => copy(node.address)} className="shrink-0 text-text-muted hover:text-neon-cyan transition-colors"><Copy size={12} /></button>
          </div>
          {copied && <p className="text-[11px] mt-1" style={{ color: '#34D399' }}>Copied!</p>}
        </div>

        {/* Chain + Hop */}
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-bg-surface border border-bg-border rounded-lg p-2.5 text-center">
            <p className="field-label">Chain</p>
            <div className="flex items-center justify-center gap-1.5">
              <ChainLogo chain={node.chain} size={16} />
              <span className="text-text-bright text-tech text-sm font-bold uppercase">{node.chain}</span>
            </div>
          </div>
          <div className="bg-bg-surface border border-bg-border rounded-lg p-2.5 text-center">
            <p className="field-label">Hop</p>
            <p className="text-text-bright text-tech text-sm font-bold">{node.hop}</p>
          </div>
        </div>

        {/* Balance + Txs + inflow/outflow (deep-analysis enriched) */}
        <div className="grid grid-cols-2 gap-2">
          {[
            ['Balance', `${node.balance?.toFixed(4) ?? '0'} ${node.balance_unit || ''}`],
            ['Transactions', node.tx_count ?? 0],
            ['Inflow', `${(node.inflow_value ?? 0).toFixed(2)}`],
            ['Outflow', `${(node.outflow_value ?? 0).toFixed(2)}`],
          ].map(([k, v]) => (
            <div key={k as string} className="bg-bg-surface border border-bg-border rounded-lg p-2.5">
              <p className="field-label">{k}</p>
              <p className="text-text-primary text-tech text-xs">{v}</p>
            </div>
          ))}
        </div>

        {/* First/last seen (deep-analysis enriched) */}
        {(node.first_seen || node.last_seen) ? (
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-bg-surface border border-bg-border rounded-lg p-2.5">
              <p className="field-label">First Seen</p>
              <p className="text-text-primary text-tech text-xs">{node.first_seen ? new Date(node.first_seen * 1000).toLocaleDateString() : '-'}</p>
            </div>
            <div className="bg-bg-surface border border-bg-border rounded-lg p-2.5">
              <p className="field-label">Last Seen</p>
              <p className="text-text-primary text-tech text-xs">{node.last_seen ? new Date(node.last_seen * 1000).toLocaleDateString() : '-'}</p>
            </div>
          </div>
        ) : null}

        {/* Entity */}
        {node.entity && (
          <div className="rounded-lg p-2.5 border border-neon-cyan/20 bg-neon-cyan/5">
            <p className="field-label">Entity Attribution</p>
            <p className="text-neon-cyan text-sm font-medium">{node.entity}</p>
          </div>
        )}

        {/* Risk labels */}
        {node.risk_labels && node.risk_labels.length > 0 && (
          <div>
            <p className="field-label">Risk Flags</p>
            <div className="flex flex-wrap gap-1.5">
              {node.risk_labels.map((lbl, i) => (
                <span key={i} className="badge text-[9px] px-1.5 py-0.5 rounded border"
                  style={{ color: cfg.color, background: `${cfg.color}14`, borderColor: `${cfg.color}44` }}>{lbl}</span>
              ))}
            </div>
          </div>
        )}

        {/* Related patterns (deep-analysis findings touching this node) */}
        {nodePatterns.length > 0 && (
          <div>
            <p className="field-label">Related Findings ({nodePatterns.length})</p>
            <div className="space-y-1.5">
              {nodePatterns.map((p, i) => (
                <div key={i} className="bg-bg-surface border border-bg-border/60 rounded px-2 py-1.5 text-[11px]">
                  <div className="flex items-center gap-2">
                    <span className="font-bold"
                      style={{ color: p.severity === 'CRITICAL' ? '#f0356b' : p.severity === 'HIGH' ? '#ef4444' : p.severity === 'MEDIUM' ? '#f59e0b' : '#64748b' }}>
                      {p.severity}
                    </span>
                    <span className="text-text-primary font-medium">{p.pattern.replace(/_/g, ' ')}</span>
                  </div>
                  {p.evidence && <p className="text-text-muted text-[10px] mt-0.5">{p.evidence}</p>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Suspicious indicator */}
        {node.is_suspicious && (
          <div className="flex items-center gap-2 border border-neon-red/30 bg-neon-red/8 rounded-lg px-3 py-2">
            <AlertTriangle size={13} style={{ color: '#F87171' }} className="shrink-0" />
            <span className="text-[11px] font-medium" style={{ color: '#F87171' }}>Flagged as suspicious</span>
          </div>
        )}

        {/* Actions */}
        <div className="space-y-2 pt-1 border-t border-bg-border">
          {/* Highlight fund path: trace seed → this node */}
          {node.id !== seed && (
            <button onClick={() => onHighlightPath(node.id)}
              className="flex items-center justify-between w-full px-3 py-2 bg-amber-500/8 hover:bg-amber-500/15 text-amber-400 rounded-lg text-xs font-medium transition-colors">
              <span>Highlight fund path (seed → here)</span>
              <Share2 size={12} />
            </button>
          )}
          <Link to={`/intel/${encodeURIComponent(node.address)}`}
            className="flex items-center justify-between w-full px-3 py-2 bg-neon-cyan/8 hover:bg-neon-cyan/15 text-neon-cyan rounded-lg text-xs font-medium transition-colors">
            <span>Full Address Intel</span><Shield size={12} />
          </Link>
          {node.explorer && (
            <a href={node.explorer} target="_blank" rel="noopener noreferrer"
              className="flex items-center justify-between w-full px-3 py-2 bg-bg-surface hover:bg-bg-elevated text-text-secondary rounded-lg text-xs font-medium transition-colors">
              <span>View on Explorer</span><ExternalLink size={12} />
            </a>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Legend ────────────────────────────────────────────────────────────────────
function Legend() {
  const items = Object.entries(RISK_GLOW)
  return (
    <div className="absolute bottom-3 left-3 flex flex-wrap gap-2 z-10 pointer-events-none">
      {items.map(([level, cfg]) => (
        <div key={level} className="flex items-center gap-1.5 rounded px-2 py-1 backdrop-blur-sm"
          style={{ background: 'rgba(4,13,26,0.85)', border: '1px solid #160a0e' }}>
          <div className="w-2.5 h-2.5 rounded-full shrink-0"
            style={{ backgroundColor: cfg.color, boxShadow: cfg.glow ? `0 0 5px ${cfg.color}` : undefined }} />
          <span className="text-[10px] text-text-muted font-medium text-tech">{cfg.label}</span>
        </div>
      ))}
    </div>
  )
}

// ── Tooltip ───────────────────────────────────────────────────────────────────
function Tooltip({ node, px, py }: { node: SimNode; px: number; py: number }) {
  const bucket = riskBucket(node.risk_score, node.risk_level as string)
  const cfg = riskCfg(bucket)
  return (
    <div className="fixed z-50 pointer-events-none rounded-lg px-3 py-2 shadow-xl text-xs"
      style={{ left: px + 16, top: py - 40, border: `1px solid ${cfg.color}55`,
               background: 'rgba(4,13,26,0.97)', backdropFilter: 'blur(8px)' }}>
      <div className="flex items-center gap-2 mb-1">
        <ChainLogo chain={node.chain} size={14} />
        <span className="text-display text-[11px] font-bold text-text-bright">{cfg.label}</span>
        {node.risk_score > 0 && <span className="text-tech text-[10px]" style={{ color: cfg.color }}>{node.risk_score}/100</span>}
      </div>
      <div className="text-tech text-text-secondary text-[11px]">{node.short_address}</div>
      {node.entity && <div className="text-neon-cyan text-[11px] italic">{node.entity}</div>}
      <div className="text-text-muted text-tech text-[10px] mt-0.5">
        {(node.balance ?? 0).toFixed(4)} {node.balance_unit}{node.tx_count ? ` · ${node.tx_count} txs` : ''}
      </div>
      <div className="text-text-dim text-[9px] mt-0.5">Click for full details</div>
    </div>
  )
}

// ── Mini-map ──────────────────────────────────────────────────────────────────
function MiniMap({ nodes, view, svgW, svgH, onPanTo }: {
  nodes: SimNode[]
  view: { x: number; y: number; z: number }
  svgW: number
  svgH: number
  onPanTo: (x: number, y: number) => void
}) {
  const MAP_W = 140, MAP_H = 90
  if (!nodes.length) return null
  const xs = nodes.map(n => n.x), ys = nodes.map(n => n.y)
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const spanX = Math.max(maxX - minX, 1), spanY = Math.max(maxY - minY, 1)
  const scaleX = MAP_W / spanX, scaleY = MAP_H / spanY
  const scale = Math.min(scaleX, scaleY)
  const toMapX = (x: number) => (x - minX) * scale
  const toMapY = (y: number) => (y - minY) * scale

  // Viewport rectangle in map coords (approx: viewport spans svgW/view.z screen px).
  const vpCx = (-view.x) / view.z, vpCy = (-view.y) / view.z
  const vpW = svgW / view.z, vpH = svgH / view.z
  const vpRectX = toMapX(vpCx), vpRectY = toMapY(vpCy)
  const vpRectW = vpW * scale, vpRectH = vpH * scale

  function handleClick(e: React.MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    const mx = e.clientX - rect.left, my = e.clientY - rect.top
    // Map coords → graph coords → target pan so that graph point centers.
    const gx = mx / scale + minX, gy = my / scale + minY
    onPanTo(gx, gy)
  }

  return (
    <div className="absolute bottom-3 right-3 z-20 rounded-lg overflow-hidden"
      style={{ background: 'rgba(4,13,26,0.9)', border: '1px solid #160a0e', backdropFilter: 'blur(6px)' }}>
      <svg width={MAP_W} height={MAP_H} onClick={handleClick} style={{ cursor: 'pointer' }}>
        {nodes.map(n => (
          <circle key={n.id} cx={toMapX(n.x)} cy={toMapY(n.y)} r={1.8}
            fill={riskBucket(n.risk_score, n.risk_level as string) === 'sanctioned' ? '#f0356b'
                : riskBucket(n.risk_score, n.risk_level as string) === 'mixer' ? '#a855f7'
                : '#64748b'} />
        ))}
        {/* Viewport rectangle */}
        <rect x={vpRectX} y={vpRectY} width={Math.max(4, vpRectW)} height={Math.max(4, vpRectH)}
          fill="none" stroke="#ffd60a" strokeWidth={1} opacity={0.7} />
      </svg>
      <p className="text-[8px] text-text-dim text-center pb-0.5 text-tech">MINI-MAP</p>
    </div>
  )
}

// ── PNG export (unchanged from prior version) ────────────────────────────────
async function exportTraceGraphPNG(svgEl: SVGSVGElement) {
  const cloned = svgEl.cloneNode(true) as SVGSVGElement
  cloned.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  const W = svgEl.clientWidth, H = svgEl.clientHeight
  cloned.setAttribute('width', String(W)); cloned.setAttribute('height', String(H))
  const svgData = new XMLSerializer().serializeToString(cloned)
  const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const img = new Image()
  img.onload = () => {
    const canvas = document.createElement('canvas')
    canvas.width = W * 2; canvas.height = H * 2
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = '#0a0608'; ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    const a = document.createElement('a')
    a.href = canvas.toDataURL('image/png')
    a.download = `trace-graph-${Date.now()}.png`
    a.click(); URL.revokeObjectURL(url)
  }
  img.src = url
}

// ── Main component ────────────────────────────────────────────────────────────
interface Props {
  graph: GraphData
  patterns: TracePattern[]
}

export default function TraceGraph({ graph, patterns }: Props) {
  const { t } = useTranslation()
  const rawNodes = graph.nodes as GraphNode[]
  // Guard against a d3-force crash: forceLink throws "node not found: <id>" if a
  // link references a node id that isn't in the node set. That can happen on
  // partial or terminal-node traces (e.g. an edge into the sanctioned seed whose
  // node was never fetched). Drop any edge whose endpoints aren't real nodes so
  // the graph renders instead of blanking the whole screen.
  const edges = useMemo(() => {
    const ids = new Set(rawNodes.map(n => n.id))
    return (graph.edges as GraphEdge[]).filter(e => ids.has(e.source) && ids.has(e.target))
  }, [graph.edges, rawNodes])
  const reducedMotion = useReducedMotion()

  // ── Force simulation ──
  const [layout, setLayout] = useState<LayoutKind>('flow')
  const [simNodes, setSimNodes] = useState<SimNode[]>([])
  const [, forceRender] = useState(0)
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const svgSizeRef = useRef({ w: 800, h: 600 })

  // Build sim nodes whenever graph data changes.
  useEffect(() => {
    if (!rawNodes.length) { setSimNodes([]); return }
    const seed = graph.seed
    const initial = layout === 'flow' ? flowLayout(rawNodes, edges, seed)
                  : layout === 'radial' ? radialLayout(rawNodes, seed)
                  : new Map<string, { x: number; y: number }>()
    const sn: SimNode[] = rawNodes.map((n, i) => {
      const pos = initial.get(n.id) ?? {
        x: 400 + Math.cos(i / Math.max(1, rawNodes.length) * Math.PI * 2) * 200,
        y: 300 + Math.sin(i / Math.max(1, rawNodes.length) * Math.PI * 2) * 200,
      }
      return { ...n, x: pos.x, y: pos.y, vx: 0, vy: 0 }
    })
    setSimNodes(sn)

    // (Re)build the d3 simulation.
    simRef.current?.stop()
    const w = svgSizeRef.current.w || 800, h = svgSizeRef.current.h || 600
    // Flow / radial are DETERMINISTIC layouts: hard-pin each node (fx/fy) so the
    // physics can never collapse them into an unreadable blob. Only 'force' runs
    // the free-floating simulation.
    if (layout !== 'force') {
      for (const n of sn) {
        const pos = initial.get(n.id)
        if (pos) { n.fx = pos.x; n.fy = pos.y; n.x = pos.x; n.y = pos.y }
      }
    }
    const sim = forceSimulation<SimNode>(sn)
      .force('link', forceLink<SimNode, SimLink>(edges.map(e => ({ source: e.source, target: e.target })))
        .id((d: any) => d.id).distance(layout === 'force' ? 120 : 60).strength(layout === 'force' ? 0.3 : 0))
      .force('collide', forceCollide<SimNode>().radius(NODE_R + 8))
      .alphaDecay(reducedMotion ? 1 : 0.03)
      .on('tick', () => forceRender(v => v + 1))
    if (layout === 'force') {
      sim.force('charge', forceManyBody().strength(-380))
        .force('center', forceCenter(w / 2, h / 2))
        .force('x', forceX(w / 2).strength(0.04))
        .force('y', forceY(h / 2).strength(0.04))
    } else {
      sim.alpha(0)   // static — positions come from the hard-pinned fx/fy
    }
    simRef.current = sim
    return () => { sim.stop() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawNodes, edges, graph.seed, layout, reducedMotion])

  // Track svg size for the simulation center + minimap.
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const update = () => {
      const r = el.getBoundingClientRect()
      svgSizeRef.current = { w: r.width, h: r.height }
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // ── Camera (pan/zoom) with smooth tweens ──
  const [view, setView] = useState({ x: 0, y: 0, z: 0.85 })
  const viewRef = useRef(view)
  viewRef.current = view
  const setViewDirect = useCallback((v: typeof view) => { viewRef.current = v; setView(v) }, [])
  const animateViewTo = useTweenView(() => viewRef.current, setViewDirect)

  const fitView = useCallback(() => {
    if (!simNodes.length) return
    const target = fitViewTransform(
      simNodes.map(n => ({ x: n.x, y: n.y })),
      svgSizeRef.current.w, svgSizeRef.current.h, 100,
    )
    if (target) animateViewTo(target)
  }, [simNodes, animateViewTo])

  // On first load of a NEW graph, center on the seed at a comfortable, STABLE
  // zoom — not fit-all. A 150-wallet flow layout is so tall that fit-all zooms
  // to near-invisible, which felt like the view "kept zooming out".
  const initialViewKey = useRef('')
  useEffect(() => {
    if (!simNodes.length || initialViewKey.current === graph.seed) return
    initialViewKey.current = graph.seed
    const seedNode = simNodes.find(n => n.id === graph.seed || n.address === graph.seed) || simNodes[0]
    const z = 0.8
    const t = setTimeout(() => setViewDirect({
      x: svgSizeRef.current.w * 0.3 - seedNode.x * z,
      y: svgSizeRef.current.h * 0.5 - seedNode.y * z,
      z,
    }), reducedMotion ? 0 : 150)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simNodes.length, graph.seed, reducedMotion])

  // Pan/zoom drag state.
  const dragRef = useRef<{ mode: 'pan' | 'node' | null; nx?: number; ny?: number; sx: number; sy: number; vx: number; vy: number; node?: SimNode }>({ mode: null, sx: 0, sy: 0, vx: 0, vy: 0 })

  function onCanvasDown(e: React.MouseEvent) {
    if ((e.target as Element).closest('.tg-node')) return
    dragRef.current = { mode: 'pan', sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y }
  }
  function onCanvasMove(e: React.MouseEvent) {
    const d = dragRef.current
    if (d.mode === 'pan') {
      setViewDirect({ ...viewRef.current, x: d.vx + (e.clientX - d.sx), y: d.vy + (e.clientY - d.sy) })
    } else if (d.mode === 'node' && d.node) {
      // Convert screen delta to graph coords.
      const gx = (e.clientX - d.sx) / viewRef.current.z
      const gy = (e.clientY - d.sy) / viewRef.current.z
      d.node.fx = (d.nx ?? 0) + gx
      d.node.fy = (d.ny ?? 0) + gy
      simRef.current?.alphaTarget(0.3).restart()
    }
  }
  function onCanvasUp() {
    if (dragRef.current.mode === 'node' && dragRef.current.node) {
      // Release the pin so physics can settle it.
      dragRef.current.node.fx = null
      dragRef.current.node.fy = null
      simRef.current?.alphaTarget(0).alpha(0.3).restart()
    }
    dragRef.current.mode = null
  }

  // Wheel zoom (centered on cursor).
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const fn = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const cx = e.clientX - r.left, cy = e.clientY - r.top
      const v = viewRef.current
      const newZ = Math.min(4, Math.max(0.15, v.z - e.deltaY * 0.0012))
      // Zoom toward cursor: keep the graph point under the cursor fixed.
      const gx = (cx - v.x) / v.z, gy = (cy - v.y) / v.z
      setViewDirect({ z: newZ, x: cx - gx * newZ, y: cy - gy * newZ })
    }
    el.addEventListener('wheel', fn, { passive: false })
    return () => el.removeEventListener('wheel', fn)
  }, [setViewDirect])

  // ── Selection / hover / emphasis ──
  const [selected, setSelected] = useState<SimNode | null>(null)
  const [hovered, setHovered] = useState<SimNode | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [highlightPath, setHighlightPath] = useState<Set<string> | null>(null)
  const [showParticles, setShowParticles] = useState(true)
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const [isolate, setIsolate] = useState(false)          // deep-dive: hide all but the highlighted path

  const searchMatches = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return new Set<string>()
    return new Set(rawNodes.filter(n =>
      n.address.toLowerCase().includes(q) ||
      (n.entity && n.entity.toLowerCase().includes(q)) ||
      (n.risk_labels && n.risk_labels.some(l => l.toLowerCase().includes(q)))
    ).map(n => n.id))
  }, [searchQuery, rawNodes])

  // Emphasis set: when a node is hovered or a path is highlighted, dim the rest.
  const emphasisSet = useMemo(() => {
    if (highlightPath) return highlightPath
    if (hovered) return connectedSubgraph(edges, hovered.id)
    return null
  }, [highlightPath, hovered, edges])

  // Isolate keeps only the highlighted/locked fund path (null = show all).
  const visibleIds = useMemo(() =>
    (isolate && emphasisSet ? new Set(emphasisSet) : null),
  [isolate, emphasisSet])

  // Frame the subset ONLY when Isolate or Full screen is toggled (not on hover),
  // so the camera never drifts / zooms out on its own.
  useEffect(() => {
    if (!isolate && !fullscreen) return
    const t = setTimeout(() => {
      const vis = isolate && emphasisSet ? simNodes.filter(n => emphasisSet.has(n.id)) : simNodes
      if (!vis.length) return
      const target = fitViewTransform(vis.map(n => ({ x: n.x, y: n.y })),
        svgSizeRef.current.w, svgSizeRef.current.h, fullscreen ? 140 : 90)
      if (target) animateViewTo(target)
    }, 130)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isolate, fullscreen])

  function highlightFundPath(targetId: string) {
    setHighlightPath(bfsPath(edges, graph.seed, targetId))
  }

  // Native browser fullscreen — a plain CSS fixed element was being clipped by an
  // ancestor containing-block (transform/backdrop-filter), so it never expanded.
  const toggleFullscreen = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    if (!document.fullscreenElement) el.requestFullscreen?.().catch(() => setFullscreen(true))
    else document.exitFullscreen?.()
  }, [])
  useEffect(() => {
    const onFs = () => setFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])

  // Clear path highlight on Escape.
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { if (document.fullscreenElement) { document.exitFullscreen?.(); return } if (fullscreen) { setFullscreen(false); return } setSelected(null); setHighlightPath(null); setSelectedEdge(null); setIsolate(false) }
    }
    window.addEventListener('keydown', fn)
    return () => window.removeEventListener('keydown', fn)
  }, [])

  // ── LOD (level of detail) ──
  const lod = useMemo(() => ({
    showText: view.z >= LOD_TEXT_Z && rawNodes.length <= 200,
    showParticles: showParticles && (visibleIds ? visibleIds.size : rawNodes.length) <= LOD_PARTICLE_NODES && view.z >= 0.3,
  }), [view.z, rawNodes.length, showParticles])

  // Node position lookup for edges.
  const nodeMap = useMemo(() => {
    const m = new Map<string, SimNode>()
    for (const n of simNodes) m.set(n.id, n)
    return m
  }, [simNodes])

  function startNodeDrag(n: SimNode, e: React.MouseEvent) {
    e.stopPropagation()
    dragRef.current = { mode: 'node', node: n, nx: n.x, ny: n.y, sx: e.clientX, sy: e.clientY, vx: 0, vy: 0 }
  }

  if (!rawNodes.length) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted text-sm">
        <Info size={14} className="mr-2" /> No graph nodes to display
      </div>
    )
  }

  const transform = `translate(${view.x},${view.y}) scale(${view.z})`
  const tbBtn = "p-1.5 rounded-lg text-text-secondary hover:text-neon-cyan transition-colors backdrop-blur-sm"
  const tbStyle = { background: 'rgba(4,13,26,0.85)', border: '1px solid #160a0e' }

  return (
    <div ref={containerRef} className={`relative overflow-hidden bg-bg-primary ${fullscreen ? 'fixed inset-0 z-[200] rounded-none' : 'w-full h-full rounded-xl'}`}
      style={{ border: '1px solid #160a0e' }}>
      {/* Toolbar */}
      <div className="absolute top-3 z-40 flex items-center gap-1.5 flex-wrap justify-end"
        style={{ right: selected ? 'calc(20rem + 0.75rem)' : '0.75rem', maxWidth: selected ? 'calc(100% - 21rem)' : undefined }}>
        {/* Search */}
        <div className="relative">
          <Search size={10} className="absolute left-2 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
          <input
            className="text-[10px] rounded-lg py-1 pl-5 pr-2 w-[130px] text-text-secondary"
            style={{ background: 'rgba(4,13,26,0.85)', border: '1px solid #160a0e', outline: 'none' }}
            placeholder="Find address/entity…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
          {searchMatches.size > 0 && (
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] text-neon-cyan font-mono">{searchMatches.size}</span>
          )}
        </div>

        {/* Layout switcher */}
        <div className="flex rounded-lg overflow-hidden" style={tbStyle}>
          {(['force', 'flow', 'radial'] as LayoutKind[]).map(l => (
            <button key={l} onClick={() => setLayout(l)}
              className={`px-2 py-1 text-[10px] font-medium capitalize transition-colors ${layout === l ? 'bg-neon-cyan/15 text-neon-cyan' : 'text-text-muted hover:text-text-primary'}`}>
              {l}
            </button>
          ))}
        </div>

        {/* Particle toggle */}
        <button onClick={() => setShowParticles(v => !v)} className={`${tbBtn} flex items-center gap-1 text-[10px] px-2`}
          style={{ ...tbStyle, color: showParticles ? '#ff5a6e' : undefined }} title="Toggle animated value particles">
          {showParticles ? <Pause size={10} /> : <Play size={10} />} Flow
        </button>

        {/* Zoom controls */}
        {[
          { onClick: () => setView(v => ({ ...v, z: Math.min(4, v.z + 0.15) })), icon: ZoomIn, title: 'Zoom in' },
          { onClick: () => setView(v => ({ ...v, z: Math.max(0.15, v.z - 0.15) })), icon: ZoomOut, title: 'Zoom out' },
          { onClick: fitView, icon: Maximize2, title: 'Fit to view' },
          { onClick: () => animateViewTo(HOME_VIEW), icon: RotateCcw, title: 'Reset view' },
        ].map(({ onClick, icon: Icon, title }) => (
          <button key={title} onClick={onClick} className={tbBtn} style={tbStyle} title={title}><Icon size={13} /></button>
        ))}

        {/* Isolate (deep-dive): hide everything except the selected wallet's fund
            path. If no path is highlighted yet, derive it from the selected node. */}
        <button onClick={() => {
            if (isolate) { setIsolate(false); return }
            let path = highlightPath
            if (!path && selected) { path = bfsPath(edges, graph.seed, selected.id); setHighlightPath(path) }
            if (!path) return   // nothing selected/highlighted — click a wallet first
            setIsolate(true)
          }}
          disabled={!isolate && !highlightPath && !selected}
          className={`${tbBtn} flex items-center gap-1 text-[10px] px-2 disabled:opacity-40`}
          style={{ ...tbStyle, color: isolate ? '#34D399' : undefined }}
          title={(highlightPath || selected)
            ? 'Isolate: show only the selected/highlighted fund path'
            : 'Click a wallet first, then Isolate to focus its fund path'}>
          <Crosshair size={11} /> Isolate
        </button>
        {/* Full screen */}
        <button onClick={toggleFullscreen} className={`${tbBtn} flex items-center gap-1 text-[10px] px-2`} style={tbStyle}
          title={fullscreen ? 'Exit full screen' : 'Full screen'}>
          {fullscreen ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
          <span>{fullscreen ? 'Exit' : 'Fullscreen'}</span>
        </button>
        <button onClick={() => svgRef.current && exportTraceGraphPNG(svgRef.current)}
          className={`${tbBtn} flex items-center gap-1 text-[10px] px-2`} style={tbStyle} title="Export PNG">
          <Download size={10} />PNG
        </button>
      </div>

      {/* Stats pill */}
      <div className="absolute top-3 left-3 z-10 flex items-center gap-3 rounded-lg px-3 py-1.5 text-[11px] text-text-muted text-tech backdrop-blur-sm" style={tbStyle}>
        <Network size={11} />
        <span>{rawNodes.length} wallets</span>
        <span className="text-text-dim">·</span>
        <span>{edges.length} transfers</span>
        {patterns.length > 0 && (<><span className="text-text-dim">·</span><span className="font-medium" style={{ color: '#ffd60a' }}>{patterns.length} findings</span></>)}
        {graph.stats?.suspicious_nodes ? (<><span className="text-text-dim">·</span><span className="font-medium" style={{ color: '#F87171' }}>{graph.stats.suspicious_nodes} flagged</span></>) : null}
      </div>

      {/* SVG canvas */}
      <svg
        ref={svgRef}
        className="w-full h-full"
        style={{ cursor: dragRef.current.mode === 'pan' ? 'grabbing' : 'grab' }}
        onMouseDown={onCanvasDown}
        onMouseMove={onCanvasMove}
        onMouseUp={onCanvasUp}
        onMouseLeave={onCanvasUp}
      >
        <ArrowDefs />
        {/* Arrow markers per risk bucket */}
        <defs>
          {Object.entries(RISK_GLOW).map(([bucket, cfg]) => (
            <marker key={bucket} id={`tg-arr-${bucket}`} markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto" markerUnits="strokeWidth">
              <path d="M0,0 L0,6 L8,3 z" fill={cfg.color} opacity="0.85" />
            </marker>
          ))}
          <pattern id="tg-grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(255,64,82,0.04)" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#tg-grid)" />

        <g transform={transform}>
          {/* Edges */}
          {edges.map((e, i) => {
            const s = nodeMap.get(e.source), t = nodeMap.get(e.target)
            if (!s || !t) return null
            if (visibleIds && (!visibleIds.has(e.source) || !visibleIds.has(e.target))) return null
            const inPath = highlightPath?.has(e.source) && highlightPath?.has(e.target)
            const dimmed = !!emphasisSet && !emphasisSet.has(e.source) && !emphasisSet.has(e.target)
            return (
              <EdgeEl key={`${e.source}|${e.target}|${e.hash || i}`} edge={e} sNode={s} tNode={t} dimmed={dimmed} inPath={!!inPath}
                showParticles={lod.showParticles}
                showLabel={lod.showText || !!inPath}
                onEdgeClick={edge => setSelectedEdge(sel => sel?.hash === edge.hash && sel?.source === edge.source ? null : edge)} />
            )
          })}

          {/* Nodes */}
          {simNodes.map(n => {
            if (visibleIds && !visibleIds.has(n.id)) return null
            const dimmed = !isolate && !!emphasisSet && !emphasisSet.has(n.id)
            return (
              <NodeEl key={n.id} n={n}
                selected={selected?.id === n.id}
                dimmed={dimmed}
                highlighted={searchMatches.has(n.id)}
                inPath={!!highlightPath?.has(n.id)}
                lod={lod}
                onSelect={(node) => setSelected(sel => sel?.id === node.id ? null : node)}
                onHover={(node, ev) => { setHovered(node); /* tooltip uses clientX/Y */ ; (node as any)._px = ev.clientX; (node as any)._py = ev.clientY }}
                onLeave={() => setHovered(null)}
                onDragStart={startNodeDrag}
              />
            )
          })}
        </g>
      </svg>

      <Legend />
      <MiniMap nodes={simNodes} view={view} svgW={svgSizeRef.current.w} svgH={svgSizeRef.current.h}
        onPanTo={(gx, gy) => {
          const v = viewRef.current
          setViewDirect({ ...v, x: svgSizeRef.current.w / 2 - gx * v.z, y: svgSizeRef.current.h / 2 - gy * v.z })
        }} />

      {/* Zoom indicator */}
      <div className="absolute bottom-3 right-44 z-10 text-[10px] text-tech text-text-dim rounded px-2 py-0.5"
        style={{ background: 'rgba(4,13,26,0.7)', border: '1px solid #160a0e' }}>
        {Math.round(view.z * 100)}%
      </div>

      {/* Node detail panel */}
      {selected && (
        <NodePanel node={selected} patterns={patterns}
          onClose={() => setSelected(null)}
          onHighlightPath={(id) => highlightFundPath(id)}
          seed={graph.seed} />
      )}

      {/* Edge detail chip */}
      {selectedEdge && !selected && (
        <div className="absolute bottom-12 left-3 z-20 rounded-lg px-3 py-2 text-xs max-w-[280px]"
          style={{ background: 'rgba(4,13,26,0.96)', border: '1px solid #160a0e', backdropFilter: 'blur(8px)' }}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-text-muted font-bold text-[10px] tracking-widest">TRANSFER</span>
            <button onClick={() => setSelectedEdge(null)} className="text-text-dim hover:text-neon-cyan"><X size={10} /></button>
          </div>
          <div className="flex items-center gap-2 mb-1">
            {selectedEdge.token && <ChainLogo chain={selectedEdge.token} size={16} />}
            <p className="font-mono text-[11px] text-neon-cyan break-all">{selectedEdge.hash ? `${selectedEdge.hash.slice(0, 20)}…` : 'No hash'}</p>
          </div>
          {selectedEdge.amount > 0 && <p className="text-text-primary text-[11px] font-mono">{fmtAmt(selectedEdge.amount, selectedEdge.token)}</p>}
          {selectedEdge.source_address && (
            <p className="text-text-dim text-[10px] mt-1 font-mono truncate">{selectedEdge.source_address.slice(0, 18)}… → {(selectedEdge.target_address || '').slice(0, 12)}…</p>
          )}
        </div>
      )}

      {/* Path-highlight banner */}
      {highlightPath && (
        <div className="absolute top-16 left-1/2 -translate-x-1/2 z-20 rounded-lg px-3 py-1.5 text-[11px] flex items-center gap-2"
          style={{ background: 'rgba(4,13,26,0.95)', border: '1px solid #ffd60a55', color: '#ffd60a', backdropFilter: 'blur(8px)' }}>
          <GitBranch size={12} />
          <span>Fund path highlighted ({highlightPath.size} wallets)</span>
          <button onClick={() => setHighlightPath(null)} className="ml-1 hover:text-white"><X size={11} /></button>
        </div>
      )}

      {/* Search match count */}
      {searchMatches.size > 0 && (
        <div className="absolute bottom-12 right-44 z-20 text-[10px] font-mono rounded px-2 py-1"
          style={{ background: 'rgba(4,13,26,0.85)', border: '1px solid #ffd60a55', color: '#ffd60a' }}>
          {searchMatches.size} match{searchMatches.size > 1 ? 'es' : ''}
        </div>
      )}

      {/* Hover tooltip */}
      {hovered && !selected && (
        <Tooltip node={hovered} px={(hovered as any)._px ?? 0} py={(hovered as any)._py ?? 0} />
      )}
    </div>
  )
}
