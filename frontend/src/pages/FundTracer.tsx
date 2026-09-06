import { useState, useEffect, useMemo, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { GitBranch, Search, Loader2, AlertCircle, Download, FolderPlus, Sparkles, Network, GitMerge, Clock, ShieldAlert, CheckCircle2 } from 'lucide-react'
import { traceAddress, traceDeepAddress, traceDeepStream, type DeepProgress } from '../api/client'
import { SeverityBadge } from '../components/RiskBadge'
import TraceGraph from '../components/TraceGraph'
import CounterpartyAnalytics from '../components/CounterpartyAnalytics'
import DeepTraceButtons from '../components/DeepTraceButtons'
import InsightsPanel from '../components/InsightsPanel'
import CinematicStage from '../components/CinematicStage'
import type { TraceResult, TracePattern, TraceAnalysis, TraceGraph as GraphData } from '../types'

// Keys under tools:fundTracer.patterns.docs.* — resolved via t() at render time.
const PATTERN_KEYS = [
  'sanctioned_exposure', 'mixer_exposure', 'scam_exposure', 'bridge_swap_exposure',
  'peel_chain', 'fan_out', 'fan_in', 'pass_through', 'round_amounts',
  'rapid_movement', 'high_volume_low_balance',
] as const

export default function FundTracer() {
  const { t } = useTranslation()
  const { addr } = useParams<{ addr: string }>()
  const navigate  = useNavigate()

  const [input,     setInput]     = useState(addr ?? '')
  const [hops,      setHops]      = useState(3)
  const [mode,      setMode]      = useState<'linear' | 'wide'>('linear')
  const [direction, setDirection] = useState<'out' | 'in' | 'both'>('out')
  const [deepMode,  setDeepMode]  = useState(false)

  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)
  const [result,   setResult]   = useState<TraceResult | null>(null)
  const [elapsed,  setElapsed]  = useState<number | null>(null)
  const [progress, setProgress] = useState<DeepProgress | null>(null)
  const [phases,   setPhases]   = useState<string[]>([])

  async function run(address: string, deep: boolean) {
    setLoading(true)
    setError(null)
    setResult(null)
    setElapsed(null)
    setProgress(null)
    setPhases([])
    const t0 = Date.now()
    try {
      // Deep mode runs the full orchestrator (5 engines + 3 algorithms). We stream
      // live progress via SSE so the user sees each phase instead of a blind wait.
      // Server budget (`timeout_seconds`) keeps it below the client abort window.
      let data: TraceResult
      if (deep) {
        setProgress({ pct: 0, label: t('tools:fundTracer.progress.starting'), detail: t('tools:fundTracer.progress.connecting') })
        let sawProgress = false
        try {
          data = await traceDeepStream(
            { address, hops, mode, direction, timeout_seconds: 220 },
            (p) => {
              sawProgress = true
              setProgress(p)
              setPhases(prev => (!p.label || prev.includes(p.label)) ? prev : [...prev, p.label])
            },
          )
        } catch (streamErr) {
          // Server-side error → don't silently re-run the whole 3-min job.
          if (sawProgress) throw streamErr
          // Transport never started (e.g. SSE blocked by a proxy) → fall back.
          data = await traceDeepAddress({ address, hops, mode, direction, timeout_seconds: 220, timeout: 250_000 })
        }
      } else {
        data = await traceAddress({ address, hops, mode, direction, timeout_seconds: 110, timeout: 130_000 })
      }
      setResult(data)
      setElapsed(Date.now() - t0)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      // Friendlier message for the common axios timeout on deep analysis.
      setError(/timeout.*exceeded/i.test(msg) && deep
        ? t('tools:fundTracer.errors.deepTimeout')
        : msg)
    } finally {
      setLoading(false)
    }
  }

  // Guards the URL-param effect from re-running a trace that the form just
  // kicked off (navigate() changes `addr`, which would otherwise fire a second,
  // plain trace on top of the deep one).
  const lastTraced = useRef<string>('')

  // Populate the box from the URL but do NOT auto-run. The user explicitly
  // chooses Trace (quick) or Deep Analyze (full + progress). Auto-running a
  // plain trace here was shadowing deep analysis AND disabling the Deep button
  // while it ran, which is why clicking Deep Analyze appeared to do nothing.
  useEffect(() => {
    if (addr) { setInput(addr); lastTraced.current = addr.toLowerCase() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addr])

  // Single entry point: pick the mode, update the URL, run exactly once.
  function startTrace(q: string, deep: boolean) {
    if (!q) return
    setDeepMode(deep)
    lastTraced.current = q.toLowerCase()   // block the nav-triggered effect from re-running
    navigate(`/trace/${encodeURIComponent(q)}`)
    run(q, deep)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    startTrace(input.trim(), false)
  }

  function exportJson() {
    if (!result) return
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `trace-${result.graph.seed.slice(0, 10)}-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const graph    = result?.graph     ?? null
  const patterns = graph?.patterns   ?? []
  const warnings = graph?.warnings   ?? []
  const stats    = graph?.stats      ?? {}

  // Risk-level distribution summary
  const riskDist = (stats as any).risk_levels ?? {}
  const riskOrder = ['sanctioned','mixer','scam','bridge_swap','entity','clean','error']

  // Dedup + cap tracer warnings so a rate-limit storm (many wallets returning
  // the same "Too many requests" error) can't render dozens of duplicate rows
  // and push the graph container into overlapping the sections below.
  const dedupedWarnings = useMemo(() => {
    const seen = new Set<string>()
    const items: string[] = []
    for (const w of warnings) {
      const key = w.slice(0, 80)
      if (!seen.has(key)) { seen.add(key); items.push(w) }
      if (items.length >= 8) break
    }
    return { items, hidden: Math.max(0, warnings.length - items.length) }
  }, [warnings])

  return (
    <div className="noscroll-page p-6 flex flex-col gap-4 h-full max-w-full">
      {/* Title */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: 'rgba(255,59,107,0.12)', border: '1px solid rgba(255,59,107,0.3)' }}>
          <GitBranch size={16} style={{ color: '#ff5d86' }} />
        </div>
        <div>
          <h1 className="text-display text-sm font-bold tracking-widest uppercase" style={{ color: 'inherit' }}>
            {t('tools:fundTracer.title')}
          </h1>
          <p className="text-text-secondary text-xs">
            {t('tools:fundTracer.subtitle')}
            {elapsed && !loading && <span className="text-text-muted ml-3">{t('tools:fundTracer.completedIn', { seconds: (elapsed/1000).toFixed(1) })}</span>}
          </p>
        </div>
      </div>

      {/* Controls */}
      <CinematicStage
        variant="trace"
        icon={GitBranch}
        kicker={t('tools:fundTracer.title')}
        title={t('tools:fundTracer.title')}
        subtitle={t('tools:fundTracer.subtitle')}
        onSubmit={handleSubmit}
        collapsed={!!result}
      >
        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_auto_auto_auto_auto] gap-3 items-end">
        <div>
          <label className="block text-[10px] text-text-muted uppercase tracking-widest mb-1">
            {t('tools:fundTracer.controls.seedAddress')}
          </label>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              className="input pl-9"
              placeholder={t('tools:fundTracer.controls.inputPlaceholder')}
              value={input}
              onChange={e => setInput(e.target.value)}
            />
          </div>
        </div>

        <div className="w-24">
          <label className="block text-[10px] text-text-muted uppercase tracking-widest mb-1">
            {t('tools:fundTracer.controls.hops')}
          </label>
          <input
            type="number" min={1} max={5}
            className="input w-full"
            value={hops}
            onChange={e => setHops(Number(e.target.value))}
          />
        </div>

        <div className="w-28">
          <label className="block text-[10px] text-text-muted uppercase tracking-widest mb-1">{t('tools:fundTracer.controls.mode')}</label>
          <select className="input w-full" value={mode} onChange={e => setMode(e.target.value as 'linear' | 'wide')}>
            <option value="linear">{t('tools:fundTracer.controls.modeLinear')}</option>
            <option value="wide">{t('tools:fundTracer.controls.modeWide')}</option>
          </select>
        </div>

        <div className="w-28">
          <label className="block text-[10px] text-text-muted uppercase tracking-widest mb-1">{t('tools:fundTracer.controls.direction')}</label>
          <select className="input w-full" value={direction} onChange={e => setDirection(e.target.value as 'out' | 'in' | 'both')}>
            <option value="out">{t('tools:fundTracer.controls.dirOutflows')}</option>
            <option value="in">{t('tools:fundTracer.controls.dirInflows')}</option>
            <option value="both">{t('tools:fundTracer.controls.dirBoth')}</option>
          </select>
        </div>

        <button type="submit" className="btn-primary h-9 self-end flex items-center gap-1.5" disabled={loading} title={t('tools:fundTracer.controls.traceTitle')}>
          {loading && !deepMode ? <Loader2 size={14} className="animate-spin" /> : <GitBranch size={14} />}
          {loading && !deepMode ? t('tools:fundTracer.controls.tracing') : t('tools:fundTracer.controls.trace')}
        </button>

        {/* Deep analysis — ONE click: runs 8 forensic passes with live progress. */}
        <button type="button"
          onClick={() => startTrace(input.trim(), true)}
          disabled={loading}
          className="h-9 self-end flex items-center gap-1.5 px-3 rounded-lg text-xs font-bold text-white shrink-0 disabled:opacity-60"
          style={{ background: 'linear-gradient(135deg,#f59e0b,#ef4444)' }}
          title={t('tools:fundTracer.controls.deepTitle')}>
          {loading && deepMode ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={13} />}
          <span>{loading && deepMode ? t('tools:fundTracer.controls.analyzing') : t('tools:fundTracer.controls.deepAnalyze')}</span>
        </button>

        {result && (
          <button type="button" onClick={exportJson}
            className="btn-ghost h-9 self-end" title={t('tools:fundTracer.controls.exportTitle')}>
            <Download size={14} />
          </button>
        )}
        </div>
      </CinematicStage>

      {/* Mode hint */}
      <p className="text-xs text-text-muted -mt-2">
        <span className="text-text-secondary">{t('tools:fundTracer.modeHintLinear')}</span>{' '}
        <span className="text-text-secondary">{t('tools:fundTracer.modeHintWide')}</span>
      </p>

      <div className="noscroll-grow flex flex-col gap-4">
      {/* Error */}
      {error && (
        <div className="card border-risk-mixer/50 flex items-start gap-3 shrink-0">
          <AlertCircle className="text-risk-mixer shrink-0 mt-0.5" size={18} />
          <div>
            <p className="text-sm font-semibold text-risk-mixer">{t('tools:fundTracer.errors.traceFailed')}</p>
            <p className="text-xs text-text-muted mt-1">{error}</p>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex-1 flex items-center justify-center" style={{ minHeight: 400 }}>
          {deepMode && progress ? (
            <div className="w-full max-w-2xl mx-auto space-y-5 rounded-2xl border border-amber-500/25 p-8"
              style={{ background: 'rgb(var(--bg-secondary) / 0.35)', boxShadow: '0 0 60px rgb(245 158 11 / 0.06)' }}>
              <div className="flex items-center gap-3">
                <Loader2 className="animate-spin text-amber-400 shrink-0" size={30} />
                <span className="text-text-primary text-2xl font-bold flex-1 leading-tight">{progress.label}</span>
                <span className="text-amber-400 text-4xl font-mono font-bold tabular-nums shrink-0">{progress.pct}%</span>
              </div>
              <div className="h-6 w-full rounded-full overflow-hidden" style={{ background: 'rgb(var(--bg-primary))', border: '1px solid rgb(var(--bg-border))' }}>
                <div className="h-full rounded-full" style={{
                  width: `${progress.pct}%`,
                  background: 'linear-gradient(90deg,#f59e0b,#ef4444)',
                  boxShadow: '0 0 18px rgb(245 158 11 / 0.6)',
                  transition: 'width 0.5s cubic-bezier(0.22,1,0.36,1)',
                }} />
              </div>
              {progress.detail && <p className="text-text-secondary text-lg">{progress.detail}</p>}
              <div className="space-y-3 pt-1">
                {phases.map((ph, i) => {
                  const isCurrent = ph === progress.label && progress.pct < 100
                  return (
                    <div key={i} className="flex items-center gap-3 text-lg">
                      {isCurrent
                        ? <Loader2 size={20} className="animate-spin text-amber-400 shrink-0" />
                        : <CheckCircle2 size={20} className="text-green-400 shrink-0" />}
                      <span className={isCurrent ? 'text-text-primary font-semibold' : 'text-text-secondary'}>{ph}</span>
                    </div>
                  )
                })}
              </div>
              <p className="text-sm text-text-muted pt-3 border-t border-border/50">
                {t('tools:fundTracer.progress.following', { hops })}
              </p>
            </div>
          ) : (
            <div className="text-center space-y-3">
              <Loader2 className={`animate-spin mx-auto ${deepMode ? 'text-amber-400' : 'text-accent-cyan'}`} size={36} />
              <p className="text-text-secondary text-sm">
                {deepMode ? t('tools:fundTracer.progress.runningDeep') : t('tools:fundTracer.progress.tracingFlows')}
              </p>
              <p className="text-text-muted text-xs">
                {deepMode
                  ? t('tools:fundTracer.progress.deepHint', { hops })
                  : t('tools:fundTracer.progress.traceHint', { hops })}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Stats bar */}
      {!loading && stats && Object.keys(stats).length > 0 && (
        <div className="flex gap-3 flex-wrap shrink-0">
          {[
            { label: t('tools:fundTracer.stats.wallets'),   val: (stats as any).nodes,            color: 'text-text-primary' },
            { label: t('tools:fundTracer.stats.transfers'), val: (stats as any).edges,            color: 'text-text-primary' },
            { label: t('tools:fundTracer.stats.flagged'),   val: (stats as any).suspicious_nodes, color: 'text-red-400' },
            { label: t('tools:fundTracer.stats.patterns'),  val: (stats as any).patterns,         color: 'text-amber-400' },
            { label: t('tools:fundTracer.stats.tlEvents'),  val: (stats as any).timeline_events,  color: 'text-text-secondary' },
          ].map(({ label, val, color }) => (
            <div key={label} className="bg-bg-secondary border border-border rounded-lg px-3 py-2 text-center min-w-[70px]">
              <p className="text-[10px] text-text-muted uppercase tracking-widest">{label}</p>
              <p className={`text-xl font-bold font-mono ${color}`}>{val ?? 0}</p>
            </div>
          ))}
          {/* Risk distribution */}
          {Object.keys(riskDist).length > 0 && riskOrder.filter(r => riskDist[r]).map((r) => (
            <div key={r} className="bg-bg-secondary border border-border rounded-lg px-3 py-2 text-center min-w-[70px]">
              <p className="text-[10px] text-text-muted uppercase tracking-widest">{r.replace('_', '/')}</p>
              <p className="text-xl font-bold font-mono"
                style={{ color: r === 'sanctioned' ? '#f0356b' : r === 'mixer' ? '#ef4444' :
                                 r === 'scam' ? '#f97316' : r === 'bridge_swap' ? '#f59e0b' :
                                 r === 'entity' ? '#ff5a6e' : r === 'clean' ? '#22c55e' : '#475569' }}>
                {riskDist[r]}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Warnings (deduped + capped + scroll-boxed so a rate-limit storm
          can't flood the layout and push the graph into other sections) */}
      {dedupedWarnings.items.length > 0 && !loading && (
        <div className="card border-amber-700/30 bg-amber-900/5 shrink-0 max-h-40 overflow-y-auto">
          <p className="text-xs text-amber-400 font-semibold mb-1">{t('tools:fundTracer.warnings.title')}</p>
          {dedupedWarnings.items.map((w, i) => (
            <p key={i} className="text-xs text-text-muted">{w}</p>
          ))}
          {dedupedWarnings.hidden > 0 && (
            <p className="text-xs text-text-muted/60 italic mt-1">
              {t('tools:fundTracer.warnings.hidden', { count: dedupedWarnings.hidden })}
            </p>
          )}
        </div>
      )}

      {/* ── Deep Analysis Summary ──
          Quick-glance chips of the top findings from the orchestrator (only
          shown when /trace/deep was used and produced an analysis block). */}
      {!loading && (graph as GraphData)?.analysis && (() => {
        const a = (graph as GraphData).analysis as TraceAnalysis
        const chips: { icon: typeof Network; label: string; value: string | number; tone: string }[] = []
        const clusters = a.engines?.clusters
        if (clusters?.count) {
          chips.push({ icon: Network, label: t('tools:fundTracer.chips.walletClusters'), value: clusters.count, tone: '#38bdf8' })
        }
        const cc = a.engines?.crosschain
        if (cc && (cc.bridge_hops || cc.value_matches)) {
          chips.push({ icon: GitMerge, label: t('tools:fundTracer.chips.crosschain'), value: t('tools:fundTracer.chips.crosschainValue', { bridges: cc.bridge_hops || 0, matches: cc.value_matches || 0 }), tone: '#f59e0b' })
        }
        if (a.peel_chains?.length) {
          chips.push({ icon: GitBranch, label: t('tools:fundTracer.chips.peelChains'), value: a.peel_chains.length, tone: '#f0356b' })
        }
        if (a.layering?.length) {
          chips.push({ icon: ShieldAlert, label: t('tools:fundTracer.chips.layering'), value: a.layering.length, tone: '#a855f7' })
        }
        if (a.dwell?.rapid_wallet_count) {
          chips.push({ icon: Clock, label: t('tools:fundTracer.chips.rapidWallets'), value: a.dwell.rapid_wallet_count, tone: '#ef4444' })
        }
        const co = a.engines?.cashout
        if (co?.primary_dest) {
          chips.push({ icon: ShieldAlert, label: t('tools:fundTracer.chips.primaryCashout'), value: `${co.primary_dest.slice(0, 10)}…`, tone: '#fb7185' })
        }
        if (!chips.length) return null
        return (
          <div className="flex gap-2 flex-wrap shrink-0">
            {chips.map((c, i) => (
              <div key={i} className="flex items-center gap-2 rounded-lg px-3 py-2 border"
                style={{ background: `${c.tone}10`, borderColor: `${c.tone}40` }}>
                <c.icon size={14} style={{ color: c.tone }} />
                <div>
                  <p className="text-[9px] uppercase tracking-widest text-text-muted">{c.label}</p>
                  <p className="text-xs font-bold" style={{ color: c.tone }}>{c.value}</p>
                </div>
              </div>
            ))}
          </div>
        )
      })()}

      {/* ── THE GRAPH ──
          Wrapper is `relative overflow-hidden` so the z-30 NodePanel, z-20
          toolbar, and z-10 legend living inside TraceGraph are clipped to this
          box and cannot paint over the patterns table / analytics below. */}
      {!loading && graph && (graph as GraphData).nodes.length > 0 && (
        <div className="shrink-0 relative overflow-hidden rounded-xl border border-border"
          style={{ height: Math.max(560, Math.min(820, (graph as GraphData).nodes.length * 60 + 220)) }}>
          <TraceGraph graph={graph as GraphData} patterns={patterns as TracePattern[]} />
        </div>
      )}

      {/* Patterns table */}
      {patterns.length > 0 && !loading && (
        <div className="card shrink-0">
          <p className="card-title">{t('tools:fundTracer.patterns.title', { count: patterns.length })}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-text-secondary">
                  <th className="text-left pb-2 pr-3">{t('tools:fundTracer.patterns.colSeverity')}</th>
                  <th className="text-left pb-2 pr-3">{t('tools:fundTracer.patterns.colPattern')}</th>
                  <th className="text-left pb-2 pr-3">{t('tools:fundTracer.patterns.colConfidence')}</th>
                  <th className="text-left pb-2">{t('tools:fundTracer.patterns.colDescription')}</th>
                </tr>
              </thead>
              <tbody>
                {(patterns as TracePattern[]).map((p, i) => {
                  const patKey = p.pattern.toLowerCase().replace(/ /g, '_')
                  // Look up the translated doc; fall back to evidence if the key isn't in our set.
                  const desc = (PATTERN_KEYS as readonly string[]).includes(patKey)
                    ? t(`tools:fundTracer.patterns.docs.${patKey}`)
                    : p.evidence
                  return (
                    <tr key={i} className="border-b border-border/50 hover:bg-bg-tertiary/50">
                      <td className="py-2 pr-3">
                        <SeverityBadge severity={p.severity} />
                      </td>
                      <td className="py-2 pr-3 font-semibold text-text-primary whitespace-nowrap">
                        {p.pattern.replace(/_/g, ' ')}
                      </td>
                      <td className="py-2 pr-3 text-text-muted capitalize">{p.confidence}</td>
                      <td className="py-2 text-text-secondary max-w-md">{desc}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Shared analytics layer: flow concentration, terminal sinks, predictions */}
      {graph && (
        <InsightsPanel
          context="trace"
          address={graph.seed || input}
          data={{ graph }}
          refreshKey={`${graph.seed || input}-${(graph as GraphData).edges?.length ?? 0}`}
          className="shrink-0"
        />
      )}

      {/* Exchange Usage · Top Counterparties · Entity Predictions */}
      {graph && (
        <div className="relative z-[1] shrink-0 rounded-xl" style={{ background: 'rgb(var(--bg-primary))' }}>
          <CounterpartyAnalytics address={graph.seed || input} chain="auto" />
        </div>
      )}

      {/* V2 F9: Deep trace for BTC/SOL when the subject is on those chains */}
      {graph && <DeepTraceButtons address={graph.seed || input} />}

      {/* Empty state */}
      {!loading && !graph && !error && (
        <div className="flex-1 flex items-center justify-center" style={{ minHeight: 300 }}>
          <div className="text-center space-y-3">
            <GitBranch className="mx-auto text-text-muted" size={44} />
            <p className="text-text-secondary">{t('tools:fundTracer.empty.title')}</p>
            <p className="text-text-muted text-xs max-w-sm">
              {t('tools:fundTracer.empty.hint')}
            </p>
          </div>
        </div>
      )}
      </div>
    </div>
  )
}
