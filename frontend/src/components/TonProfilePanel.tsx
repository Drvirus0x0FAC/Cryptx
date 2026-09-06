/**
 * TonProfilePanel - TonViewer-style rendering of a TON wallet or NFT address.
 * Account header + balances, then Tokens / NFTs / Activity tabs, or full NFT-item detail.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  BadgeCheck, Copy, ExternalLink, Coins, Image as ImageIcon, Activity,
  ShieldAlert, Wallet, Gem, AlertTriangle, Check, Globe, Tag, Layers, TrendingUp, Hash,
} from 'lucide-react'
import type { TonProfile, TonJetton, TonNft, TonEvent, TonScanProfile, TonScanNftItem } from '../types'

function short(v: string, n = 6) {
  return v && v.length > n * 2 + 2 ? `${v.slice(0, n)}…${v.slice(-n)}` : v
}
function usd(n: number | null | undefined) {
  if (n == null) return '-'
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}
function ago(ts: number) {
  if (!ts) return ''
  const s = Math.floor(Date.now() / 1000) - ts
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function CopyBtn({ value }: { value: string }) {
  const [done, setDone] = useState(false)
  if (!value) return null
  return (
    <button className="text-text-muted hover:text-neon-cyan" title="Copy"
      onClick={() => { navigator.clipboard?.writeText(value); setDone(true); setTimeout(() => setDone(false), 1200) }}>
      {done ? <Check size={11} /> : <Copy size={11} />}
    </button>
  )
}

function TokenIcon({ src, fallback }: { src?: string; fallback: React.ReactNode }) {
  const [err, setErr] = useState(false)
  if (!src || err) return <div className="flex items-center justify-center h-full w-full text-text-muted">{fallback}</div>
  return <img src={src} alt="" className="h-full w-full object-cover" loading="lazy" onError={() => setErr(true)} />
}

export default function TonProfilePanel({ ton }: { ton: TonProfile }) {
  const { t } = useTranslation()
  const [tab, setTab] = useState<'tokens' | 'nfts' | 'activity'>(
    ton.kind === 'nft_item' ? 'activity' : (ton.jettons.length ? 'tokens' : ton.nfts.length ? 'nfts' : 'activity'))
  const a = ton.account
  const item = ton.nft_item

  return (
    <div className="space-y-4">
      {/* ── Account header ── */}
      <div className="card overflow-hidden p-0">
        <div className="border-b border-border p-4" style={{ background: 'linear-gradient(135deg, rgba(0,152,234,0.14), rgba(10,132,255,0.06))' }}>
          <div className="flex items-start gap-4">
            <div className="h-14 w-14 shrink-0 overflow-hidden rounded-full border border-neon-cyan/30 bg-bg-secondary">
              <TokenIcon src={a.icon} fallback={<Wallet size={22} />} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate text-lg font-bold text-text-primary">{a.name || short(ton.address.given, 10)}</h2>
                {a.is_scam && (
                  <span className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold" style={{ background: 'rgba(255,45,85,0.16)', color: '#ff2d55' }}>
                    <ShieldAlert size={10} /> SCAM
                  </span>
                )}
                <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider" style={{ background: 'rgba(0,152,234,0.16)', color: '#4aa3ff' }}>
                  {ton.kind.replace('_', ' ')}
                </span>
                <span className={`rounded-full px-2 py-0.5 text-[10px] ${a.status === 'active' ? 'text-emerald-400' : 'text-amber-400'}`}
                  style={{ background: 'var(--bg-secondary)' }}>{a.status}</span>
                {ton.address.testnet && <span className="rounded-full px-2 py-0.5 text-[10px] text-amber-300" style={{ background: 'rgba(255,159,10,0.14)' }}>testnet</span>}
              </div>
              <div className="mt-2 space-y-1 font-mono text-[11px] text-text-secondary">
                <div className="flex items-center gap-1.5"><span className="text-text-muted">bounceable</span> {short(ton.address.bounceable || ton.address.given, 10)} <CopyBtn value={ton.address.bounceable || ton.address.given} /></div>
                {ton.address.raw && <div className="flex items-center gap-1.5"><span className="text-text-muted">raw</span> {short(ton.address.raw, 8)} <CopyBtn value={ton.address.raw} /></div>}
              </div>
            </div>
            <a href={ton.explorer} target="_blank" rel="noreferrer noopener"
              className="flex shrink-0 items-center gap-1 rounded-md border border-border px-2.5 py-1.5 text-[11px] text-neon-cyan hover:border-neon-cyan/50">
              TonViewer <ExternalLink size={11} />
            </a>
          </div>
        </div>
        {/* balances */}
        <div className="grid grid-cols-2 gap-px bg-bg-border md:grid-cols-4">
          {[
            { label: 'TON Balance', value: `${a.balance_ton.toLocaleString(undefined, { maximumFractionDigits: 4 })}`, sub: usd(a.balance_usd) },
            { label: 'Portfolio', value: usd(ton.totals.portfolio_usd), sub: 'TON + jettons' },
            { label: 'Jettons', value: String(ton.totals.jetton_count), sub: usd(ton.totals.jetton_value_usd) },
            { label: 'NFTs', value: String(ton.totals.nft_count), sub: ton.kind === 'nft_item' ? 'this item' : 'held' },
          ].map((s) => (
            <div key={s.label} className="bg-bg-primary px-4 py-3">
              <p className="text-[10px] uppercase tracking-widest text-text-muted">{s.label}</p>
              <p className="mt-1 font-mono text-lg font-bold text-text-primary">{s.value}</p>
              <p className="text-[11px] text-text-muted">{s.sub}</p>
            </div>
          ))}
        </div>
      </div>

      {/* ── TONScan enrichment (tonscan.com) ── */}
      {ton.tonscan && <TonScanSection tonscan={ton.tonscan} />}

      {/* ── NFT item detail (when the subject IS an NFT) ── */}
      {item && !item.error && (
        <div className="card p-0 overflow-hidden">
          <div className="grid gap-0 md:grid-cols-[280px_1fr]">
            <div className="aspect-square bg-bg-secondary">
              <TokenIcon src={item.image} fallback={<Gem size={40} />} />
            </div>
            <div className="p-4 space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-lg font-bold text-text-primary flex items-center gap-2">
                    {item.name}
                    {item.verified && <BadgeCheck size={16} className="text-neon-cyan" />}
                  </h3>
                  <p className="text-xs text-text-muted">{item.collection.name}
                    {item.collection.address && <CopyBtn value={item.collection.address} />}
                  </p>
                </div>
                {item.on_sale && item.sale_price && (
                  <span className="rounded-md px-2 py-1 text-xs font-bold text-emerald-400" style={{ background: 'rgba(34,197,120,0.14)' }}>
                    On sale · {item.sale_price}
                  </span>
                )}
              </div>
              {item.description && <p className="text-xs text-text-secondary line-clamp-3">{item.description}</p>}
              <div className="flex flex-wrap gap-3 text-[11px] text-text-muted">
                <span>Owner: <span className="font-mono text-text-secondary">{item.owner.name || short(item.owner.address, 6)}</span></span>
                <span>Trust: {item.trust}</span>
                {item.dns && <span>DNS: {item.dns}</span>}
              </div>
              {item.attributes.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-1">
                  {item.attributes.map((at, i) => (
                    <div key={i} className="rounded-md border border-border bg-bg-secondary px-2 py-1">
                      <p className="text-[9px] uppercase tracking-wider text-text-muted">{at.trait}</p>
                      <p className="text-[11px] text-text-primary">{String(at.value)}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {item?.error && (
        <div className="card text-xs text-text-muted flex items-center gap-2"><AlertTriangle size={13} className="text-amber-400" /> NFT item metadata unavailable ({item.error}).</div>
      )}

      {/* ── Tabs: Tokens / NFTs / Activity (wallets) ── */}
      {!item && (
        <>
          <div className="flex gap-1 rounded-lg border border-border bg-bg-secondary/60 p-1 text-xs">
            {([['tokens', Coins, `Tokens ${ton.jettons.length}`], ['nfts', ImageIcon, `NFTs ${ton.nfts.length}`], ['activity', Activity, `Activity ${ton.events.length}`]] as const).map(([id, Icon, label]) => (
              <button key={id} onClick={() => setTab(id)}
                className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 transition-colors ${tab === id ? 'bg-bg-elevated text-text-primary' : 'text-text-muted hover:text-text-secondary'}`}>
                <Icon size={13} /> {label}
              </button>
            ))}
          </div>

          {tab === 'tokens' && <JettonTable jettons={ton.jettons} />}
          {tab === 'nfts' && <NftGrid nfts={ton.nfts} />}
          {tab === 'activity' && <EventList events={ton.events} />}
        </>
      )}
      {item && <EventList events={ton.events} />}
    </div>
  )
}

function JettonTable({ jettons }: { jettons: TonJetton[] }) {
  if (!jettons.length) return <div className="card text-center py-8 text-xs text-text-muted">No jetton (token) balances.</div>
  return (
    <div className="card p-0 overflow-hidden">
      {jettons.map((j) => (
        <div key={j.address} className="flex items-center gap-3 border-b border-border/60 px-4 py-2.5 last:border-0">
          <div className="h-8 w-8 shrink-0 overflow-hidden rounded-full bg-bg-secondary">
            <TokenIcon src={j.image} fallback={<Coins size={14} />} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
              {j.symbol}
              {j.verification === 'whitelist' && <BadgeCheck size={12} className="text-neon-cyan" />}
              {j.verification === 'none' && <span className="text-[9px] text-amber-400">unverified</span>}
            </p>
            <p className="truncate text-[11px] text-text-muted">{j.name}</p>
          </div>
          <div className="text-right">
            <p className="font-mono text-sm text-text-primary">{j.balance.toLocaleString(undefined, { maximumFractionDigits: 4 })}</p>
            <p className="text-[11px] text-text-muted">{j.value_usd != null ? usd(j.value_usd) : '-'}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

function NftGrid({ nfts }: { nfts: TonNft[] }) {
  if (!nfts.length) return <div className="card text-center py-8 text-xs text-text-muted">No NFTs held by this account.</div>
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
      {nfts.map((n) => (
        <a key={n.address} href={`https://tonviewer.com/${n.address}`} target="_blank" rel="noreferrer noopener"
          className="card p-0 overflow-hidden group hover:border-neon-cyan/40">
          <div className="aspect-square bg-bg-secondary"><TokenIcon src={n.image} fallback={<Gem size={26} />} /></div>
          <div className="p-2">
            <p className="flex items-center gap-1 truncate text-[11px] font-semibold text-text-primary">
              {n.verified && <BadgeCheck size={10} className="shrink-0 text-neon-cyan" />}{n.name}
            </p>
            <p className="truncate text-[10px] text-text-muted">{n.collection}</p>
          </div>
        </a>
      ))}
    </div>
  )
}

function EventList({ events }: { events: TonEvent[] }) {  if (!events.length) return <div className="card text-center py-8 text-xs text-text-muted">No recent on-chain activity.</div>
  return (
    <div className="card p-0 overflow-hidden">
      {events.map((e) => (
        <div key={e.event_id} className="flex items-start gap-3 border-b border-border/60 px-4 py-2.5 last:border-0"
          style={e.is_scam ? { borderLeft: '3px solid #ff2d55' } : undefined}>
          <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-bg-secondary">
            <Activity size={13} className={e.is_scam ? 'text-red-400' : 'text-neon-cyan'} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-2 text-xs font-semibold text-text-primary">
              {e.type}
              {e.is_scam && <span className="text-[9px] text-red-400">SCAM</span>}
              {e.action_count > 1 && <span className="text-[9px] text-text-muted">+{e.action_count - 1} more</span>}
            </p>
            <p className="truncate text-[11px] text-text-secondary">{e.description}</p>
            {e.counterparties.length > 0 && (
              <p className="mt-0.5 truncate font-mono text-[10px] text-text-muted">
                {e.counterparties.map((c) => c.name || short(c.address, 5)).join(', ')}
              </p>
            )}
          </div>
          <div className="shrink-0 text-right">
            {e.value && <p className="font-mono text-[11px] text-text-primary">{e.value}</p>}
            <p className="text-[10px] text-text-muted">{ago(e.timestamp)}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── TONScan section: data scraped live from tonscan.com ────────────────────────
function TonScanSection({ tonscan }: { tonscan: TonScanProfile }) {
  const ts = tonscan
  const hasStats = !!(ts.tonscan_floor_price || ts.tonscan_volume || ts.tonscan_balance)
  const hasItems = ts.tonscan_nft_items.length > 0 || ts.tonscan_nft_images.length > 0

  // Merge images into items for rendering (item may lack an image)
  const items: TonScanNftItem[] = ts.tonscan_nft_items.length
    ? ts.tonscan_nft_items
    : ts.tonscan_nft_images.map((image, i) => ({ name: `NFT #${i + 1}`, image, sale_status: 'unknown', last_sale_ton: null }))

  return (
    <div className="card overflow-hidden p-0" style={{ borderColor: 'rgba(0,152,234,0.28)' }}>
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5"
        style={{ background: 'linear-gradient(135deg, rgba(0,152,234,0.10), rgba(10,132,255,0.04))' }}>
        <div className="flex items-center gap-2">
          <Globe size={14} className="text-neon-cyan" />
          <h3 className="text-xs font-bold uppercase tracking-widest text-text-primary">TONScan Profile</h3>
          <span className="rounded-full px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-text-muted"
            style={{ background: 'var(--bg-secondary)' }}>
            {ts.tonscan_entity_type || 'entity'}
          </span>
        </div>
        <a href={ts.tonscan_url} target="_blank" rel="noreferrer noopener"
          className="flex items-center gap-1 text-[11px] text-neon-cyan hover:underline">
          tonscan.com <ExternalLink size={11} />
        </a>
      </div>

      <div className="space-y-3 p-4">
        {/* Identity row */}
        {(ts.tonscan_name || ts.tonscan_dns) && (
          <div className="flex flex-wrap items-center gap-2">
            {ts.tonscan_name && (
              <span className="text-sm font-bold text-text-primary">{ts.tonscan_name}</span>
            )}
            {ts.tonscan_dns && (
              <span className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold"
                style={{ background: 'rgba(0,152,234,0.14)', color: '#4aa3ff' }}>
                <Globe size={10} /> {ts.tonscan_dns}
              </span>
            )}
          </div>
        )}

        {ts.tonscan_description && (
          <p className="text-xs text-text-secondary line-clamp-3">{ts.tonscan_description}</p>
        )}

        {/* Stats grid */}
        {hasStats && (
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {ts.tonscan_balance && (
              <StatChip icon={<Wallet size={11} />} label="Balance" value={ts.tonscan_balance} />
            )}
            {ts.tonscan_floor_price && (
              <StatChip icon={<Tag size={11} />} label="Floor Price" value={ts.tonscan_floor_price} />
            )}
            {ts.tonscan_volume && (
              <StatChip icon={<TrendingUp size={11} />} label="Volume" value={ts.tonscan_volume} />
            )}
            {ts.tonscan_contract_hash && (
              <StatChip icon={<Hash size={11} />} label="Contract"
                value={short(ts.tonscan_contract_hash, 6)} />
            )}
          </div>
        )}

        {/* Interfaces */}
        {ts.tonscan_interfaces.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <Layers size={11} className="text-text-muted" />
            {ts.tonscan_interfaces.map((iface) => (
              <span key={iface} className="rounded-md px-1.5 py-0.5 text-[10px] font-mono text-text-secondary"
                style={{ background: 'var(--bg-secondary)' }}>
                {iface}
              </span>
            ))}
          </div>
        )}

        {/* Contract hash with copy */}
        {ts.tonscan_contract_hash && (
          <div className="flex items-center gap-1.5 font-mono text-[11px] text-text-muted">
            <span className="text-text-muted">contract:</span>
            <span className="text-text-secondary">{short(ts.tonscan_contract_hash, 10)}</span>
            <CopyBtn value={ts.tonscan_contract_hash} />
          </div>
        )}

        {/* NFT items grid */}
        {hasItems && (
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-text-muted">
              <ImageIcon size={11} /> NFT Items ({items.length})
            </p>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
              {items.slice(0, 24).map((n, i) => (
                <div key={i} className="card p-0 overflow-hidden">
                  <div className="relative aspect-square bg-bg-secondary">
                    {n.image ? (
                      <TokenIcon src={n.image} fallback={<Gem size={18} />} />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-text-muted">
                        <Gem size={18} />
                      </div>
                    )}
                    {n.sale_status === 'for_sale' && (
                      <span className="absolute right-1 top-1 rounded px-1 py-0.5 text-[8px] font-bold text-emerald-300"
                        style={{ background: 'rgba(34,197,120,0.22)' }}>SALE</span>
                    )}
                    {n.sale_status === 'sold' && (
                      <span className="absolute right-1 top-1 rounded px-1 py-0.5 text-[8px] font-bold text-amber-300"
                        style={{ background: 'rgba(245,158,11,0.22)' }}>SOLD</span>
                    )}
                  </div>
                  <p className="truncate px-1.5 py-1 text-[9px] text-text-secondary">{n.name}</p>
                  {typeof n.last_sale_ton === 'number' && n.last_sale_ton > 0 && (
                    <p className="px-1.5 pb-1 text-[9px] font-mono text-text-muted">
                      last: {n.last_sale_ton.toLocaleString(undefined, { maximumFractionDigits: 2 })} TON
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        <p className="text-[9px] text-text-muted">
          Data scraped live from tonscan.com (public). Marketplace prices and sale status are
          indicative — verify on-chain before evidentiary use.
        </p>
      </div>
    </div>
  )
}

function StatChip({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-bg-secondary px-2.5 py-2">
      <p className="flex items-center gap-1 text-[9px] uppercase tracking-wider text-text-muted">
        {icon} {label}
      </p>
      <p className="mt-0.5 truncate font-mono text-[12px] font-semibold text-text-primary">{value}</p>
    </div>
  )
}
