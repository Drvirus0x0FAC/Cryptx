import { useState, useEffect } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import CounterpartyAnalytics from '../components/CounterpartyAnalytics'
import {
  Search, ExternalLink, Copy, GitBranch, BarChart2,
  Loader2, AlertCircle, User,
  FolderPlus, ChevronDown, ChevronUp, Brain, Bot,
  Database, Tag, ShieldAlert, Gauge, Layers, ListTree, Network, Shield, X,
} from 'lucide-react'
import { lookupAddress, scoreRisk, listCases, addAddressToCase, attributionAnalysis } from '../api/client'
import type { AddressIntel as Intel, RiskScore, Case } from '../types'
import RiskBadge from '../components/RiskBadge'
import SanctionsBanner from '../components/SanctionsBanner'
import TransactionTable from '../components/TransactionTable'
import TokenHoldings from '../components/TokenHoldings'
import MixerAlerts from '../components/MixerAlerts'
import RiskGauge from '../components/RiskGauge'
import RiskSignalList from '../components/RiskSignalList'
import ExposureBreakdown from '../components/ExposureBreakdown'
import CategoryBadges from '../components/CategoryBadges'
import ResultTabs from '../components/ResultTabs'
import InsightsPanel from '../components/InsightsPanel'
import CinematicStage from '../components/CinematicStage'
import { useTabParam } from '../hooks/useTabParam'
import TimeTravelPanel from '../components/TimeTravelPanel'
import DeepTraceButtons from '../components/DeepTraceButtons'

function deriveRiskLevel(intel: Intel): 'clean' | 'entity' | 'bridge_swap' | 'scam' | 'mixer' | 'sanctioned' | 'error' {
  if (intel.sanctions?.sanctioned) return 'sanctioned'
  if ((intel.mixer_hits?.length ?? 0) > 0) return 'mixer'
  if ((intel.scam_reports?.count ?? 0) > 0) return 'scam'
  if (intel.chain_hop_swap?.risk_level === 'high') return 'bridge_swap'
  if (intel.arkham?.found) return 'entity'
  if (intel.chain_hop_swap?.risk_level === 'medium') return 'bridge_swap'
  if (intel.error) return 'error'
  return 'clean'
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-bg-surface border border-bg-border rounded-lg p-3">
      <p className="field-label">{label}</p>
      <p className="text-lg font-bold text-text-primary text-tech">{value}</p>
      {sub && <p className="text-[11px] text-text-secondary mt-0.5">{sub}</p>}
    </div>
  )
}

function fmtUsd(v?: number) {
  if (typeof v !== 'number' || !isFinite(v)) return '$0'
  if (v > 0 && v < 0.01) return '<$0.01'
  return '$' + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtAmount(v?: number) {
  if (typeof v !== 'number' || !isFinite(v)) return '0'
  if (v !== 0 && Math.abs(v) < 0.0001) return v.toExponential(2)
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 })
}

function AttributionAnalysisCard({ address }: { address: string }) {
  const { t } = useTranslation()
  const { data, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['attribution-analysis', address],
    queryFn: () => attributionAnalysis(address),
    enabled: !!address,
    retry: false,
    staleTime: 10 * 60_000,
  })

  const owner = data?.owner
  const portfolio = data?.portfolio
  const tokens = (portfolio?.tokens ?? []).filter(t => (t.symbol || t.name))
  const chains = portfolio?.chains ?? []
  const protocols = portfolio?.protocols ?? []

  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <p className="card-title mb-0 flex items-center gap-2">
          <Database size={14} className="text-accent-cyan" /> {t('tools:addressIntel.attribution.title')}
        </p>
        {isFetching && <Loader2 size={14} className="animate-spin text-text-muted" />}
      </div>

      {isFetching && !data && (
        <p className="text-sm text-text-secondary mt-3">{t('tools:addressIntel.attribution.running')}</p>
      )}

      {isError && (
        <div className="mt-3 space-y-2">
          <p className="text-sm text-risk-medium">{t('tools:addressIntel.attribution.failed', { error: error instanceof Error ? error.message : 'unknown error' })}</p>
          <button onClick={() => refetch()} className="btn-secondary text-xs">{t('tools:addressIntel.attribution.retry')}</button>
        </div>
      )}

      {data && !isFetching && !owner && !portfolio && (
        <div className="mt-3 space-y-2">
          <p className="text-sm text-text-secondary">{t('tools:addressIntel.attribution.none')}</p>
          <button onClick={() => refetch()} className="btn-secondary text-xs">{t('tools:addressIntel.attribution.rerun')}</button>
        </div>
      )}

      {/* Owner attribution */}
      {owner && (
        <div className="mt-3">
          <p className="field-label">{t('tools:addressIntel.attribution.owner')}</p>
          <div className="flex items-center gap-2 mt-1">
            <User size={15} className="text-accent-cyan shrink-0" />
            <span className="font-semibold text-text-primary">{owner.name}</span>
            {owner.verified && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent-cyan/15 text-accent-cyan">{t('tools:addressIntel.attribution.verified')}</span>
            )}
            {typeof owner.confidence === 'number' && (
              <span className="text-[10px] text-text-muted">{t('tools:addressIntel.attribution.confidence', { pct: Math.round((owner.confidence ?? 0) * 100) })}</span>
            )}
          </div>
          {owner.type && <p className="text-xs text-text-secondary mt-1 capitalize">{owner.type}</p>}
          {(owner.aliases?.length ?? 0) > 0 && (
            <p className="text-xs text-text-muted mt-1">{t('tools:addressIntel.attribution.alsoKnownAs', { aliases: owner.aliases!.join(', ') })}</p>
          )}
          {owner.bio && <p className="text-xs text-text-secondary mt-1 italic">{owner.bio}</p>}
          {(owner.labels?.length ?? 0) > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {owner.labels!.slice(0, 8).map((l, i) => (
                <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-bg-surface border border-bg-border text-text-secondary">{l}</span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Associated wallet balances / portfolio */}
      {portfolio && (
        <div className="mt-4 pt-3 border-t border-border">
          <div className="flex items-center justify-between">
            <p className="field-label mb-0">{t('tools:addressIntel.attribution.balances')}</p>
            <span className="text-tech font-bold text-text-primary">{fmtUsd(portfolio.total_usd)}</span>
          </div>

          {chains.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {chains.filter(c => c.usd_value > 0).slice(0, 8).map((c, i) => (
                <span key={i} className="text-[11px] px-2 py-0.5 rounded-full bg-bg-surface border border-bg-border text-text-secondary">
                  {c.chain_name} <span className="text-tech text-text-primary">{fmtUsd(c.usd_value)}</span>
                </span>
              ))}
            </div>
          )}

          {tokens.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-text-muted border-b border-border">
                    <th className="text-left font-normal py-1.5">{t('tools:addressIntel.attribution.tokenCol')}</th>
                    <th className="text-right font-normal py-1.5">{t('tools:addressIntel.attribution.priceCol')}</th>
                    <th className="text-right font-normal py-1.5">{t('tools:addressIntel.attribution.amountCol')}</th>
                    <th className="text-right font-normal py-1.5">{t('tools:addressIntel.attribution.usdCol')}</th>
                  </tr>
                </thead>
                <tbody>
                  {tokens.slice(0, 25).map((tok, i) => (
                    <tr key={i} className="border-b border-border/50">
                      <td className="py-1.5">
                        <span className="font-medium text-text-primary">{tok.symbol || tok.name}</span>
                        {tok.chain && <span className="text-[10px] text-text-muted ml-1.5">{tok.chain}</span>}
                        {(tok.is_scam || tok.is_suspicious) && (
                          <span className="text-[9px] text-risk-scam ml-1.5">{tok.is_scam ? t('tools:addressIntel.attribution.scam') : t('tools:addressIntel.attribution.suspicious')}</span>
                        )}
                      </td>
                      <td className="text-right text-text-secondary text-tech">{tok.price ? fmtUsd(tok.price) : '—'}</td>
                      <td className="text-right text-text-secondary text-tech">{fmtAmount(tok.amount)}</td>
                      <td className="text-right text-text-primary text-tech">{fmtUsd(tok.usd_value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {tokens.length > 25 && (
                <p className="text-[10px] text-text-muted mt-1">{t('tools:addressIntel.attribution.moreTokens', { count: tokens.length - 25 })}</p>
              )}
            </div>
          )}

          {protocols.length > 0 && (
            <div className="mt-3">
              <p className="field-label">{t('tools:addressIntel.attribution.defiPositions')}</p>
              <div className="space-y-1 mt-1">
                {protocols.slice(0, 8).map((p, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="text-text-secondary">{p.name}{p.chain && <span className="text-text-muted ml-1.5">{p.chain}</span>}</span>
                    <span className="text-tech text-text-primary">{fmtUsd(p.net_usd_value)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ScamCard({ scam }: { scam: Intel['scam_reports'] }) {
  const { t } = useTranslation()
  if (!scam || scam.skipped || !scam.found) return null
  return (
    <div className="card border-risk-scam/30">
      <p className="card-title text-risk-scam">{t('tools:addressIntel.scam.title', { count: scam.count ?? 0 })}</p>
      {(scam.records ?? []).slice(0, 5).map((rec, i) => (
        <div key={i} className="border-t border-border/50 py-2 text-xs space-y-1">
          {rec.name && <p><span className="text-text-muted">{t('tools:addressIntel.scam.name')}</span> {rec.name}</p>}
          {rec.category && <p><span className="text-text-muted">{t('tools:addressIntel.scam.category')}</span> {rec.category}</p>}
          {rec.date && <p><span className="text-text-muted">{t('tools:addressIntel.scam.date')}</span> {rec.date}</p>}
          {(rec.report || rec.description) && (
            <p className="text-text-secondary italic">{rec.report ?? rec.description}</p>
          )}
        </div>
      ))}
    </div>
  )
}

function PublicEnrichmentCard({ enrichment }: { enrichment: Intel['public_enrichment'] }) {
  const { t } = useTranslation()
  if (!enrichment || enrichment.error) return null
  const summary = enrichment.summary
  const labels = enrichment.labels ?? []
  const isTransientProviderNoise = (s: { name?: string; detail?: string }) => {
    const detail = s.detail ?? ''
    return /unavailable|retry later/i.test(detail) || (s.name === 'CryptoScamDB' && /HTTP 5\d\d/i.test(detail))
  }
  const failingSources = (enrichment.sources ?? []).filter((s) => s && !s.ok && s.configured && s.detail && !isTransientProviderNoise(s))
  const unconfiguredSources = (enrichment.sources ?? []).filter((s) => s && !s.configured)
  const hasContent =
    summary?.label_count > 0 ||
    summary?.abuse_report_count > 0 ||
    summary?.ransomware_hit_count > 0 ||
    summary?.portfolio_usd != null ||
    summary?.defi_chain_tvl != null ||
    unconfiguredSources.length > 0
  if (!hasContent) return null

  return (
    <div className="card">
      <div className="flex items-center justify-between gap-3">
        <p className="card-title mb-0">{t('tools:addressIntel.enrichment.title')}</p>
        <span className="text-[10px] text-text-muted">{t('tools:addressIntel.enrichment.subtitle')}</span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
        <StatCard label={t('tools:addressIntel.enrichment.publicLabels')} value={summary.label_count ?? 0} />
        <StatCard label={t('tools:addressIntel.enrichment.abuseReports')} value={summary.abuse_report_count ?? 0} />
        <StatCard label={t('tools:addressIntel.enrichment.ransomwareHits')} value={summary.ransomware_hit_count ?? 0} />
        <StatCard
          label={t('tools:addressIntel.enrichment.chainTvl')}
          value={summary.defi_chain_tvl != null ? `$${Number(summary.defi_chain_tvl).toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '-'}
        />
      </div>

      {summary.ransomware_hit_count > 0 && (
        <div className="mt-4 border border-risk-critical/40 bg-risk-critical/10 rounded-lg p-3">
          <div className="flex items-center gap-2 text-risk-critical text-sm font-semibold">
            <ShieldAlert size={15} />
            {t('tools:addressIntel.enrichment.ransomwareMatch')}
          </div>
          {(enrichment.ransomware?.matches ?? []).slice(0, 4).map((match, i) => (
            <p key={i} className="text-xs text-text-secondary mt-1">
              {match.label} <span className="text-text-muted">{t('tools:addressIntel.enrichment.via', { source: match.source })}</span>
            </p>
          ))}
        </div>
      )}

      {labels.length > 0 && (
        <div className="mt-4">
          <p className="text-xs text-text-muted uppercase tracking-widest mb-2">{t('tools:addressIntel.enrichment.labelsTitle')}</p>
          <div className="space-y-1.5">
            {labels.slice(0, 8).map((label, i) => (
              <div key={`${label.source}-${label.label}-${i}`} className="flex items-center gap-2 text-xs">
                <Tag size={12} className="text-accent-cyan shrink-0" />
                <span className="text-text-primary">{label.label}</span>
                <span className="text-text-muted">({label.category || t('tools:addressIntel.enrichment.labelCategoryLabel')} · {label.source})</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {enrichment.prices?.assets && Object.keys(enrichment.prices.assets).length > 0 && (
        <div className="mt-4">
          <p className="text-xs text-text-muted uppercase tracking-widest mb-2">{t('tools:addressIntel.enrichment.marketContext')} <span className="normal-case tracking-normal text-text-dim">{t('tools:addressIntel.enrichment.marketContextSub')}</span></p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(enrichment.prices.assets).slice(0, 8).map(([symbol, asset]) => (
              <span key={symbol} className="badge border border-border bg-bg-tertiary text-text-secondary">
                {symbol}: ${Number(asset.usd ?? 0).toLocaleString(undefined, { maximumFractionDigits: 4 })}
              </span>
            ))}
          </div>
        </div>
      )}

      {failingSources.length > 0 && (
        <div className="mt-4 border-t border-border pt-3">
          <div className="flex items-start gap-2 text-xs text-text-muted">
            <Database size={13} className="mt-0.5 shrink-0" />
            <div>
              <p className="text-risk-medium">
                {t('tools:addressIntel.enrichment.providerWarnings', { warnings: failingSources.map((s) => `${s.name}: ${s.detail || t('tools:addressIntel.enrichment.unavailable')}`).join('; ') })}
              </p>
            </div>
          </div>
        </div>
      )}
      {unconfiguredSources.length > 0 && (
        <p className="mt-3 text-[11px] text-text-muted">
          {t('tools:addressIntel.enrichment.optionalProviders', { providers: unconfiguredSources.map((s) => s.name).join(', ') })}
        </p>
      )}
    </div>
  )
}

function AddToCasePanel({ address, chain, risk }: { address: string; chain: string; risk?: RiskScore }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [selectedCase, setSelectedCase] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const { data: cases = [] } = useQuery<Case[]>({
    queryKey: ['cases'],
    queryFn: listCases,
    enabled: open,
  })

  const handleSave = async () => {
    if (!selectedCase) return
    setSaving(true)
    try {
      await addAddressToCase(selectedCase, {
        address,
        chain,
        label,
        risk_score: risk?.score ?? -1,
        risk_level: risk?.risk_level ?? '',
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} className="btn-secondary py-1.5 text-xs">
        <FolderPlus size={13} />
        {t('tools:addressIntel.addToCase.button')}
        {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-72 card border-neon-cyan/30 shadow-xl z-50 space-y-3">
          <p className="card-title">{t('tools:addressIntel.addToCase.title')}</p>
          {cases.length === 0 ? (
            <p className="text-[11px] text-text-secondary">
              {t('tools:addressIntel.addToCase.noCases')} <a href="/cases" className="text-neon-cyan hover:underline">{t('tools:addressIntel.addToCase.createOne')}</a>
            </p>
          ) : (
            <>
              <select
                value={selectedCase}
                onChange={(e) => setSelectedCase(e.target.value)}
                className="input"
              >
                <option value="">{t('tools:addressIntel.addToCase.selectCase')}</option>
                {cases.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder={t('tools:addressIntel.addToCase.labelPlaceholder')}
                className="input"
              />
              <button
                onClick={handleSave}
                disabled={!selectedCase || saving}
                className="btn-primary w-full justify-center text-xs"
              >
                {saved ? t('tools:addressIntel.addToCase.added') : saving ? t('tools:addressIntel.addToCase.saving') : t('tools:addressIntel.addToCase.addAddress')}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default function AddressIntel() {
  const { t } = useTranslation()
  const { addr } = useParams<{ addr: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  // Support both /intel/:addr and /intel?address=...
  const initialAddr = addr ?? searchParams.get('address') ?? ''
  const [input, setInput] = useState(initialAddr)
  const [target, setTarget] = useState(initialAddr)
  const [copied, setCopied] = useState(false)
  const [showRiskDetail, setShowRiskDetail] = useState(true)
  const [showInvestigationGraph, setShowInvestigationGraph] = useState(false)

  useEffect(() => {
    if (!showInvestigationGraph) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setShowInvestigationGraph(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [showInvestigationGraph])

  const [activeResultTab, setActiveResultTab] = useTabParam<'overview' | 'intel' | 'activity' | 'network'>(
    'overview', ['overview', 'intel', 'activity', 'network'])

  useEffect(() => {
    const a = addr ?? searchParams.get('address') ?? ''
    if (a) { setTarget(a); setInput(a) }
  }, [addr, searchParams])

  const { data, isFetching, error } = useQuery<Intel>({
    queryKey: ['address', target],
    queryFn: () => lookupAddress(target),
    enabled: !!target,
    retry: false,
  })

  const { data: risk, isFetching: riskFetching } = useQuery<RiskScore>({
    queryKey: ['risk', target, data?.chain],
    queryFn: () => scoreRisk(data!),
    enabled: !!data && !data.error,
    retry: false,
  })

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    const q = input.trim()
    if (!q) return
    navigate(`/intel/${encodeURIComponent(q)}`)
    setTarget(q)
  }

  function copyAddr() {
    if (!data?.address) return
    navigator.clipboard.writeText(data.address)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const riskLevel = data ? deriveRiskLevel(data) : undefined
  const allTxs = [...(data?.recent_txs ?? []), ...(data?.token_txs ?? [])]
    .filter((t, i, a) => a.findIndex(x => (x.hash ?? x.txid) === (t.hash ?? t.txid)) === i)
    .sort((a, b) => (b.time ?? '').localeCompare(a.time ?? ''))

  return (
    <div className="noscroll-page p-6 max-w-6xl mx-auto space-y-4">
      {/* Search bar */}
      <CinematicStage
        variant="intel"
        icon={Shield}
        kicker={t('tools:addressIntel.title')}
        title={t('tools:addressIntel.title')}
        subtitle={t('tools:addressIntel.inputPlaceholder')}
        onSubmit={handleSearch}
        collapsed={!!data}
      >
        <div className="flex gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[240px]">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              className="input pl-9"
              placeholder={t('tools:addressIntel.inputPlaceholder')}
              value={input}
              onChange={e => setInput(e.target.value)}
            />
          </div>
          <button type="submit" className="btn-primary" disabled={isFetching}>
            {isFetching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
            {t('tools:addressIntel.lookup')}
          </button>
          {data && (
            <>
              <button
                type="button" className="btn-ghost"
                onClick={() => navigate(`/trace/${encodeURIComponent(data.address)}`)}
              >
                <GitBranch size={14} /> {t('tools:addressIntel.trace')}
              </button>
              <button
                type="button" className="btn-ghost"
                onClick={() => navigate(`/ai-agent`)}
              >
                <Bot size={14} /> {t('tools:addressIntel.ai')}
              </button>
              <button
                type="button" className="btn-ghost"
                onClick={() => navigate(`/forensics/${encodeURIComponent(data.address)}`)}
              >
                <Brain size={14} /> {t('tools:addressIntel.forensics')}
              </button>
              <button
                type="button" className="btn-ghost"
                onClick={() => navigate(`/dex/${encodeURIComponent(data.address)}`)}
              >
                <BarChart2 size={14} /> {t('tools:addressIntel.dex')}
              </button>
            </>
          )}
        </div>
      </CinematicStage>

      {/* Error */}
      {error && (
        <div className="card border-risk-mixer/50 flex items-start gap-3">
          <AlertCircle className="text-risk-mixer shrink-0 mt-0.5" size={18} />
          <div>
            <p className="text-sm font-semibold text-risk-mixer">{t('tools:addressIntel.errors.lookupFailed')}</p>
            <p className="text-xs text-text-muted mt-1">
              {error instanceof Error ? error.message : String(error)}
            </p>
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {isFetching && !data && (
        <div className="space-y-4">
          {[1, 2, 3].map(i => (
            <div key={i} className="card animate-pulse">
              <div className="h-4 bg-bg-elevated rounded w-1/3 mb-3" />
              <div className="h-8 bg-bg-elevated rounded w-1/2" />
            </div>
          ))}
        </div>
      )}

      {/* Results */}
      {data && (
        <div className="noscroll-grow space-y-4">
          {/* ── Header card ── */}
          <div className="card">
            <div className="flex items-start justify-between flex-wrap gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  <span className="badge border border-accent-cyan/40 text-accent-cyan bg-accent-cyan/10 font-bold">
                    {data.chain}
                  </span>
                  {riskLevel && <RiskBadge level={riskLevel} />}
                  {data.source && (
                    <span className="text-[10px] text-text-muted">{t('tools:addressIntel.header.via', { source: data.source })}</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-text-primary break-all">{data.address}</span>
                  <button onClick={copyAddr} className="text-text-muted hover:text-accent-cyan shrink-0">
                    <Copy size={12} />
                  </button>
                  {copied && <span className="text-xs text-risk-clean">{t('tools:addressIntel.header.copied')}</span>}
                </div>
                {data.explorer && (
                  <a href={data.explorer} target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-1 text-xs text-accent-cyan hover:underline mt-1">
                    <ExternalLink size={11} /> {t('tools:addressIntel.header.viewOnExplorer')}
                  </a>
                )}
              </div>
              <AddToCasePanel address={data.address} chain={data.chain} risk={risk} />
            </div>

            {/* Stats grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
              <StatCard
                label={t('tools:addressIntel.stats.balance')}
                value={`${data.balance ?? 0} ${data.balance_unit}`}
                sub={data.portfolio_usd != null ? `≈ $${data.portfolio_usd.toLocaleString()}` : undefined}
              />
              <StatCard label={t('tools:addressIntel.stats.transactions')} value={data.tx_count ?? 0} sub={
                data.native_tx_count != null
                  ? t('tools:addressIntel.stats.txSplit', { native: data.native_tx_count, token: data.token_tx_count ?? 0 })
                  : undefined
              } />
              <StatCard label={t('tools:addressIntel.stats.firstSeen')} value={data.first_seen?.slice(0, 10) ?? '-'} />
              <StatCard label={t('tools:addressIntel.stats.lastActive')} value={data.last_seen?.slice(0, 10) ?? '-'} />
            </div>

            {data.total_received !== undefined && (
              <p className="text-xs text-text-muted mt-3">
                {t('tools:addressIntel.stats.totalReceived')} <span className="text-text-secondary font-mono">{data.total_received} {data.balance_unit}</span>
              </p>
            )}
            {data.fallback_warning && (
              <p className="text-xs text-risk-medium mt-2 italic">{data.fallback_warning}</p>
            )}
          </div>

          {/* ── Workbench: content left · inspector rail right ── */}
          <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_300px] gap-4 items-start">
          <div className="space-y-4 min-w-0">
          <ResultTabs
            active={activeResultTab}
            onChange={setActiveResultTab}
            tabs={[
              { id: 'overview', label: t('tools:addressIntel.tabs.overview'), icon: Gauge, count: risk?.signals.length },
              {
                id: 'intel', label: t('tools:addressIntel.tabs.intel'), icon: ShieldAlert,
                count: (data.mixer_hits?.length ?? 0) + (data.scam_reports?.count ?? 0) + (data.tokens?.length ?? 0),
              },
              { id: 'activity', label: t('tools:addressIntel.tabs.activity'), icon: ListTree, count: allTxs.length },
              { id: 'network', label: t('tools:addressIntel.tabs.network'), icon: Network },
            ]}
          />

          {/* ── Risk Score Card (CARA-style) ── */}
          {activeResultTab === 'overview' && <div className="intel-panel-grid">
          <div className="card">
            <div
              className="flex items-center justify-between cursor-pointer"
              onClick={() => setShowRiskDetail(!showRiskDetail)}
            >
              <div className="flex items-center gap-2">
                <p className="card-title mb-0">{t('tools:addressIntel.risk.title')}</p>
                {riskFetching && <Loader2 size={14} className="animate-spin text-text-muted" />}
              </div>
              {showRiskDetail ? <ChevronUp size={16} className="text-text-muted" /> : <ChevronDown size={16} className="text-text-muted" />}
            </div>

            {risk && (
              <div className={showRiskDetail ? '' : 'hidden'}>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-4">
                  {/* Gauge */}
                  <div className="flex justify-center">
                    <RiskGauge score={risk.score} level={risk.risk_level} size={160} />
                  </div>

                  {/* Categories + indicators */}
                  <div className="space-y-4">
                    <div>
                      <p className="text-xs text-text-muted uppercase tracking-widest mb-2">{t('tools:addressIntel.risk.categories')}</p>
                      <CategoryBadges categories={risk.categories} />
                      {risk.categories.length === 0 && (
                        <span className="text-xs text-risk-clean">{t('tools:addressIntel.risk.noneDetected')}</span>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-[11px]">
                      {[
                        { label: t('tools:addressIntel.risk.indicators.mixer'), val: risk.indicators.mixer_interactions,  alert: true  },
                        { label: t('tools:addressIntel.risk.indicators.scam'),  val: risk.indicators.scam_reports,        alert: true  },
                        { label: t('tools:addressIntel.risk.indicators.bridge'), val: risk.indicators.bridge_interactions, alert: false },
                        { label: t('tools:addressIntel.risk.indicators.swap'),   val: risk.indicators.swap_interactions,   alert: false },
                      ].map(({ label, val, alert }) => (
                        <div key={label} className="flex justify-between">
                          <span className="text-text-muted">{label}</span>
                          <span className="text-tech font-bold"
                            style={{ color: alert && val > 0 ? '#F87171' : val > 0 ? '#FBBF24' : '#34D399' }}>
                            {val}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Exposure */}
                  <div>
                    <p className="text-xs text-text-muted uppercase tracking-widest mb-2">{t('tools:addressIntel.risk.exposure')}</p>
                    <ExposureBreakdown exposure={risk.exposure} />
                  </div>
                </div>

                {/* Signals list */}
                {risk.signals.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-border">
                    <p className="text-xs text-text-muted uppercase tracking-widest mb-3">
                      {t('tools:addressIntel.risk.signals', { count: risk.signals.length })}
                    </p>
                    <RiskSignalList signals={risk.signals} />
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Sanctions */}
          <SanctionsBanner sanctions={data.sanctions} mixerHits={data.mixer_hits} />

          {/* Public enrichment */}
          <PublicEnrichmentCard enrichment={data.public_enrichment} />
          </div>}

          {activeResultTab === 'intel' && <div className="intel-panel-grid">
          {/* Mixer / Bridge alerts */}
          <MixerAlerts mixerHits={data.mixer_hits} chainHopSwap={data.chain_hop_swap} />

          {/* Unified owner attribution + associated wallet balances (auto) */}
          <AttributionAnalysisCard address={data.address} />

          {/* Scam reports */}
          <ScamCard scam={data.scam_reports} />

          {/* Tokens */}
          {(data.tokens?.length ?? 0) > 0 && (
            <TokenHoldings tokens={data.tokens!} chain={data.chain} />
          )}
          </div>}

          {activeResultTab === 'activity' && <div className="intel-panel-grid">
          {/* Transactions */}
          {allTxs.length > 0 && (
            <TransactionTable txs={allTxs} chain={data.chain} title={t('tools:addressIntel.activity.allTransactions')} />
          )}
          {data.recent_txs && data.recent_txs.length > 0 && allTxs.length === 0 && (
            <TransactionTable txs={data.recent_txs} chain={data.chain} title={t('tools:addressIntel.activity.recentTransactions')} />
          )}
          {allTxs.length === 0 && (
            <div className="card">
              <p className="card-title">{t('tools:addressIntel.activity.title')}</p>
              <p className="text-sm text-text-secondary">{t('tools:addressIntel.activity.empty')}</p>
            </div>
          )}
          </div>}

          {activeResultTab === 'network' && <div className="intel-panel-grid">
          {/* Exchange Usage · Top Counterparties · Entity Predictions */}
          <CounterpartyAnalytics address={data.address} chain={data.chain || 'auto'} />
          </div>}
          </div>

          {/* ── Inspector rail ── */}
          <aside className="space-y-4 xl:sticky xl:top-4">
            <div className="card">
              <p className="card-title">{t('tools:addressIntel.risk.snapshot')}</p>
              {risk ? (
                <div className="space-y-3">
                  <div className="flex justify-center">
                    <RiskGauge score={risk.score} level={risk.risk_level} size={110} />
                  </div>
                  <CategoryBadges categories={risk.categories} />
                  {risk.signals.length > 0 && (
                    <RiskSignalList signals={risk.signals.slice(0, 4)} compact />
                  )}
                </div>
              ) : (
                <p className="text-xs text-text-muted">
                  {riskFetching ? t('tools:addressIntel.risk.scoring') : t('tools:addressIntel.risk.unavailable')}
                </p>
              )}
            </div>

            <div className="card">
              <p className="card-title">{t('tools:addressIntel.pivots.title')}</p>
              <div className="grid grid-cols-1 gap-2">
                <button className="btn-secondary justify-center" onClick={() => setShowInvestigationGraph(true)}>
                  <Network size={14} /> Investigation Graph
                </button>
                <button className="btn-secondary justify-center" onClick={() => navigate(`/holistic/${encodeURIComponent(data.address)}`)}>
                  <Layers size={14} /> {t('tools:addressIntel.pivots.holisticTrace')}
                </button>
                <button className="btn-secondary justify-center" onClick={() => navigate(`/trace/${encodeURIComponent(data.address)}`)}>
                  <GitBranch size={14} /> {t('tools:addressIntel.pivots.fundTracer')}
                </button>
                <button className="btn-secondary justify-center" onClick={() => navigate(`/forensics/${encodeURIComponent(data.address)}`)}>
                  <Brain size={14} /> {t('tools:addressIntel.forensics')}
                </button>
              </div>
            </div>

            {/* Shared analytics layer: predictive + anomaly + population insights */}
            <InsightsPanel
              context="address"
              address={data.address}
              chain={data.chain || ''}
              refreshKey={data.address}
            />

            {/* V2 F8: Time-travel historical state reconstruction */}
            <TimeTravelPanel address={data.address} chain={data.chain} txList={allTxs as unknown as Record<string, unknown>[]} />

            {/* V2 F9: Deep trace (BTC UTXO / Solana SPL) */}
            <DeepTraceButtons address={data.address} chain={data.chain} />
          </aside>
          </div>
        </div>
      )}

      {/* Investigation Graph — full-screen in-app overlay with iframe */}
      {showInvestigationGraph && data && (
        <div className="igraph-overlay">
          <div className="igraph-overlay-toolbar">
            <Network size={16} className="igraph-overlay-icon" />
            <span className="igraph-overlay-title">Investigation Graph</span>
            <span className="igraph-overlay-addr">{data.address.slice(0, 10)}…</span>
            <div className="igraph-overlay-actions">
              <button
                type="button"
                onClick={() => setShowInvestigationGraph(false)}
                className="igraph-overlay-close"
                title="Close (Esc)"
              >
                <X size={16} />
              </button>
            </div>
          </div>
          <div className="igraph-overlay-body">
            <iframe
              src={`/nexus-embed/${encodeURIComponent(data.address)}`}
              title="Investigation Graph"
              className="igraph-overlay-iframe"
              allow="fullscreen"
            />
          </div>
        </div>
      )}
    </div>
  )
}
