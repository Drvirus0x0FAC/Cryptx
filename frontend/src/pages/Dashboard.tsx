import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BellRing,
  Bug,
  CheckCircle2,
  ChevronRight,
  Clock,
  Database,
  Eye,
  FolderOpen,
  Gauge,
  GitBranch,
  Network,
  Newspaper,
  Plus,
  Radar,
  Radio,
  Search,
  Snowflake,
  Target,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react'
import {
  listCases, freezeNetKpis, scamAtlasSummary, listMonitorNotifications,
  getThreatFeedNews, getSpotPrice,
} from '../api/client'
import type { Case } from '../types'
import { SUPPORTED_CHAINS, SUPPORTED_TOKENS, TOTAL_CHAINS, TOTAL_TOKENS } from '../lib/coverage'
import CoverageModal from '../components/CoverageModal'
import InsightsPanel from '../components/InsightsPanel'

const SAMPLE_ADDRS = [
  { label: 'Tornado Cash', addr: '0xd90e2f925DA726b50C4ED8D0Fb90Ad053324F31b', risk: 'CRITICAL' },
  { label: 'Huobi Wallet', addr: '0xaB5C66752a9e8167967685F1450532fB96d5d24f', risk: 'LOW' },
  { label: 'Binance Hot', addr: '0x3f5CE5FBFe3E9af3971dD833D26BA9b5C936f0bE', risk: 'CLEAN' },
]

const RISK_BADGE_CLS: Record<string, string> = {
  CRITICAL: 'critical',
  HIGH: 'critical',
  MEDIUM: 'low',
  LOW: 'low',
  CLEAN: 'clean',
}

const FAMILY_META: Record<string, { labelKey: string; tone: string }> = {
  EVM: { labelKey: 'dashboard:families.evm', tone: '#627eea' },
  UTXO: { labelKey: 'dashboard:families.utxo', tone: '#f7931a' },
  Solana: { labelKey: 'dashboard:families.solana', tone: '#14f195' },
  Tron: { labelKey: 'dashboard:families.tron', tone: '#eb0029' },
  Cosmos: { labelKey: 'dashboard:families.cosmos', tone: '#8b5cf6' },
  others: { labelKey: 'dashboard:families.others', tone: '#94a3b8' },
}

const LIVE_FEED = [
  { label: 'Mixer exposure detected', chain: 'ETH', score: 91 },
  { label: 'Bridge hop correlated', chain: 'ARB', score: 74 },
  { label: 'Exchange cash-out lead', chain: 'TRX', score: 63 },
  { label: 'Victim cluster matched', chain: 'BTC', score: 86 },
]

const PULSE_ASSETS = ['BTC', 'ETH', 'SOL', 'TRX']
const PULSE_TONES: Record<string, string> = { BTC: '#f7931a', ETH: '#627eea', SOL: '#14f195', TRX: '#eb0029' }

function RiskRing({ score }: { score: number }) {
  const color = score >= 80 ? '#F87171' : score >= 60 ? '#FB923C' : score >= 40 ? '#FBBF24' : '#34D399'
  const label = score >= 80 ? 'CRITICAL' : score >= 60 ? 'HIGH' : score >= 40 ? 'MEDIUM' : score > 0 ? 'LOW' : 'CLEAN'
  const circ = 2 * Math.PI * 22
  const fill = (score / 100) * circ

  return (
    <div className="home-risk-ring">
      <div className="home-risk-ring-visual">
        <svg viewBox="0 0 56 56" className="-rotate-90">
          <circle cx="28" cy="28" r="22" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="5" />
          <circle
            cx="28"
            cy="28"
            r="22"
            fill="none"
            stroke={color}
            strokeWidth="5"
            strokeDasharray={`${fill} ${circ}`}
            strokeLinecap="round"
            style={{ transition: 'stroke-dasharray 0.9s cubic-bezier(0.22,1,0.36,1)' }}
          />
        </svg>
        <span style={{ color }}>{score}</span>
      </div>
      <b style={{ color }}>{label}</b>
    </div>
  )
}

/**
 * Enforces the home grid structure directly on the DOM with !important, so the
 * layout is correct even when a dev server serves a stale CSS transform (flaky
 * file-watching on mounted/OneDrive paths). Harmless when CSS is fresh — it sets
 * the same values the stylesheet already carries.
 */
function useEnforceHomeLayout(ref: React.RefObject<HTMLDivElement>) {
  useLayoutEffect(() => {
    const root = ref.current
    if (!root) return
    const top = root.querySelector<HTMLElement>('.cxhome-top')
    const bottom = root.querySelector<HTMLElement>('.cxhome-bottom')
    const ticker = root.querySelector<HTMLElement>('.cxhome-ticker')
    const set = (el: HTMLElement | null, props: Record<string, string>) => {
      if (!el) return
      for (const [k, v] of Object.entries(props)) el.style.setProperty(k, v, 'important')
    }
    const clear = (el: HTMLElement | null, keys: string[]) => {
      if (!el) return
      for (const k of keys) el.style.removeProperty(k)
    }
    const rootKeys = ['display', 'grid-template-columns', 'grid-auto-flow', 'grid-template-rows', 'height', 'max-height', 'overflow']
    const childKeys = ['display', 'grid-column', 'grid-template-columns']

    const apply = () => {
      const wide = window.innerWidth > 1180
      if (!wide) {
        // let the stacking media query own the layout
        clear(root, rootKeys); clear(top, childKeys); clear(bottom, childKeys); clear(ticker, ['grid-column'])
        return
      }
      const cols3 = window.innerWidth > 1450
      set(root, {
        display: 'grid',
        height: '100%',
        'max-height': '100%',
        overflow: 'hidden',
        'grid-template-columns': '100%',
        'grid-auto-flow': 'row',
        'grid-template-rows': 'minmax(0,1.05fr) minmax(0,0.95fr) 30px',
      })
      set(top, {
        display: 'grid', 'grid-column': '1',
        'grid-template-columns': wide && window.innerWidth <= 1450
          ? 'minmax(0,1.5fr) minmax(360px,0.78fr)'
          : 'minmax(0,1.72fr) minmax(400px,0.72fr)',
      })
      set(bottom, {
        display: 'grid', 'grid-column': '1',
        'grid-template-columns': cols3
          ? 'minmax(0,1.3fr) minmax(300px,0.9fr) minmax(300px,0.9fr)'
          : 'minmax(0,1.2fr) minmax(280px,0.9fr) minmax(280px,0.9fr)',
      })
      set(ticker, { 'grid-column': '1' })
    }

    apply()
    window.addEventListener('resize', apply)
    return () => window.removeEventListener('resize', apply)
  })
}

export default function Dashboard() {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [showCoverage, setShowCoverage] = useState(false)
  const navigate = useNavigate()
  const rootRef = useRef<HTMLDivElement>(null)
  useEnforceHomeLayout(rootRef)

  const { data: cases = [] } = useQuery<Case[]>({
    queryKey: ['cases'],
    queryFn: listCases,
  })

  /* Live intelligence — all best-effort, zeros/empty when idle */
  const { data: kpis } = useQuery<any>({
    queryKey: ['home-freeze-kpis'], queryFn: freezeNetKpis, staleTime: 60_000, retry: false,
  })
  const { data: scamSum } = useQuery<any>({
    queryKey: ['home-scam-summary'], queryFn: scamAtlasSummary, staleTime: 120_000, retry: false,
  })
  const { data: notifs = [] } = useQuery<any[]>({
    queryKey: ['home-monitor-notifs'],
    queryFn: () => listMonitorNotifications({ unread_only: true, limit: 5 }),
    staleTime: 45_000, retry: false,
  })
  const { data: news } = useQuery<any>({
    queryKey: ['home-threat-news'],
    queryFn: () => getThreatFeedNews({ limit: 6 }),
    staleTime: 300_000, retry: false,
  })
  const { data: pulse = [] } = useQuery<any[]>({
    queryKey: ['home-market-pulse'],
    queryFn: () => Promise.all(PULSE_ASSETS.map(a => getSpotPrice(a).catch(() => ({ asset: a, usd: null })))),
    staleTime: 60_000, refetchInterval: 90_000, retry: false,
  })

  const activeCases = cases.filter(c => c.status === 'active')
  const visibleCases = activeCases.slice(0, 3)
  const alertCases = cases.filter(c => (c.max_risk_score ?? 0) >= 60).length
  const totalAddrs = cases.reduce((s, c) => s + (c.address_count ?? 0), 0)
  const maxRisk = cases.reduce((m, c) => Math.max(m, c.max_risk_score ?? 0), 0)
  const liveTraceCount = SUPPORTED_CHAINS.filter(c => c.liveTrace).length
  const headlines: any[] = news?.items?.slice(0, 5) ?? []

  const familyStats = useMemo(() => {
    const grouped = SUPPORTED_CHAINS.reduce<Record<string, typeof SUPPORTED_CHAINS>>((acc, chain) => {
      ;(acc[chain.family] ||= []).push(chain)
      return acc
    }, {})

    return Object.entries(grouped)
      .map(([family, chains]) => ({
        family,
        chains,
        live: chains.filter(chain => chain.liveTrace).length,
        meta: FAMILY_META[family] || FAMILY_META.others,
      }))
      .sort((a, b) => b.chains.length - a.chains.length)
  }, [])

  const stablecoinCount = SUPPORTED_TOKENS.filter(t => t.category === 'stablecoin').length
  const coverageLead = SUPPORTED_CHAINS.slice(0, 14)

  // Case risk distribution (live) — for the Operations Deck mini-histogram
  const riskDist = useMemo(() => {
    const buckets = [
      { key: 'CRITICAL', min: 80, tone: '#f87171', n: 0 },
      { key: 'HIGH', min: 60, tone: '#fb923c', n: 0 },
      { key: 'MEDIUM', min: 40, tone: '#fbbf24', n: 0 },
      { key: 'LOW', min: 1, tone: '#38bdf8', n: 0 },
      { key: 'CLEAN', min: 0, tone: '#34d399', n: 0 },
    ]
    for (const c of cases) {
      const s = c.max_risk_score ?? 0
      const b = buckets.find(x => s >= x.min) || buckets[buckets.length - 1]
      b.n++
    }
    const max = Math.max(1, ...buckets.map(b => b.n))
    return buckets.map(b => ({ ...b, pct: (b.n / max) * 100 }))
  }, [cases])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const q = query.trim()
    if (!q) return
    navigate(`/intel/${encodeURIComponent(q)}`)
  }

  const tickerItems = [
    ...LIVE_FEED.map(f => `⚠ ${f.chain} · ${f.label} · ${t('dashboard:ticker.risk')} ${f.score}`),
    `❄ $${Number(kpis?.value_frozen_usd ?? 0).toLocaleString()} ${t('dashboard:ticker.frozenSeized')}`,
    `☣ ${scamSum?.network_count ?? 0} ${t('dashboard:panels.scamNetworks')} · ${scamSum?.synthetic_kyc_flags ?? 0} ${t('dashboard:ticker.syntheticKyc')}`,
    ...headlines.map((h: any) => `📰 ${h.title}`),
    `⛓ ${TOTAL_CHAINS} ${t('dashboard:stats.chains')} · ${liveTraceCount} ${t('dashboard:panels.liveTraceable')} · ${TOTAL_TOKENS} ${t('dashboard:ticker.trackedAssets')}`,
  ]

  return (
    <div className="cxhome" ref={rootRef}>
      <div className="home-bg" aria-hidden="true">
        <span className="home-orbit home-orbit-a" />
        <span className="home-orbit home-orbit-b" />
        <span className="home-trace trace-a" />
        <span className="home-trace trace-b" />
        <span className="home-trace trace-c" />
        <div className="home-radar">
          <span />
          <span />
          <span />
          <b>AML</b>
        </div>
        <div className="home-market">
          {Array.from({ length: 18 }).map((_, i) => <span key={i} />)}
        </div>
        <div className="home-hash-rain">
          <span>0x71c9...af32</span><span>bc1q9f...4e2a</span><span>TRX bridge hop</span>
          <span>mixer exposure</span><span>OFAC clear</span><span>BASE exit</span>
        </div>
      </div>

      <div className="cxhome-top">
        <section className="home-hero" aria-label="CrypTX investigation launch">
          <div className="home-status-row">
            <span className="home-pill online"><i /> {t('dashboard:pills.systemsOnline')}</span>
            <button type="button" onClick={() => setShowCoverage(true)} className="home-pill home-pill-button">
              <Zap size={12} /> {t('dashboard:pills.chainsSupported', { count: TOTAL_CHAINS })}
            </button>
            <span className="home-pill"><Target size={12} /> {t('dashboard:pills.aiTriageReady')}</span>
            <span className="home-pill"><Database size={12} /> {t('dashboard:pills.evidencePipelineArmed')}</span>
          </div>

          <div className="home-hero-grid">
            <div className="home-brand-block">
              <div className="home-title-lockup">
                <img src="/cryptx-icon.svg" alt="CrypTX lock logo" />
                <div>
                  <h1>
                    {t('dashboard:hero.title')}
                  </h1>
                  <p className="home-subtitle">
                    {t('dashboard:hero.subtitle')}
                  </p>
                </div>
              </div>
            </div>

            <div className="home-live-brief" aria-label={t('dashboard:liveBrief.title')}>
              <div className="home-brief-core">
                <span><Radar size={14} /> {t('dashboard:liveBrief.radarLabel')}</span>
                <strong>{alertCases || LIVE_FEED.length}</strong>
                <small>{t('dashboard:liveBrief.prioritySignals', { count: alertCases || LIVE_FEED.length })}</small>
              </div>
              <div className="home-feed-list">
                {LIVE_FEED.map((item, index) => (
                  <span key={item.label} style={{ '--delay': `${index * 0.22}s` } as CSSProperties}>
                    <b>{item.chain}</b>
                    {item.label}
                    <i>{item.score}</i>
                  </span>
                ))}
              </div>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="home-search">
            <Search size={18} />
            <input
              placeholder={t('dashboard:search.placeholder')}
              value={query}
              onChange={e => setQuery(e.target.value)}
              autoFocus
            />
            <button type="submit">
              <Eye size={15} />
              {t('dashboard:search.button')}
            </button>
          </form>

          <button
            type="button"
            onClick={() => navigate('/investigation-graph')}
            className="home-igraph-btn"
          >
            <Network size={16} />
            <span>Investigation Graph</span>
            <GitBranch size={13} style={{ opacity: 0.5 }} />
          </button>

          <div className="home-quick-row">
            <span>{t('dashboard:search.try')}</span>
            {SAMPLE_ADDRS.map(({ label, addr, risk }) => (
              <button key={addr} type="button" onClick={() => navigate(`/intel/${encodeURIComponent(addr)}`)}>
                <b className={RISK_BADGE_CLS[risk]}>{risk}</b>
                {label}
              </button>
            ))}
          </div>
        </section>

        <aside className="home-intel">
          {/* Predictive threat board: highest pre-crime probabilities on file */}
          <InsightsPanel context="dashboard" compact />

          <div className="home-risk-panel">
            <div className="home-risk-head">
              <p><Activity size={12} /> {t('dashboard:panels.portfolioRisk')}</p>
              <RiskRing score={maxRisk} />
            </div>
            <div className="home-stat-grid">
              {[
                { label: t('dashboard:stats.activeCases'), val: activeCases.length, color: '#34D399' },
                { label: t('dashboard:stats.highRisk'), val: alertCases, color: '#F87171' },
                { label: t('dashboard:stats.totalCases'), val: cases.length, color: '#38BDF8' },
                { label: t('dashboard:stats.addresses'), val: totalAddrs, color: '#F59E0B' },
              ].map(({ label, val, color }) => (
                <button key={label} type="button" onClick={() => navigate('/cases')}>
                  <strong style={{ color }}>{val}</strong>
                  <span>{label}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="home-coverage-panel">
            <button type="button" onClick={() => setShowCoverage(true)} className="home-coverage-head">
              <span><Gauge size={13} /> {t('dashboard:panels.coverageMatrix')}</span>
              <small>{t('dashboard:panels.openMatrix')} <ChevronRight size={11} /></small>
            </button>

            <div className="home-coverage-score">
              <div>
                <strong>{TOTAL_CHAINS}</strong>
                <span>{t('dashboard:stats.chains')}</span>
              </div>
              <div>
                <strong>{liveTraceCount}</strong>
                <span>{t('dashboard:stats.liveTrace')}</span>
              </div>
              <div>
                <strong>{TOTAL_TOKENS}</strong>
                <span>{t('dashboard:stats.tokens')}</span>
              </div>
              <div>
                <strong>{stablecoinCount}</strong>
                <span>{t('dashboard:panels.stablecoins')}</span>
              </div>
            </div>

            <div className="home-chain-rail" aria-label="Supported chain preview">
              {coverageLead.map(chain => (
                <span
                  key={chain.id}
                  style={{ background: chain.color, color: chain.textColor } as CSSProperties}
                  title={`${chain.name} (${chain.symbol})${chain.liveTrace ? ` - ${t('dashboard:panels.liveTraceable')}` : ''}`}
                >
                  {chain.symbol.slice(0, 4)}
                </span>
              ))}
              <button type="button" onClick={() => setShowCoverage(true)}>
                +{TOTAL_CHAINS - coverageLead.length}
              </button>
            </div>

            <div className="home-family-stack">
              {familyStats.map(({ family, chains, live, meta }) => (
                <button
                  key={family}
                  type="button"
                  onClick={() => setShowCoverage(true)}
                  style={{ '--tone': meta.tone, '--pct': `${(live / Math.max(chains.length, 1)) * 100}%` } as CSSProperties}
                >
                  <span>
                    <b>{t(meta.labelKey)}</b>
                    <small>{live}/{chains.length} {t('dashboard:panels.liveTraceable')}</small>
                  </span>
                  <i />
                </button>
              ))}
            </div>
          </div>
        </aside>
      </div>

      <div className="cxhome-bottom">
        {/* ── Live Intelligence: real threat headlines + market pulse ── */}
        <section className="home-command">
          <div className="home-section-title">
            <span><Newspaper size={13} /> {t('dashboard:panels.liveIntelWire')}</span>
            <button type="button" onClick={() => navigate('/threat-landscape')}>
              {t('dashboard:panels.threatLandscape')} <ChevronRight size={12} />
            </button>
          </div>

          <div className="home-wire-list">
            {headlines.length > 0 ? headlines.map((h: any, i: number) => (
              <button
                key={h.id ?? i}
                type="button"
                onClick={() => navigate('/threat-landscape')}
                style={{ '--delay': `${i * 0.1}s` } as CSSProperties}
              >
                <i />
                <span>{h.title}</span>
                <small>{h.source || h.feed || 'wire'}</small>
              </button>
            )) : (
              <div className="home-wire-empty">
                <Radio size={16} />
                <span>{t('dashboard:panels.threatFeedIdle')}</span>
              </div>
            )}
          </div>

          <div className="home-pulse-strip" aria-label="Market pulse">
            <b className="home-pulse-tag"><Activity size={12} /> {t('dashboard:panels.marketPulse')}</b>
            {PULSE_ASSETS.map(sym => {
              const p = (pulse as any[]).find(x => (x?.asset || '').toUpperCase() === sym)
              const usd = p?.usd
              return (
                <span key={sym} className="home-pulse-item" style={{ '--tone': PULSE_TONES[sym] } as CSSProperties}>
                  <b>{sym}</b>
                  <strong>{usd != null ? `$${Number(usd).toLocaleString(undefined, { maximumFractionDigits: usd < 10 ? 4 : 0 })}` : '—'}</strong>
                  {usd != null ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                </span>
              )
            })}
            <small>{t('dashboard:panels.marketPulseHint')}</small>
          </div>
        </section>

        {/* ── Operations Deck: live outcome metrics (not navigation) ── */}
        <section className="home-ops">
          <div className="home-section-title">
            <span><Snowflake size={13} /> {t('dashboard:panels.operationsDeck')}</span>
            <small className="home-ops-live"><i /> {t('dashboard:panels.live')}</small>
          </div>

          <div className="home-ops-kpis">
            <button type="button" onClick={() => navigate('/freeze-desk?tab=kpis')} style={{ '--tone': '#38bdf8' } as CSSProperties}>
              <Snowflake size={14} />
              <strong>${Number(kpis?.value_frozen_usd ?? 0).toLocaleString()}</strong>
              <span>{t('dashboard:panels.valueFrozen')}</span>
            </button>
            <button type="button" onClick={() => navigate('/freeze-desk')} style={{ '--tone': '#34d399' } as CSSProperties}>
              <Radio size={14} />
              <strong>{kpis?.auto_queued_requests ?? 0}</strong>
              <span>{t('dashboard:panels.autoQueued')}</span>
            </button>
            <button type="button" onClick={() => navigate('/scam-atlas')} style={{ '--tone': '#f59e0b' } as CSSProperties}>
              <Bug size={14} />
              <strong>{scamSum?.network_count ?? 0}</strong>
              <span>{t('dashboard:panels.scamNetworks')}</span>
            </button>
            <button type="button" onClick={() => navigate('/monitor')} style={{ '--tone': '#f87171' } as CSSProperties}>
              <BellRing size={14} />
              <strong>{notifs.length}</strong>
              <span>{t('dashboard:panels.unreadMonitor')}</span>
            </button>
          </div>

          <div className="home-ops-feed">
            {notifs.slice(0, 2).map((n: any) => (
              <button key={n.id} type="button" onClick={() => navigate('/monitor')}>
                <b>{(n.chain || '?').toUpperCase()}</b>
                <span>{(n.address || '').slice(0, 12)}… {t('dashboard:panels.newActivity')}</span>
                <i>{(n.created_at || '').slice(11, 16)}</i>
              </button>
            ))}
            {notifs.length === 0 && (
              <p className="home-ops-quiet"><CheckCircle2 size={12} /> {t('dashboard:panels.monitorsQuiet')}</p>
            )}
          </div>

          {/* Live case-risk distribution — analytical, no sidebar duplication */}
          <div className="home-riskdist">
            <p className="home-riskdist-title"><Gauge size={11} /> {t('dashboard:panels.caseRiskDist')}</p>
            <div className="home-riskdist-bars">
              {riskDist.map(b => (
                <button
                  key={b.key}
                  type="button"
                  onClick={() => navigate('/cases')}
                  title={`${b.n} case${b.n !== 1 ? 's' : ''} at ${b.key} risk`}
                  style={{ '--tone': b.tone } as CSSProperties}
                >
                  <span className="home-riskdist-track"><i style={{ height: `${b.pct}%` }} /></span>
                  <strong>{b.n}</strong>
                  <small>{b.key.slice(0, 4)}</small>
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* ── Active Investigations (classic) ── */}
        <section className="home-cases">
          <div className="home-section-title">
            <span><Clock size={13} /> {t('dashboard:panels.activeInvestigations')}</span>
            <button type="button" onClick={() => navigate('/cases')}>{t('dashboard:panels.viewAll')} <ChevronRight size={12} /></button>
          </div>

          {visibleCases.length > 0 ? (
            <div className="home-case-list">
              {visibleCases.map(c => (
                <button key={c.id} type="button" onClick={() => navigate(`/cases/${c.id}`)}>
                  <RiskRing score={c.max_risk_score ?? 0} />
                  <span>
                    <strong>{c.name}</strong>
                    <small>{t('dashboard:panels.addressesCount', { count: c.address_count ?? 0 })} - {new Date(c.updated_at).toLocaleDateString()}</small>
                  </span>
                  <ChevronRight size={14} />
                </button>
              ))}
            </div>
          ) : (
            <div className="home-empty-case">
              <FolderOpen size={20} />
              <span>{t('dashboard:panels.noCases')}</span>
              <button type="button" onClick={() => navigate('/cases')}><Plus size={13} /> {t('dashboard:panels.createCase')}</button>
            </div>
          )}

          {alertCases > 0 && (
            <div className="home-alert">
              <AlertTriangle size={13} />
              {t('dashboard:panels.highRiskAlert', { count: alertCases })}
              <ArrowRight size={12} />
            </div>
          )}

          {alertCases === 0 && (
            <div className="home-clear">
              <CheckCircle2 size={13} />
              {t('dashboard:panels.noHighRisk')}
            </div>
          )}
        </section>
      </div>

      {/* ── Bottom intel ticker (cinematic, live data mix) ── */}
      <footer className="hx-ticker cxhome-ticker">
        <b className="hx-ticker-tag"><Radar size={11} /> {t('dashboard:panels.intelWire')}</b>
        <div className="hx-ticker-track">
          <div className="hx-ticker-run">
            {[...tickerItems, ...tickerItems].map((t, i) => <span key={i}>{t}</span>)}
          </div>
        </div>
      </footer>

      <CoverageModal open={showCoverage} onClose={() => setShowCoverage(false)} />
    </div>
  )
}
