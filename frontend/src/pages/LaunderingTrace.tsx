import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Droplets, Loader2, ArrowRightLeft, Shuffle, Crosshair } from 'lucide-react'
import { detectPoisoning, swapTrace, launderingTypologies } from '../api/client'
import CinematicStage from '../components/CinematicStage'

type Tab = 'poisoning' | 'swap' | 'typologies'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}
function parseJSON<T>(s: string, fallback: T): T {
  try { return s.trim() ? JSON.parse(s) : fallback } catch { return fallback }
}
const TABS: { id: Tab; label: string; icon: typeof Droplets }[] = [
  { id: 'poisoning', label: 'Address Poisoning', icon: Crosshair },
  { id: 'swap', label: 'Swap Continuation', icon: ArrowRightLeft },
  { id: 'typologies', label: 'Laundering Typologies', icon: Shuffle },
]

export default function LaunderingTrace() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('poisoning')
  return (
    <div className="noscroll-page p-6 max-w-7xl mx-auto space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
          <Droplets size={22} className="text-neon-cyan" /> Modern Laundering &amp; Tracing
        </h1>
        <p className="text-sm text-text-muted mt-1">
          Close the 2026 dead-ends — look-alike poisoning, no-KYC instant-swap continuation, and peel-chain /
          micro-fragmentation typologies. Deterministic leads with explicit confidence.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
              tab === t.id ? 'bg-neon-cyan/15 text-neon-cyan' : 'text-text-muted hover:text-text-primary'}`}>
            <t.icon size={14} /> {t.label}
          </button>
        ))}
      </div>
      <div className="noscroll-grow">
      <CinematicStage variant="laundering" icon={Droplets} title="Modern Laundering & Tracing" subtitle="Close the 2026 dead-ends — look-alike poisoning, no-KYC instant-swap continuation, and peel-chain / micro-fragmentation typologies. Deterministic leads with explicit confidence." collapsed={false}>
        {tab === 'poisoning' && <PoisoningTab />}
        {tab === 'swap' && <SwapTab />}
        {tab === 'typologies' && <TypologyTab />}
      </CinematicStage>
      </div>
    </div>
  )
}

const SAMPLE_TRANSFERS = '[\n  {"from":"0xVICTIM…","to":"0xrealCounterparty…","value_usd":5000},\n  {"from":"0xlookAlike…","to":"0xVICTIM…","value_usd":0,"tx_hash":"0x…"}\n]'

function PoisoningTab() {
  const [subject, setSubject] = useState('')
  const [transfers, setTransfers] = useState(SAMPLE_TRANSFERS)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(''); const [res, setRes] = useState<any>(null)
  async function run() {
    setLoading(true); setErr(''); setRes(null)
    try { setRes(await detectPoisoning({ subject, transfers: parseJSON(transfers, []) })) }
    catch (e) { setErr(friendlyError(e)) } finally { setLoading(false) }
  }
  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <input className="input" placeholder="Subject / victim address" value={subject} onChange={e => setSubject(e.target.value)} />
        <textarea className="input font-mono text-xs h-40" value={transfers} onChange={e => setTransfers(e.target.value)} />
        <button className="btn-primary w-full justify-center flex items-center gap-2" onClick={run} disabled={loading || !subject}>
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Crosshair size={16} />} Detect poisoning
        </button>
      </div>
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {res && (
        <div className="card space-y-3">
          <span className="text-lg font-bold" style={{ color: res.severity === 'critical' ? '#ff4052' : '#34D399' }}>{res.verdict}</span>
          <div className="flex gap-3 text-sm text-text-muted">
            <span>{res.real_counterparties} real counterparties</span>·<span>{res.inbound_dust_transfers} dust in</span>·<span>{res.poisoning_hits.length} hits</span>
          </div>
          {res.poisoning_hits.map((h: any, i: number) => (
            <div key={i} className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm">
              <div className="font-mono text-red-300">{h.poison_address}</div>
              <div className="text-text-secondary mt-1">{h.detail}</div>
            </div>
          ))}
          <p className="text-xs text-text-muted border-t border-border pt-2">{res.guidance}</p>
        </div>
      )}
    </div>
  )
}

function SwapTab() {
  const [subject, setSubject] = useState('')
  const [transfers, setTransfers] = useState('[\n  {"from":"0xSUBJECT…","to":"0xc145990e84155416144c532e31f89b840ca8c2ce","value_usd":10000,"tx_hash":"0x…","timestamp":1710000000}\n]')
  const [outputs, setOutputs] = useState('[\n  {"value_usd":9900,"chain":"btc","tx_hash":"0x…","timestamp":1710003600}\n]')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(''); const [res, setRes] = useState<any>(null)
  async function run() {
    setLoading(true); setErr(''); setRes(null)
    try { setRes(await swapTrace({ subject, transfers: parseJSON(transfers, []), candidate_outputs: parseJSON(outputs, []) })) }
    catch (e) { setErr(friendlyError(e)) } finally { setLoading(false) }
  }
  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <input className="input" placeholder="Subject address" value={subject} onChange={e => setSubject(e.target.value)} />
        <label className="text-xs text-text-muted">Outgoing flows (to detect swap-service entries)</label>
        <textarea className="input font-mono text-xs h-28" value={transfers} onChange={e => setTransfers(e.target.value)} />
        <label className="text-xs text-text-muted">Candidate outputs on destination chains (to re-match by value + time)</label>
        <textarea className="input font-mono text-xs h-24" value={outputs} onChange={e => setOutputs(e.target.value)} />
        <button className="btn-primary w-full justify-center flex items-center gap-2" onClick={run} disabled={loading || !subject}>
          {loading ? <Loader2 size={16} className="animate-spin" /> : <ArrowRightLeft size={16} />} Trace continuation
        </button>
      </div>
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {res && (
        <div className="card space-y-3">
          <span className="text-lg font-bold text-neon-cyan">{res.verdict}</span>
          {res.swap_entries.map((e: any, i: number) => (
            <div key={i} className="rounded-lg border border-border bg-bg-secondary/40 p-3 text-sm">
              <span className="badge mr-2">{e.service}</span><span className="text-text-muted">{e.service_type}{e.kyc ? '' : ' · no-KYC'}</span>
              <div className="text-text-secondary mt-1">{e.note}</div>
              <div className="text-xs font-mono text-text-muted mt-1">${Number(e.value_usd).toLocaleString()} → {e.deposit_address}</div>
            </div>
          ))}
          {res.continuation_matches.map((m: any, i: number) => (
            <div key={i} className="rounded-lg border border-neon-cyan/40 bg-neon-cyan/10 p-3 text-sm">
              <div className="flex items-center justify-between"><span className="font-semibold">{m.service} → {m.output_chain}</span><span className="badge">{(m.confidence * 100).toFixed(0)}% conf</span></div>
              <div className="text-text-secondary mt-1">{m.detail}</div>
            </div>
          ))}
          {res.dead_end && <p className="text-xs text-amber-400">Trace boundary reached — supply candidate outputs on likely destination chains to re-match.</p>}
          <p className="text-xs text-text-muted border-t border-border pt-2">{res.disclaimer}</p>
        </div>
      )}
    </div>
  )
}

function TypologyTab() {
  const [subject, setSubject] = useState('')
  const [transfers, setTransfers] = useState('[\n  {"from":"0xSUBJECT…","to":"0xA…","value_usd":1500,"timestamp":1},\n  {"from":"0xSUBJECT…","to":"0xB…","value_usd":1450,"timestamp":2}\n]')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(''); const [res, setRes] = useState<any>(null)
  async function run() {
    setLoading(true); setErr(''); setRes(null)
    try { setRes(await launderingTypologies({ subject, transfers: parseJSON(transfers, []) })) }
    catch (e) { setErr(friendlyError(e)) } finally { setLoading(false) }
  }
  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <input className="input" placeholder="Subject address" value={subject} onChange={e => setSubject(e.target.value)} />
        <textarea className="input font-mono text-xs h-40" value={transfers} onChange={e => setTransfers(e.target.value)} />
        <button className="btn-primary w-full justify-center flex items-center gap-2" onClick={run} disabled={loading || !subject}>
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Shuffle size={16} />} Score typologies
        </button>
      </div>
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {res && (
        <div className="card space-y-3">
          <div className="flex flex-wrap gap-3 text-sm text-text-muted">
            <span className="text-text-primary font-semibold">{res.verdict}</span>
            <span>{res.outflow_count} out</span>·<span>{res.distinct_destinations} destinations</span>·<span>layering: {res.layering}</span>
          </div>
          {res.typologies.map((t: any, i: number) => (
            <div key={i} className="rounded-lg border border-border bg-bg-secondary/40 p-3">
              <div className="flex items-center justify-between"><span className="font-semibold text-text-primary">{t.title}</span><span className="badge">{(t.confidence * 100).toFixed(0)}% conf</span></div>
              <p className="text-sm text-text-secondary mt-1">{t.detail}</p>
              <p className="text-xs font-mono text-text-muted mt-1">{t.evidence}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
