/**
 * BlockchainThreatLandscape — comprehensive crypto threat intelligence hub.
 *
 * Tabs:
 *   1. News — aggregated RSS/Atom feeds from curated crypto security sources
 *   2. Incidents — live ransomware extortion incidents (ransomware.live + ransomlook)
 *   3. Threat Actors — comprehensive profiles with crypto wallets, TTPs, victim data
 *   4. Gang Profiles — ransomware group profiles with TTPs, leak sites
 *   5. Address Intel — all tracked crypto addresses with actor attribution
 *   6. Intel Dashboard — unified threat intelligence dashboard with stats
 *
 * Detail routes:
 *   /threat-landscape/:id        → news article detail
 *   /threat-landscape/group/:name → ransomware group detail
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ShieldAlert, RefreshCw, Loader2, ExternalLink, ArrowLeft, Clock,
  AlertTriangle, Rss, User, CalendarDays, Search, CheckCircle2, XCircle,
  Skull, Target, Newspaper, BarChart3, Globe, Bitcoin, Copy, ChevronDown,
  ChevronUp, Crosshair, Activity, TrendingUp, Users, Zap, Wallet,
  DollarSign, Database, Filter,
} from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getThreatFeedNews, getThreatFeedItem,
  getRansomwareGroups, getRansomwareIncidents, getRansomwareStats,
  getRansomwareFeed, getRansomwareGroupDetail, searchRansomware,
  getThreatActors, getThreatActorDetail, getAddressIntel,
  getThreatBaseline, refreshThreatData, getThreatRefreshStatus,
} from '../api/client'
import type {
  ThreatFeedItem, ThreatFeedSource,
  RansomwareGroup, RansomwareIncident, RansomwareStats,
  ThreatActorProfile, AddressIntelEntry, CryptoAddresses, CryptoWallet,
  ThreatBaselineResponse,
} from '../types'

/* ── Tab definitions ─────────────────────────────────────────────────────────── */
type TabId = 'news' | 'incidents' | 'actors' | 'gangs' | 'addresses' | 'feed'
const TABS: { id: TabId; label: string; icon: typeof Newspaper }[] = [
  { id: 'news', label: 'Threat News', icon: Newspaper },
  { id: 'incidents', label: 'Incidents', icon: Skull },
  { id: 'actors', label: 'Threat Actors', icon: Target },
  { id: 'gangs', label: 'Gang Profiles', icon: Users },
  { id: 'addresses', label: 'Address Intel', icon: Database },
  { id: 'feed', label: 'Intel Dashboard', icon: BarChart3 },
]

/* ── HTML sanitizer ──────────────────────────────────────────────────────────── */
const ALLOWED_TAGS = new Set([
  'p', 'br', 'b', 'i', 'em', 'strong', 'a', 'ul', 'ol', 'li', 'h1', 'h2',
  'h3', 'h4', 'h5', 'h6', 'blockquote', 'code', 'pre', 'span', 'div',
  'img', 'figure', 'figcaption', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
  'hr', 'sup', 'sub', 'small',
])
const ALLOWED_ATTRS: Record<string, Set<string>> = {
  a: new Set(['href', 'title', 'rel', 'target']),
  img: new Set(['src', 'alt', 'width', 'height']),
  td: new Set(['colspan', 'rowspan']),
  th: new Set(['colspan', 'rowspan']),
}
const DANGEROUS_PROTOCOLS = /^(javascript|data|vbscript):/i

function sanitizeHtml(html: string): string {
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    function walk(node: Node) {
      const toRemove: Node[] = []
      for (const child of Array.from(node.childNodes)) {
        if (child.nodeType === Node.ELEMENT_NODE) {
          const el = child as Element
          const tag = el.tagName.toLowerCase()
          if (!ALLOWED_TAGS.has(tag)) { toRemove.push(child); continue }
          for (const attr of Array.from(el.attributes)) {
            const name = attr.name.toLowerCase()
            const allowed = ALLOWED_ATTRS[tag]
            if (!allowed || !allowed.has(name)) { el.removeAttribute(attr.name); continue }
            if ((name === 'href' || name === 'src') && DANGEROUS_PROTOCOLS.test(attr.value.trim())) {
              el.removeAttribute(attr.name)
            }
          }
          if (tag === 'a') { el.setAttribute('rel', 'noopener noreferrer'); el.setAttribute('target', '_blank') }
          for (const attr of Array.from(el.attributes)) {
            if (attr.name.toLowerCase().startsWith('on')) el.removeAttribute(attr.name)
          }
          walk(child)
        } else if (child.nodeType === Node.COMMENT_NODE) { toRemove.push(child) }
      }
      for (const n of toRemove) {
        if (n.nodeType === Node.ELEMENT_NODE) {
          const text = document.createTextNode((n as Element).textContent || '')
          node.replaceChild(text, n)
        } else { node.removeChild(n) }
      }
    }
    walk(doc.body)
    return doc.body.innerHTML
  } catch { return html.replace(/<[^>]*>/g, '') }
}

/* ── Helpers ───────────────────────────────────────────────────────────────── */
const SOURCE_TONE: Record<string, string> = {
  qualys: 'text-neon-red border-neon-red/30 bg-neon-red/10',
  vault12: 'text-neon-cyan border-neon-cyan/30 bg-neon-cyan/10',
  schneier: 'text-neon-amber border-neon-amber/30 bg-neon-amber/10',
  ackee: 'text-neon-purple border-neon-purple/30 bg-neon-purple/10',
  buzzsprout: 'text-neon-green border-neon-green/30 bg-neon-green/10',
  bleepingcomputer: 'text-blue-400 border-blue-400/30 bg-blue-400/10',
  therecord: 'text-red-400 border-red-400/30 bg-red-400/10',
  darkreading: 'text-orange-400 border-orange-400/30 bg-orange-400/10',
  krebsonsecurity: 'text-yellow-400 border-yellow-400/30 bg-yellow-400/10',
  thehackernews: 'text-emerald-400 border-emerald-400/30 bg-emerald-400/10',
  cisa_alerts: 'text-sky-400 border-sky-400/30 bg-sky-400/10',
  chainalysis: 'text-indigo-400 border-indigo-400/30 bg-indigo-400/10',
  elliptic: 'text-teal-400 border-teal-400/30 bg-teal-400/10',
  trmlabs: 'text-violet-400 border-violet-400/30 bg-violet-400/10',
}
function tone(sourceId: string): string {
  return SOURCE_TONE[sourceId] || 'text-text-secondary border-border bg-bg-surface'
}
function fmtDate(iso: string | null | undefined): string {
  if (!iso) return 'Undated'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return 'Undated'
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}
function relative(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso).getTime()
  if (isNaN(d)) return ''
  const diff = Date.now() - d
  const day = 86_400_000
  if (diff < day) return 'Today'
  if (diff < 2 * day) return 'Yesterday'
  if (diff < 7 * day) return `${Math.floor(diff / day)}d ago`
  if (diff < 30 * day) return `${Math.floor(diff / (7 * day))}w ago`
  return `${Math.floor(diff / (30 * day))}mo ago`
}
function shortAddr(addr: string): string {
  if (addr.length <= 16) return addr
  return `${addr.slice(0, 8)}…${addr.slice(-6)}`
}
function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).catch(() => {})
}
function fmtUSD(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`
  return `$${n.toFixed(0)}`
}
function totalAddrs(a: CryptoAddresses | undefined): number {
  if (!a) return 0
  return (a.btc?.length || 0) + (a.eth?.length || 0) + (a.xmr?.length || 0) +
    (a.ltc?.length || 0) + (a.doge?.length || 0) + (a.zec?.length || 0) +
    (a.dash?.length || 0) + (a.bch?.length || 0)
}

/* ── Crypto address badge — supports all 8 chains ──────────────────────────── */
const CHAIN_COLORS: Record<string, string> = {
  btc: 'text-amber-400 bg-amber-400/10 border-amber-400/30',
  eth: 'text-blue-400 bg-blue-400/10 border-blue-400/30',
  xmr: 'text-orange-400 bg-orange-400/10 border-orange-400/30',
  ltc: 'text-gray-300 bg-gray-300/10 border-gray-300/30',
  doge: 'text-yellow-300 bg-yellow-300/10 border-yellow-300/30',
  zec: 'text-violet-400 bg-violet-400/10 border-violet-400/30',
  dash: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/30',
  bch: 'text-green-400 bg-green-400/10 border-green-400/30',
}
const CHAIN_LABELS: Record<string, string> = {
  btc: 'BTC', eth: 'ETH', xmr: 'XMR', ltc: 'LTC',
  doge: 'DOGE', zec: 'ZEC', dash: 'DASH', bch: 'BCH',
}

function CryptoAddrBadge({ address, chain }: { address: string; chain: string }) {
  return (
    <span className={`inline-flex items-center gap-1 text-[9px] font-mono px-1.5 py-0.5 rounded border ${CHAIN_COLORS[chain] || 'text-text-muted border-border'}`}>
      <Bitcoin size={8} />
      {CHAIN_LABELS[chain] || chain.toUpperCase()}: {shortAddr(address)}
      <button onClick={(e) => { e.stopPropagation(); copyToClipboard(address) }} className="hover:opacity-70" title="Copy address">
        <Copy size={8} />
      </button>
    </span>
  )
}

function CryptoAddressList({ addresses }: { addresses: CryptoAddresses }) {
  const all = Object.entries(addresses || {}).flatMap(([chain, addrs]) =>
    (addrs || []).map((a: string) => ({ a, c: chain }))
  )
  if (all.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {all.map(({ a, c }) => <CryptoAddrBadge key={`${c}-${a}`} address={a} chain={c} />)}
    </div>
  )
}

function WalletBadge({ wallet }: { wallet: CryptoWallet }) {
  return (
    <div className="bg-bg-surface rounded-lg p-2 border border-border/60 text-[10px]">
      <div className="flex items-center gap-1.5 mb-1">
        <span className={`font-mono font-bold ${CHAIN_COLORS[wallet.chain]?.split(' ')[0] || 'text-text-bright'}`}>
          {CHAIN_LABELS[wallet.chain] || wallet.chain.toUpperCase()}
        </span>
        <span className="font-mono text-text-secondary">{shortAddr(wallet.address)}</span>
        <button onClick={() => copyToClipboard(wallet.address)} className="hover:opacity-70 ml-auto" title="Copy">
          <Copy size={9} />
        </button>
      </div>
      <div className="flex items-center gap-3 text-text-dim">
        {wallet.balance_usd > 0 && <span className="text-neon-green font-semibold">{fmtUSD(wallet.balance_usd)}</span>}
        {wallet.tx_count > 0 && <span>{wallet.tx_count} txs</span>}
        {wallet.last_tx_time && <span>Last: {fmtDate(wallet.last_tx_time)}</span>}
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   TAB 1: NEWS
   ══════════════════════════════════════════════════════════════════════════════ */
function SourceChip({ s, active, onClick }: { s: ThreatFeedSource; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-[11px] font-semibold transition
        ${active ? tone(s.id) : 'text-text-muted border-border bg-bg-surface hover:text-text-secondary'}`}
      title={s.error ? `Feed error: ${s.error}` : `${s.count ?? 0} items · ${s.category}`}>
      {s.error ? <XCircle size={11} className="text-neon-red" /> : <CheckCircle2 size={11} className="text-neon-green" />}
      {s.name}
      {typeof s.count === 'number' && <span className="opacity-60">· {s.count}</span>}
    </button>
  )
}

function NewsCard({ item, onOpen }: { item: ThreatFeedItem; onOpen: () => void }) {
  return (
    <article onClick={onOpen}
      className="group cursor-pointer bg-bg-card border border-border rounded-xl overflow-hidden
                 hover:border-neon-cyan/40 hover:shadow-[0_0_0_1px_rgb(var(--accent-blue)/0.25)] transition flex flex-col">
      {item.image ? (
        <div className="h-36 overflow-hidden bg-bg-surface">
          <img src={item.image} alt="" loading="lazy"
            className="w-full h-full object-cover group-hover:scale-105 transition duration-500"
            onError={(e) => { (e.currentTarget.parentElement as HTMLElement).style.display = 'none' }} />
        </div>
      ) : (
        <div className="h-1.5 bg-gradient-to-r from-neon-cyan/40 via-neon-purple/30 to-transparent" />
      )}
      <div className="p-4 flex flex-col gap-2 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`inline-flex items-center gap-1 text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border ${tone(item.source_id)}`}>
            <Rss size={9} /> {item.publisher}
          </span>
          <span className="text-[9px] uppercase tracking-wider text-text-muted">{item.category}</span>
        </div>
        <h3 className="text-sm font-bold text-text-bright leading-snug line-clamp-3 group-hover:text-neon-cyan transition">{item.title}</h3>
        <p className="text-[12px] text-text-muted line-clamp-2 flex-1">{item.summary}</p>
        <div className="flex items-center gap-3 text-[10px] text-text-dim pt-1 border-t border-border/60">
          <span className="inline-flex items-center gap-1"><CalendarDays size={10} /> {fmtDate(item.published)}</span>
          {relative(item.published) && <span className="text-text-muted">{relative(item.published)}</span>}
          {item.reading_minutes > 0 && <span className="inline-flex items-center gap-1 ml-auto"><Clock size={10} /> {item.reading_minutes} min</span>}
        </div>
      </div>
    </article>
  )
}

function NewsTab() {
  const navigate = useNavigate()
  const [source, setSource] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ['threat-feed-news'],
    queryFn: () => getThreatFeedNews({ limit: 120 }),
    staleTime: 10 * 60_000,
  })
  const items = useMemo(() => {
    let list = data?.items ?? []
    if (source) list = list.filter((i) => i.source_id === source)
    if (q.trim()) {
      const needle = q.toLowerCase()
      list = list.filter((i) => i.title.toLowerCase().includes(needle) || i.summary.toLowerCase().includes(needle))
    }
    return list
  }, [data, source, q])

  return (
    <div>
      <div className="flex items-center gap-2 flex-wrap mb-5">
        <button onClick={() => setSource(null)}
          className={`px-2.5 py-1 rounded-md border text-[11px] font-semibold transition
            ${!source ? 'text-neon-cyan border-neon-cyan/40 bg-neon-cyan/10' : 'text-text-muted border-border bg-bg-surface hover:text-text-secondary'}`}>
          All feeds
        </button>
        {(data?.sources ?? []).map((s) => (
          <SourceChip key={s.id} s={s} active={source === s.id} onClick={() => setSource(source === s.id ? null : s.id)} />
        ))}
        <div className="relative ml-auto">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search headlines…"
            className="pl-8 pr-3 py-1.5 rounded-lg bg-bg-surface border border-border text-[12px] text-text-primary
                       placeholder:text-text-dim focus:border-neon-cyan/40 focus:outline-none w-56" />
        </div>
        <button onClick={() => refetch()} disabled={isFetching}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-bg-surface
                     text-text-secondary text-[12px] font-semibold hover:text-text-bright hover:border-neon-cyan/40 transition disabled:opacity-50">
          {isFetching ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Refresh
        </button>
      </div>
      {isLoading && <div className="flex items-center justify-center gap-2 text-text-muted py-24"><Loader2 size={18} className="animate-spin" /> Loading threat feeds…</div>}
      {isError && <div className="flex items-center gap-2 text-neon-red bg-neon-red/10 border border-neon-red/30 rounded-lg px-4 py-3 text-[13px]"><AlertTriangle size={16} /> Could not load threat feeds.</div>}
      {!isLoading && !isError && items.length === 0 && <div className="text-center text-text-muted py-24 text-[13px]">No articles match your filters.</div>}
      {!isLoading && items.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {items.map((item) => <NewsCard key={item.id} item={item} onOpen={() => navigate(`/threat-landscape/${item.id}`)} />)}
        </div>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   TAB 2: INCIDENTS
   ══════════════════════════════════════════════════════════════════════════════ */
function IncidentCard({ incident }: { incident: RansomwareIncident }) {
  const [expanded, setExpanded] = useState(false)
  const hasCrypto = totalAddrs(incident.crypto_addresses) > 0
  return (
    <div className="bg-bg-card border border-border rounded-xl p-4 hover:border-neon-red/30 transition">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1.5">
            <span className="inline-flex items-center gap-1 text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border text-neon-red border-neon-red/30 bg-neon-red/10">
              <Skull size={9} /> {incident.group || 'Unknown'}
            </span>
            {incident.victim_industry && (
              <span className="text-[9px] uppercase tracking-wider text-text-muted">{incident.victim_industry}</span>
            )}
            {incident.victim_country && (
              <span className="text-[9px] text-text-dim flex items-center gap-0.5"><Globe size={9} />{incident.victim_country}</span>
            )}
          </div>
          <h3 className="text-sm font-bold text-text-bright leading-snug line-clamp-2">{incident.title}</h3>
          {incident.victim_name && (
            <p className="text-[11px] text-text-muted mt-0.5">Victim: {incident.victim_name} {incident.website && `(${incident.website})`}</p>
          )}
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] text-text-dim">{fmtDate(incident.discovered)}</div>
          <div className="text-[9px] text-text-muted">{relative(incident.discovered)}</div>
          {hasCrypto && (
            <span className="inline-flex items-center gap-0.5 text-[8px] font-bold uppercase px-1 py-0.5 rounded bg-amber-400/10 text-amber-400 border border-amber-400/30 mt-1">
              <Bitcoin size={8} /> {totalAddrs(incident.crypto_addresses)} addr
            </span>
          )}
        </div>
      </div>
      {incident.description && (
        <p className="text-[11px] text-text-muted mt-2 line-clamp-2">{incident.description.slice(0, 300)}</p>
      )}
      {hasCrypto && (
        <div className="mt-2">
          <button onClick={() => setExpanded(!expanded)} className="text-[10px] text-neon-cyan hover:underline flex items-center gap-1">
            {expanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
            {expanded ? 'Hide' : 'Show'} crypto addresses ({totalAddrs(incident.crypto_addresses)})
          </button>
          {expanded && <CryptoAddressList addresses={incident.crypto_addresses} />}
        </div>
      )}
      <div className="flex items-center gap-3 text-[10px] text-text-dim mt-2 pt-2 border-t border-border/60">
        {incident.ransom_demanded && <span>Ransom: {incident.ransom_demanded}</span>}
        {incident.data_leaked && <span>Data leaked: {incident.data_leaked}</span>}
        {incident.post_url && (
          <a href={incident.post_url} target="_blank" rel="noopener noreferrer" className="ml-auto text-neon-cyan hover:underline inline-flex items-center gap-0.5">
            Source <ExternalLink size={9} />
          </a>
        )}
      </div>
    </div>
  )
}

function IncidentsTab({ baseline }: { baseline?: ThreatBaselineResponse | null }) {
  const [groupFilter, setGroupFilter] = useState('')
  const [search, setSearch] = useState('')
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['ransomware-incidents', groupFilter],
    queryFn: () => getRansomwareIncidents({ group: groupFilter || undefined, limit: 200 }),
    staleTime: 10 * 60_000,
    placeholderData: () => {
      if (!groupFilter && baseline?.incidents) return baseline.incidents
      return undefined
    },
  })
  const incidents = useMemo(() => {
    let list = data?.incidents ?? []
    if (search.trim()) {
      const needle = search.toLowerCase()
      list = list.filter(i =>
        i.title.toLowerCase().includes(needle) ||
        i.group.toLowerCase().includes(needle) ||
        (i.victim_name || '').toLowerCase().includes(needle) ||
        i.description.toLowerCase().includes(needle)
      )
    }
    return list
  }, [data, search])

  return (
    <div>
      {data && (
        <div className="grid grid-cols-3 gap-3 mb-5">
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-neon-red">{data.total}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Total Incidents</div>
          </div>
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-amber-400">{data.with_crypto_addresses}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">With Crypto Addresses</div>
          </div>
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-neon-cyan">{new Set(data.incidents.map(i => i.group)).size}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Active Groups</div>
          </div>
        </div>
      )}
      <div className="flex items-center gap-3 flex-wrap mb-5">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search incidents, victims, groups…"
            className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-bg-surface border border-border text-[12px] text-text-primary
                       placeholder:text-text-dim focus:border-neon-cyan/40 focus:outline-none" />
        </div>
        <input value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)} placeholder="Filter by group…"
          className="px-3 py-1.5 rounded-lg bg-bg-surface border border-border text-[12px] text-text-primary
                     placeholder:text-text-dim focus:border-neon-cyan/40 focus:outline-none w-40" />
        <button onClick={() => refetch()} disabled={isFetching}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-bg-surface
                     text-text-secondary text-[12px] font-semibold hover:text-text-bright hover:border-neon-cyan/40 transition disabled:opacity-50">
          {isFetching ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Refresh
        </button>
      </div>
      {isLoading && <div className="flex items-center justify-center gap-2 text-text-muted py-24"><Loader2 size={18} className="animate-spin" /> Loading incidents…</div>}
      {isError && <div className="flex items-center gap-2 text-neon-red bg-neon-red/10 border border-neon-red/30 rounded-lg px-4 py-3 text-[13px]"><AlertTriangle size={16} /> Could not load incidents.</div>}
      {!isLoading && !isError && incidents.length === 0 && <div className="text-center text-text-muted py-24 text-[13px]">No incidents match your filters.</div>}
      {!isLoading && incidents.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {incidents.map((inc, idx) => <IncidentCard key={`${inc.group}-${inc.title}-${idx}`} incident={inc} />)}
        </div>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   TAB 3: THREAT ACTORS — comprehensive profiles with wallets
   ══════════════════════════════════════════════════════════════════════════════ */
function ThreatActorCard({ profile, onSelect }: { profile: ThreatActorProfile; onSelect: () => void }) {
  const hasWallets = (profile.wallets?.length || 0) > 0
  const hasCrypto = profile.total_addresses > 0
  return (
    <div onClick={onSelect}
      className="cursor-pointer bg-bg-card border border-border rounded-xl p-4 hover:border-neon-purple/40 transition">
      <div className="flex items-start justify-between gap-2 mb-2">
        <h3 className="text-sm font-bold text-text-bright leading-snug">{profile.name}</h3>
        <div className="flex items-center gap-1 shrink-0">
          {profile.active && (
            <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded bg-neon-green/10 text-neon-green border border-neon-green/30">Active</span>
          )}
          {profile.raas && (
            <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded bg-neon-purple/10 text-neon-purple border border-neon-purple/30">RaaS</span>
          )}
          {hasCrypto && (
            <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded bg-amber-400/10 text-amber-400 border border-amber-400/30">
              <Bitcoin size={8} className="inline" /> {profile.total_addresses}
            </span>
          )}
        </div>
      </div>
      {profile.aliases.length > 0 && (
        <p className="text-[10px] text-text-muted mb-1">aka: {profile.aliases.join(', ')}</p>
      )}
      {profile.description && (
        <p className="text-[11px] text-text-muted line-clamp-2 mb-2">{profile.description.slice(0, 200)}</p>
      )}
      <div className="grid grid-cols-3 gap-2 mb-2">
        <div className="text-center">
          <div className="text-sm font-bold text-neon-red">{profile.victim_count}</div>
          <div className="text-[8px] text-text-dim uppercase">Victims</div>
        </div>
        <div className="text-center">
          <div className="text-sm font-bold text-neon-cyan">{profile.incident_count}</div>
          <div className="text-[8px] text-text-dim uppercase">Incidents</div>
        </div>
        <div className="text-center">
          <div className="text-sm font-bold text-amber-400">{profile.wallet_stats?.total_wallets || 0}</div>
          <div className="text-[8px] text-text-dim uppercase">Wallets</div>
        </div>
      </div>
      {profile.wallet_stats && profile.wallet_stats.total_balance_usd > 0 && (
        <div className="flex items-center gap-1 text-[10px] text-neon-green mb-2">
          <DollarSign size={10} /> {fmtUSD(profile.wallet_stats.total_balance_usd)} tracked balance
        </div>
      )}
      {profile.chains_used.length > 0 && (
        <div className="flex items-center gap-1 flex-wrap">
          {profile.chains_used.map(c => (
            <span key={c} className="text-[8px] px-1 py-0.5 rounded bg-bg-surface text-text-dim border border-border/60">{c}</span>
          ))}
        </div>
      )}
    </div>
  )
}

function ThreatActorDetail({ name, onBack }: { name: string; onBack: () => void }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['threat-actor-detail', name],
    queryFn: () => getThreatActorDetail(name),
    staleTime: 15 * 60_000,
  })
  const [showWallets, setShowWallets] = useState(false)

  if (isLoading) return <div className="flex items-center justify-center gap-2 text-text-muted py-24"><Loader2 size={18} className="animate-spin" /> Loading threat actor profile…</div>
  if (isError) return <div className="text-neon-red py-12 text-center">Failed to load profile.</div>
  if (!data?.profile) return <div className="text-text-muted py-12 text-center">Profile not found.</div>

  const p = data.profile as ThreatActorProfile
  return (
    <div>
      <button onClick={onBack} className="inline-flex items-center gap-1.5 text-[12px] text-text-muted hover:text-neon-cyan transition mb-5">
        <ArrowLeft size={14} /> Back to Threat Actors
      </button>
      {/* Header */}
      <div className="bg-bg-card border border-border rounded-xl p-6 mb-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-xl font-display font-bold text-text-bright">{p.name}</h2>
            {p.aliases.length > 0 && <p className="text-[12px] text-text-muted mt-1">Also known as: {p.aliases.join(', ')}</p>}
          </div>
          <div className="flex items-center gap-2">
            {p.active && <span className="text-[9px] font-bold uppercase px-2 py-1 rounded bg-neon-green/10 text-neon-green border border-neon-green/30">Active</span>}
            {p.raas && <span className="text-[9px] font-bold uppercase px-2 py-1 rounded bg-neon-purple/10 text-neon-purple border border-neon-purple/30">RaaS</span>}
            <a href={p.profile_url} target="_blank" rel="noopener noreferrer"
              className="text-[11px] text-neon-cyan hover:underline inline-flex items-center gap-1">
              View source <ExternalLink size={10} />
            </a>
          </div>
        </div>
        {p.description && <p className="text-[13px] text-text-secondary mb-4 leading-relaxed">{p.description}</p>}
        {/* Stats row */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
          <div className="bg-bg-surface rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-neon-red">{p.victim_count}</div>
            <div className="text-[9px] text-text-muted uppercase">Victims</div>
          </div>
          <div className="bg-bg-surface rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-neon-cyan">{p.incident_count}</div>
            <div className="text-[9px] text-text-muted uppercase">Incidents</div>
          </div>
          <div className="bg-bg-surface rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-amber-400">{p.total_addresses}</div>
            <div className="text-[9px] text-text-muted uppercase">Crypto Addresses</div>
          </div>
          <div className="bg-bg-surface rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-neon-green">{p.wallet_stats?.total_wallets || 0}</div>
            <div className="text-[9px] text-text-muted uppercase">Wallets</div>
          </div>
          <div className="bg-bg-surface rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-neon-purple">{p.ttps.length}</div>
            <div className="text-[9px] text-text-muted uppercase">TTPs</div>
          </div>
        </div>
        {p.wallet_stats && p.wallet_stats.total_balance_usd > 0 && (
          <div className="flex items-center gap-2 text-[12px] text-neon-green bg-neon-green/5 border border-neon-green/20 rounded-lg px-3 py-2 mb-4">
            <DollarSign size={14} /> Tracked balance: {fmtUSD(p.wallet_stats.total_balance_usd)} · {p.wallet_stats.total_tx_count} total transactions
          </div>
        )}
        {p.victim_countries.length > 0 && (
          <div className="mb-3">
            <span className="text-[10px] text-text-dim uppercase tracking-wider">Targeted countries: </span>
            <span className="text-[11px] text-text-secondary">{p.victim_countries.join(', ')}</span>
          </div>
        )}
        {p.victim_industries.length > 0 && (
          <div className="mb-3">
            <span className="text-[10px] text-text-dim uppercase tracking-wider">Targeted industries: </span>
            <span className="text-[11px] text-text-secondary">{p.victim_industries.join(', ')}</span>
          </div>
        )}
      </div>
      {/* Crypto Wallets */}
      {p.wallets && p.wallets.length > 0 && (
        <div className="bg-bg-card border border-border rounded-xl p-6 mb-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold text-text-bright flex items-center gap-2">
              <Wallet size={14} className="text-amber-400" /> Crypto Wallets ({p.wallets.length})
            </h3>
            <button onClick={() => setShowWallets(!showWallets)} className="text-[11px] text-neon-cyan hover:underline">
              {showWallets ? 'Collapse' : 'Expand all'}
            </button>
          </div>
          <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 ${showWallets ? '' : 'max-h-48 overflow-y-auto'}`}>
            {(showWallets ? p.wallets : p.wallets.slice(0, 12)).map((w, i) => (
              <WalletBadge key={`${w.address}-${i}`} wallet={w} />
            ))}
          </div>
          {!showWallets && p.wallets.length > 12 && (
            <button onClick={() => setShowWallets(true)} className="text-[11px] text-neon-cyan hover:underline mt-2">
              Show all {p.wallets.length} wallets…
            </button>
          )}
        </div>
      )}
      {/* Known Address Matches */}
      {p.known_address_matches && p.known_address_matches.length > 0 && (
        <div className="bg-bg-card border border-neon-red/20 rounded-xl p-6 mb-6">
          <h3 className="text-sm font-bold text-text-bright flex items-center gap-2 mb-3">
            <AlertTriangle size={14} className="text-neon-red" /> Known Malicious Addresses
          </h3>
          <div className="space-y-2">
            {p.known_address_matches.map((m, i) => (
              <div key={i} className="bg-bg-surface rounded-lg p-3 border border-neon-red/10">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-[8px] font-bold uppercase px-1.5 py-0.5 rounded border ${
                    m.severity === 'critical' ? 'text-neon-red border-neon-red/30 bg-neon-red/10' :
                    m.severity === 'high' ? 'text-neon-amber border-neon-amber/30 bg-neon-amber/10' :
                    'text-text-muted border-border bg-bg-surface'
                  }`}>{m.severity}</span>
                  <span className="text-[10px] font-mono text-text-bright">{shortAddr(m.address)}</span>
                  <span className="text-[9px] text-text-dim">{CHAIN_LABELS[m.chain] || m.chain}</span>
                  <button onClick={() => copyToClipboard(m.address)} className="ml-auto hover:opacity-70"><Copy size={9} /></button>
                </div>
                <div className="text-[11px] text-neon-cyan font-semibold">{m.label}</div>
                <div className="text-[10px] text-text-muted mt-0.5">{m.context}</div>
                <div className="text-[9px] text-text-dim mt-1">Source: {m.source}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {/* TTPs */}
      {p.ttps.length > 0 && (
        <div className="bg-bg-card border border-border rounded-xl p-6 mb-6">
          <h3 className="text-sm font-bold text-text-bright mb-3 flex items-center gap-2"><Crosshair size={14} /> MITRE ATT&CK Tactics</h3>
          <div className="space-y-3">
            {p.ttps.map((ttp, i) => (
              <div key={i} className="bg-bg-surface rounded-lg p-3">
                <div className="text-[11px] font-bold text-neon-cyan mb-1">{ttp.tactic_name} ({ttp.tactic_id})</div>
                <div className="space-y-1">
                  {ttp.techniques.map((tech, j) => (
                    <div key={j} className="text-[11px] text-text-secondary flex items-start gap-2">
                      <span className="text-text-dim font-mono shrink-0">{tech.id}</span>
                      <span>{tech.name}</span>
                      {tech.details && <span className="text-text-dim text-[10px]">— {tech.details.slice(0, 150)}</span>}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {/* Affiliates */}
      {p.affiliates && p.affiliates.length > 0 && (
        <div className="bg-bg-card border border-border rounded-xl p-6 mb-6">
          <h3 className="text-sm font-bold text-text-bright mb-3 flex items-center gap-2"><Users size={14} /> Known Affiliates</h3>
          <div className="flex flex-wrap gap-2">
            {p.affiliates.map((a, i) => (
              <span key={i} className="text-[11px] px-2 py-1 rounded bg-bg-surface border border-border text-text-secondary">{a}</span>
            ))}
          </div>
        </div>
      )}
      {/* Incidents */}
      {data.incidents?.length > 0 && (
        <div className="bg-bg-card border border-border rounded-xl p-6">
          <h3 className="text-sm font-bold text-text-bright mb-3 flex items-center gap-2"><Skull size={14} /> Known Incidents ({data.incident_count})</h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {(data.incidents as RansomwareIncident[]).slice(0, 20).map((inc, idx) => (
              <IncidentCard key={idx} incident={inc} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ThreatActorsTab({ baseline }: { baseline?: ThreatBaselineResponse | null }) {
  const [search, setSearch] = useState('')
  const [selectedActor, setSelectedActor] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState('victim_count')
  const [cryptoOnly, setCryptoOnly] = useState(false)
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['threat-actors', sortBy, cryptoOnly],
    queryFn: () => getThreatActors({ limit: 200, sort_by: sortBy, with_crypto_only: cryptoOnly }),
    staleTime: 15 * 60_000,
    placeholderData: () => {
      if (sortBy === 'victim_count' && !cryptoOnly && baseline?.actors) return baseline.actors
      return undefined
    },
  })
  const profiles = useMemo(() => {
    let list = data?.profiles ?? []
    if (search.trim()) {
      const needle = search.toLowerCase()
      list = list.filter(p =>
        p.name.toLowerCase().includes(needle) ||
        p.description.toLowerCase().includes(needle) ||
        p.aliases.some(a => a.toLowerCase().includes(needle))
      )
    }
    return list
  }, [data, search])

  if (selectedActor) return <ThreatActorDetail name={selectedActor} onBack={() => setSelectedActor(null)} />

  return (
    <div>
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-neon-purple">{data.total}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Threat Actors</div>
          </div>
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-amber-400">{data.with_crypto}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">With Crypto</div>
          </div>
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-neon-green">{data.with_wallets}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">With Wallets</div>
          </div>
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-neon-cyan">{fmtUSD(data.total_wallet_balance_usd)}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Total Tracked</div>
          </div>
        </div>
      )}
      <div className="flex items-center gap-3 flex-wrap mb-5">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search actors, aliases…"
            className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-bg-surface border border-border text-[12px] text-text-primary
                       placeholder:text-text-dim focus:border-neon-cyan/40 focus:outline-none" />
        </div>
        <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-bg-surface border border-border text-[12px] text-text-primary focus:border-neon-cyan/40 focus:outline-none">
          <option value="victim_count">Sort: Victims</option>
          <option value="incident_count">Sort: Incidents</option>
          <option value="total_addresses">Sort: Addresses</option>
          <option value="name">Sort: Name</option>
        </select>
        <label className="inline-flex items-center gap-1.5 text-[11px] text-text-secondary cursor-pointer">
          <input type="checkbox" checked={cryptoOnly} onChange={(e) => setCryptoOnly(e.target.checked)}
            className="rounded border-border" />
          <Filter size={11} /> Crypto only
        </label>
        <button onClick={() => refetch()} disabled={isFetching}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-bg-surface
                     text-text-secondary text-[12px] font-semibold hover:text-text-bright hover:border-neon-cyan/40 transition disabled:opacity-50">
          {isFetching ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Refresh
        </button>
      </div>
      {isLoading && <div className="flex items-center justify-center gap-2 text-text-muted py-24"><Loader2 size={18} className="animate-spin" /> Loading threat actor profiles…</div>}
      {isError && <div className="flex items-center gap-2 text-neon-red bg-neon-red/10 border border-neon-red/30 rounded-lg px-4 py-3 text-[13px]"><AlertTriangle size={16} /> Could not load profiles.</div>}
      {!isLoading && !isError && profiles.length === 0 && <div className="text-center text-text-muted py-24 text-[13px]">No actors match your filters.</div>}
      {!isLoading && profiles.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {profiles.map((p) => <ThreatActorCard key={p.name} profile={p} onSelect={() => setSelectedActor(p.name)} />)}
        </div>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   TAB 4: GANG PROFILES (legacy — simpler view)
   ══════════════════════════════════════════════════════════════════════════════ */
function GangCard({ group, onSelect }: { group: RansomwareGroup; onSelect: () => void }) {
  const hasCrypto = totalAddrs(group.crypto_addresses) > 0
  return (
    <div onClick={onSelect}
      className="cursor-pointer bg-bg-card border border-border rounded-xl p-4 hover:border-neon-purple/40 transition">
      <div className="flex items-start justify-between gap-2 mb-2">
        <h3 className="text-sm font-bold text-text-bright leading-snug">{group.name}</h3>
        <div className="flex items-center gap-1 shrink-0">
          {group.active_sites.length > 0 && (
            <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded bg-neon-green/10 text-neon-green border border-neon-green/30">Active</span>
          )}
          {hasCrypto && (
            <span className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded bg-amber-400/10 text-amber-400 border border-amber-400/30">
              <Bitcoin size={8} className="inline" /> {totalAddrs(group.crypto_addresses)}
            </span>
          )}
        </div>
      </div>
      {group.aliases.length > 0 && <p className="text-[10px] text-text-muted mb-1">aka: {group.aliases.join(', ')}</p>}
      {group.description && <p className="text-[11px] text-text-muted line-clamp-3 mb-2">{group.description.slice(0, 250)}</p>}
      <div className="flex items-center gap-3 text-[10px] text-text-dim flex-wrap">
        <span className="inline-flex items-center gap-1"><Globe size={10} /> {group.active_sites.length} sites</span>
        <span className="inline-flex items-center gap-1"><Crosshair size={10} /> {group.ttps.length} TTPs</span>
        {group.victim_count !== undefined && <span className="inline-flex items-center gap-1"><Skull size={10} /> {group.victim_count} victims</span>}
      </div>
      {hasCrypto && <CryptoAddressList addresses={group.crypto_addresses} />}
    </div>
  )
}

function GangsTab({ baseline }: { baseline?: ThreatBaselineResponse | null }) {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null)
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['ransomware-groups'],
    queryFn: () => getRansomwareGroups(),
    staleTime: 15 * 60_000,
    placeholderData: () => baseline?.groups ?? undefined,
  })
  const groups = useMemo(() => {
    let list = data?.groups ?? []
    if (search.trim()) {
      const needle = search.toLowerCase()
      list = list.filter(g =>
        g.name.toLowerCase().includes(needle) ||
        g.description.toLowerCase().includes(needle) ||
        g.aliases.some(a => a.toLowerCase().includes(needle))
      )
    }
    return list
  }, [data, search])

  if (selectedGroup) return <GangDetail groupName={selectedGroup} onBack={() => setSelectedGroup(null)} />

  return (
    <div>
      {data && (
        <div className="grid grid-cols-3 gap-3 mb-5">
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-neon-purple">{data.total}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Total Groups</div>
          </div>
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-neon-green">{data.active}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Active Now</div>
          </div>
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-amber-400">{data.with_wallets || 0}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">With Wallets</div>
          </div>
        </div>
      )}
      <div className="flex items-center gap-3 flex-wrap mb-5">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search gangs, aliases, descriptions…"
            className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-bg-surface border border-border text-[12px] text-text-primary
                       placeholder:text-text-dim focus:border-neon-cyan/40 focus:outline-none" />
        </div>
        <button onClick={() => refetch()} disabled={isFetching}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-bg-surface
                     text-text-secondary text-[12px] font-semibold hover:text-text-bright hover:border-neon-cyan/40 transition disabled:opacity-50">
          {isFetching ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Refresh
        </button>
      </div>
      {isLoading && <div className="flex items-center justify-center gap-2 text-text-muted py-24"><Loader2 size={18} className="animate-spin" /> Loading gang profiles…</div>}
      {isError && <div className="flex items-center gap-2 text-neon-red bg-neon-red/10 border border-neon-red/30 rounded-lg px-4 py-3 text-[13px]"><AlertTriangle size={16} /> Could not load gang profiles.</div>}
      {!isLoading && !isError && groups.length === 0 && <div className="text-center text-text-muted py-24 text-[13px]">No groups match your search.</div>}
      {!isLoading && groups.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {groups.map((g) => <GangCard key={g.name} group={g} onSelect={() => setSelectedGroup(g.name)} />)}
        </div>
      )}
    </div>
  )
}

function GangDetail({ groupName, onBack }: { groupName: string; onBack: () => void }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['ransomware-group', groupName],
    queryFn: () => getRansomwareGroupDetail(groupName),
    staleTime: 15 * 60_000,
  })
  if (isLoading) return <div className="flex items-center justify-center gap-2 text-text-muted py-24"><Loader2 size={18} className="animate-spin" /> Loading group profile…</div>
  if (isError) return <div className="text-neon-red py-12 text-center">Failed to load group profile.</div>
  if (!data?.group) return <div className="text-text-muted py-12 text-center">Group not found.</div>

  const g = data.group as RansomwareGroup
  return (
    <div>
      <button onClick={onBack} className="inline-flex items-center gap-1.5 text-[12px] text-text-muted hover:text-neon-cyan transition mb-5">
        <ArrowLeft size={14} /> Back to Gang Profiles
      </button>
      <div className="bg-bg-card border border-border rounded-xl p-6 mb-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-xl font-display font-bold text-text-bright">{g.name}</h2>
            {g.aliases.length > 0 && <p className="text-[12px] text-text-muted mt-1">Also known as: {g.aliases.join(', ')}</p>}
          </div>
          <a href={g.profile_url} target="_blank" rel="noopener noreferrer"
            className="text-[11px] text-neon-cyan hover:underline inline-flex items-center gap-1">
            View source <ExternalLink size={10} />
          </a>
        </div>
        {g.description && <p className="text-[13px] text-text-secondary mb-4 leading-relaxed">{g.description}</p>}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <div className="bg-bg-surface rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-neon-green">{g.active_sites.length}</div>
            <div className="text-[9px] text-text-muted uppercase">Active Sites</div>
          </div>
          <div className="bg-bg-surface rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-neon-cyan">{g.ttps.length}</div>
            <div className="text-[9px] text-text-muted uppercase">TTPs</div>
          </div>
          <div className="bg-bg-surface rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-amber-400">{totalAddrs(g.crypto_addresses)}</div>
            <div className="text-[9px] text-text-muted uppercase">Crypto Addresses</div>
          </div>
          <div className="bg-bg-surface rounded-lg p-3 text-center">
            <div className="text-lg font-bold text-neon-purple">{g.victim_count || 0}</div>
            <div className="text-[9px] text-text-muted uppercase">Victims</div>
          </div>
        </div>
        {totalAddrs(g.crypto_addresses) > 0 && (
          <div className="mb-4">
            <h4 className="text-[11px] font-bold uppercase tracking-wider text-amber-400 mb-2 flex items-center gap-1"><Bitcoin size={12} /> Known Crypto Addresses</h4>
            <CryptoAddressList addresses={g.crypto_addresses} />
          </div>
        )}
        {g.wallets && g.wallets.length > 0 && (
          <div className="mb-4">
            <h4 className="text-[11px] font-bold uppercase tracking-wider text-amber-400 mb-2 flex items-center gap-1"><Wallet size={12} /> Wallet Intelligence ({g.wallets.length})</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {g.wallets.slice(0, 10).map((w, i) => <WalletBadge key={i} wallet={w} />)}
            </div>
          </div>
        )}
      </div>
      {g.ttps.length > 0 && (
        <div className="bg-bg-card border border-border rounded-xl p-6 mb-6">
          <h3 className="text-sm font-bold text-text-bright mb-3 flex items-center gap-2"><Crosshair size={14} /> MITRE ATT&CK Tactics</h3>
          <div className="space-y-3">
            {g.ttps.map((ttp, i) => (
              <div key={i} className="bg-bg-surface rounded-lg p-3">
                <div className="text-[11px] font-bold text-neon-cyan mb-1">{ttp.tactic_name} ({ttp.tactic_id})</div>
                <div className="space-y-1">
                  {ttp.techniques.map((tech, j) => (
                    <div key={j} className="text-[11px] text-text-secondary flex items-start gap-2">
                      <span className="text-text-dim font-mono shrink-0">{tech.id}</span>
                      <span>{tech.name}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {data.incidents?.length > 0 && (
        <div className="bg-bg-card border border-border rounded-xl p-6">
          <h3 className="text-sm font-bold text-text-bright mb-3 flex items-center gap-2"><Skull size={14} /> Known Incidents ({data.incident_count})</h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {(data.incidents as RansomwareIncident[]).slice(0, 20).map((inc, idx) => (
              <IncidentCard key={idx} incident={inc} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   TAB 5: ADDRESS INTELLIGENCE
   ══════════════════════════════════════════════════════════════════════════════ */
function AddressIntelTab({ baseline }: { baseline?: ThreatBaselineResponse | null }) {
  const [chainFilter, setChainFilter] = useState('')
  const [actorFilter, setActorFilter] = useState('')
  const [balanceOnly, setBalanceOnly] = useState(false)
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['address-intel', chainFilter, actorFilter, balanceOnly],
    queryFn: () => getAddressIntel({ limit: 500, chain: chainFilter || undefined, actor: actorFilter || undefined, with_balance_only: balanceOnly }),
    staleTime: 10 * 60_000,
    placeholderData: () => {
      if (!chainFilter && !actorFilter && !balanceOnly && baseline?.addresses) return baseline.addresses
      return undefined
    },
  })

  return (
    <div>
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-amber-400">{data.total}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Tracked Addresses</div>
          </div>
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-neon-green">{fmtUSD(data.total_balance_usd)}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Total Balance</div>
          </div>
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-neon-cyan">{Object.keys(data.by_chain).length}</div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">Chains</div>
          </div>
          <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
            <div className="text-sm font-bold text-neon-purple">
              {Object.entries(data.by_chain).map(([c, n]) => `${CHAIN_LABELS[c] || c}:${n}`).join(' · ')}
            </div>
            <div className="text-[10px] text-text-muted uppercase tracking-wider">By Chain</div>
          </div>
        </div>
      )}
      <div className="flex items-center gap-3 flex-wrap mb-5">
        <select value={chainFilter} onChange={(e) => setChainFilter(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-bg-surface border border-border text-[12px] text-text-primary focus:border-neon-cyan/40 focus:outline-none">
          <option value="">All chains</option>
          {Object.entries(data?.by_chain || {}).map(([c, n]) => (
            <option key={c} value={c}>{CHAIN_LABELS[c] || c} ({n})</option>
          ))}
        </select>
        <input value={actorFilter} onChange={(e) => setActorFilter(e.target.value)} placeholder="Filter by actor…"
          className="px-3 py-1.5 rounded-lg bg-bg-surface border border-border text-[12px] text-text-primary
                     placeholder:text-text-dim focus:border-neon-cyan/40 focus:outline-none w-40" />
        <label className="inline-flex items-center gap-1.5 text-[11px] text-text-secondary cursor-pointer">
          <input type="checkbox" checked={balanceOnly} onChange={(e) => setBalanceOnly(e.target.checked)} className="rounded border-border" />
          <DollarSign size={11} /> With balance
        </label>
        <button onClick={() => refetch()} disabled={isFetching}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-bg-surface
                     text-text-secondary text-[12px] font-semibold hover:text-text-bright hover:border-neon-cyan/40 transition disabled:opacity-50 ml-auto">
          {isFetching ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Refresh
        </button>
      </div>
      {isLoading && <div className="flex items-center justify-center gap-2 text-text-muted py-24"><Loader2 size={18} className="animate-spin" /> Loading address intelligence…</div>}
      {isError && <div className="flex items-center gap-2 text-neon-red bg-neon-red/10 border border-neon-red/30 rounded-lg px-4 py-3 text-[13px]"><AlertTriangle size={16} /> Could not load address data.</div>}
      {!isLoading && data && data.addresses.length > 0 && (
        <div className="space-y-2">
          {data.addresses.map((addr, idx) => (
            <div key={`${addr.address}-${idx}`} className="bg-bg-card border border-border rounded-lg p-3 hover:border-amber-400/30 transition">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <CryptoAddrBadge address={addr.address} chain={addr.chain} />
                    {addr.known_info && (
                      <span className={`text-[8px] font-bold uppercase px-1.5 py-0.5 rounded border ${
                        addr.known_info.severity === 'critical' ? 'text-neon-red border-neon-red/30 bg-neon-red/10' :
                        addr.known_info.severity === 'high' ? 'text-neon-amber border-neon-amber/30 bg-neon-amber/10' :
                        'text-text-muted border-border'
                      }`}>{addr.known_info.severity}</span>
                    )}
                    {addr.wallet_data && addr.wallet_data.balance_usd > 0 && (
                      <span className="text-[9px] text-neon-green font-semibold">{fmtUSD(addr.wallet_data.balance_usd)}</span>
                    )}
                  </div>
                  {addr.actors.length > 0 && (
                    <div className="flex items-center gap-1 flex-wrap mb-1">
                      <span className="text-[9px] text-text-dim">Actors:</span>
                      {addr.actors.map((a, i) => (
                        <span key={i} className="text-[9px] px-1 py-0.5 rounded bg-neon-red/10 text-neon-red border border-neon-red/20">{a}</span>
                      ))}
                    </div>
                  )}
                  {addr.known_info && (
                    <div className="text-[10px] text-text-muted">{addr.known_info.label} — {addr.known_info.context?.slice(0, 120)}</div>
                  )}
                  {addr.incidents.length > 0 && (
                    <div className="text-[9px] text-text-dim mt-1">{addr.incidents.length} linked incidents</div>
                  )}
                </div>
                <div className="text-right shrink-0 text-[9px] text-text-dim">
                  <div>{addr.chain_label}</div>
                  {addr.wallet_data?.tx_count ? <div>{addr.wallet_data.tx_count} txs</div> : null}
                  <div className="text-[8px]">{addr.sources.join(', ')}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {!isLoading && data && data.addresses.length === 0 && <div className="text-center text-text-muted py-24 text-[13px]">No addresses match your filters.</div>}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   TAB 6: INTEL DASHBOARD
   ══════════════════════════════════════════════════════════════════════════════ */
function IntelDashboardTab({ baseline }: { baseline?: ThreatBaselineResponse | null }) {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['ransomware-feed'],
    queryFn: () => getRansomwareFeed({ limit: 50 }),
    staleTime: 10 * 60_000,
    placeholderData: () => {
      if (!baseline) return undefined
      // Synthesize a feed response from baseline data
      return {
        summary: {
          total_groups: baseline.groups.total,
          active_groups: baseline.groups.active,
          total_incidents: baseline.incidents.total,
          incidents_with_crypto_addresses: baseline.incidents.with_crypto_addresses,
          total_tracked_addresses: baseline.addresses.total,
          known_malicious_addresses: baseline.addresses.addresses.filter(a => a.known_info).length,
          threat_actors_profiled: baseline.actors.total,
        },
        stats: baseline.stats,
        recent_incidents: baseline.incidents.incidents.slice(0, 20),
        active_groups: baseline.groups.groups.filter(g => g.active_sites?.length > 0).slice(0, 20).map(g => ({
          name: g.name, sites: g.active_sites.length, ttps_count: g.ttps?.length || 0,
        })),
        incidents_with_crypto: baseline.incidents.incidents.filter(i => totalAddrs(i.crypto_addresses) > 0).slice(0, 20),
        top_addresses: baseline.addresses.addresses.filter(a => a.actors.length > 0).slice(0, 20),
        threat_actors_summary: baseline.actors.profiles.slice(0, 15).map(p => ({
          name: p.name, incident_count: p.incident_count,
          total_addresses: p.total_addresses, active: p.active,
          chains_used: p.chains_used, victim_count: p.victim_count,
        })),
        generated_at: baseline.generated_at,
      }
    },
  })
  if (isLoading) return <div className="flex items-center justify-center gap-2 text-text-muted py-24"><Loader2 size={18} className="animate-spin" /> Loading intelligence dashboard…</div>
  if (isError) return <div className="flex items-center gap-2 text-neon-red bg-neon-red/10 border border-neon-red/30 rounded-lg px-4 py-3 text-[13px]"><AlertTriangle size={16} /> Could not load intel feed.</div>
  if (!data) return null

  return (
    <div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <div className="bg-gradient-to-br from-neon-red/10 to-transparent border border-neon-red/20 rounded-xl p-4 text-center">
          <Users size={18} className="text-neon-red mx-auto mb-1" />
          <div className="text-2xl font-bold text-text-bright">{data.summary.total_groups}</div>
          <div className="text-[10px] text-text-muted uppercase tracking-wider">Tracked Groups</div>
        </div>
        <div className="bg-gradient-to-br from-neon-green/10 to-transparent border border-neon-green/20 rounded-xl p-4 text-center">
          <Activity size={18} className="text-neon-green mx-auto mb-1" />
          <div className="text-2xl font-bold text-text-bright">{data.summary.active_groups}</div>
          <div className="text-[10px] text-text-muted uppercase tracking-wider">Active Operations</div>
        </div>
        <div className="bg-gradient-to-br from-neon-purple/10 to-transparent border border-neon-purple/20 rounded-xl p-4 text-center">
          <Target size={18} className="text-neon-purple mx-auto mb-1" />
          <div className="text-2xl font-bold text-text-bright">{data.summary.total_incidents}</div>
          <div className="text-[10px] text-text-muted uppercase tracking-wider">Total Incidents</div>
        </div>
        <div className="bg-gradient-to-br from-amber-400/10 to-transparent border border-amber-400/20 rounded-xl p-4 text-center">
          <Bitcoin size={18} className="text-amber-400 mx-auto mb-1" />
          <div className="text-2xl font-bold text-text-bright">{data.summary.total_tracked_addresses || 0}</div>
          <div className="text-[10px] text-text-muted uppercase tracking-wider">Crypto Addresses</div>
        </div>
      </div>
      {/* Extra stats row */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-neon-cyan">{data.summary.threat_actors_profiled || 0}</div>
          <div className="text-[10px] text-text-muted uppercase tracking-wider">Actors Profiled</div>
        </div>
        <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-neon-green">{data.summary.known_malicious_addresses || 0}</div>
          <div className="text-[10px] text-text-muted uppercase tracking-wider">Known Malicious</div>
        </div>
        <div className="bg-bg-card border border-border rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-amber-400">{data.summary.incidents_with_crypto_addresses}</div>
          <div className="text-[10px] text-text-muted uppercase tracking-wider">Crypto-Linked</div>
        </div>
      </div>

      <div className="flex items-center justify-end mb-4">
        <button onClick={() => refetch()} disabled={isFetching}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-bg-surface
                     text-text-secondary text-[12px] font-semibold hover:text-text-bright hover:border-neon-cyan/40 transition disabled:opacity-50">
          {isFetching ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Refresh All
        </button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Most active groups */}
        <div className="bg-bg-card border border-border rounded-xl p-5">
          <h3 className="text-sm font-bold text-text-bright mb-3 flex items-center gap-2">
            <TrendingUp size={14} className="text-neon-cyan" /> Most Active Groups
          </h3>
          <div className="space-y-2">
            {data.active_groups.slice(0, 15).map((g, i) => (
              <div key={g.name} className="flex items-center gap-3 text-[12px]">
                <span className="text-text-dim w-5 text-right">{i + 1}.</span>
                <span className="text-text-bright font-semibold flex-1">{g.name}</span>
                <span className="text-[10px] text-neon-green">{g.sites} sites</span>
                <span className="text-[10px] text-neon-cyan">{g.ttps_count} TTPs</span>
              </div>
            ))}
          </div>
        </div>

        {/* Threat actors summary */}
        <div className="bg-bg-card border border-border rounded-xl p-5">
          <h3 className="text-sm font-bold text-text-bright mb-3 flex items-center gap-2">
            <Target size={14} className="text-neon-purple" /> Top Threat Actors
          </h3>
          <div className="space-y-2">
            {(data.threat_actors_summary || []).slice(0, 15).map((a, i) => (
              <div key={a.name} className="flex items-center gap-3 text-[12px]">
                <span className="text-text-dim w-5 text-right">{i + 1}.</span>
                <span className="text-text-bright font-semibold flex-1">{a.name}</span>
                <span className="text-[10px] text-neon-red">{a.victim_count} victims</span>
                <span className="text-[10px] text-amber-400">{a.total_addresses} addr</span>
                {a.active && <span className="text-[8px] text-neon-green">●</span>}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Crypto-linked incidents */}
      <div className="bg-bg-card border border-border rounded-xl p-5 mt-6">
        <h3 className="text-sm font-bold text-text-bright mb-3 flex items-center gap-2">
          <Bitcoin size={14} className="text-amber-400" /> Incidents with Crypto Addresses
        </h3>
        <div className="space-y-3">
          {data.incidents_with_crypto.slice(0, 15).map((inc, idx) => (
            <div key={idx} className="bg-bg-surface rounded-lg p-3">
              <div className="flex items-start justify-between gap-2 mb-1">
                <div>
                  <span className="text-[9px] font-bold uppercase text-neon-red">{inc.group}</span>
                  <h4 className="text-[12px] font-semibold text-text-bright">{inc.title}</h4>
                </div>
                <span className="text-[10px] text-text-dim shrink-0">{fmtDate(inc.discovered)}</span>
              </div>
              <CryptoAddressList addresses={inc.crypto_addresses} />
            </div>
          ))}
          {data.incidents_with_crypto.length === 0 && (
            <p className="text-[12px] text-text-muted text-center py-6">No crypto-linked incidents found in recent data.</p>
          )}
        </div>
      </div>

      {/* Recent incidents timeline */}
      <div className="bg-bg-card border border-border rounded-xl p-5 mt-6">
        <h3 className="text-sm font-bold text-text-bright mb-3 flex items-center gap-2">
          <Clock size={14} className="text-neon-cyan" /> Recent Incidents Timeline
        </h3>
        <div className="space-y-2">
          {data.recent_incidents.slice(0, 20).map((inc, idx) => (
            <div key={idx} className="flex items-center gap-3 text-[12px] py-1.5 border-b border-border/40 last:border-0">
              <span className="text-text-dim text-[10px] shrink-0 w-20">{fmtDate(inc.discovered)}</span>
              <span className="text-neon-red font-bold text-[10px] uppercase shrink-0 w-24 truncate">{inc.group}</span>
              <span className="text-text-bright truncate flex-1">{inc.title}</span>
              {inc.victim_country && <span className="text-text-dim text-[10px] shrink-0">{inc.victim_country}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   NEWS DETAIL VIEW
   ══════════════════════════════════════════════════════════════════════════════ */
function ThreatFeedDetail({ id }: { id: string }) {
  const navigate = useNavigate()
  const { data: item, isLoading, isError } = useQuery({
    queryKey: ['threat-feed-item', id],
    queryFn: () => getThreatFeedItem(id),
  })
  return (
    <div className="page-enter max-w-[860px] mx-auto px-5 py-6">
      <button onClick={() => navigate('/threat-landscape')} className="inline-flex items-center gap-1.5 text-[12px] text-text-muted hover:text-neon-cyan transition mb-5">
        <ArrowLeft size={14} /> Back to Threat Landscape
      </button>
      {isLoading && <div className="flex items-center justify-center gap-2 text-text-muted py-24"><Loader2 size={18} className="animate-spin" /> Loading article…</div>}
      {isError && (
        <div className="flex items-center gap-2 text-neon-red bg-neon-red/10 border border-neon-red/30 rounded-lg px-4 py-3 text-[13px]">
          <AlertTriangle size={16} /> Article unavailable. <button onClick={() => navigate('/threat-landscape')} className="underline">go back</button>.
        </div>
      )}
      {item && (
        <article>
          <div className="flex items-center gap-2 flex-wrap mb-3">
            <span className={`inline-flex items-center gap-1 text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${tone(item.source_id)}`}>
              <Rss size={10} /> {item.publisher}
            </span>
            <span className="text-[10px] uppercase tracking-wider text-text-muted">{item.category}</span>
          </div>
          <h1 className="text-2xl font-display font-bold text-text-bright leading-tight mb-3">{item.title}</h1>
          <div className="flex items-center gap-4 text-[12px] text-text-muted mb-5 pb-5 border-b border-border flex-wrap">
            {item.author && <span className="inline-flex items-center gap-1"><User size={12} /> {item.author}</span>}
            <span className="inline-flex items-center gap-1"><CalendarDays size={12} /> {fmtDate(item.published)}</span>
            {item.reading_minutes > 0 && <span className="inline-flex items-center gap-1"><Clock size={12} /> {item.reading_minutes} min read</span>}
            {item.link && <a href={item.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 ml-auto text-neon-cyan hover:underline">Open original <ExternalLink size={12} /></a>}
          </div>
          {item.image && <img src={item.image} alt="" className="w-full rounded-xl border border-border mb-6 object-cover max-h-80" onError={(e) => { e.currentTarget.style.display = 'none' }} />}
          {item.content_html ? (
            <div className="threat-article prose-invert" dangerouslySetInnerHTML={{ __html: sanitizeHtml(item.content_html) }} />
          ) : (
            <p className="text-text-secondary">{item.summary}</p>
          )}
          {item.link && (
            <div className="mt-8 pt-5 border-t border-border">
              <a href={item.link} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-neon-cyan/10 border border-neon-cyan/30 text-neon-cyan text-[13px] font-semibold hover:bg-neon-cyan/20 transition">
                Read the full article at the source <ExternalLink size={14} />
              </a>
            </div>
          )}
        </article>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   MAIN ENTRY — Tabbed layout with shared baseline
   ══════════════════════════════════════════════════════════════════════════════ */
function ThreatLandscapeHome() {
  const [activeTab, setActiveTab] = useState<TabId>('actors')
  const queryClient = useQueryClient()

  // Single baseline fetch — loads ALL tab data at once from server cache
  const { data: baseline, isLoading: baselineLoading, isError: baselineError, refetch: refetchBaseline } = useQuery({
    queryKey: ['threat-baseline'],
    queryFn: getThreatBaseline,
    staleTime: 5 * 60_000,     // consider stale after 5 min
    gcTime: 30 * 60_000,       // keep in cache 30 min
    retry: 2,
    retryDelay: 3000,
  })

  // Poll refresh status when a background refresh is running
  const { data: refreshStatus } = useQuery({
    queryKey: ['threat-refresh-status'],
    queryFn: getThreatRefreshStatus,
    refetchInterval: (query) => query.state.data?.running ? 3000 : false,
  })

  const isRefreshing = refreshStatus?.running ?? false

  const handleRefresh = async () => {
    try {
      await refreshThreatData()
      // Poll until refresh completes, then refetch baseline
      const poll = setInterval(async () => {
        const status = await getThreatRefreshStatus()
        if (!status.running) {
          clearInterval(poll)
          await queryClient.invalidateQueries({ queryKey: ['threat-baseline'] })
        }
      }, 3000)
    } catch { /* ignore */ }
  }

  // When baseline loads, invalidate individual tab queries so they pick up fresh data
  useMemo(() => {
    if (baseline) {
      queryClient.setQueryData(['ransomware-groups'], baseline.groups)
      queryClient.setQueryData(['ransomware-incidents', ''], baseline.incidents)
      queryClient.setQueryData(['threat-actors', 'victim_count', false], baseline.actors)
      queryClient.setQueryData(['address-intel', '', '', false], baseline.addresses)
    }
  }, [baseline, queryClient])

  return (
    <div className="page-enter max-w-[1400px] mx-auto px-5 py-6">
      <div className="flex items-start justify-between gap-4 flex-wrap mb-5">
        <div className="flex items-start gap-3">
          <div className="p-2.5 rounded-xl bg-neon-red/10 border border-neon-red/30">
            <ShieldAlert className="text-neon-red" size={22} />
          </div>
          <div>
            <h1 className="text-xl font-display font-bold text-text-bright">Blockchain Threat Landscape</h1>
            <p className="text-[13px] text-text-muted mt-0.5">
              Comprehensive crypto threat intelligence — ransomware actors, crypto wallets, incidents & live monitoring.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {baseline?.cache_populated && baseline?.cache_age_sec != null && (
            <span className="text-[10px] text-text-dim">
              Cache: {baseline.cache_age_sec < 60 ? `${baseline.cache_age_sec}s` : `${Math.round(baseline.cache_age_sec / 60)}m`} old
            </span>
          )}
          {isRefreshing && (
            <span className="inline-flex items-center gap-1 text-[10px] text-neon-cyan">
              <Loader2 size={10} className="animate-spin" /> Refreshing…
            </span>
          )}
          <button onClick={handleRefresh} disabled={isRefreshing || baselineLoading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-bg-surface
                       text-text-secondary text-[12px] font-semibold hover:text-text-bright hover:border-neon-cyan/40 transition disabled:opacity-50">
            {isRefreshing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {isRefreshing ? 'Updating…' : 'Refresh All'}
          </button>
        </div>
      </div>

      {/* First-load states */}
      {baselineLoading && (
        <div className="flex flex-col items-center justify-center gap-3 text-text-muted py-24">
          <Loader2 size={24} className="animate-spin text-neon-cyan" />
          <div className="text-[13px]">Loading threat intelligence baseline…</div>
          <div className="text-[11px] text-text-dim">Fetching from multiple sources — this may take a moment on first load.</div>
        </div>
      )}
      {baselineError && !baseline && (
        <div className="flex flex-col items-center gap-3 py-24">
          <div className="flex items-center gap-2 text-neon-red bg-neon-red/10 border border-neon-red/30 rounded-lg px-4 py-3 text-[13px]">
            <AlertTriangle size={16} /> Could not load threat data. The intelligence sources may be unreachable.
          </div>
          <button onClick={() => refetchBaseline()}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border border-neon-cyan/40 bg-neon-cyan/10 text-neon-cyan text-[12px] font-semibold hover:bg-neon-cyan/20 transition">
            <RefreshCw size={14} /> Retry
          </button>
        </div>
      )}

      {/* Tab bar — only show once we have data or are retrying */}
      {(baseline || !baselineLoading) && (
        <>
          <div className="flex items-center gap-1 mb-6 border-b border-border overflow-x-auto">
            {TABS.map(tab => {
              const Icon = tab.icon
              const isActive = activeTab === tab.id
              return (
                <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                  className={`inline-flex items-center gap-1.5 px-4 py-2.5 text-[12px] font-semibold border-b-2 transition whitespace-nowrap
                    ${isActive ? 'text-neon-cyan border-neon-cyan' : 'text-text-muted border-transparent hover:text-text-secondary hover:border-border'}`}>
                  <Icon size={14} /> {tab.label}
                </button>
              )
            })}
          </div>
          {activeTab === 'news' && <NewsTab />}
          {activeTab === 'incidents' && <IncidentsTab baseline={baseline} />}
          {activeTab === 'actors' && <ThreatActorsTab baseline={baseline} />}
          {activeTab === 'gangs' && <GangsTab baseline={baseline} />}
          {activeTab === 'addresses' && <AddressIntelTab baseline={baseline} />}
          {activeTab === 'feed' && <IntelDashboardTab baseline={baseline} />}
        </>
      )}
    </div>
  )
}

/* ── Entry ─────────────────────────────────────────────────────────────────── */
export default function BlockchainThreatLandscape() {
  const { id } = useParams()
  if (id) return <ThreatFeedDetail id={id} />
  return <ThreatLandscapeHome />
}
