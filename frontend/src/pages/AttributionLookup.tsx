import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  BadgeCheck, FileSearch, Fingerprint, Gavel, Loader2, Plus, Search, ShieldAlert, X,
} from 'lucide-react'
import { getAttribution, addAttribution } from '../api/attribution'
import CinematicStage from '../components/CinematicStage'
import type { Attribution, AttributionResult } from '../api/attribution'

const CHAINS = ['', 'eth', 'btc', 'bsc', 'polygon', 'arbitrum', 'optimism', 'base', 'trx']
const CATEGORIES = ['sanctioned', 'exchange', 'mixer', 'bridge', 'dex', 'darknet', 'scam', 'ransomware', 'terrorist_financing', 'gambling', 'merchant', 'contract', 'unknown']

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

function classColor(c: string) {
  if (c === 'deterministic') return '#22c578'
  if (c === 'analyst') return '#fbbf24'
  if (c === 'heuristic') return '#9a858c'
  return '#9a858c'
}
function confColor(c: number) {
  if (c >= 0.95) return '#22c578'
  if (c >= 0.7) return '#fbbf24'
  return '#ff7a18'
}

function AttributionCard({ a }: { a: Attribution }) {
  return (
    <div className="rounded-lg border border-border bg-bg-secondary p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded px-2 py-0.5 text-[10px] font-bold uppercase" style={{ color: classColor(a.method_class), background: `${classColor(a.method_class)}1a` }}>{a.method_class}</span>
            <span className="rounded border border-border px-2 py-0.5 text-[10px] text-text-muted">{a.category}</span>
          </div>
          <p className="mt-1.5 text-sm font-semibold text-text-primary">{a.label || a.actor || a.category}</p>
          <p className="text-[11px] text-text-muted">via <span className="font-mono">{a.method}</span></p>
        </div>
        <div className="text-right">
          <p className="font-mono text-lg font-bold" style={{ color: confColor(a.confidence) }}>{Math.round(a.confidence * 100)}%</p>
          <p className="text-[9px] uppercase tracking-widest text-text-muted">confidence</p>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
        <span className="text-text-muted">Source: <span className="text-text-secondary">{a.source}</span></span>
        <span className="text-text-muted">By: <span className="text-text-secondary">{a.assigned_by}</span></span>
        <span className="text-text-muted">{new Date(a.assigned_at).toLocaleString()}</span>
      </div>
      {a.evidence.length > 0 && (
        <div className="mt-2 rounded border border-border/60 bg-bg-primary/40 p-2">
          <p className="mb-1 text-[9px] uppercase tracking-widest text-text-muted">Evidence</p>
          {a.evidence.map((e, i) => (
            <p key={i} className="font-mono text-[10px] text-text-secondary break-all">
              <span className="text-neon-cyan">{e.type}</span>: {e.value}{e.ref ? <span className="text-text-muted"> · {e.ref}</span> : ''}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

export default function AttributionLookup() {
  const { t } = useTranslation()
  const [address, setAddress] = useState('')
  const [chain, setChain] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AttributionResult | null>(null)
  const [showAdd, setShowAdd] = useState(false)

  // add form
  const [fCat, setFCat] = useState('scam')
  const [fActor, setFActor] = useState('')
  const [fSource, setFSource] = useState('')
  const [fConf, setFConf] = useState('0.7')
  const [fEvid, setFEvid] = useState('')
  const [fBy, setFBy] = useState('analyst')

  async function run(addr?: string) {
    const clean = (addr ?? address).trim()
    if (!clean || loading) return
    setAddress(clean); setLoading(true); setError(null)
    try { setResult(await getAttribution(clean, chain || undefined)) }
    catch (e) { setError(friendlyError(e)) } finally { setLoading(false) }
  }

  async function submitAdd() {
    if (!address.trim() || !fActor.trim()) return
    setLoading(true); setError(null)
    try {
      const res = await addAttribution({
        address: address.trim(), category: fCat, actor: fActor.trim(), source: fSource.trim(),
        confidence: Number(fConf) || 0.6, chain: chain || undefined, assigned_by: fBy.trim() || 'analyst',
        evidence: fEvid.trim() ? [{ type: 'analyst_note', value: fEvid.trim(), ref: `assigned by ${fBy.trim() || 'analyst'}` }] : [],
      })
      setResult(res); setShowAdd(false); setFActor(''); setFEvid('')
    } catch (e) { setError(friendlyError(e)) } finally { setLoading(false) }
  }

  return (
    <div className="noscroll-page mx-auto max-w-5xl space-y-5 p-6">
      <div className="card overflow-hidden p-0">
        <div className="flex items-start gap-4 border-b border-border p-5" style={{ background: 'linear-gradient(135deg, rgba(34,197,120,0.1), rgba(255,64,82,0.06))' }}>
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-neon-green/35 bg-neon-green/10">
            <Fingerprint size={22} className="text-neon-green" />
          </div>
          <div>
            <h1 className="text-display text-lg font-bold uppercase tracking-widest text-text-primary">{t('tools:attribution.title')}</h1>
            <p className="mt-1 max-w-3xl text-sm text-text-secondary">
              Court-defensible address attribution. Every label carries its source, method, confidence, and cited evidence -
              deterministic exact-match labels are court-defensible; heuristic labels are investigative leads.
            </p>
          </div>
        </div>
        <CinematicStage
          variant="attribution"
          icon={Fingerprint}
          collapsed={!!result}
        >
          <div className="space-y-3 p-4">
            <div className="grid gap-3 lg:grid-cols-[1fr_120px_auto]">
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
                <input className="input pl-9" placeholder="Address to attribute (0x… / bc1… / T…)" value={address}
                  onChange={e => setAddress(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') run() }} />
              </div>
              <select className="input" value={chain} onChange={e => setChain(e.target.value)}>
                {CHAINS.map(c => <option key={c} value={c}>{c ? c.toUpperCase() : 'any chain'}</option>)}
              </select>
              <button className="btn-primary" disabled={loading || !address.trim()} onClick={() => run()}>
                {loading ? <Loader2 size={14} className="animate-spin" /> : <FileSearch size={14} />} Attribute
              </button>
            </div>
          </div>
        </CinematicStage>
      </div>

      {/* Results — grows & scrolls internally */}
      <div className="noscroll-grow space-y-5">
      {error && <div className="rounded-lg border border-neon-red/35 bg-neon-red/10 p-4 text-sm text-neon-red">{error}</div>}

      {result && (
        <>
          {/* Court-defensibility verdict */}
          <div className="card flex flex-wrap items-center justify-between gap-3" style={{ borderColor: result.court_defensible ? 'rgba(34,197,120,0.4)' : 'rgba(255,159,10,0.4)' }}>
            <div className="flex items-center gap-3">
              {result.court_defensible
                ? <Gavel size={26} className="text-neon-green" />
                : <ShieldAlert size={26} className="text-neon-amber" />}
              <div>
                <p className="text-lg font-bold" style={{ color: result.court_defensible ? '#22c578' : '#fbbf24' }}>
                  {result.court_defensible ? 'Court-defensible attribution' : 'Investigative lead only'}
                </p>
                <p className="text-xs text-text-muted">{result.court_defensible_reason}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button className="btn-ghost text-xs" title="Printable methodology document: how every attribution was derived (print → PDF)"
                onClick={() => import('../api/boards').then(m => m.openSourceReport(address.trim(), chain || undefined))}>
                <FileSearch size={13} /> Source Report
              </button>
              <button className="btn-ghost text-xs" onClick={() => setShowAdd(s => !s)}>
                {showAdd ? <X size={13} /> : <Plus size={13} />} {showAdd ? 'Cancel' : 'Add analyst attribution'}
              </button>
            </div>
          </div>

          {showAdd && (
            <div className="card space-y-3">
              <p className="text-sm font-bold text-text-primary">Add analyst attribution (provenance-tracked)</p>
              <div className="grid gap-3 md:grid-cols-3">
                <select className="input" value={fCat} onChange={e => setFCat(e.target.value)}>
                  {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <input className="input" placeholder="Actor / entity" value={fActor} onChange={e => setFActor(e.target.value)} />
                <input className="input" placeholder="Confidence 0-1" value={fConf} onChange={e => setFConf(e.target.value)} />
                <input className="input" placeholder="Source (e.g. victim report #42)" value={fSource} onChange={e => setFSource(e.target.value)} />
                <input className="input" placeholder="Assigned by (analyst)" value={fBy} onChange={e => setFBy(e.target.value)} />
                <input className="input" placeholder="Evidence note" value={fEvid} onChange={e => setFEvid(e.target.value)} />
              </div>
              <button className="btn-primary text-xs" disabled={loading || !fActor.trim()} onClick={submitAdd}>
                {loading ? <Loader2 size={13} className="animate-spin" /> : <BadgeCheck size={13} />} Save attribution
              </button>
              <p className="text-[11px] text-text-muted">Analyst attributions are recorded as `analyst` method-class (not court-defensible on their own) with full provenance and audit trail.</p>
            </div>
          )}

          {/* Summary */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div className="rounded-lg border border-border bg-bg-secondary px-3 py-3"><p className="text-[10px] uppercase tracking-widest text-text-muted">Attributions</p><p className="mt-1 font-mono text-xl font-bold text-text-primary">{result.attribution_count}</p></div>
            <div className="rounded-lg border border-border bg-bg-secondary px-3 py-3"><p className="text-[10px] uppercase tracking-widest text-text-muted">Top confidence</p><p className="mt-1 font-mono text-xl font-bold" style={{ color: confColor(result.overall_confidence) }}>{Math.round(result.overall_confidence * 100)}%</p></div>
            <div className="rounded-lg border border-border bg-bg-secondary px-3 py-3"><p className="text-[10px] uppercase tracking-widest text-text-muted">Categories</p><p className="mt-1 truncate text-sm text-text-primary">{result.categories.join(', ') || '-'}</p></div>
            <div className="rounded-lg border border-border bg-bg-secondary px-3 py-3"><p className="text-[10px] uppercase tracking-widest text-text-muted">Actors</p><p className="mt-1 truncate text-sm text-text-primary">{result.actors.join(', ') || '-'}</p></div>
          </div>

          {result.attributions.length === 0 ? (
            <div className="card text-sm text-text-muted">No attributions found for this address. Add an analyst attribution above, or it may simply be unknown.</div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {result.attributions.map((a, i) => <AttributionCard key={a.id || i} a={a} />)}
            </div>
          )}

          <p className="text-[11px] italic text-text-muted">{result.disclaimer}</p>
        </>
      )}
      </div>
    </div>
  )
}
