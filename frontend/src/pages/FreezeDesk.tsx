import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import {
  Radio, Loader2, PlusCircle, Trash2, RefreshCw, Building2, Eye, Gauge, BookOpen,
  PauseCircle, PlayCircle, Snowflake,
} from 'lucide-react'
import {
  freezeNetDirectory, freezeNetAddWatch, freezeNetListWatches, freezeNetSetWatchStatus,
  freezeNetDeleteWatch, freezeNetEvaluate, freezeNetScan, freezeNetEvents, freezeNetKpis,
} from '../api/client'
import CinematicStage from '../components/CinematicStage'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

/**
 * Freeze Desk — T3/Beacon-style freeze-network operationalization (3.2).
 * Routing directory of issuer/VASP intake channels, a Beacon-lite watchlist that
 * auto-drafts freeze packages the moment watched funds touch a labeled VASP,
 * and the freeze KPI telemetry agencies report upward.
 */
export default function FreezeDesk() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<'watch' | 'directory' | 'kpis'>('watch')
  return (
    <div className="noscroll-page p-6 max-w-7xl mx-auto space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
          <Radio size={22} className="text-neon-cyan" /> Freeze Desk — Beacon-Lite Watch
        </h1>
        <p className="text-sm text-text-muted mt-1">
          Operational last mile: watch traced illicit addresses; the moment funds touch a labeled VASP or mixer,
          a freeze-request package is auto-drafted into <Link to="/recovery" className="text-neon-cyan hover:underline">Freeze &amp; Recovery</Link>.
          Includes the issuer/VASP intake directory and freeze KPIs.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {([['watch', 'Watchlist', Eye], ['directory', 'Intake Directory', BookOpen], ['kpis', 'Freeze KPIs', Gauge]] as const).map(([id, label, Icon]) => (
          <button key={id} onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
              tab === id ? 'bg-neon-cyan/15 text-neon-cyan' : 'text-text-muted hover:text-text-primary'}`}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>
      <div className="noscroll-grow">
      <CinematicStage variant="freeze" icon={Radio} title="Freeze Desk — Beacon-Lite Watch" subtitle="Operational last mile: watch traced illicit addresses; the moment funds touch a labeled VASP or mixer, a freeze-request package is auto-drafted into Freeze & Recovery. Includes the issuer/VASP intake directory and freeze KPIs." collapsed={false}>
        {tab === 'watch' && <WatchTab />}
        {tab === 'directory' && <DirectoryTab />}
        {tab === 'kpis' && <KpisTab />}
      </CinematicStage>
      </div>
    </div>
  )
}

function WatchTab() {
  const [watches, setWatches] = useState<any[]>([])
  const [events, setEvents] = useState<any[]>([])
  const [f, setF] = useState({ address: '', chain: 'eth', asset: 'USDT', case_id: '', min_usd: '', reason: '' })
  const [manual, setManual] = useState<{ wid: string; counterparty: string; amount: string }>({ wid: '', counterparty: '', amount: '' })
  const [busy, setBusy] = useState(false)
  const [scanMsg, setScanMsg] = useState('')
  const [err, setErr] = useState('')

  async function refresh() {
    try {
      const [w, ev] = await Promise.all([freezeNetListWatches(), freezeNetEvents()])
      setWatches(w.watches || []); setEvents(ev.events || [])
    } catch (e) { setErr(friendlyError(e)) }
  }
  useEffect(() => { refresh() }, [])

  async function add() {
    setBusy(true); setErr('')
    try {
      await freezeNetAddWatch({ ...f, min_usd: Number(f.min_usd) || 0, auto_queue: true })
      setF({ address: '', chain: 'eth', asset: 'USDT', case_id: '', min_usd: '', reason: '' })
      refresh()
    } catch (e) { setErr(friendlyError(e)) } finally { setBusy(false) }
  }

  async function scan() {
    setBusy(true); setErr(''); setScanMsg('')
    try {
      const r = await freezeNetScan()
      setScanMsg(`Scanned ${r.scanned} monitor notification(s) — ${r.matches} VASP/mixer touch(es) queued.`)
      refresh()
    } catch (e) { setErr(friendlyError(e)) } finally { setBusy(false) }
  }

  async function evaluate() {
    if (!manual.wid || !manual.counterparty) return
    setBusy(true); setErr('')
    try {
      const r = await freezeNetEvaluate(manual.wid, { counterparty: manual.counterparty, direction: 'out', amount_usd: Number(manual.amount) || 0 })
      setScanMsg(r.matched
        ? `Matched: counterparty labeled '${r.label?.name || r.label?.kind}' — freeze package ${r.event?.request_id ? `#${r.event.request_id.slice(0, 8)} auto-drafted` : 'event recorded'}.`
        : `No match: ${r.reason}.`)
      refresh()
    } catch (e) { setErr(friendlyError(e)) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">Add watch</p>
          <input className="input" placeholder="Traced illicit address" value={f.address} onChange={e => setF(p => ({ ...p, address: e.target.value }))} />
          <div className="grid grid-cols-3 gap-2">
            <input className="input" placeholder="Chain" value={f.chain} onChange={e => setF(p => ({ ...p, chain: e.target.value }))} />
            <input className="input" placeholder="Asset" value={f.asset} onChange={e => setF(p => ({ ...p, asset: e.target.value }))} />
            <input className="input" placeholder="Min $ (opt)" value={f.min_usd} onChange={e => setF(p => ({ ...p, min_usd: e.target.value }))} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input className="input" placeholder="Case ID (opt)" value={f.case_id} onChange={e => setF(p => ({ ...p, case_id: e.target.value }))} />
            <input className="input" placeholder="Reason" value={f.reason} onChange={e => setF(p => ({ ...p, reason: e.target.value }))} />
          </div>
          <button className="btn-primary w-full justify-center flex items-center gap-2" onClick={add} disabled={busy || !f.address}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : <PlusCircle size={15} />} Watch address
          </button>
          <p className="text-[11px] text-text-muted">
            Tip: also add the address to <Link to="/monitor" className="text-neon-cyan hover:underline">Wallet Monitor</Link> — the
            Beacon-lite scan sweeps monitor notifications for VASP touches.
          </p>
        </div>

        <div className="card space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">Manual transfer check</p>
          <select className="input text-sm" value={manual.wid} onChange={e => setManual(p => ({ ...p, wid: e.target.value }))}>
            <option value="">Select watch…</option>
            {watches.map(w => <option key={w.id} value={w.id}>{w.address.slice(0, 18)}… ({w.chain})</option>)}
          </select>
          <input className="input" placeholder="Counterparty address" value={manual.counterparty} onChange={e => setManual(p => ({ ...p, counterparty: e.target.value }))} />
          <input className="input" placeholder="Amount USD (opt)" value={manual.amount} onChange={e => setManual(p => ({ ...p, amount: e.target.value }))} />
          <div className="flex gap-2">
            <button className="btn-secondary flex-1 justify-center flex items-center gap-2" onClick={evaluate} disabled={busy || !manual.wid || !manual.counterparty}>
              <Snowflake size={15} /> Evaluate
            </button>
            <button className="btn-primary flex-1 justify-center flex items-center gap-2" onClick={scan} disabled={busy}>
              {busy ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} Beacon-lite scan
            </button>
          </div>
        </div>
      </div>

      {scanMsg && <div className="card border-green-500/40 text-green-300 text-sm">{scanMsg}</div>}
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}

      <div className="card overflow-x-auto">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Active watches</p>
        <table className="w-full text-sm">
          <thead><tr className="text-text-muted text-left"><th className="p-2">Address</th><th className="p-2">Chain</th><th className="p-2">Asset</th><th className="p-2">Min $</th><th className="p-2">Events</th><th className="p-2">Status</th><th className="p-2"></th></tr></thead>
          <tbody>
            {watches.map(w => (
              <tr key={w.id} className="border-t border-border">
                <td className="p-2 font-mono text-xs break-all max-w-[240px]">{w.address}</td>
                <td className="p-2 uppercase text-xs">{w.chain}</td>
                <td className="p-2 text-xs">{w.asset}</td>
                <td className="p-2 text-xs">{w.min_usd ? `$${Number(w.min_usd).toLocaleString()}` : '—'}</td>
                <td className="p-2 text-xs">{w.event_count}</td>
                <td className="p-2"><span className="badge text-[10px]" style={{ color: w.status === 'active' ? '#34D399' : '#9a858c' }}>{w.status}</span></td>
                <td className="p-2 flex gap-2">
                  <button className="text-text-muted hover:text-text-primary" title={w.status === 'active' ? 'Pause' : 'Activate'}
                    onClick={async () => { await freezeNetSetWatchStatus(w.id, w.status === 'active' ? 'paused' : 'active'); refresh() }}>
                    {w.status === 'active' ? <PauseCircle size={15} /> : <PlayCircle size={15} />}
                  </button>
                  <button className="text-red-400/70 hover:text-red-400" onClick={async () => { await freezeNetDeleteWatch(w.id); refresh() }}><Trash2 size={15} /></button>
                </td>
              </tr>
            ))}
            {watches.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-text-muted">No watches yet.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="card overflow-x-auto">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Watch events (auto-queued packages)</p>
        <table className="w-full text-sm">
          <thead><tr className="text-text-muted text-left"><th className="p-2">Time</th><th className="p-2">Kind</th><th className="p-2">Counterparty</th><th className="p-2">VASP</th><th className="p-2">USD</th><th className="p-2">Freeze request</th></tr></thead>
          <tbody>
            {events.map(e => (
              <tr key={e.id} className="border-t border-border text-xs">
                <td className="p-2 whitespace-nowrap">{(e.at || '').slice(0, 16).replace('T', ' ')}</td>
                <td className="p-2"><span className="badge text-[10px]">{e.kind}</span></td>
                <td className="p-2 font-mono break-all max-w-[200px]">{e.counterparty || '—'}</td>
                <td className="p-2">{e.vasp_name || '—'}</td>
                <td className="p-2">{e.amount_usd ? `$${Number(e.amount_usd).toLocaleString()}` : '—'}</td>
                <td className="p-2">{e.request_id
                  ? <Link to="/recovery?tab=tracker" className="text-neon-cyan hover:underline font-mono">#{e.request_id.slice(0, 8)}</Link>
                  : '—'}</td>
              </tr>
            ))}
            {events.length === 0 && <tr><td colSpan={6} className="p-4 text-center text-text-muted">No events yet — run a Beacon-lite scan.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function DirectoryTab() {
  const [rows, setRows] = useState<any[]>([])
  const [asset, setAsset] = useState('')
  useEffect(() => { freezeNetDirectory(asset).then(d => setRows(d.directory || [])).catch(() => {}) }, [asset])
  return (
    <div className="space-y-3">
      <div className="flex gap-2 items-center">
        <input className="input w-56" placeholder="Filter by asset (USDT, USDC…)" value={asset} onChange={e => setAsset(e.target.value)} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {rows.map((d, i) => (
          <div key={i} className="card space-y-1.5">
            <p className="flex items-center gap-2 font-semibold text-text-primary">
              <Building2 size={15} className="text-neon-cyan" /> {d.name}
              <span className="badge text-[10px] uppercase">{d.type}</span>
            </p>
            <p className="text-xs text-text-secondary">Channel: {d.channel}</p>
            <p className="text-xs text-text-muted">Assets: {d.assets.join(', ')} · Chains: {d.chains.join(', ')}</p>
            <div>
              <p className="text-[11px] uppercase tracking-wider text-text-muted mt-1">Evidence format</p>
              <ul className="list-disc pl-4 text-xs text-text-secondary space-y-0.5">
                {d.evidence_format.map((x: string, j: number) => <li key={j}>{x}</li>)}
              </ul>
            </div>
            <p className="text-[11px] text-text-muted italic">{d.sla_note}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function KpisTab() {
  const [k, setK] = useState<any>(null)
  const [err, setErr] = useState('')
  useEffect(() => { freezeNetKpis().then(setK).catch(e => setErr(friendlyError(e))) }, [])
  if (err) return <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>
  if (!k) return <div className="card text-sm text-text-muted">Computing freeze telemetry…</div>
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <div className="card"><p className="text-xs text-text-muted">Value frozen/seized</p><p className="text-2xl font-bold text-green-400">${Number(k.value_frozen_usd).toLocaleString()}</p></div>
        <div className="card"><p className="text-xs text-text-muted">Frozen / total requests</p><p className="text-2xl font-bold text-text-primary">{k.frozen_or_seized} / {k.total_requests}</p></div>
        <div className="card"><p className="text-xs text-text-muted">Median time-to-freeze</p><p className="text-2xl font-bold text-text-primary">{k.median_time_to_freeze_hours != null ? `${k.median_time_to_freeze_hours}h` : '—'}</p></div>
        <div className="card"><p className="text-xs text-text-muted">Auto-queued by watch</p><p className="text-2xl font-bold text-neon-cyan">{k.auto_queued_requests}</p></div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card overflow-x-auto">
          <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">By freeze target</p>
          <table className="w-full text-sm">
            <thead><tr className="text-text-muted text-left"><th className="p-2">Target</th><th className="p-2">Requests</th><th className="p-2">USD</th></tr></thead>
            <tbody>
              {(k.by_target || []).map((t: any, i: number) => (
                <tr key={i} className="border-t border-border text-xs">
                  <td className="p-2">{t.target}</td><td className="p-2">{t.count}</td>
                  <td className="p-2">${Number(t.amount_usd).toLocaleString()}</td>
                </tr>
              ))}
              {(!k.by_target || k.by_target.length === 0) && <tr><td colSpan={3} className="p-4 text-center text-text-muted">No requests yet.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="card overflow-x-auto">
          <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Monthly frozen value</p>
          <table className="w-full text-sm">
            <thead><tr className="text-text-muted text-left"><th className="p-2">Month</th><th className="p-2">USD frozen</th></tr></thead>
            <tbody>
              {(k.monthly_frozen_usd || []).map((m: any, i: number) => (
                <tr key={i} className="border-t border-border text-xs">
                  <td className="p-2">{m.month}</td><td className="p-2">${Number(m.amount_usd).toLocaleString()}</td>
                </tr>
              ))}
              {(!k.monthly_frozen_usd || k.monthly_frozen_usd.length === 0) && <tr><td colSpan={2} className="p-4 text-center text-text-muted">No frozen value recorded yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
