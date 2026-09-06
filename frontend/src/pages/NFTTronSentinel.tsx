import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Activity, AlertTriangle, BadgeCheck, Boxes, Copy, ExternalLink, Fingerprint, Gem, GitBranch,
  ImageOff, Loader2, Network, Radar, Search, ShieldAlert, Sparkles, Users, Wallet, Zap,
} from 'lucide-react'
import { analyzeNFTTron } from '../api/client'
import CinematicStage from '../components/CinematicStage'
import ResultTabs from '../components/ResultTabs'
import TonProfilePanel from '../components/TonProfilePanel'
import { useTabParam } from '../hooks/useTabParam'
import type { NFTTronGraphNode, NFTTronResult, OpenSeaLookup, OpenSeaNFT } from '../types'

const CHAINS = ['auto', 'ton', 'evm', 'tron']

function short(value: string, n = 7) {
  return value.length > n * 2 + 3 ? `${value.slice(0, n)}...${value.slice(-n)}` : value
}

function money(value: number | undefined | null) {
  const n = Number(value || 0)
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

function riskColor(score: number) {
  if (score >= 80) return '#ff2d55'
  if (score >= 60) return '#ff9f0a'
  if (score >= 35) return '#ffd60a'
  return '#ff4052'
}

function severityColor(severity: string) {
  const s = severity.toUpperCase()
  if (s === 'HIGH' || s === 'CRITICAL') return '#ff2d55'
  if (s === 'MEDIUM') return '#ff9f0a'
  return '#ff4052'
}

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-lg border border-border bg-bg-secondary px-3 py-3">
      <p className="text-[10px] uppercase tracking-widest text-text-muted">{label}</p>
      <p className="mt-1 font-mono text-xl font-bold text-text-primary">{value}</p>
      {sub && <p className="mt-0.5 truncate text-[11px] text-text-muted">{sub}</p>}
    </div>
  )
}

function SentinelGraph({ result, onSelect }: { result: NFTTronResult; onSelect: (node: NFTTronGraphNode) => void }) {
  const visual = useMemo(() => {
    const nodes = result.graph.nodes.slice(0, 32)
    const positions: Record<string, { x: number; y: number }> = {}
    const center = nodes[0]
    if (center) positions[center.id] = { x: 450, y: 230 }
    nodes.slice(1).forEach((node, i) => {
      const ring = i < 12 ? 150 : 230
      const angle = (Math.PI * 2 * i) / Math.max(1, nodes.length - 1)
      positions[node.id] = { x: 450 + Math.cos(angle) * ring, y: 230 + Math.sin(angle) * ring * 0.72 }
    })
    return { nodes, edges: result.graph.edges.slice(0, 48), positions }
  }, [result])

  if (!visual.nodes.length) return null

  return (
    <div className="card overflow-hidden p-0">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <h3 className="text-sm font-bold uppercase tracking-widest text-text-primary">Sentinel Link Map</h3>
          <p className="text-xs text-text-muted">Subject, NFT collections, TRON counterparties, and lead relationships.</p>
        </div>
        <Network size={18} className="text-neon-cyan" />
      </div>
      <svg viewBox="0 0 900 460" className="block h-[460px] w-full bg-[#0a0608]">
        <defs>
          <filter id="sentinelGlow">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <g opacity="0.16">
          {Array.from({ length: 15 }).map((_, i) => <line key={`v${i}`} x1={i * 64} y1="0" x2={i * 64} y2="460" stroke="#3a1f28" />)}
          {Array.from({ length: 8 }).map((_, i) => <line key={`h${i}`} x1="0" y1={i * 64} x2="900" y2={i * 64} stroke="#3a1f28" />)}
        </g>
        {visual.edges.map((edge, i) => {
          const s = visual.positions[edge.source]
          const t = visual.positions[edge.target]
          if (!s || !t) return null
          return (
            <g key={`${edge.source}-${edge.target}-${i}`}>
              <line x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke="#ff4052" strokeOpacity="0.32" strokeWidth={Math.max(1, Math.min(5, edge.weight))} />
              <text x={(s.x + t.x) / 2} y={(s.y + t.y) / 2 - 4} fill="#9a858c" fontSize="10" textAnchor="middle">{edge.label}</text>
            </g>
          )
        })}
        {visual.nodes.map((node, i) => {
          const p = visual.positions[node.id]
          const color = riskColor(node.risk)
          const r = i === 0 ? 28 : 17 + Math.min(node.risk / 12, 8)
          return (
            <g key={node.id} transform={`translate(${p.x},${p.y})`} filter="url(#sentinelGlow)" onClick={() => onSelect(node)} className="cursor-pointer">
              <circle r={r} fill={color} fillOpacity={i === 0 ? 0.34 : 0.18} stroke={color} strokeWidth={i === 0 ? 2.5 : 1.5} />
              <text y={4} textAnchor="middle" fill="#e6f7ff" fontSize={i === 0 ? 11 : 9} fontWeight="700">{short(node.label, 6)}</text>
              <text y={r + 14} textAnchor="middle" fill="#9a858c" fontSize="9">{node.type}</text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function NodeDrawer({ node }: { node: NFTTronGraphNode | null }) {
  if (!node) return null
  return (
    <div className="card">
      <p className="text-[10px] uppercase tracking-widest text-text-muted">Selected lead</p>
      <p className="mt-1 break-all font-mono text-sm text-text-primary">{node.id}</p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Stat label="Type" value={node.type} />
        <Stat label="Risk" value={node.risk} />
      </div>
    </div>
  )
}

function priceTag(price: number, currency: string) {
  if (!price) return null
  return `${Number(price).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${currency || 'ETH'}`
}

function NFTCard({ nft }: { nft: OpenSeaNFT }) {
  const [broken, setBroken] = useState(false)
  const last = priceTag(nft.last_sale_price, nft.last_sale_currency)
  const current = priceTag(nft.current_price, nft.current_price_currency)
  const body = (
    <div className="group overflow-hidden rounded-lg border border-border bg-bg-secondary transition hover:border-neon-cyan/45">
      <div className="relative aspect-square w-full overflow-hidden bg-[#0c0709]">
        {nft.image_url && !broken ? (
          <img
            src={nft.image_url}
            alt={nft.name}
            loading="lazy"
            onError={() => setBroken(true)}
            className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-text-muted">
            <ImageOff size={26} />
          </div>
        )}
        {nft.rarity_rank ? (
          <span className="absolute left-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-bold text-neon-amber">
            #{nft.rarity_rank}
          </span>
        ) : null}
      </div>
      <div className="p-2">
        <p className="truncate text-xs font-semibold text-text-primary">{nft.name}</p>
        <p className="truncate text-[10px] text-text-muted">{nft.collection_name || short(nft.contract_address, 5)}</p>
        {(current || last) && (
          <p className="mt-1 truncate font-mono text-[10px] text-neon-cyan">
            {current ? `List ${current}` : `Last ${last}`}
          </p>
        )}
      </div>
    </div>
  )
  return nft.permalink ? (
    <a href={nft.permalink} target="_blank" rel="noreferrer" className="block">{body}</a>
  ) : body
}

function OpenSeaPanel({ data }: { data: OpenSeaLookup }) {
  const p = data.profile
  const hasNothing = !p && !data.nfts.length && !data.collections.length
  return (
    <div className="card overflow-hidden p-0">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <Gem size={16} className="text-neon-cyan" />
          <div>
            <h3 className="text-sm font-bold uppercase tracking-widest text-text-primary">OpenSea Live Lookup</h3>
            <p className="text-xs text-text-muted">
              Scraped from opensea.io on submit
              {data.degraded ? ' (profile-only fallback)' : ''}.
            </p>
          </div>
        </div>
        {data.profile_url && (
          <a href={data.profile_url} target="_blank" rel="noreferrer"
            className="flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-xs text-text-secondary hover:border-neon-cyan/40 hover:text-text-primary">
            View on OpenSea <ExternalLink size={12} />
          </a>
        )}
      </div>

      <div className="space-y-4 p-4">
        {data.error && (
          <div className="rounded-lg border border-neon-amber/40 bg-neon-amber/10 px-3 py-2 text-xs text-neon-amber">
            {data.error}
          </div>
        )}

        {p && (
          <div className="overflow-hidden rounded-lg border border-border bg-bg-secondary">
            {p.banner_image_url && (
              <div className="h-20 w-full bg-cover bg-center" style={{ backgroundImage: `url(${p.banner_image_url})` }} />
            )}
            <div className="flex items-start gap-3 p-3">
              <div className="h-14 w-14 shrink-0 overflow-hidden rounded-full border border-border bg-[#0c0709]">
                {p.profile_image_url ? (
                  <img src={p.profile_image_url} alt="" className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-text-muted"><Wallet size={18} /></div>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate font-bold text-text-primary">{p.display_name || p.username || short(p.address, 7)}</p>
                  {p.is_verified && <BadgeCheck size={15} className="shrink-0 text-neon-cyan" />}
                  {p.is_staff && <span className="rounded bg-neon-purple/15 px-1.5 py-0.5 text-[9px] font-bold text-neon-purple">STAFF</span>}
                </div>
                {p.username && p.display_name && <p className="truncate text-xs text-text-muted">@{p.username}</p>}
                {p.bio && <p className="mt-1 line-clamp-2 text-xs text-text-secondary">{p.bio}</p>}
                <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-text-muted">
                  <span className="inline-flex items-center gap-1"><Users size={11} /> {p.follower_count.toLocaleString()} followers</span>
                  <span>{p.following_count.toLocaleString()} following</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {p && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Portfolio" value={money(p.portfolio_value_usd)} sub="OpenSea est." />
            <Stat label="NFT %" value={`${Math.round((p.nft_percentage || 0) * 100)}%`} sub="of portfolio" />
            <Stat label="NFTs" value={data.counts.nfts} sub={`${data.counts.collections} collections`} />
            <Stat label="Activity" value={data.counts.events} sub="events scraped" />
          </div>
        )}

        {data.nfts.length > 0 && (
          <div>
            <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-text-muted">NFT Gallery</p>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6">
              {data.nfts.slice(0, 30).map(nft => (
                <NFTCard key={`${nft.contract_address}-${nft.token_id}-${nft.name}`} nft={nft} />
              ))}
            </div>
          </div>
        )}

        {data.collections.length > 0 && (
          <div>
            <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-text-muted">Collections</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {data.collections.slice(0, 12).map(col => (
                <div key={col.slug || col.name} className="flex items-center gap-3 rounded-lg border border-border bg-bg-secondary p-2">
                  <div className="h-9 w-9 shrink-0 overflow-hidden rounded bg-[#0c0709]">
                    {col.image_url && <img src={col.image_url} alt="" className="h-full w-full object-cover" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-semibold text-text-primary">{col.name}</p>
                    <p className="truncate text-[10px] text-text-muted">
                      {col.item_count ? `${col.item_count} owned` : ''}{col.floor_price ? ` · floor ${col.floor_price} ${col.floor_currency}` : ''}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {data.events.length > 0 && (
          <div>
            <p className="mb-2 flex items-center gap-1 text-[11px] font-bold uppercase tracking-widest text-text-muted">
              <Activity size={12} /> Recent Activity
            </p>
            <div className="space-y-1.5">
              {data.events.slice(0, 12).map((ev, i) => {
                const price = priceTag(ev.price, ev.currency)
                return (
                  <div key={`${ev.transaction_hash}-${i}`} className="flex items-center justify-between gap-3 rounded-lg border border-border bg-bg-secondary px-3 py-1.5 text-xs">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="rounded bg-neon-cyan/10 px-1.5 py-0.5 text-[10px] font-bold uppercase text-neon-cyan">{ev.event_type}</span>
                      <span className="truncate text-text-secondary">{ev.asset_name || short(ev.asset_token_id, 6)}</span>
                    </div>
                    <div className="flex shrink-0 items-center gap-2 text-text-muted">
                      {price && <span className="font-mono text-neon-green">{price}</span>}
                      {ev.transaction_hash && (
                        <a href={`https://etherscan.io/tx/${ev.transaction_hash}`} target="_blank" rel="noreferrer" className="hover:text-neon-cyan">
                          <ExternalLink size={11} />
                        </a>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {hasNothing && !data.error && (
          <p className="text-sm text-text-muted">
            OpenSea returned no public profile, NFTs, or activity for this address.
          </p>
        )}
      </div>
    </div>
  )
}

export default function NFTTronSentinel() {
  const { t } = useTranslation()
  const [subject, setSubject] = useState('')
  const [chain, setChain] = useState('auto')
  const [focus, setFocus] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<NFTTronResult | null>(null)
  const [selectedNode, setSelectedNode] = useState<NFTTronGraphNode | null>(null)
  const [activeTab, setActiveTab] = useTabParam<'investigation' | 'opensea'>(
    'investigation', ['investigation', 'opensea'])

  async function run() {
    const clean = subject.trim()
    if (!clean || loading) return
    setLoading(true)
    setError(null)
    setSelectedNode(null)
    try {
      const data = await analyzeNFTTron({ subject: clean, chain, focus })
      setResult(data)
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setLoading(false)
    }
  }

  function exportJSON() {
    if (!result) return
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `nft-tron-sentinel-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="noscroll-page mx-auto max-w-7xl space-y-5 p-6">
      <div className="mission-launch-stage grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="card overflow-hidden p-0">
          <div className="relative border-b border-border p-5" style={{ background: 'linear-gradient(135deg, rgba(255,64,82,0.12), rgba(255,59,107,0.08))' }}>
            <div className="flex items-start gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-neon-cyan/35 bg-neon-cyan/10">
                <Gem size={22} className="text-neon-cyan" />
              </div>
              <div>
                <h1 className="text-display text-lg font-bold uppercase tracking-widest text-text-primary">NFT / TON Sentinel</h1>
                <p className="mt-1 max-w-3xl text-sm text-text-secondary">
                  Paste a TON wallet or NFT address for a full TonViewer-style profile (balances, jettons, NFTs, activity), plus cybercrime leads for NFT theft, drainer approvals, wash-trading, and TRON/TRC20 laundering.
                </p>
              </div>
            </div>
          </div>
          <CinematicStage
            variant="nft"
            icon={Gem}
            collapsed={!!result}
          >
            <div className="space-y-3 p-4">
              <div className="grid gap-3 lg:grid-cols-[1fr_130px_auto]">
                <div className="relative">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
                  <input
                    className="input pl-9"
                    placeholder="TON address (EQ… / UQ…), NFT address, EVM wallet, TRON address, or tx hash..."
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') run() }}
                  />
                </div>
                <select className="input" value={chain} onChange={(e) => setChain(e.target.value)}>
                  {CHAINS.map(c => <option key={c} value={c}>{c.toUpperCase()}</option>)}
                </select>
                <button className="btn-primary" disabled={loading || !subject.trim()} onClick={run}>
                  {loading ? <Loader2 size={14} className="animate-spin" /> : <Radar size={14} />}
                  Launch Sentinel
                </button>
              </div>
              <textarea
                className="input min-h-[72px] resize-y text-sm"
                placeholder="Optional focus: stolen BAYC, fake mint, TRC20 cashout, phishing drainer, wash-trading loop..."
                value={focus}
                onChange={(e) => setFocus(e.target.value)}
              />
            </div>
          </CinematicStage>
        </div>

        <div className="card">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-neon-amber" />
            <h2 className="text-sm font-bold uppercase tracking-widest text-text-primary">Core Algorithms</h2>
          </div>
          <div className="mt-3 space-y-2 text-xs text-text-secondary">
            {[
              'NFT approval drainer patterning',
              'Stolen token-ID custody timeline leads',
              'Wash-trade loop and price anomaly triage',
              'TRON/TRC20 velocity and fan-out scoring',
              'OSINT pivots for marketplaces, social reports, code leaks, and explorers',
            ].map(item => (
              <div key={item} className="flex items-start gap-2 rounded-lg border border-border bg-bg-secondary/60 px-3 py-2">
                <Zap size={12} className="mt-0.5 shrink-0 text-neon-cyan" />
                <span>{item}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {loading && (
        <div className="card">
          <div className="flex items-center gap-4">
            <Loader2 size={30} className="animate-spin text-neon-amber" />
            <div className="flex-1">
              <p className="font-semibold text-text-primary">Running NFT/TRON cybercrime investigation</p>
              <p className="mt-1 text-sm text-text-muted">Classifying subject, querying public telemetry, scoring local motifs, and generating OSINT pivots.</p>
              <div className="mt-3 h-2 overflow-hidden rounded-full border border-border bg-bg-secondary">
                <div className="h-full w-2/3 animate-pulse rounded-full" style={{ background: 'linear-gradient(90deg, #ff3b6b, #ff4052, #00ff88)' }} />
              </div>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-neon-red/35 bg-neon-red/10 p-4 text-sm text-neon-red">
          {error}
        </div>
      )}

      {result && (
        <div className="noscroll-grow space-y-5">
          <div className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
            <div className="card">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[10px] uppercase tracking-widest text-text-muted">Sentinel Risk</p>
                  <p className="text-3xl font-black text-text-primary">{result.risk_level}</p>
                </div>
                <div className="flex h-20 w-20 items-center justify-center rounded-full border text-2xl font-black"
                  style={{ color: riskColor(result.risk_score), borderColor: riskColor(result.risk_score), background: `${riskColor(result.risk_score)}14` }}>
                  {result.risk_score}
                </div>
              </div>
              <p className="mt-4 text-sm text-text-secondary">{result.summary.assessment}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <span className="badge">{result.classification.chain}</span>
                <span className="badge">{result.classification.kind}</span>
                <span className={result.classification.valid ? 'badge-success' : 'badge-warning'}>
                  {result.classification.valid ? 'validated' : 'needs review'}
                </span>
              </div>
              <div className="mt-4 flex gap-2">
                <button className="btn-ghost text-xs" onClick={() => navigator.clipboard?.writeText(result.subject)}>
                  <Copy size={13} /> Copy Subject
                </button>
                <button className="btn-ghost text-xs" onClick={exportJSON}>
                  <GitBranch size={13} /> Export JSON
                </button>
              </div>
            </div>

            {!result.ton_profile && (
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                <Stat label="NFTs" value={result.nft.metrics.nft_count} sub={`${result.nft.metrics.collection_count} collections`} />
                <Stat label="NFT Floor" value={money(result.nft.metrics.estimated_floor_value_usd)} sub="public estimate" />
                <Stat label="TRX Balance" value={result.tron.metrics.native_balance_trx} sub="TRON native" />
                <Stat label="TRC20 TX" value={result.tron.metrics.trc20_count} sub={`${result.tron.metrics.usdt_transfer_count} USDT`} />
                <Stat label="Fan-out" value={result.tron.metrics.unique_counterparties} sub="counterparties" />
                <Stat label="Contract Calls" value={result.tron.metrics.contract_call_count} sub="TRON triggers" />
              </div>
            )}
            {result.ton_profile && (
              <div className="rounded-lg border border-border bg-bg-secondary/60 p-3 text-xs text-text-secondary">
                Live TON profile resolved from tonapi.io. Balances, jettons, NFTs, and activity below mirror TonViewer;
                risk signals are local investigative leads.
              </div>
            )}
          </div>

          {/* ── TON (TonViewer-style) profile view ── */}
          {result.ton_profile && (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
              <div className="space-y-4">
                <TonProfilePanel ton={result.ton_profile} />
              </div>
              <div className="space-y-4">
                <div className="card">
                  <div className="mb-3 flex items-center gap-2">
                    <ShieldAlert size={16} className="text-neon-red" />
                    <h3 className="text-sm font-bold uppercase tracking-widest text-text-primary">TON Risk Signals</h3>
                  </div>
                  <div className="space-y-3">
                    {result.signals.map((signal, i) => (
                      <div key={`${signal.title}-${i}`} className="rounded-lg border bg-bg-secondary p-3" style={{ borderColor: `${severityColor(signal.severity)}55` }}>
                        <div className="flex items-start justify-between gap-3">
                          <p className="font-semibold text-text-primary">{signal.title}</p>
                          <span className="rounded-full px-2 py-1 text-[10px] font-bold" style={{ color: severityColor(signal.severity), background: `${severityColor(signal.severity)}18` }}>{signal.severity}</span>
                        </div>
                        <p className="mt-1 text-xs text-text-secondary">{signal.detail}</p>
                        {signal.evidence.map(ev => <p key={ev} className="mt-1 text-[11px] text-text-muted">- {ev}</p>)}
                      </div>
                    ))}
                  </div>
                </div>
                <div className="card">
                  <div className="mb-3 flex items-center gap-2">
                    <ExternalLink size={16} className="text-neon-green" />
                    <h3 className="text-sm font-bold uppercase tracking-widest text-text-primary">Explorers & Pivots</h3>
                  </div>
                  <div className="space-y-2">
                    {result.osint_pivots.filter(p => p.url).map(pivot => (
                      <a key={`${pivot.kind}-${pivot.url}`} href={pivot.url} target="_blank" rel="noreferrer"
                        className="flex items-center justify-between gap-3 rounded-lg border border-border bg-bg-secondary px-3 py-2 text-xs text-text-secondary hover:border-neon-cyan/40 hover:text-text-primary">
                        <span>{pivot.title}</span><ExternalLink size={12} />
                      </a>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {!result.ton_profile && (<>
          <ResultTabs
            active={activeTab}
            onChange={setActiveTab}
            tabs={[
              { id: 'investigation', label: 'Investigation', icon: ShieldAlert, count: result.signals.length },
              { id: 'opensea', label: 'OpenSea Profile', icon: Gem, count: result.nft.metrics.nft_count },
            ]}
          />

          {activeTab === 'opensea' && (
            result.opensea
              ? <OpenSeaPanel data={result.opensea} />
              : <div className="card"><p className="text-sm text-text-muted">No public OpenSea profile telemetry for this subject.</p></div>
          )}

          {activeTab === 'investigation' && (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="space-y-4">
              <div className="card">
                <div className="mb-3 flex items-center gap-2">
                  <ShieldAlert size={16} className="text-neon-red" />
                  <h3 className="text-sm font-bold uppercase tracking-widest text-text-primary">Crime Signals</h3>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  {result.signals.map((signal, i) => (
                    <div key={`${signal.title}-${i}`} className="rounded-lg border bg-bg-secondary p-3" style={{ borderColor: `${severityColor(signal.severity)}55` }}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="font-semibold text-text-primary">{signal.title}</p>
                          <p className="mt-1 text-xs text-text-secondary">{signal.detail}</p>
                        </div>
                        <span className="rounded-full px-2 py-1 text-[10px] font-bold" style={{ color: severityColor(signal.severity), background: `${severityColor(signal.severity)}18` }}>
                          {signal.severity}
                        </span>
                      </div>
                      <div className="mt-3 space-y-1">
                        {signal.evidence.map(ev => (
                          <p key={ev} className="text-[11px] text-text-muted">- {ev}</p>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <SentinelGraph result={result} onSelect={setSelectedNode} />

              <div className="card">
                <div className="mb-3 flex items-center gap-2">
                  <Boxes size={16} className="text-neon-cyan" />
                  <h3 className="text-sm font-bold uppercase tracking-widest text-text-primary">NFT Collection Leads</h3>
                </div>
                {result.nft.collections.length === 0 ? (
                  <p className="text-sm text-text-muted">No NFT collection telemetry returned. Use the OSINT pivots and transaction evidence to continue manually.</p>
                ) : (
                  <div className="grid gap-3 md:grid-cols-2">
                    {result.nft.collections.map(col => (
                      <div key={col.id} className="rounded-lg border border-border bg-bg-secondary p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="truncate font-semibold text-text-primary">{col.name}</p>
                            <p className="break-all font-mono text-[11px] text-text-muted">{col.id}</p>
                          </div>
                          <span className="rounded-full bg-neon-cyan/10 px-2 py-1 text-xs font-bold text-neon-cyan">{col.count}</span>
                        </div>
                        <p className="mt-2 text-xs text-text-secondary">Max observed floor: <span className="font-mono text-text-primary">{money(col.floor_usd)}</span></p>
                        <div className="mt-2 flex flex-wrap gap-1">
                          {col.sample_tokens.map(t => (
                            <span key={`${t.contract}-${t.token_id}`} className="rounded border border-border px-2 py-0.5 text-[10px] text-text-muted">{t.name}</span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="space-y-4">
              <NodeDrawer node={selectedNode} />
              <div className="card">
                <div className="mb-3 flex items-center gap-2">
                  <Fingerprint size={16} className="text-neon-amber" />
                  <h3 className="text-sm font-bold uppercase tracking-widest text-text-primary">Crime Motifs</h3>
                </div>
                <div className="space-y-3">
                  {result.motifs.map(motif => (
                    <div key={motif.id} className="rounded-lg border border-border bg-bg-secondary p-3">
                      <div className="flex items-center justify-between gap-2">
                        <p className="font-semibold text-text-primary">{motif.title}</p>
                        <span className="font-mono text-xs text-neon-cyan">{Math.round(motif.relevance * 100)}%</span>
                      </div>
                      <p className="mt-1 text-xs text-text-secondary">{motif.logic}</p>
                      <div className="mt-2 space-y-1">
                        {motif.next_steps.slice(0, 2).map(step => <p key={step} className="text-[11px] text-text-muted">- {step}</p>)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card">
                <div className="mb-3 flex items-center gap-2">
                  <ExternalLink size={16} className="text-neon-green" />
                  <h3 className="text-sm font-bold uppercase tracking-widest text-text-primary">OSINT Pivots</h3>
                </div>
                <div className="space-y-2">
                  {result.osint_pivots.map(pivot => (
                    <a key={`${pivot.kind}-${pivot.url}`} href={pivot.url} target="_blank" rel="noreferrer"
                      className="flex items-center justify-between gap-3 rounded-lg border border-border bg-bg-secondary px-3 py-2 text-xs text-text-secondary hover:border-neon-cyan/40 hover:text-text-primary">
                      <span>{pivot.title}</span>
                      <ExternalLink size={12} />
                    </a>
                  ))}
                </div>
              </div>

              <div className="card">
                <div className="mb-3 flex items-center gap-2">
                  <AlertTriangle size={16} className="text-neon-amber" />
                  <h3 className="text-sm font-bold uppercase tracking-widest text-text-primary">Playbook</h3>
                </div>
                <div className="space-y-2">
                  {result.investigation_playbook.map(step => (
                    <p key={step} className="rounded-lg border border-border bg-bg-secondary px-3 py-2 text-xs text-text-secondary">{step}</p>
                  ))}
                </div>
              </div>
            </div>
          </div>
          )}
          </>)}
        </div>
      )}
    </div>
  )
}
