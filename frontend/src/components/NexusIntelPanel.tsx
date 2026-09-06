/**
 * NexusIntelPanel - Intelligence capabilities embedded inside the Nexus Graph page.
 * Receives graph data already built by Nexus, runs engines without JSON pasting.
 * Tabs: Wallet Clustering · Cashout Detection · Multi-Route Pathfinder · Cross-Chain
 */
import { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Users, AlertTriangle, BarChart2, Globe, Search,
  CheckCircle, Info, DollarSign, Link2, ArrowRight,
  Clock, Shield, Zap, Hash, ChevronDown, ChevronRight,
  RefreshCw, Play,
} from 'lucide-react'
import {
  analyzeCluster,
  detectCashout,
  findPaths,
  traceCrossChain,
} from '../api/client'
import type {
  NexusNode, NexusEdge,
  WalletCluster, CashoutIndicator,
  InvestigationPath, CrossChainResult, BridgeHop, ValueTimeMatch,
} from '../types'

// ── Shared helpers ────────────────────────────────────────────────────────────

function shortAddr(a: string) {
  return a && a.length > 16 ? `${a.slice(0, 6)}…${a.slice(-4)}` : (a || '')
}

function confColor(c: number) {
  if (c >= 75) return 'text-red-400'
  if (c >= 50) return 'text-yellow-400'
  return 'text-text-muted'
}

const SEV_COLOR: Record<string, string> = {
  high: 'text-red-400', medium: 'text-yellow-400', low: 'text-neon-green', critical: 'text-red-500',
}

const RISK_COLORS: Record<string, string> = {
  critical: 'text-red-400', high: 'text-orange-400', medium: 'text-yellow-400', low: 'text-neon-green',
}

const METHOD_LABELS: Record<string, string> = {
  gas_funder: 'Gas Funder', common_counterparty: 'Shared Counterparty',
  temporal_coordination: 'Temporal Coordination', same_value_pattern: 'Same-Value',
  common_deposit_address: 'Common Deposit', address_reuse: 'Address Reuse',
}

const STRATEGY_LABELS: Record<string, string> = {
  shortest: 'Shortest Path', highest_value: 'Highest Value', highest_risk: 'Highest Risk',
  most_recent: 'Most Recent', mixer_routed: 'Mixer-Routed', bridge_routed: 'Bridge-Routed',
}

const STRATEGY_ICON: Record<string, React.ElementType> = {
  shortest: Zap, highest_value: DollarSign, highest_risk: AlertTriangle,
  most_recent: Clock, mixer_routed: Shield, bridge_routed: Link2,
}

// ── Sub-renderers ─────────────────────────────────────────────────────────────

function ClusterCard({ cluster, idx }: { cluster: WalletCluster; idx: number }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-lg border border-bg-border bg-bg-elevated overflow-hidden">
      <button
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-bg-hover transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <span className="text-[10px] font-bold text-text-muted w-5">{idx + 1}</span>
        <Users size={14} className="text-neon-cyan shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-text-primary">
              {cluster.member_count} wallet{cluster.member_count !== 1 ? 's' : ''}
            </span>
            <span className="text-[10px] text-text-muted">lead: {shortAddr(cluster.lead_address)}</span>
            {cluster.methods.map(m => (
              <span key={m} className="px-1.5 py-0.5 rounded text-[9px] bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/20">
                {METHOD_LABELS[m] || m}
              </span>
            ))}
          </div>
        </div>
        <span className={`text-xs font-bold shrink-0 ${confColor(cluster.confidence)}`}>
          {cluster.confidence.toFixed(0)}%
        </span>
        {open ? <ChevronDown size={13} className="text-text-muted" /> : <ChevronRight size={13} className="text-text-muted" />}
      </button>
      {open && (
        <div className="border-t border-bg-border px-4 py-3 space-y-3">
          <div className="flex items-start gap-2 text-[11px] text-yellow-300">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            <span>{cluster.finding}</span>
          </div>
          <div>
            <div className="text-[10px] text-text-muted mb-1 uppercase tracking-wide">Members</div>
            <div className="flex flex-wrap gap-1.5">
              {cluster.members.map(m => (
                <span key={m} className="font-mono text-[10px] px-2 py-0.5 rounded bg-bg-primary border border-bg-border text-text-secondary" title={m}>
                  {shortAddr(m)}
                </span>
              ))}
            </div>
          </div>
          {cluster.evidence.length > 0 && (
            <ul className="space-y-1">
              {cluster.evidence.map((ev, i) => (
                <li key={i} className="flex items-start gap-1.5 text-[11px] text-text-secondary">
                  <CheckCircle size={10} className="text-neon-green mt-0.5 shrink-0" /> {ev}
                </li>
              ))}
            </ul>
          )}
          <div className="flex items-start gap-1.5 text-[10px] text-text-muted italic">
            <Info size={10} className="mt-0.5 shrink-0" /> {cluster.disclaimer}
          </div>
        </div>
      )}
    </div>
  )
}

function CashoutCard({ ind, idx }: { ind: CashoutIndicator; idx: number }) {
  return (
    <div className="rounded-lg border border-bg-border bg-bg-elevated px-4 py-3 flex items-start gap-3">
      <span className="text-[10px] font-bold text-text-muted w-5 mt-0.5">{idx + 1}</span>
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-semibold ${SEV_COLOR[ind.severity] || 'text-text-primary'}`}>
            {ind.type.replace(/_/g, ' ').toUpperCase()}
          </span>
          {ind.dest_label && <span className="text-[10px] text-text-muted">→ {ind.dest_label}</span>}
          {ind.total_value !== undefined && <span className="text-[10px] text-text-muted">{ind.total_value?.toFixed(4)}</span>}
          {ind.tx_count !== undefined && <span className="text-[10px] text-text-muted">{ind.tx_count} tx</span>}
        </div>
        <div className="text-[11px] text-text-secondary">{ind.description}</div>
      </div>
      <span className={`text-xs font-bold shrink-0 ${confColor(ind.confidence)}`}>{ind.confidence}%</span>
    </div>
  )
}

function PathCard({ path }: { path: InvestigationPath }) {
  const [open, setOpen] = useState(false)
  const Icon = STRATEGY_ICON[path.strategy] || Hash
  return (
    <div className="rounded-lg border border-bg-border bg-bg-elevated overflow-hidden">
      <button
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-bg-hover transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <Icon size={14} className="text-purple-400 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-text-primary">{STRATEGY_LABELS[path.strategy] || path.strategy}</span>
            <span className="text-[10px] text-text-muted">{path.hop_count} hop{path.hop_count !== 1 ? 's' : ''}</span>
            {path.destination.label && <span className="text-[10px] text-neon-cyan">→ {path.destination.label}</span>}
            {path.total_value > 0 && <span className="text-[10px] text-text-muted">{path.total_value.toFixed(4)}</span>}
          </div>
        </div>
        <span className={`text-xs font-bold shrink-0 ${confColor(path.confidence)}`}>{path.confidence}%</span>
        {open ? <ChevronDown size={13} className="text-text-muted" /> : <ChevronRight size={13} className="text-text-muted" />}
      </button>
      {open && (
        <div className="border-t border-bg-border px-4 py-3 space-y-2">
          <div className="flex flex-wrap gap-1.5 items-center text-[11px]">
            {path.path.map((addr, i) => (
              <span key={i} className="flex items-center gap-1">
                <span className="font-mono px-2 py-0.5 rounded bg-bg-primary border border-bg-border text-text-secondary text-[10px]" title={addr}>
                  {shortAddr(addr)}
                </span>
                {i < path.path.length - 1 && <span className="text-text-muted">→</span>}
              </span>
            ))}
          </div>
          {path.hops.length > 0 && (
            <table className="w-full text-[10px] text-text-muted">
              <thead>
                <tr className="border-b border-bg-border">
                  <th className="text-left py-1">From</th><th className="text-left py-1">To</th>
                  <th className="text-right py-1">Value</th><th className="text-left py-1">Token</th>
                </tr>
              </thead>
              <tbody>
                {path.hops.map((h, i) => (
                  <tr key={i} className="border-b border-bg-border/50">
                    <td className="py-1 font-mono">{shortAddr(h.from)}</td>
                    <td className="py-1 font-mono">{shortAddr(h.to)}</td>
                    <td className="py-1 text-right">{h.value.toFixed(4)}</td>
                    <td className="py-1">{h.token}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

function BridgeHopCard({ hop }: { hop: BridgeHop }) {
  return (
    <div className="rounded-lg border border-bg-border bg-bg-elevated px-4 py-3 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <Link2 size={13} className="text-orange-400 shrink-0" />
        <span className="text-xs font-semibold text-text-primary">{hop.bridge_name}</span>
        <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${
          hop.direction === 'outbound'
            ? 'bg-red-900/30 text-red-400 border border-red-700/30'
            : 'bg-neon-green/10 text-neon-green border border-neon-green/20'
        }`}>{hop.direction}</span>
        {hop.dest_chains.length > 0 && <span className="text-[10px] text-text-muted">→ {hop.dest_chains.slice(0, 4).join(', ')}</span>}
        <span className={`text-xs font-bold ml-auto ${confColor(hop.confidence)}`}>{hop.confidence}%</span>
      </div>
      <div className="text-[11px] text-text-secondary">{hop.description}</div>
      <div className="flex items-center gap-4 text-[10px] text-text-muted flex-wrap">
        <span>{hop.value.toFixed(4)} {hop.token.toUpperCase()}</span>
        {hop.tx_hash && <span className="font-mono">{hop.tx_hash.slice(0, 14)}…</span>}
        {hop.timestamp > 0 && <span>{new Date(hop.timestamp * 1000).toISOString().slice(0, 19).replace('T', ' ')} UTC</span>}
      </div>
    </div>
  )
}

function ValueMatchCard({ match }: { match: ValueTimeMatch }) {
  return (
    <div className="rounded-lg border border-bg-border bg-bg-elevated px-4 py-3 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <DollarSign size={13} className="text-yellow-400 shrink-0" />
        <span className="text-xs font-semibold text-text-primary">Value-Time Match</span>
        <span className={`text-xs font-bold ml-auto ${confColor(match.confidence)}`}>{match.confidence}%</span>
      </div>
      <div className="text-[11px] text-text-secondary">{match.description}</div>
      <div className="flex items-center gap-3 text-[10px] text-text-muted flex-wrap">
        <span className="font-mono">{shortAddr(match.out_address)}</span>
        <ArrowRight size={10} />
        <span className="font-mono">{shortAddr(match.in_address)}</span>
        <span>Δt={match.time_diff_sec.toFixed(0)}s</span>
        <span>Δv={match.value_diff_pct.toFixed(1)}%</span>
      </div>
    </div>
  )
}

function CollapsibleSection({ title, count, color, children }: {
  title: string; count: number; color?: string; children: React.ReactNode
}) {
  const [open, setOpen] = useState(true)
  if (count === 0) return null
  return (
    <div>
      <button onClick={() => setOpen(o => !o)} className="flex items-center gap-2 mb-2 w-full text-left">
        <span className={`text-sm font-semibold ${color || 'text-text-primary'}`}>{title}</span>
        <span className="text-[10px] text-text-muted">({count})</span>
        {open ? <ChevronDown size={13} className="text-text-muted" /> : <ChevronRight size={13} className="text-text-muted" />}
      </button>
      {open && <div className="space-y-2">{children}</div>}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

type IntelTab = 'cluster' | 'cashout' | 'paths' | 'crosschain'

interface Props {
  nodes:       NexusNode[]
  edges:       NexusEdge[]
  seedAddress: string
}

export default function NexusIntelPanel({ nodes, edges, seedAddress }: Props) {
  const { t } = useTranslation()
  const [tab, setTab]       = useState<IntelTab>('cluster')
  const [loading, setLoad]  = useState(false)
  const [error, setError]   = useState('')
  // Allow override of subject (default = seed)
  const [subject, setSubj]  = useState(seedAddress)

  // Cluster state
  const [clusters, setClusters]     = useState<WalletCluster[]>([])
  const [clusterSum, setClusterSum] = useState('')
  const [clusterDis, setClusterDis] = useState('')

  // Cashout state
  const [cashoutInds, setCashoutInds] = useState<CashoutIndicator[]>([])
  const [cashoutRisk, setCashoutRisk] = useState<{ level: string; score: number; summary: string } | null>(null)

  // Paths state
  const [paths, setPaths]       = useState<InvestigationPath[]>([])
  const [pathSummary, setPSum]  = useState('')

  // Cross-chain state
  const [xchain, setXchain]   = useState<CrossChainResult | null>(null)

  const runCluster = useCallback(async () => {
    setLoad(true); setError('')
    try {
      const res = await analyzeCluster({ nodes, edges })
      setClusters(res.clustering.clusters)
      setClusterSum(res.clustering.summary)
      setClusterDis(res.clustering.disclaimer)
    } catch (e) { setError(String(e)) }
    finally { setLoad(false) }
  }, [nodes, edges])

  const runCashout = useCallback(async () => {
    if (!subject.trim()) { setError('Subject wallet address required'); return }
    setLoad(true); setError('')
    try {
      const res = await detectCashout({ subject_id: subject.trim(), nodes, edges })
      setCashoutInds(res.cashout.indicators)
      setCashoutRisk(res.cashout.risk)
    } catch (e) { setError(String(e)) }
    finally { setLoad(false) }
  }, [subject, nodes, edges])

  const runPaths = useCallback(async () => {
    if (!subject.trim()) { setError('Source wallet address required'); return }
    setLoad(true); setError('')
    try {
      const res = await findPaths({ source_id: subject.trim(), nodes, edges })
      const p = res.paths
      setPaths(p.unique_paths)
      setPSum(`${p.path_count} path(s) to ${p.target_count} target(s) · max confidence ${p.max_confidence.toFixed(0)}%`)
    } catch (e) { setError(String(e)) }
    finally { setLoad(false) }
  }, [subject, nodes, edges])

  const runXchain = useCallback(async () => {
    if (!subject.trim()) { setError('Subject wallet address required'); return }
    setLoad(true); setError('')
    try {
      const res = await traceCrossChain({ subject_id: subject.trim(), nodes, edges })
      setXchain(res.crosschain)
    } catch (e) { setError(String(e)) }
    finally { setLoad(false) }
  }, [subject, nodes, edges])

  function handleRun() {
    if (tab === 'cluster')    return runCluster()
    if (tab === 'cashout')    return runCashout()
    if (tab === 'paths')      return runPaths()
    if (tab === 'crosschain') return runXchain()
  }

  const TABS: { id: IntelTab; label: string; icon: React.ElementType }[] = [
    { id: 'cluster',    label: 'Wallet Clustering',      icon: Users },
    { id: 'cashout',    label: 'Cashout Detection',      icon: AlertTriangle },
    { id: 'paths',      label: 'Multi-Route Pathfinder', icon: BarChart2 },
    { id: 'crosschain', label: 'Cross-Chain Trace',      icon: Globe },
  ]

  const needsSubject = tab !== 'cluster'
  const runLabel = tab === 'cluster' ? 'Run Clustering'
    : tab === 'cashout'    ? 'Detect Cashout'
    : tab === 'paths'      ? 'Find Paths'
    : 'Trace Cross-Chain'

  return (
    <div className="card space-y-4">
      {/* Panel header */}
      <div className="flex items-center gap-2">
        <Search size={14} className="text-text-muted" />
        <h3 className="card-title">Investigation Capabilities</h3>
        <span className="text-[10px] text-text-muted ml-auto">{nodes.length} nodes · {edges.length} flows from Nexus graph</span>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-bg-border flex-wrap">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => { setTab(id); setError('') }}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors -mb-px ${
              tab === id
                ? 'border-neon-cyan text-neon-cyan'
                : 'border-transparent text-text-secondary hover:text-text-primary'
            }`}
          >
            <Icon size={13} /> {label}
          </button>
        ))}
      </div>

      {/* Subject override (not needed for clustering) */}
      {needsSubject && (
        <div>
          <label className="block text-[11px] text-text-muted mb-1">
            {tab === 'paths' ? 'Source wallet' : 'Subject wallet'}
            <span className="ml-2 text-text-dim text-[10px]">(defaults to graph seed)</span>
          </label>
          <input
            className="input w-full font-mono text-xs"
            value={subject}
            onChange={e => setSubj(e.target.value)}
            placeholder={seedAddress || '0x…'}
          />
        </div>
      )}

      {/* Run button + error */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleRun}
          disabled={loading}
          className="btn-primary px-5 py-2 text-xs flex items-center gap-2"
        >
          {loading
            ? <span className="inline-block w-3 h-3 border-2 border-white/20 border-t-white rounded-full animate-spin" />
            : <Play size={13} />
          }
          {runLabel}
        </button>
        {tab === 'cluster' && (
          <span className="text-[10px] text-text-dim">Analyzes all {nodes.length} nodes for common-control leads</span>
        )}
        {error && (
          <span className="text-[11px] text-red-400 flex items-center gap-1">
            <AlertTriangle size={11} /> {error}
          </span>
        )}
      </div>

      {/* ── Clustering results ── */}
      {tab === 'cluster' && clusters.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <h4 className="text-sm font-semibold text-text-primary">
              {clusters.length} Cluster{clusters.length !== 1 ? 's' : ''} Found
            </h4>
            <span className="text-[11px] text-text-muted">{clusterSum}</span>
          </div>
          {clusterDis && (
            <div className="flex items-start gap-2 text-[10px] text-text-muted italic bg-yellow-900/10 border border-yellow-700/20 rounded-lg px-3 py-2">
              <Info size={11} className="mt-0.5 shrink-0 text-yellow-500" />
              {clusterDis}
            </div>
          )}
          <div className="space-y-2">
            {clusters.map((c, i) => <ClusterCard key={c.cluster_id} cluster={c} idx={i} />)}
          </div>
        </div>
      )}
      {tab === 'cluster' && !loading && clusters.length === 0 && (
        <p className="text-[11px] text-text-muted py-2">Run clustering to identify common-control leads in the graph.</p>
      )}

      {/* ── Cashout results ── */}
      {tab === 'cashout' && cashoutRisk && (
        <div className="space-y-3">
          <div className="flex items-center gap-4">
            <h4 className="text-sm font-semibold text-text-primary">
              {cashoutInds.length} Indicator{cashoutInds.length !== 1 ? 's' : ''}
            </h4>
            <span className={`text-xs font-bold uppercase ${SEV_COLOR[cashoutRisk.level] || 'text-text-primary'}`}>
              {cashoutRisk.level} risk · {cashoutRisk.score}/100
            </span>
          </div>
          <div className="text-[11px] text-text-secondary">{cashoutRisk.summary}</div>
          <div className="space-y-2">
            {cashoutInds.map((ind, i) => <CashoutCard key={i} ind={ind} idx={i} />)}
          </div>
        </div>
      )}
      {tab === 'cashout' && !loading && !cashoutRisk && (
        <p className="text-[11px] text-text-muted py-2">Run to detect exchange deposits, structuring, stablecoin off-ramps, and other cashout patterns.</p>
      )}

      {/* ── Paths results ── */}
      {tab === 'paths' && paths.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <h4 className="text-sm font-semibold text-text-primary">
              {paths.length} Unique Path{paths.length !== 1 ? 's' : ''}
            </h4>
            <span className="text-[11px] text-text-muted">{pathSummary}</span>
          </div>
          <div className="space-y-2">
            {paths.map((p, i) => <PathCard key={i} path={p} />)}
          </div>
        </div>
      )}
      {tab === 'paths' && !loading && paths.length === 0 && (
        <p className="text-[11px] text-text-muted py-2">Find all paths from the source wallet using 6 routing strategies (shortest, highest value, highest risk, mixer-routed, bridge-routed, most recent).</p>
      )}

      {/* ── Cross-chain results ── */}
      {tab === 'crosschain' && xchain && (
        <div className="space-y-4">
          {/* Risk summary bar */}
          <div className="rounded-lg border border-bg-border bg-bg-elevated px-4 py-3 flex flex-wrap gap-6">
            <div>
              <div className="text-[10px] text-text-muted uppercase">Risk level</div>
              <div className={`text-lg font-bold uppercase ${RISK_COLORS[xchain.risk.level] || 'text-text-primary'}`}>{xchain.risk.level}</div>
            </div>
            <div>
              <div className="text-[10px] text-text-muted uppercase">Score</div>
              <div className="text-lg font-bold text-text-primary">{xchain.risk.score}/100</div>
            </div>
            <div>
              <div className="text-[10px] text-text-muted uppercase">Bridge hops</div>
              <div className="text-lg font-bold text-text-primary">{xchain.risk.bridge_hops}</div>
            </div>
            <div>
              <div className="text-[10px] text-text-muted uppercase">Chains</div>
              <div className="text-sm font-semibold text-neon-cyan">{xchain.chains_involved.join(', ') || '-'}</div>
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[10px] text-text-muted uppercase">Summary</div>
              <div className="text-[11px] text-text-secondary">{xchain.summary}</div>
            </div>
          </div>

          <CollapsibleSection title="Bridge Hops" count={xchain.bridge_hops.length} color="text-orange-400">
            {xchain.bridge_hops.map((h, i) => <BridgeHopCard key={i} hop={h} />)}
          </CollapsibleSection>

          <CollapsibleSection title="Value-Time Matches" count={xchain.value_matches.length} color="text-yellow-400">
            {xchain.value_matches.map((m, i) => <ValueMatchCard key={i} match={m} />)}
          </CollapsibleSection>

          <CollapsibleSection title="Wrapped Asset Movements" count={xchain.wrapped_movements.length} color="text-purple-400">
            {xchain.wrapped_movements.map((w, i) => (
              <div key={i} className="rounded-lg border border-bg-border bg-bg-elevated px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-purple-400">{w.token}</span>
                  <span className={`text-xs font-bold ml-auto ${confColor(w.confidence)}`}>{w.confidence}%</span>
                </div>
                <div className="text-[11px] text-text-secondary mt-1">{w.description}</div>
              </div>
            ))}
          </CollapsibleSection>

          <CollapsibleSection title="Stablecoin Hops" count={xchain.stablecoin_hops.length} color="text-neon-cyan">
            {xchain.stablecoin_hops.map((s, i) => (
              <div key={i} className="rounded-lg border border-bg-border bg-bg-elevated px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-neon-cyan">{s.token}</span>
                  <span className="text-[10px] text-text-muted">${s.out_usd.toLocaleString()} out / ${s.in_usd.toLocaleString()} in</span>
                  <span className={`text-xs font-bold ml-auto ${confColor(s.confidence)}`}>{s.confidence}%</span>
                </div>
                <div className="text-[11px] text-text-secondary mt-1">{s.description}</div>
              </div>
            ))}
          </CollapsibleSection>

          {xchain.total_findings === 0 && (
            <div className="flex items-center gap-2 text-[11px] text-neon-green">
              <CheckCircle size={14} /> No cross-chain activity detected in this graph
            </div>
          )}
        </div>
      )}
      {tab === 'crosschain' && !loading && !xchain && (
        <p className="text-[11px] text-text-muted py-2">Detect bridge hops, value-time matched transfers, wrapped assets, and stablecoin cross-chain movements.</p>
      )}
    </div>
  )
}
