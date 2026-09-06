import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle, ArrowRight, BadgeCheck, GitMerge, Layers, Loader2,
  Network, Radar, ShieldAlert, Waypoints, Zap,
} from 'lucide-react'
import { analyzeAmlDemix, demixBridge, demixMixer } from '../api/client'
import CinematicStage from '../components/CinematicStage'
import ResultTabs from '../components/ResultTabs'
import { useTabParam } from '../hooks/useTabParam'
import type { AmlDemixResult, AmlTypology, DemixLink, DemixResult } from '../types'

type Tab = 'mixer' | 'bridge' | 'aml'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

function confColor(c: number) {
  if (c >= 0.85) return '#ff4052'
  if (c >= 0.68) return '#ff9f0a'
  if (c >= 0.45) return '#ffd60a'
  return '#9a858c'
}

function riskColor(level?: string) {
  if (level === 'critical') return '#ff4052'
  if (level === 'high') return '#ff7a18'
  if (level === 'medium') return '#ffd60a'
  return '#34D399'
}

function short(v: unknown, size = 16) {
  const s = String(v || '')
  if (!s) return '-'
  return s.length > size ? `${s.slice(0, 8)}...${s.slice(-4)}` : s
}

function parseInput(input: string): Record<string, unknown> {
  try {
    return JSON.parse(input)
  } catch {
    throw new Error('Input must be valid JSON')
  }
}

function CandidateRows({ link }: { link: DemixLink }) {
  return (
    <div className="mt-2 space-y-2">
      {link.candidates.map((candidate, i) => (
        <div key={i} className="rounded border border-bg-border/70 bg-bg-primary/40 p-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-mono text-[11px] text-text-primary">
              {short(candidate.deposit_tx || candidate.dest_tx || candidate.source_tx || candidate.tx_hash)}
            </span>
            <span className="font-mono text-[11px] font-bold" style={{ color: confColor(candidate.confidence) }}>
              {Math.round(candidate.confidence * 100)}%
            </span>
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[10px] text-text-muted">
            {Boolean(candidate.chain) && <span className="badge badge-muted">{String(candidate.chain)}</span>}
            {Boolean(candidate.dest_chain) && <span className="badge badge-muted">{String(candidate.dest_chain)}</span>}
            {Boolean(candidate.token) && <span className="badge badge-muted">{String(candidate.token)}</span>}
            {Boolean(candidate.dest_token_out) && <span className="badge badge-muted">{String(candidate.dest_token_out)}</span>}
            {candidate.time_gap_seconds != null && <span>{Number(candidate.time_gap_seconds).toLocaleString()}s gap</span>}
            {candidate.amount_diff_pct != null && <span>{Number(candidate.amount_diff_pct).toFixed(2)}% value delta</span>}
          </div>
          <ul className="mt-1 space-y-0.5">
            {candidate.reasons.map(reason => (
              <li key={reason} className="text-[10px] text-text-secondary">- {reason}</li>
            ))}
          </ul>
        </div>
      ))}
      {link.candidate_count === 0 && <p className="text-[11px] text-text-muted">No candidate matches.</p>}
    </div>
  )
}

function LinkCard({ link }: { link: DemixLink }) {
  const title = link.withdrawal_tx
    ? `Withdrawal ${short(link.withdrawal_tx)}`
    : link.source_tx
      ? `Source ${short(link.source_tx)}`
      : `Finding ${short(link.tx_hash || link.source_chain || link.chain)}`

  return (
    <div className="rounded-lg border border-bg-border bg-bg-secondary p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-mono text-xs text-text-primary">{title}</p>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[10px] text-text-muted">
            {Boolean(link.chain) && <span className="badge badge-muted">{String(link.chain)}</span>}
            {Boolean(link.source_chain) && <span className="badge badge-muted">{String(link.source_chain)}</span>}
            {Boolean(link.token) && <span className="badge badge-muted">{String(link.token)}</span>}
            {link.amount != null && <span>{Number(link.amount).toLocaleString()}</span>}
            {link.anonymity_set != null && <span>anon-set {String(link.anonymity_set)}</span>}
          </div>
        </div>
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-bold"
          style={{ color: confColor(link.best_confidence), background: `${confColor(link.best_confidence)}1a` }}
        >
          {Math.round(link.best_confidence * 100)}%
        </span>
      </div>
      <CandidateRows link={link} />
    </div>
  )
}

function RiskStrip({ result }: { result: DemixResult | AmlDemixResult }) {
  const risk = result.risk
  if (!risk) return null
  const color = riskColor(risk.level)
  const indicatorCount = 'indicator_count' in risk ? risk.indicator_count : risk.typology_count
  const chainCount = 'chain_count' in risk ? risk.chain_count : undefined
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <div className="rounded-lg border border-bg-border bg-bg-elevated p-3">
        <p className="text-[10px] uppercase tracking-widest text-text-muted">AML Risk</p>
        <p className="mt-1 text-2xl font-bold" style={{ color }}>{risk.score}/100</p>
      </div>
      <div className="rounded-lg border border-bg-border bg-bg-elevated p-3">
        <p className="text-[10px] uppercase tracking-widest text-text-muted">Level</p>
        <p className="mt-1 text-sm font-bold uppercase" style={{ color }}>{risk.level}</p>
      </div>
      <div className="rounded-lg border border-bg-border bg-bg-elevated p-3">
        <p className="text-[10px] uppercase tracking-widest text-text-muted">Indicators</p>
        <p className="mt-1 text-2xl font-bold text-text-primary">{indicatorCount ?? 0}</p>
      </div>
      <div className="rounded-lg border border-bg-border bg-bg-elevated p-3">
        <p className="text-[10px] uppercase tracking-widest text-text-muted">Chains</p>
        <p className="mt-1 text-2xl font-bold text-text-primary">{chainCount ?? '-'}</p>
      </div>
    </div>
  )
}

function TypologyPanel({ typologies = [] }: { typologies?: AmlTypology[] }) {
  if (!typologies.length) return null
  return (
    <div className="card">
      <p className="card-title flex items-center gap-2"><ShieldAlert size={12} /> Laundering Typologies</p>
      <div className="grid gap-3 md:grid-cols-2">
        {typologies.map(t => (
          <div key={`${t.code}-${t.title}`} className="rounded-lg border border-bg-border bg-bg-elevated p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-bold text-text-primary">{t.title}</p>
                <p className="mt-1 text-[11px] leading-relaxed text-text-secondary">{t.detail}</p>
              </div>
              <span className="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase" style={{ color: riskColor(t.severity), background: `${riskColor(t.severity)}18` }}>
                {t.severity}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {t.evidence.slice(0, 5).map(e => <span key={e} className="badge badge-muted font-mono">{short(e, 14)}</span>)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function DemixResultView({ result }: { result: DemixResult }) {
  return (
    <div className="space-y-4">
      <RiskStrip result={result} />
      <TypologyPanel typologies={result.typologies} />
      <div className="card">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <h3 className="text-sm font-bold uppercase tracking-widest text-text-primary">{result.method}</h3>
          <span className="rounded-full bg-neon-red/10 px-2 py-1 text-[10px] font-bold text-neon-red">
            {result.high_confidence_links} high-confidence links
          </span>
          <span className="text-xs text-text-muted">{result.links.length} total</span>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {result.links.map((l, i) => <LinkCard key={i} link={l} />)}
        </div>
        <p className="mt-4 text-[11px] italic text-text-muted">{result.disclaimer}</p>
      </div>
    </div>
  )
}

function AmlResultView({ result }: { result: AmlDemixResult }) {
  const mixer = result.components.mixer
  const bridge = result.components.bridge
  const chainSwaps = result.components.chain_swaps

  return (
    <div className="space-y-4">
      <RiskStrip result={result} />
      <div className="rounded-lg border border-neon-red/25 bg-neon-red/10 p-4">
        <p className="text-sm font-semibold text-text-primary">{result.summary}</p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <span className="rounded border border-bg-border bg-bg-primary/50 p-2 text-xs text-text-secondary">
            Mixer links: <b className="text-text-primary">{mixer?.high_confidence_links ?? 0}</b>
          </span>
          <span className="rounded border border-bg-border bg-bg-primary/50 p-2 text-xs text-text-secondary">
            Bridge links: <b className="text-text-primary">{bridge?.high_confidence_links ?? 0}</b>
          </span>
          <span className="rounded border border-bg-border bg-bg-primary/50 p-2 text-xs text-text-secondary">
            Chain swaps: <b className="text-text-primary">{chainSwaps.chain_swap_count}</b>
          </span>
        </div>
      </div>

      <TypologyPanel typologies={result.typologies} />

      <div className="card">
        <p className="card-title flex items-center gap-2"><BadgeCheck size={12} /> Analyst Next Steps</p>
        <div className="grid gap-2 md:grid-cols-2">
          {result.recommended_actions.map(action => (
            <div key={action} className="rounded-lg border border-bg-border bg-bg-elevated p-3 text-xs text-text-secondary">
              {action}
            </div>
          ))}
        </div>
      </div>

      {chainSwaps.links.length > 0 && (
        <div className="card">
          <p className="card-title flex items-center gap-2"><Network size={12} /> Chain-Swap Candidates</p>
          <div className="grid gap-3 md:grid-cols-2">
            {chainSwaps.links.map((l, i) => <LinkCard key={i} link={l} />)}
          </div>
        </div>
      )}

      {mixer && <DemixResultView result={mixer} />}
      {bridge && <DemixResultView result={bridge} />}
      <p className="text-[11px] italic text-text-muted">{result.disclaimer}</p>
    </div>
  )
}

const MIXER_SAMPLE = JSON.stringify({
  deposits: [
    { tx_hash: '0xdep1', chain: 'ETH', mixer_name: 'Tornado Cash', address: '0xaaa', funder: '0xfunder', token: 'ETH', amount: 1, pool: '1 ETH', timestamp: 1700000000, relayer: '0xrel' },
    { tx_hash: '0xdep2', chain: 'ETH', mixer_name: 'Tornado Cash', address: '0xbbb', token: 'ETH', amount: 1, pool: '1 ETH', timestamp: 1700000500 },
  ],
  withdrawals: [
    { tx_hash: '0xwd1', chain: 'ETH', mixer_name: 'Tornado Cash', recipient: '0xaaa', token: 'ETH', amount: 1, pool: '1 ETH', timestamp: 1700003600, relayer: '0xrel' },
  ],
}, null, 2)

const BRIDGE_SAMPLE = JSON.stringify({
  source_events: [
    { tx_hash: '0xsrc1', chain: 'ETH', dest_chain: 'BSC', protocol: 'Stargate Bridge', token: 'USDC', amount: 100000, timestamp: 1700000000, sender: '0xsource', recipient: '0xlayer' },
  ],
  dest_events: [
    { tx_hash: '0xdst1', chain: 'BSC', protocol: 'Stargate Bridge', token: 'USDC', amount: 99850, timestamp: 1700000900, sender: '0xbridge', recipient: '0xlayer' },
  ],
}, null, 2)

const AML_SAMPLE = JSON.stringify({
  deposits: [
    { tx_hash: '0xdep1', chain: 'ETH', mixer_name: 'Tornado Cash', address: '0xaaa', token: 'ETH', amount: 10, pool: '10 ETH', timestamp: 1700000000 },
  ],
  withdrawals: [
    { tx_hash: '0xwd1', chain: 'ETH', mixer_name: 'Tornado Cash', recipient: '0xlayer', token: 'ETH', amount: 10, pool: '10 ETH', timestamp: 1700007200 },
  ],
  source_events: [
    { tx_hash: '0xbr1', chain: 'ETH', dest_chain: 'ARB', protocol: 'Across Bridge', token: 'USDC', amount: 18000, timestamp: 1700009000, sender: '0xlayer', recipient: '0xlayer' },
  ],
  dest_events: [
    { tx_hash: '0xbr2', chain: 'ARB', protocol: 'Across Bridge', token: 'USDC', amount: 17920, timestamp: 1700010200, recipient: '0xlayer' },
  ],
  chain_events: [
    { tx_hash: '0xswap1', chain: 'ARB', event_type: 'swap', protocol: 'Uniswap', token: 'USDC', token_out: 'WETH', amount: 17920, timestamp: 1700010800, sender: '0xlayer', recipient: '0xlayer' },
    { tx_hash: '0xbr3', chain: 'ARB', dest_chain: 'BASE', event_type: 'bridge', protocol: 'Socket', token: 'WETH', amount: 5.4, timestamp: 1700011800, sender: '0xlayer', recipient: '0xlayer2' },
    { tx_hash: '0xswap2', chain: 'BASE', event_type: 'swap', protocol: '1inch', token: 'WETH', token_out: 'USDT', amount: 5.35, timestamp: 1700012600, sender: '0xlayer2', recipient: '0xexchangeDeposit' },
  ],
}, null, 2)

const TAB_COPY: Record<Tab, { icon: typeof Layers; label: string; sample: string; blurb: string }> = {
  mixer: {
    icon: Layers,
    label: 'Mixer Demix',
    sample: MIXER_SAMPLE,
    blurb: 'Link deposits to withdrawals across Tornado-style pools, tumblers, and CoinJoin-like batches.',
  },
  bridge: {
    icon: Waypoints,
    label: 'Bridge Reconcile',
    sample: BRIDGE_SAMPLE,
    blurb: 'Reconcile source-chain lock/burn events to destination-chain mint/unlock events.',
  },
  aml: {
    icon: Radar,
    label: 'AML Chain-Swap',
    sample: AML_SAMPLE,
    blurb: 'Detect mixer exits, bridge hops, asset swaps, and multi-chain laundering typologies in one report.',
  },
}

export default function DemixLab() {
  const { t } = useTranslation()
  const [tab, setTab] = useTabParam<Tab>('aml', ['mixer', 'bridge', 'aml'])
  const [input, setInput] = useState(() => TAB_COPY[tab].sample)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<DemixResult | AmlDemixResult | null>(null)

  const active = TAB_COPY[tab]
  const resultKind = useMemo(() => result?.method || '', [result])

  function switchTab(next: Tab) {
    setTab(next)
    setInput(TAB_COPY[next].sample)
    setError(null)
    setResult(null)
  }

  async function run() {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const payload = parseInput(input)
      if (tab === 'mixer') {
        setResult(await demixMixer(payload as { deposits: never[]; withdrawals: never[] }))
      } else if (tab === 'bridge') {
        setResult(await demixBridge(payload as { source_events: never[]; dest_events: never[] }))
      } else {
        setResult(await analyzeAmlDemix(payload))
      }
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="noscroll-page mx-auto max-w-7xl space-y-5 p-6">
      <div className="noscroll-grow card overflow-hidden p-0">
        <div className="flex flex-col gap-4 border-b border-bg-border p-5 lg:flex-row lg:items-center lg:justify-between" style={{ background: 'linear-gradient(135deg, rgba(255,64,82,0.16), rgba(255,159,10,0.08))' }}>
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-neon-red/35 bg-neon-red/10">
              <GitMerge size={22} className="text-neon-red" />
            </div>
            <div>
              <h1 className="text-display text-lg font-bold uppercase tracking-widest text-text-primary">{t('tools:demix.title')}</h1>
              <p className="mt-1 max-w-3xl text-sm text-text-secondary">
                Probabilistic demixing, bridge reconciliation, and chain-swap laundering detection for investigator review.
              </p>
            </div>
          </div>
          <ResultTabs
            active={tab}
            onChange={switchTab}
            tabs={(['mixer', 'bridge', 'aml'] as Tab[]).map(t => ({
              id: t, label: TAB_COPY[t].label, icon: TAB_COPY[t].icon,
            }))}
          />
        </div>

        <CinematicStage
          variant="demix"
          icon={GitMerge}
          collapsed={false}
        >
          <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <div className="space-y-3">
              <div className="rounded-lg border border-bg-border bg-bg-elevated p-3">
                <div className="flex items-center gap-2 text-sm font-semibold text-text-primary">
                  <active.icon size={15} className="text-neon-red" />
                  {active.label}
                </div>
                <p className="mt-1 text-xs leading-relaxed text-text-secondary">{active.blurb}</p>
              </div>
              <textarea
                className="input min-h-[420px] resize-y font-mono text-xs"
                value={input}
                onChange={e => setInput(e.target.value)}
                spellCheck={false}
              />
              <button className="btn-primary w-full justify-center" disabled={loading} onClick={run}>
                {loading ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                Run AML Analysis
              </button>
            </div>

            <div className="space-y-4">
              {error && (
                <div className="rounded-lg border border-neon-red/35 bg-neon-red/10 p-4 text-sm text-neon-red">
                  <AlertTriangle size={14} className="mr-2 inline" /> {error}
                </div>
              )}

              {!result && !error && (
                <div className="flex min-h-[520px] flex-col items-center justify-center rounded-lg border border-bg-border bg-bg-secondary p-8 text-center">
                  <Radar size={34} className="text-neon-red" />
                  <p className="mt-3 text-sm font-semibold text-text-primary">Ready for demixing analysis</p>
                  <p className="mt-1 max-w-md text-xs text-text-muted">
                    Paste normalized events from explorers, indexers, trace graphs, or bridge logs. The engine returns ranked leads with reasons and AML typologies.
                  </p>
                  <div className="mt-5 flex items-center gap-2 text-[11px] text-text-muted">
                    Mixer <ArrowRight size={11} /> Bridge <ArrowRight size={11} /> Swap <ArrowRight size={11} /> Cash-out
                  </div>
                </div>
              )}

              {result && resultKind === 'aml_laundering_detection' && <AmlResultView result={result as AmlDemixResult} />}
              {result && resultKind !== 'aml_laundering_detection' && <DemixResultView result={result as DemixResult} />}
            </div>
          </div>
        </CinematicStage>
      </div>
    </div>
  )
}
