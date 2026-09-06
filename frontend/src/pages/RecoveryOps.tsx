import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Snowflake, Loader2, Send, ListChecks, Building2 } from 'lucide-react'
import {
  recoveryRoute, previewFreezeRequest, createFreezeRequest, listFreezeRequests,
  setFreezeStatus, recoverySummary,
} from '../api/client'
import CinematicStage from '../components/CinematicStage'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}
const STATUSES = ['draft', 'submitted', 'acknowledged', 'frozen', 'seized', 'rejected', 'closed']
function statusColor(s: string) {
  if (s === 'frozen' || s === 'seized') return '#34D399'
  if (s === 'rejected') return '#ff4052'
  if (s === 'submitted' || s === 'acknowledged') return '#ffd60a'
  return '#9a858c'
}

export default function RecoveryOps() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<'new' | 'tracker'>('new')
  return (
    <div className="noscroll-page p-6 max-w-7xl mx-auto space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
          <Snowflake size={22} className="text-neon-cyan" /> Recovery — Freeze &amp; Seizure
        </h1>
        <p className="text-sm text-text-muted mt-1">
          The last mile: route a traced illicit wallet to the party that can actually freeze it (stablecoin issuer
          or VASP desk), generate the request package, and track it to resolution.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {([['new', 'New Request', Send], ['tracker', 'Request Tracker', ListChecks]] as const).map(([id, label, Icon]) => (
          <button key={id} onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
              tab === id ? 'bg-neon-cyan/15 text-neon-cyan' : 'text-text-muted hover:text-text-primary'}`}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>
      <div className="noscroll-grow">
      <CinematicStage variant="recovery" icon={Snowflake} title="Recovery — Freeze & Seizure" subtitle="The last mile: route a traced illicit wallet to the party that can actually freeze it (stablecoin issuer or VASP desk), generate the request package, and track it to resolution." collapsed={false}>
        {tab === 'new' && <NewRequestTab />}
        {tab === 'tracker' && <TrackerTab />}
      </CinematicStage>
      </div>
    </div>
  )
}

function NewRequestTab() {
  const [f, setF] = useState({ address: '', chain: 'eth', asset: 'USDT', amount_usd: '', case_id: '', reason: '', vasp_name: '', requester: '' })
  const [route, setRoute] = useState<any>(null)
  const [preview, setPreview] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(''); const [created, setCreated] = useState<any>(null)
  const set = (k: string, v: string) => setF(p => ({ ...p, [k]: v }))

  useEffect(() => {
    if (!f.asset) return
    recoveryRoute(f.asset, f.chain, f.vasp_name).then(setRoute).catch(() => setRoute(null))
  }, [f.asset, f.chain, f.vasp_name])

  async function doPreview() {
    setLoading(true); setErr(''); setPreview(null)
    try { setPreview(await previewFreezeRequest({ ...f, amount_usd: Number(f.amount_usd) || 0 })) }
    catch (e) { setErr(friendlyError(e)) } finally { setLoading(false) }
  }
  async function doCreate() {
    setLoading(true); setErr('')
    try { setCreated(await createFreezeRequest({ ...f, amount_usd: Number(f.amount_usd) || 0 })) }
    catch (e) { setErr(friendlyError(e)) } finally { setLoading(false) }
  }

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="grid gap-3 md:grid-cols-2">
          <input className="input" placeholder="Illicit address to freeze" value={f.address} onChange={e => set('address', e.target.value)} />
          <input className="input" placeholder="Chain (eth, trx, sol…)" value={f.chain} onChange={e => set('chain', e.target.value)} />
          <input className="input" placeholder="Asset (USDT, USDC…)" value={f.asset} onChange={e => set('asset', e.target.value)} />
          <input className="input" placeholder="Amount (USD)" value={f.amount_usd} onChange={e => set('amount_usd', e.target.value)} />
          <input className="input" placeholder="Case ID (optional)" value={f.case_id} onChange={e => set('case_id', e.target.value)} />
          <input className="input" placeholder="Requester" value={f.requester} onChange={e => set('requester', e.target.value)} />
        </div>
        <textarea className="input text-sm h-20" placeholder="Reason / basis for the freeze request" value={f.reason} onChange={e => set('reason', e.target.value)} />
        {route && (
          <div className="rounded-lg border border-border bg-bg-secondary/40 p-3 text-sm flex items-start gap-2">
            <Building2 size={16} className="text-neon-cyan mt-0.5 shrink-0" />
            <div>
              <span className="font-semibold text-text-primary">{route.target_name}</span>
              <span className="badge ml-2 text-[10px]">{route.target_type}</span>
              <p className="text-text-secondary mt-1">{route.authority}. {route.note}</p>
              <p className="text-xs text-text-muted mt-1">Channel: {route.channel}</p>
            </div>
          </div>
        )}
        <div className="flex gap-2">
          <button className="btn-secondary flex-1 justify-center flex items-center gap-2" onClick={doPreview} disabled={loading || !f.address || !f.asset}>
            {loading ? <Loader2 size={16} className="animate-spin" /> : <ListChecks size={16} />} Preview package
          </button>
          <button className="btn-primary flex-1 justify-center flex items-center gap-2" onClick={doCreate} disabled={loading || !f.address || !f.asset}>
            <Send size={16} /> Create &amp; track
          </button>
        </div>
      </div>

      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {created && (
        <div className="card border-green-500/40 text-sm">
          <span className="text-green-300 font-semibold">Request created</span> — id <span className="font-mono">{created.id}</span>, status {created.status}, target {created.target_name}. Track it under Request Tracker.
        </div>
      )}
      {preview && (
        <div className="card space-y-3">
          <span className="font-semibold text-text-primary">Freeze-request package (preview)</span>
          <pre className="whitespace-pre-wrap rounded-lg border border-border bg-bg-secondary/40 p-3 text-xs text-text-secondary">{preview.package.cover_note}</pre>
          <div>
            <p className="text-sm text-text-muted mb-1">Required attachments:</p>
            <ul className="list-disc pl-5 text-sm text-text-secondary space-y-0.5">
              {preview.package.required_attachments.map((a: string, i: number) => <li key={i}>{a}</li>)}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}

function TrackerTab() {
  const [rows, setRows] = useState<any[]>([])
  const [summary, setSummary] = useState<any>(null)
  const [err, setErr] = useState('')

  async function refresh() {
    try {
      const [list, sum] = await Promise.all([listFreezeRequests(), recoverySummary()])
      setRows(list.requests || []); setSummary(sum)
    } catch (e) { setErr(friendlyError(e)) }
  }
  useEffect(() => { refresh() }, [])

  async function advance(id: string, status: string) {
    try { await setFreezeStatus(id, { status }); refresh() } catch (e) { setErr(friendlyError(e)) }
  }

  return (
    <div className="space-y-4">
      {summary && (
        <div className="grid gap-3 md:grid-cols-3">
          <div className="card"><p className="text-xs text-text-muted">Total requests</p><p className="text-2xl font-bold text-text-primary">{summary.total_requests}</p></div>
          <div className="card"><p className="text-xs text-text-muted">Value frozen / seized</p><p className="text-2xl font-bold text-green-400">${Number(summary.value_frozen_or_seized_usd).toLocaleString()}</p></div>
          <div className="card"><p className="text-xs text-text-muted">Statuses</p><p className="text-sm text-text-secondary mt-1">{Object.entries(summary.by_status || {}).map(([k, v]: any) => `${k}: ${v.count}`).join(' · ') || '—'}</p></div>
        </div>
      )}
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-text-muted text-left"><th className="p-2">Address</th><th className="p-2">Asset</th><th className="p-2">USD</th><th className="p-2">Target</th><th className="p-2">Status</th><th className="p-2">Advance</th></tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} className="border-t border-border">
                <td className="p-2 font-mono text-xs break-all max-w-[220px]">{r.address}</td>
                <td className="p-2">{r.asset}</td>
                <td className="p-2">${Number(r.amount_usd).toLocaleString()}</td>
                <td className="p-2">{r.target_name}</td>
                <td className="p-2"><span className="badge" style={{ background: statusColor(r.status) + '22', color: statusColor(r.status) }}>{r.status}</span></td>
                <td className="p-2">
                  <select className="input text-xs py-1" value={r.status} onChange={e => advance(r.id, e.target.value)}>
                    {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={6} className="p-4 text-center text-text-muted">No freeze requests yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
