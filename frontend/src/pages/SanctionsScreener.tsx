import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ReactNode } from 'react'
import { AlertOctagon, CheckCircle2, ChevronRight, Copy, ExternalLink, Loader2, RefreshCw, Search, ShieldAlert, ShieldCheck, X } from 'lucide-react'
import { screenSanctions, searchSanctions, sanctionsStatus, refreshSanctions, getSanctionsEntity } from '../api/client'
import type { SanctionsEntityDetail, SanctionsMatch, SanctionsScreenResult, SanctionsSearchResult, SanctionsStatus } from '../types'
import CinematicStage from '../components/CinematicStage'
import FeedSyncPanel from '../components/FeedSyncPanel'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

const EXPLORERS: Record<string, (a: string) => string> = {
  eth: a => `https://etherscan.io/address/${a}`,
  btc: a => `https://mempool.space/address/${a}`,
  tron: a => `https://tronscan.org/#/address/${a}`,
  trx: a => `https://tronscan.org/#/address/${a}`,
}

function explorerUrl(chain: string, address: string): string | null {
  const fn = EXPLORERS[(chain || '').toLowerCase()]
  return fn ? fn(address) : null
}

function MatchCard({ m, onClick }: { m: SanctionsMatch; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group w-full rounded-lg border border-neon-red/35 bg-neon-red/5 p-3 text-left transition-colors hover:border-neon-red/70 hover:bg-neon-red/10 focus:outline-none focus:ring-2 focus:ring-neon-red/50"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-bold text-text-primary">{m.name}</p>
          <p className="text-[11px] uppercase tracking-widest text-text-muted">{m.type} · {m.source}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {typeof m.score === 'number' && (
            <span className="rounded-full bg-neon-amber/15 px-2 py-1 text-[10px] font-bold text-neon-amber">{Math.round(m.score * 100)}% match</span>
          )}
          <ChevronRight size={16} className="text-text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-neon-red" />
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {m.programs.map(p => <span key={p} className="rounded border border-border px-2 py-0.5 text-[10px] text-text-muted">{p}</span>)}
        {m.country && <span className="rounded border border-border px-2 py-0.5 text-[10px] text-text-muted">{m.country}</span>}
        {m.listed_on && <span className="rounded border border-border px-2 py-0.5 text-[10px] text-text-muted">listed {m.listed_on}</span>}
      </div>
      {m.aliases.length > 0 && <p className="mt-2 text-[11px] text-text-muted">aka: {m.aliases.join(', ')}</p>}
      <p className="mt-2 text-[10px] font-semibold uppercase tracking-widest text-neon-red/70 opacity-0 transition-opacity group-hover:opacity-100">View full details →</p>
    </button>
  )
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_1fr] gap-3 py-2">
      <span className="text-[11px] uppercase tracking-widest text-text-muted">{label}</span>
      <div className="text-sm text-text-primary">{children}</div>
    </div>
  )
}

function AddressRow({ address, chain }: { address: string; chain: string }) {
  const [copied, setCopied] = useState(false)
  const url = explorerUrl(chain, address)
  async function copy() {
    try { await navigator.clipboard.writeText(address); setCopied(true); setTimeout(() => setCopied(false), 1200) } catch { /* ignore */ }
  }
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-bg-secondary/50 px-3 py-2">
      {chain && <span className="shrink-0 rounded bg-bg-elevated px-1.5 py-0.5 text-[10px] font-bold uppercase text-text-muted">{chain}</span>}
      <code className="min-w-0 flex-1 truncate font-mono text-xs text-text-secondary" title={address}>{address}</code>
      <button type="button" onClick={copy} className="shrink-0 text-text-muted hover:text-text-primary" title="Copy address">
        {copied ? <CheckCircle2 size={14} className="text-neon-green" /> : <Copy size={14} />}
      </button>
      {url && (
        <a href={url} target="_blank" rel="noreferrer" className="shrink-0 text-text-muted hover:text-neon-cyan" title="Open in explorer">
          <ExternalLink size={14} />
        </a>
      )}
    </div>
  )
}

function SanctionsDetailDrawer({ uid, onClose }: { uid: string; onClose: () => void }) {
  const [detail, setDetail] = useState<SanctionsEntityDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true); setError(null); setDetail(null)
    getSanctionsEntity(uid)
      .then(d => { if (alive) setDetail(d) })
      .catch(e => { if (alive) setError(friendlyError(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [uid])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-[70] flex justify-end bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-md flex-col border-l border-border bg-bg-elevated shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border p-5"
          style={{ background: 'linear-gradient(135deg, rgba(255,45,85,0.12), rgba(255,159,10,0.05))' }}>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-neon-red/35 bg-neon-red/10">
              <AlertOctagon size={18} className="text-neon-red" />
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-widest text-neon-red">Sanctioned entity</p>
              <h2 className="text-sm font-bold text-text-primary">{detail?.name ?? '…'}</h2>
            </div>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary" title="Close">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {loading && (
            <div className="flex items-center gap-2 text-sm text-text-muted"><Loader2 size={14} className="animate-spin" /> Loading details…</div>
          )}
          {error && !loading && (
            <div className="rounded-lg border border-neon-red/35 bg-neon-red/10 p-3 text-sm text-neon-red">{error}</div>
          )}
          {detail && !loading && (
            <div className="divide-y divide-border">
              <DetailRow label="Name">{detail.name}</DetailRow>
              <DetailRow label="Type"><span className="capitalize">{detail.type}</span></DetailRow>
              <DetailRow label="Source">{detail.source || '—'}</DetailRow>
              <DetailRow label="Listed on">{detail.listed_on || '—'}</DetailRow>
              <DetailRow label="Country">{detail.country || '—'}</DetailRow>
              <DetailRow label="Programs">
                {detail.programs.length ? (
                  <div className="flex flex-wrap gap-1">
                    {detail.programs.map(p => <span key={p} className="rounded border border-border px-2 py-0.5 text-[10px] text-text-muted">{p}</span>)}
                  </div>
                ) : '—'}
              </DetailRow>
              <DetailRow label="Aliases">
                {detail.aliases.length ? (
                  <ul className="space-y-0.5">{detail.aliases.map(a => <li key={a} className="text-text-secondary">{a}</li>)}</ul>
                ) : '—'}
              </DetailRow>
              <DetailRow label="Entity ID"><code className="font-mono text-xs text-text-muted">{detail.uid}</code></DetailRow>

              <div className="pt-4">
                <p className="mb-2 text-[11px] uppercase tracking-widest text-text-muted">
                  Designated addresses ({detail.address_count})
                </p>
                {detail.addresses.length ? (
                  <div className="space-y-2">
                    {detail.addresses.map(a => <AddressRow key={`${a.chain}:${a.address}`} address={a.address} chain={a.chain} />)}
                  </div>
                ) : (
                  <p className="text-sm text-text-muted">No blockchain addresses on record for this entity.</p>
                )}
              </div>

              {detail.updated_at && (
                <p className="pt-4 text-[10px] text-text-muted">Record updated {new Date(detail.updated_at).toLocaleString()}</p>
              )}
            </div>
          )}
        </div>

        <div className="border-t border-border p-4">
          <p className="text-[11px] leading-relaxed text-text-muted">
            Investigative lead only — confirm against the official primary source before any compliance action.
          </p>
        </div>
      </div>
    </div>
  )
}

export default function SanctionsScreener() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<'address' | 'name'>('address')
  const [address, setAddress] = useState('')
  const [chain, setChain] = useState('')
  const [name, setName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [screen, setScreen] = useState<SanctionsScreenResult | null>(null)
  const [search, setSearch] = useState<SanctionsSearchResult | null>(null)
  const [status, setStatus] = useState<SanctionsStatus | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [selectedUid, setSelectedUid] = useState<string | null>(null)

  useEffect(() => { sanctionsStatus().then(setStatus).catch(() => undefined) }, [])

  async function runScreen() {
    if (!address.trim() || loading) return
    setLoading(true); setError(null); setScreen(null)
    try { setScreen(await screenSanctions(address.trim(), chain || undefined)) }
    catch (e) { setError(friendlyError(e)) } finally { setLoading(false) }
  }

  async function runSearch() {
    if (!name.trim() || loading) return
    setLoading(true); setError(null); setSearch(null)
    try { setSearch(await searchSanctions(name.trim())) }
    catch (e) { setError(friendlyError(e)) } finally { setLoading(false) }
  }

  async function runRefresh() {
    setRefreshing(true); setError(null)
    try { await refreshSanctions(); setStatus(await sanctionsStatus()) }
    catch (e) { setError(friendlyError(e)) } finally { setRefreshing(false) }
  }

  return (
    <div className="noscroll-page mx-auto max-w-5xl space-y-5 p-6">
      <div className="card overflow-hidden p-0">
        <div className="flex items-start gap-4 border-b border-border p-5" style={{ background: 'linear-gradient(135deg, rgba(255,45,85,0.12), rgba(255,159,10,0.06))' }}>
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-neon-red/35 bg-neon-red/10">
            <ShieldAlert size={22} className="text-neon-red" />
          </div>
          <div className="flex-1">
            <h1 className="text-display text-lg font-bold uppercase tracking-widest text-text-primary">{t('tools:sanctions.title')}</h1>
            <p className="mt-1 max-w-3xl text-sm text-text-secondary">{t('tools:sanctions.subtitle')}</p>
          </div>
          {status && (
            <div className="hidden text-right sm:block">
              <p className="font-mono text-xl font-bold text-text-primary">{status.entity_count}</p>
              <p className="text-[10px] uppercase tracking-widest text-text-muted">entities · {status.address_count} addrs</p>
              <button className="btn-ghost mt-2 text-xs" disabled={refreshing} onClick={runRefresh}>
                {refreshing ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} {t('tools:sanctions.refresh')}
              </button>
            </div>
          )}
        </div>

        {/* V2: Auto-sync feeds + diff alerts */}
        <div className="border-b border-border px-5 py-4" style={{ background: 'rgba(96,165,250,0.03)' }}>
          <FeedSyncPanel />
        </div>

        <div className="flex gap-1 border-b border-border px-4 pt-3">
          {(['address', 'name'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`rounded-t-lg px-4 py-2 text-sm font-semibold ${tab === t ? 'bg-bg-secondary text-text-primary' : 'text-text-muted hover:text-text-secondary'}`}>
              {t === 'address' ? 'Address screen' : 'Name search'}
            </button>
          ))}
        </div>

        <CinematicStage
          variant="sanctions"
          icon={ShieldAlert}
          collapsed={!!screen || !!search}
        >
          <div className="space-y-3 p-4">
            {tab === 'address' ? (
              <div className="grid gap-3 lg:grid-cols-[1fr_130px_auto]">
                <div className="relative">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
                  <input className="input pl-9" placeholder="0x… / bc1… / T…" value={address}
                    onChange={e => setAddress(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') runScreen() }} />
                </div>
                <input className="input" placeholder="chain (opt)" value={chain} onChange={e => setChain(e.target.value)} />
                <button className="btn-primary" disabled={loading || !address.trim()} onClick={runScreen}>
                  {loading ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />} Screen
                </button>
              </div>
            ) : (
              <div className="grid gap-3 lg:grid-cols-[1fr_auto]">
                <div className="relative">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
                  <input className="input pl-9" placeholder="Entity or individual name (fuzzy)…" value={name}
                    onChange={e => setName(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') runSearch() }} />
                </div>
                <button className="btn-primary" disabled={loading || !name.trim()} onClick={runSearch}>
                  {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />} Search
                </button>
              </div>
            )}
          </div>
        </CinematicStage>
      </div>

      {/* Results — grows & scrolls internally */}
      <div className="noscroll-grow space-y-5">
      {error && <div className="rounded-lg border border-neon-red/35 bg-neon-red/10 p-4 text-sm text-neon-red">{error}</div>}

      {screen && tab === 'address' && (
        <div className="card">
          {screen.sanctioned ? (
            <div className="mb-4 flex items-center gap-3 rounded-lg border border-neon-red/40 bg-neon-red/10 p-3">
              <AlertOctagon size={22} className="text-neon-red" />
              <div>
                <p className="font-bold text-neon-red">SANCTIONED - {screen.match_count} match{screen.match_count > 1 ? 'es' : ''}</p>
                <p className="break-all font-mono text-xs text-text-muted">{screen.address}</p>
              </div>
            </div>
          ) : (
            <div className="mb-4 flex items-center gap-3 rounded-lg border border-neon-green/40 bg-neon-green/10 p-3">
              <CheckCircle2 size={22} className="text-neon-green" />
              <div>
                <p className="font-bold text-neon-green">No sanctions match</p>
                <p className="break-all font-mono text-xs text-text-muted">{screen.address}</p>
              </div>
            </div>
          )}
          <div className="grid gap-3 md:grid-cols-2">{screen.matches.map(m => <MatchCard key={m.uid} m={m} onClick={() => setSelectedUid(m.uid)} />)}</div>
        </div>
      )}

      {search && tab === 'name' && (
        <div className="card">
          <p className="mb-3 text-sm text-text-secondary">{search.match_count} match{search.match_count !== 1 ? 'es' : ''} for "<span className="text-text-primary">{search.query}</span>"</p>
          <div className="grid gap-3 md:grid-cols-2">{search.matches.map(m => <MatchCard key={m.uid} m={m} onClick={() => setSelectedUid(m.uid)} />)}</div>
          {search.match_count === 0 && <p className="text-sm text-text-muted">No entities matched. Try a different spelling or run a feed refresh.</p>}
        </div>
      )}

      {status && (
        <p className="text-center text-[11px] text-text-muted">
          Dataset: {status.sources.map(s => `${s.source} (${s.entities})`).join(' · ')}
          {status.refreshed_at ? ` · last refresh ${new Date(status.refreshed_at).toLocaleString()}` : ' · seed only'}
        </p>
      )}

      {selectedUid && <SanctionsDetailDrawer uid={selectedUid} onClose={() => setSelectedUid(null)} />}
      </div>
    </div>
  )
}
