import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle, Bot, Download, ExternalLink, Hash, Loader2,
  Network, Route, Search, ShieldAlert, Target, Zap, CheckCircle2,
} from 'lucide-react'
import { getTxInvestigationJob, startTxInvestigationJob } from '../api/client'
import CounterpartyAnalytics from '../components/CounterpartyAnalytics'
import DefiThreatPanel from '../components/DefiThreatPanel'
import ResultTabs from '../components/ResultTabs'
import { useTabParam } from '../hooks/useTabParam'
import type { TxLensFlow, TxLensJob, TxLensResult, TxLensResponse } from '../types'
import CinematicStage from '../components/CinematicStage'

const CHAINS = ['AUTO', 'ETH', 'MATIC', 'BSC', 'ARB', 'OP', 'BASE', 'BTC', 'TRX']

function short(value: string, n = 8) {
  if (!value) return ''
  return value.length > n * 2 + 2 ? `${value.slice(0, n)}...${value.slice(-n)}` : value
}

function pct(v: number | undefined | null) {
  return `${Math.round((v ?? 0) * 100)}%`
}

function riskColor(score: number) {
  if (score >= 80) return '#F87171'
  if (score >= 60) return '#FBBF24'
  if (score >= 35) return '#ffd60a'
  return '#ff5a6e'
}

function sevColor(sev: string) {
  if (sev === 'HIGH') return '#F87171'
  if (sev === 'MEDIUM') return '#FBBF24'
  return '#ff5a6e'
}

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-bg-secondary border border-border rounded-lg px-3 py-2">
      <p className="text-[10px] text-text-muted uppercase tracking-widest">{label}</p>
      <p className="text-lg font-bold text-text-primary font-mono">{value}</p>
      {sub && <p className="text-[11px] text-text-muted truncate">{sub}</p>}
    </div>
  )
}

function exportTxLens(result: TxLensResult) {
  const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `tx-lens-${result.tx_hash.slice(0, 12)}-${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: unknown; status?: number }; message?: string }
  const data = err.response?.data
  let detail = ''
  if (typeof data === 'string') detail = data
  else if (data && typeof data === 'object' && 'detail' in data) detail = String((data as { detail?: unknown }).detail ?? '')
  return detail || err.message || String(e)
}

// Stage identifiers map to tools:txLens.progress.stages.* translations.
// The `id` is the value returned by the backend `job.stage`; we keep the
// canonical English id as the lookup key so any stage the server emits resolves.
const STAGE_IDS = ['resolving', 'extracting', 'enriching', 'labels', 'expanding', 'algorithms', 'ai', 'finalizing'] as const
type StageId = (typeof STAGE_IDS)[number]

// The backend sends one of a known set of stage strings; normalise to our id.
const STAGE_ID_BY_LABEL: Record<string, StageId> = {
  'Resolving Transaction': 'resolving',
  'Extracting Value Flows': 'extracting',
  'Enriching Parties': 'enriching',
  'Loading Local Labels': 'labels',
  'Expanding Trace Context': 'expanding',
  'Running Local Algorithms': 'algorithms',
  'Synthesizing AI Assessment': 'ai',
  'Finalizing Report': 'finalizing',
}

function ProgressPanel({ job }: { job: TxLensJob | null }) {
  const { t } = useTranslation()
  const progress = job?.progress ?? 0
  const activeRaw = job?.stage || ''
  // Map the raw stage label to our id; default to 'resolving' if unknown.
  const activeId: StageId = (STAGE_ID_BY_LABEL[activeRaw] ?? 'resolving')
  const activeLabel = activeRaw
    ? t(`tools:txLens.progress.stages.${activeId}`)
    : t('tools:txLens.progress.starting')
  return (
    <div className="card space-y-4">
      <div className="flex items-center gap-4">
        <Loader2 className="animate-spin text-neon-amber shrink-0" size={30} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-text-primary font-semibold">{activeLabel}</p>
            <span className="font-mono text-xs text-neon-amber">{progress}%</span>
          </div>
          <p className="text-xs text-text-muted mt-1">{job?.detail || t('tools:txLens.progress.detailFallback')}</p>
          <div className="h-2 rounded-full bg-bg-secondary border border-border mt-3 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{ width: `${progress}%`, background: 'linear-gradient(90deg, #FBBF24, #ff5a6e)' }}
            />
          </div>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2">
        {STAGE_IDS.map((id) => {
          const done = STAGE_IDS.indexOf(id) < STAGE_IDS.indexOf(activeId) || progress >= 100
          const current = id === activeId
          return (
            <div
              key={id}
              className="flex items-center gap-2 border border-border rounded-lg px-3 py-2 bg-bg-secondary/50"
              style={{ borderColor: current ? 'rgba(255,159,10,0.5)' : undefined }}
            >
              {done ? <CheckCircle2 size={13} className="text-neon-green" /> : current ? <Loader2 size={13} className="animate-spin text-neon-amber" /> : <span className="w-[13px] h-[13px] rounded-full border border-text-muted/40" />}
              <span className={current ? 'text-neon-amber text-xs' : 'text-text-secondary text-xs'}>{t(`tools:txLens.progress.stages.${id}`)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function TxGraph({ result, selected, onSelect }: {
  result: TxLensResult
  selected: string | null
  onSelect: (addr: string) => void
}) {
  const { t } = useTranslation()
  const [layout, setLayout] = useState<'flow' | 'risk' | 'role'>('flow')
  const [query, setQuery] = useState('')
  const [assetType, setAssetType] = useState('all')
  const [minRisk, setMinRisk] = useState(0)
  const [focusMode, setFocusMode] = useState(false)
  const [showLabels, setShowLabels] = useState(true)
  const [selectedFlow, setSelectedFlow] = useState<TxLensFlow | null>(null)

  const visual = useMemo(() => {
    const neighborSet = new Set<string>()
    if (selected) {
      neighborSet.add(selected)
      result.value_flows.forEach((f) => {
        if (f.source === selected) neighborSet.add(f.target)
        if (f.target === selected) neighborSet.add(f.source)
      })
    }
    const q = query.trim().toLowerCase()
    const nodes = result.local_graph.nodes.filter((n) => {
      if (n.id === selected) return true
      if (focusMode && selected && !neighborSet.has(n.id)) return false
      if (q && !n.address.toLowerCase().includes(q) && !n.role.toLowerCase().includes(q) && !n.risk_level.toLowerCase().includes(q)) return false
      return n.risk_score >= minRisk || n.inbound > 0 || n.outbound > 0
    }).sort((a, b) => (b.risk_score + b.inbound + b.outbound) - (a.risk_score + a.inbound + a.outbound)).slice(0, 90)
    const visible = new Set(nodes.map((n) => n.id))
    const positions: Record<string, { x: number; y: number }> = {}

    const placeColumn = (items: typeof nodes, x: number, top: number, bottom: number) => {
      items.forEach((node, i) => {
        const y = top + ((bottom - top) * (i + 1)) / (items.length + 1)
        positions[node.id] = { x, y }
      })
    }
    if (layout === 'risk') {
      placeColumn(nodes.filter((n) => n.risk_score >= 70), 160, 50, 430)
      placeColumn(nodes.filter((n) => n.risk_score >= 35 && n.risk_score < 70), 450, 50, 430)
      placeColumn(nodes.filter((n) => n.risk_score < 35), 740, 50, 430)
    } else if (layout === 'role') {
      placeColumn(nodes.filter((n) => n.role.includes('initiator') || n.role.includes('sender')), 140, 50, 430)
      placeColumn(nodes.filter((n) => n.role.includes('intermediate') || (n.inbound > 0 && n.outbound > 0)), 450, 50, 430)
      placeColumn(nodes.filter((n) => n.role.includes('recipient') || (n.inbound > 0 && n.outbound === 0)), 760, 50, 430)
    } else {
      const senders = nodes.filter((n) => n.outbound > 0 && n.inbound === 0)
      const receivers = nodes.filter((n) => n.inbound > 0 && n.outbound === 0)
      const intermediates = nodes.filter((n) => n.inbound > 0 && n.outbound > 0)
      placeColumn(senders, 130, 50, 430)
      placeColumn(intermediates, 450, 70, 410)
      placeColumn(receivers, 770, 50, 430)
    }
    nodes.forEach((node, i) => {
      if (!positions[node.id]) {
        positions[node.id] = { x: 450 + Math.cos(i) * 150, y: 240 + Math.sin(i) * 135 }
      }
    })
    const edges = result.value_flows
      .filter((f) => visible.has(f.source) && visible.has(f.target))
      .filter((f) => assetType === 'all' || f.asset_type === assetType)
      .slice(0, 180)
    return { nodes, edges, positions, neighborSet }
  }, [result, selected, focusMode, query, minRisk, assetType, layout])

  return (
    <div className="border border-border rounded-lg bg-bg-secondary overflow-hidden">
      <div className="p-3 border-b border-border bg-bg-card/40 space-y-3">
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto_auto_auto_auto] gap-2">
          <div className="relative">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input className="input pl-8 py-1.5 text-xs" placeholder={t('tools:txLens.graph.findPlaceholder')} value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <select className="input py-1.5 text-xs" value={layout} onChange={(e) => setLayout(e.target.value as typeof layout)}>
            <option value="flow">{t('tools:txLens.graph.layoutFlow')}</option>
            <option value="risk">{t('tools:txLens.graph.layoutRisk')}</option>
            <option value="role">{t('tools:txLens.graph.layoutRole')}</option>
          </select>
          <select className="input py-1.5 text-xs" value={assetType} onChange={(e) => setAssetType(e.target.value)}>
            <option value="all">{t('tools:txLens.graph.allFlows')}</option>
            <option value="native">Native</option>
            <option value="token">Token</option>
            <option value="internal">Internal</option>
            <option value="utxo_inferred">BTC inferred</option>
          </select>
          <button className="btn-ghost text-xs" onClick={() => setFocusMode((v) => !v)}>{focusMode ? t('tools:txLens.graph.focusOn') : t('tools:txLens.graph.focusOff')}</button>
          <button className="btn-ghost text-xs" onClick={() => setShowLabels((v) => !v)}>{showLabels ? t('tools:txLens.graph.labelsOn') : t('tools:txLens.graph.labelsOff')}</button>
        </div>
        <label className="block text-xs text-text-secondary">{t('tools:txLens.graph.minRisk')} <span className="font-mono text-text-primary">{minRisk}</span>
          <input className="w-full accent-amber-400" type="range" min="0" max="90" step="5" value={minRisk} onChange={(e) => setMinRisk(Number(e.target.value))} />
        </label>
      </div>
      <svg viewBox="0 0 900 480" className="w-full h-[480px] block">
        <rect width="900" height="480" fill="#0a0608" />
        <g opacity="0.18">
          {Array.from({ length: 15 }).map((_, i) => <line key={`v${i}`} x1={i * 64} y1="0" x2={i * 64} y2="480" stroke="#2a1620" />)}
          {Array.from({ length: 8 }).map((_, i) => <line key={`h${i}`} x1="0" y1={i * 64} x2="900" y2={i * 64} stroke="#2a1620" />)}
        </g>
        <text x="50" y="30" fill="#98828a" fontSize="11" fontFamily="monospace">{t('tools:txLens.graph.colSenders')}</text>
        <text x="410" y="30" fill="#98828a" fontSize="11" fontFamily="monospace">{layout === 'risk' ? t('tools:txLens.graph.colMediumRisk') : t('tools:txLens.graph.colIntermediates')}</text>
        <text x="735" y="30" fill="#98828a" fontSize="11" fontFamily="monospace">{layout === 'risk' ? t('tools:txLens.graph.colLowRisk') : t('tools:txLens.graph.colRecipients')}</text>

        {visual.edges.map((edge: TxLensFlow, i) => {
          const s = visual.positions[edge.source]
          const t = visual.positions[edge.target]
          if (!s || !t) return null
          const width = Math.max(1, Math.min(5, Math.log10(Number(edge.value || 0) + 1) + 1))
          const color = edge.asset_type === 'token' ? '#ff5d86' : edge.asset_type === 'internal' ? '#FBBF24' : '#ff5a6e'
          const hot = selected && (edge.source === selected || edge.target === selected)
          return (
            <g key={`${edge.source}-${edge.target}-${i}`}>
              <line
                x1={s.x}
                y1={s.y}
                x2={t.x}
                y2={t.y}
                stroke={hot ? '#fff2f4' : color}
                strokeWidth={hot ? width + 1.5 : width}
                opacity={hot ? 0.88 : 0.4}
                className="cursor-pointer"
                onClick={() => setSelectedFlow(edge)}
              />
              {showLabels && i < 24 && (
                <text x={(s.x + t.x) / 2} y={(s.y + t.y) / 2 - 4} fill="#9a858c" fontSize="9" fontFamily="monospace">
                  {edge.value} {edge.token}
                </text>
              )}
            </g>
          )
        })}

        {visual.nodes.map((node) => {
          const p = visual.positions[node.id]
          if (!p) return null
          const isSelected = selected === node.id
          const isNeighbor = selected && visual.neighborSet.has(node.id)
          const radius = Math.max(7, Math.min(16, 7 + node.risk_score / 12))
          return (
            <g key={node.id} onClick={() => onSelect(node.id)} className="cursor-pointer">
              <circle cx={p.x} cy={p.y} r={radius + (isSelected ? 7 : 2)} fill="transparent" stroke={isSelected ? '#fff2f4' : isNeighbor ? '#FBBF24' : riskColor(node.risk_score)} strokeWidth={isSelected ? 2 : 1} opacity="0.85" />
              <circle cx={p.x} cy={p.y} r={radius} fill={riskColor(node.risk_score)} opacity={!selected || isSelected || isNeighbor ? 0.9 : 0.32}>
                <title>{node.address}</title>
              </circle>
              {showLabels && (isSelected || node.risk_score >= 45) && (
                <text x={p.x + radius + 5} y={p.y + 4} fill="#9bb8d3" fontSize="10" fontFamily="monospace">
                  {node.short}
                </text>
              )}
            </g>
          )
        })}
        <g transform="translate(18 420)">
          <rect width="376" height="44" rx="6" fill="#0a0608" stroke="#2a1620" opacity="0.92" />
          <line x1="18" y1="15" x2="48" y2="15" stroke="#ff5a6e" /><text x="56" y="19" fill="#b09aa0" fontSize="10">{t('tools:txLens.graph.legendNative')}</text>
          <line x1="114" y1="15" x2="144" y2="15" stroke="#ff5d86" /><text x="152" y="19" fill="#b09aa0" fontSize="10">{t('tools:txLens.graph.legendToken')}</text>
          <line x1="206" y1="15" x2="236" y2="15" stroke="#FBBF24" /><text x="244" y="19" fill="#b09aa0" fontSize="10">{t('tools:txLens.graph.legendInternal')}</text>
          <circle cx="24" cy="32" r="5" fill="#F87171" /><text x="36" y="36" fill="#b09aa0" fontSize="10">{t('tools:txLens.graph.legendHighRisk')}</text>
        </g>
      </svg>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 p-3 border-t border-border bg-bg-card/30">
        <Stat label={t('tools:txLens.graph.statVisibleParties')} value={visual.nodes.length} />
        <Stat label={t('tools:txLens.graph.statVisibleFlows')} value={visual.edges.length} />
        <Stat label={t('tools:txLens.graph.statAssetFilter')} value={assetType} />
        <Stat label={t('tools:txLens.graph.statSelected')} value={selected ? short(selected) : '-'} />
        <Stat label={t('tools:txLens.graph.statLayout')} value={layout} />
      </div>
      {selectedFlow && (
        <div className="mx-3 mb-3 border border-neon-amber/25 rounded-lg p-3 bg-bg-card/60">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold text-text-primary">{short(selectedFlow.source)} {'->'} {short(selectedFlow.target)}</p>
              <p className="text-xs text-text-muted mt-1">
                {selectedFlow.value} {selectedFlow.token} · {selectedFlow.asset_type} · {selectedFlow.evidence}
              </p>
              {selectedFlow.contract && <p className="text-[11px] text-text-dim mt-1 font-mono">{t('tools:txLens.graph.flowContract', { addr: selectedFlow.contract })}</p>}
            </div>
            <span className="badge badge-muted">{selectedFlow.time || t('tools:txLens.graph.flowTimeUnknown')}</span>
          </div>
        </div>
      )}
    </div>
  )
}

export default function TxLens() {
  const { t } = useTranslation()
  const { chain: chainParam, hash: hashParam } = useParams()
  const [hash, setHash] = useState('')
  const [chain, setChain] = useState(chainParam || 'AUTO')
  const [focus, setFocus] = useState('')
  const [includeAi, setIncludeAi] = useState(true)
  const [deepEnrichment, setDeepEnrichment] = useState(true)
  const [expandTraces, setExpandTraces] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<TxLensResponse | null>(null)
  const [job, setJob] = useState<TxLensJob | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useTabParam<'graph' | 'analysis' | 'parties'>(
    'graph', ['graph', 'analysis', 'parties'])

  useEffect(() => {
    if (hashParam) setHash(decodeURIComponent(hashParam))
    if (chainParam) setChain(chainParam.toUpperCase())
  }, [chainParam, hashParam])

  async function run() {
    const target = hash.trim()
    if (!target) return
    setLoading(true)
    setError(null)
    setResult(null)
    setJob(null)
    setSelected(null)
    try {
      const started = await startTxInvestigationJob({
        hash: target,
        chain: chain === 'AUTO' ? undefined : chain,
        include_ai: includeAi,
        analyst_focus: focus,
        enrich_addresses: deepEnrichment || includeAi || expandTraces,
        expand_traces: expandTraces,
        max_addresses: deepEnrichment ? 8 : 4,
      })
      setJob(started)
      let current = started
      while (current.status === 'queued' || current.status === 'running') {
        await new Promise((resolve) => setTimeout(resolve, 1200))
        current = await getTxInvestigationJob(started.job_id)
        setJob(current)
      }
      if (current.status === 'failed') {
        throw new Error(current.error || current.detail || t('tools:txLens.errors.jobFailed'))
      }
      if (!current.result) {
        throw new Error(t('tools:txLens.errors.noResult'))
      }
      setResult(current.result)
      setSelected(current.result.tx_lens.parties[0]?.address ?? null)
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setLoading(false)
    }
  }

  const lens = result?.tx_lens
  const selectedParty = lens?.parties.find((p) => p.address === selected)

  return (
    <div className="noscroll-page p-6 max-w-7xl mx-auto space-y-5">
      <CinematicStage
        variant="txlens"
        icon={Hash}
        kicker={t('tools:txLens.title')}
        title={t('tools:txLens.title')}
        subtitle={t('tools:txLens.subtitle')}
        collapsed={!!result}
      >
        <div className="space-y-3">
        <div className="grid grid-cols-1 lg:grid-cols-[130px_1fr_auto] gap-3">
          <select className="input" value={chain} onChange={(e) => setChain(e.target.value)}>
            {CHAINS.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              className="input pl-9"
              placeholder={t('tools:txLens.inputPlaceholder')}
              value={hash}
              onChange={(e) => setHash(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') run()
              }}
            />
          </div>
          <button className="btn-primary" disabled={loading || !hash.trim()} onClick={run}>
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Target size={14} />}
            {t('tools:txLens.submit')}
          </button>
        </div>
        <textarea
          className="input min-h-[70px] resize-y"
          placeholder={t('tools:txLens.focusPlaceholder')}
          value={focus}
          onChange={(e) => setFocus(e.target.value)}
        />
        <div className="flex flex-wrap gap-4 text-xs text-text-secondary">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={includeAi} onChange={(e) => setIncludeAi(e.target.checked)} />
            {t('tools:txLens.options.includeAi')}
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={deepEnrichment} onChange={(e) => setDeepEnrichment(e.target.checked)} />
            {t('tools:txLens.options.deepEnrichment')}
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={expandTraces} onChange={(e) => setExpandTraces(e.target.checked)} />
            {t('tools:txLens.options.expandTraces')}
          </label>
          <span className="text-text-dim">
            {t('tools:txLens.options.fullModeHint')}
          </span>
        </div>
        </div>
      </CinematicStage>

      {error && (
        <div className="card border-risk-mixer/50 flex items-start gap-3">
          <AlertTriangle className="text-risk-mixer shrink-0 mt-0.5" size={18} />
          <div>
            <p className="text-sm font-semibold text-risk-mixer">{t('tools:txLens.errors.failed')}</p>
            <p className="text-xs text-text-muted mt-1">{error}</p>
          </div>
        </div>
      )}

      {loading && <ProgressPanel job={job} />}

      {lens && !loading && (
        <div className="noscroll-grow space-y-5">
          <div className="card">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="card-title flex items-center gap-2"><Hash size={13} /> {t('tools:txLens.profile.title')}</p>
                <p className="font-mono text-sm text-text-primary break-all">{lens.tx_hash}</p>
                <div className="flex flex-wrap gap-3 mt-2 text-xs text-text-muted">
                  <span>{lens.chain}</span>
                  <span>{lens.summary.status}</span>
                  <span>{lens.summary.timestamp || t('tools:txLens.profile.timeUnavailable')}</span>
                  {lens.transaction.explorer_url && (
                    <a href={lens.transaction.explorer_url} target="_blank" rel="noreferrer" className="text-neon-cyan hover:underline flex items-center gap-1">
                      {t('tools:txLens.profile.explorer')} <ExternalLink size={11} />
                    </a>
                  )}
                </div>
              </div>
              <button className="btn-ghost text-xs" onClick={() => exportTxLens(lens)}>
                <Download size={13} />
                {t('tools:txLens.profile.exportJson')}
              </button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-7 gap-3 mt-4">
              <Stat label={t('tools:txLens.profile.statTxRisk')} value={lens.summary.tx_risk_score} />
              <Stat label={t('tools:txLens.profile.statParties')} value={lens.summary.party_count} />
              <Stat label={t('tools:txLens.profile.statFlows')} value={lens.summary.flow_count} />
              <Stat label={t('tools:txLens.profile.statAssets')} value={lens.summary.asset_count} />
              <Stat label={t('tools:txLens.profile.statIndicators')} value={lens.summary.indicator_count} />
              <Stat label={t('tools:txLens.profile.statTopParty')} value={lens.summary.highest_party_risk} />
              <Stat label={t('tools:txLens.profile.statValue')} value={lens.transaction.value ?? 0} sub={lens.transaction.native_unit || lens.chain} />
            </div>
          </div>

          <ResultTabs
            active={activeTab}
            onChange={setActiveTab}
            tabs={[
              { id: 'graph', label: t('tools:txLens.tabs.flowGraph'), icon: Network, count: lens.summary.flow_count },
              {
                id: 'analysis', label: t('tools:txLens.tabs.analysis'), icon: Zap,
                count: lens.laundering_indicators.length + lens.attribution_hypotheses.length,
              },
              { id: 'parties', label: t('tools:txLens.tabs.parties'), icon: ShieldAlert, count: lens.pivot_leads.length },
            ]}
          />

          {activeTab === 'graph' && (
          <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-5">
            <div className="card">
              <p className="card-title flex items-center gap-2"><Network size={13} /> {t('tools:txLens.panels.graphTitle')}</p>
              <TxGraph result={lens} selected={selected} onSelect={setSelected} />
            </div>
            <div className="space-y-5">
              <div className="card">
                <p className="card-title flex items-center gap-2"><ShieldAlert size={13} /> {t('tools:txLens.panels.selectedParty')}</p>
                {selectedParty ? (
                  <div>
                    <p className="font-mono text-xs text-text-primary break-all">{selectedParty.address}</p>
                    <div className="grid grid-cols-2 gap-2 mt-3">
                      <Stat label={t('tools:txLens.panels.risk')} value={selectedParty.risk_score} sub={selectedParty.risk_level} />
                      <Stat label={t('tools:txLens.panels.role')} value={selectedParty.role} />
                      <Stat label={t('tools:txLens.panels.inbound')} value={selectedParty.inbound} />
                      <Stat label={t('tools:txLens.panels.outbound')} value={selectedParty.outbound} />
                    </div>
                    <div className="mt-3 text-xs text-text-secondary">
                      <p>{t('tools:txLens.panels.labels')} {selectedParty.labels.join(', ') || '-'}</p>
                      <Link to={`/intel/${encodeURIComponent(selectedParty.address)}`} className="text-neon-cyan hover:underline mt-2 inline-block">
                        {t('tools:txLens.panels.openIntel')}
                      </Link>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-text-muted">{t('tools:txLens.panels.selectPartyHint')}</p>
                )}
              </div>
              <div className="card">
                <p className="card-title flex items-center gap-2"><Route size={13} /> {t('tools:txLens.panels.traceContext')}</p>
                <p className="text-xs text-text-secondary">
                  {t('tools:txLens.panels.traced')} {(lens.trace_context.traced_addresses || []).map(short).join(', ') || t('tools:txLens.panels.notExpanded')}
                </p>
                {(lens.trace_context.warnings || []).map((w, i) => (
                  <p key={i} className="text-xs text-neon-amber mt-2">{w}</p>
                ))}
              </div>
            </div>
          </div>
          )}

          {activeTab === 'analysis' && (<>
          {result?.ai_assessment && (
            <div className="card border-neon-cyan/25">
              <p className="card-title flex items-center gap-2"><Bot size={13} /> {t('tools:txLens.panels.aiTitle')}</p>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 text-sm">
                {Object.entries(result.ai_assessment).map(([key, value]) => (
                  <div key={key} className="border border-border rounded-lg p-3 bg-bg-secondary/50">
                    <p className="text-[10px] text-text-muted uppercase tracking-widest mb-2">{key.replace(/_/g, ' ')}</p>
                    <p className="text-text-secondary whitespace-pre-wrap">{Array.isArray(value) ? value.join('\n') : String(value ?? '')}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* V2 F6: DeFi threat detection (stablecoin freeze / flash-loan / rug-pull / MEV) */}
          <DefiThreatPanel txList={(lens.value_flows || []) as unknown as Record<string, unknown>[]} subject={lens.parties[0]?.address} />

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            <div className="card">
              <p className="card-title flex items-center gap-2"><Zap size={13} /> {t('tools:txLens.panels.laundering')}</p>
              <div className="space-y-3">
                {lens.laundering_indicators.map((ind, i) => (
                  <div key={i} className="border border-border rounded-lg p-3 bg-bg-secondary/50">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-text-primary">{ind.name}</p>
                      <span className="text-xs font-mono" style={{ color: sevColor(ind.severity) }}>{ind.severity} {pct(ind.score)}</span>
                    </div>
                    <ul className="mt-2 space-y-1">
                      {ind.evidence.map((ev, j) => <li key={j} className="text-xs text-text-secondary">- {ev}</li>)}
                    </ul>
                  </div>
                ))}
                {lens.laundering_indicators.length === 0 && <p className="text-sm text-text-muted">{t('tools:txLens.panels.launderingEmpty')}</p>}
              </div>
            </div>

            <div className="card">
              <p className="card-title flex items-center gap-2"><Target size={13} /> {t('tools:txLens.panels.attribution')}</p>
              <div className="space-y-3">
                {lens.attribution_hypotheses.map((h, i) => (
                  <div key={`${h.address}-${i}`} className="border border-border rounded-lg p-3 bg-bg-secondary/50">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-text-primary">{h.candidate}</p>
                      <span className="badge badge-muted">{pct(h.confidence)}</span>
                    </div>
                    {h.address && <p className="mt-1 break-all font-mono text-xs leading-snug text-text-muted">{h.address} · {h.role}</p>}
                    <ul className="mt-2 space-y-1">
                      {h.evidence.map((ev, j) => <li key={j} className="text-xs text-text-secondary">- {ev}</li>)}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="card">
            <p className="card-title flex items-center gap-2"><Route size={13} /> {t('tools:txLens.panels.nextSteps')}</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {lens.next_steps.map((step, i) => (
                <p key={i} className="text-xs text-text-secondary border border-border rounded-lg p-3 bg-bg-secondary/50">{step}</p>
              ))}
            </div>
          </div>
          </>)}

          {activeTab === 'parties' && (<>
          <div className="card">
            <p className="card-title flex items-center gap-2"><ShieldAlert size={13} /> {t('tools:txLens.panels.partyQueue')}</p>
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead><tr><th>{t('tools:txLens.table.colPriority')}</th><th>{t('tools:txLens.table.colAddress')}</th><th>{t('tools:txLens.table.colRole')}</th><th>{t('tools:txLens.table.colRisk')}</th><th>{t('tools:txLens.table.colFlow')}</th><th>{t('tools:txLens.table.colReasons')}</th></tr></thead>
                <tbody>
                  {lens.pivot_leads.map((p) => (
                    <tr key={p.address} onClick={() => setSelected(p.address)} className="cursor-pointer">
                      <td className="font-mono text-text-primary">{p.priority_score}</td>
                      <td className="min-w-[320px] max-w-[680px] break-all font-mono text-[11px] leading-snug">{p.address}</td>
                      <td>{p.role}</td>
                      <td style={{ color: riskColor(p.priority_score) }}>{p.risk_level}</td>
                      <td>{lens.parties.find((x) => x.address === p.address)?.inbound ?? 0} / {lens.parties.find((x) => x.address === p.address)?.outbound ?? 0}</td>
                      <td>{p.reasons.join('; ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Exchange Usage · Top Counterparties · Entity Predictions (for the focused party) */}
          {(selected || lens.parties[0]?.address) && (
            <CounterpartyAnalytics
              address={selected || lens.parties[0]?.address}
              chain={chain === 'AUTO' ? 'auto' : chain.toLowerCase()} />
          )}
          </>)}
        </div>
      )}
    </div>
  )
}
