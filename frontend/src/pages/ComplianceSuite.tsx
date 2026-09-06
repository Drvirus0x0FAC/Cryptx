import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Landmark, Loader2, PlusCircle, ShieldCheck, ListChecks, FileCheck2, Trash2,
  PlayCircle, ScrollText, AlertTriangle, CheckCircle2, CircleDot,
} from 'lucide-react'
import {
  complyCreateProgram, complyListPrograms, complyGetProgram, complyDeleteProgram,
  complyAddAddresses, complyListAddresses, complyRemoveAddress, complyRunScreening,
  complyGetScreening, complyListScreenings, complyEvaluateTransfers, complyReport, complyAuditLog,
} from '../api/client'
import CinematicStage from '../components/CinematicStage'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

const LEVEL_COLOR: Record<string, string> = { blocked: '#ff4052', review: '#ffd60a', clear: '#34D399' }
const OB_STATUS: Record<string, { color: string; Icon: typeof CheckCircle2 }> = {
  met: { color: '#34D399', Icon: CheckCircle2 },
  action_required: { color: '#ff4052', Icon: AlertTriangle },
  attention: { color: '#ffd60a', Icon: CircleDot },
}

/**
 * CrypTX Comply — GENIUS-Act-shaped stablecoin compliance suite (3.1).
 * Programs → address book → KYT screening runs → Travel-Rule evaluation →
 * examiner report + audit trail.
 */
export default function ComplianceSuite() {
  const { t } = useTranslation()
  const [programs, setPrograms] = useState<any[]>([])
  const [selected, setSelected] = useState<string>('')
  const [err, setErr] = useState('')

  async function refresh(keep = true) {
    try {
      const d = await complyListPrograms()
      setPrograms(d.programs || [])
      if (!keep || !selected) setSelected((d.programs?.[0]?.id) || '')
    } catch (e) { setErr(friendlyError(e)) }
  }
  useEffect(() => { refresh(false) }, [])

  return (
    <div className="noscroll-page p-6 max-w-7xl mx-auto space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
          <Landmark size={22} className="text-neon-cyan" /> {t('tools:comply.title')}
        </h1>
        <p className="text-sm text-text-muted mt-1">
          GENIUS-Act-shaped monitoring for issuers, fintechs, and banks: monitored address book,
          deterministic KYT screening, Travel-Rule evaluation, and an examiner-ready report with audit trail.
        </p>
      </div>
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}

      <div className="noscroll-grow">
      <CinematicStage variant="comply" icon={Landmark} title={t('tools:comply.title')} subtitle="GENIUS-Act-shaped monitoring for issuers, fintechs, and banks: monitored address book, deterministic KYT screening, Travel-Rule evaluation, and an examiner-ready report with audit trail." collapsed={false}>
      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <ProgramRail programs={programs} selected={selected} onSelect={setSelected} onChanged={() => refresh()} />
        {selected
          ? <ProgramDetail pid={selected} onDeleted={() => { setSelected(''); refresh(false) }} />
          : <div className="card text-sm text-text-muted">Create a compliance program to begin.</div>}
      </div>
      </CinematicStage>
      </div>
    </div>
  )
}

function ProgramRail({ programs, selected, onSelect, onChanged }:
  { programs: any[]; selected: string; onSelect: (id: string) => void; onChanged: () => void }) {
  const [f, setF] = useState({ name: '', org: '', asset: 'USDT', travel_rule_usd: '3000' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function create() {
    if (!f.name) return
    setBusy(true); setErr('')
    try {
      await complyCreateProgram({ ...f, travel_rule_usd: Number(f.travel_rule_usd) || 3000, chains: ['eth', 'trx'] })
      setF({ name: '', org: '', asset: 'USDT', travel_rule_usd: '3000' })
      onChanged()
    } catch (e) { setErr(friendlyError(e)) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-3">
      <div className="card space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">New program</p>
        <input className="input" placeholder="Program name" value={f.name} onChange={e => setF(p => ({ ...p, name: e.target.value }))} />
        <input className="input" placeholder="Organization" value={f.org} onChange={e => setF(p => ({ ...p, org: e.target.value }))} />
        <div className="grid grid-cols-2 gap-2">
          <input className="input" placeholder="Asset" value={f.asset} onChange={e => setF(p => ({ ...p, asset: e.target.value }))} />
          <input className="input" placeholder="TR $ threshold" value={f.travel_rule_usd} onChange={e => setF(p => ({ ...p, travel_rule_usd: e.target.value }))} />
        </div>
        <button className="btn-primary w-full justify-center flex items-center gap-2" onClick={create} disabled={busy || !f.name}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : <PlusCircle size={15} />} Create program
        </button>
        {err && <p className="text-xs text-red-400">{err}</p>}
      </div>
      <div className="card p-2 space-y-1">
        {programs.map(p => (
          <button key={p.id} onClick={() => onSelect(p.id)}
            className={`w-full text-left rounded-lg px-3 py-2 text-sm transition ${
              selected === p.id ? 'bg-neon-cyan/15 text-neon-cyan' : 'text-text-secondary hover:text-text-primary'}`}>
            <span className="font-medium">{p.name}</span>
            <span className="block text-[11px] text-text-muted">
              {p.asset} · {p.address_count} addr{p.last_run_at ? ` · last run ${p.last_run_at.slice(0, 10)}` : ''}
            </span>
          </button>
        ))}
        {programs.length === 0 && <p className="p-3 text-xs text-text-muted">No programs yet.</p>}
      </div>
    </div>
  )
}

function ProgramDetail({ pid, onDeleted }: { pid: string; onDeleted: () => void }) {
  const [tab, setTab] = useState<'book' | 'screen' | 'travel' | 'report' | 'audit'>('book')
  const [prog, setProg] = useState<any>(null)
  useEffect(() => { complyGetProgram(pid).then(setProg).catch(() => setProg(null)); setTab('book') }, [pid])
  if (!prog) return <div className="card text-sm text-text-muted">Loading program…</div>

  const stats = prog.last_stats
  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center gap-4">
        <div className="flex-1 min-w-[180px]">
          <p className="font-semibold text-text-primary">{prog.name}</p>
          <p className="text-xs text-text-muted">{prog.org || 'no org'} · {prog.asset} · Travel Rule ${Number(prog.travel_rule_usd).toLocaleString()}</p>
        </div>
        {stats && (
          <div className="flex gap-4 text-center">
            {(['blocked', 'review', 'clear'] as const).map(k => (
              <div key={k}>
                <p className="text-lg font-bold" style={{ color: LEVEL_COLOR[k] }}>{stats[k] ?? 0}</p>
                <p className="text-[10px] uppercase text-text-muted">{k}</p>
              </div>
            ))}
          </div>
        )}
        <button className="btn-secondary text-red-400 flex items-center gap-1.5 text-xs"
          onClick={async () => { await complyDeleteProgram(pid); onDeleted() }}>
          <Trash2 size={13} /> Delete
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {([['book', 'Address Book', ListChecks], ['screen', 'Screenings', ShieldCheck],
           ['travel', 'Travel Rule', FileCheck2], ['report', 'Examiner Report', ScrollText],
           ['audit', 'Audit Log', PlayCircle]] as const).map(([id, label, Icon]) => (
          <button key={id} onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
              tab === id ? 'bg-neon-cyan/15 text-neon-cyan' : 'text-text-muted hover:text-text-primary'}`}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {tab === 'book' && <AddressBookTab pid={pid} />}
      {tab === 'screen' && <ScreeningsTab pid={pid} />}
      {tab === 'travel' && <TravelRuleTab pid={pid} threshold={prog.travel_rule_usd} />}
      {tab === 'report' && <ReportTab pid={pid} />}
      {tab === 'audit' && <AuditTab pid={pid} />}
    </div>
  )
}

function AddressBookTab({ pid }: { pid: string }) {
  const [rows, setRows] = useState<any[]>([])
  const [bulk, setBulk] = useState('')
  const [role, setRole] = useState('monitored')
  const [busy, setBusy] = useState(false)
  const refresh = () => complyListAddresses(pid).then(d => setRows(d.addresses || [])).catch(() => {})
  useEffect(() => { refresh() }, [pid])

  async function add() {
    const entries = bulk.split(/[\n,;]+/).map(s => s.trim()).filter(Boolean).map(line => {
      const [address, chain, label] = line.split(/\s+/)
      return { address, chain: chain || 'eth', role, label: label || '' }
    })
    if (!entries.length) return
    setBusy(true)
    try { await complyAddAddresses(pid, entries); setBulk(''); refresh() } finally { setBusy(false) }
  }

  return (
    <div className="space-y-3">
      <div className="card space-y-2">
        <p className="text-xs text-text-muted">One per line: <span className="font-mono">address [chain] [label]</span></p>
        <textarea className="input h-24 font-mono text-xs" placeholder={'0xabc… eth treasury-hot\nTX… trx customer-deposits'}
          value={bulk} onChange={e => setBulk(e.target.value)} />
        <div className="flex gap-2">
          <select className="input w-44 text-sm" value={role} onChange={e => setRole(e.target.value)}>
            {['treasury', 'operations', 'customer', 'counterparty', 'monitored'].map(r => <option key={r}>{r}</option>)}
          </select>
          <button className="btn-primary flex items-center gap-2" onClick={add} disabled={busy || !bulk.trim()}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : <PlusCircle size={15} />} Add to book
          </button>
        </div>
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-text-muted text-left"><th className="p-2">Address</th><th className="p-2">Chain</th><th className="p-2">Role</th><th className="p-2">Label</th><th className="p-2"></th></tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} className="border-t border-border">
                <td className="p-2 font-mono text-xs break-all max-w-[280px]">{r.address}</td>
                <td className="p-2 uppercase text-xs">{r.chain}</td>
                <td className="p-2 text-xs">{r.role}</td>
                <td className="p-2 text-xs">{r.label || '—'}</td>
                <td className="p-2"><button className="text-red-400/70 hover:text-red-400" onClick={async () => { await complyRemoveAddress(pid, r.id); refresh() }}><Trash2 size={14} /></button></td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="p-4 text-center text-text-muted">Address book is empty.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ScreeningsTab({ pid }: { pid: string }) {
  const [history, setHistory] = useState<any[]>([])
  const [current, setCurrent] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const refresh = () => complyListScreenings(pid).then(d => setHistory(d.screenings || [])).catch(() => {})
  useEffect(() => { refresh(); setCurrent(null) }, [pid])

  async function run() {
    setBusy(true); setErr('')
    try { setCurrent(await complyRunScreening(pid)); refresh() }
    catch (e) { setErr(friendlyError(e)) } finally { setBusy(false) }
  }
  async function open(sid: string) {
    try { setCurrent(await complyGetScreening(sid)) } catch (e) { setErr(friendlyError(e)) }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <button className="btn-primary flex items-center gap-2" onClick={run} disabled={busy}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : <PlayCircle size={15} />} Run KYT screening
        </button>
        <div className="flex gap-2 flex-wrap">
          {history.map(h => (
            <button key={h.id} onClick={() => open(h.id)}
              className={`rounded-lg border border-border px-2 py-1 text-[11px] transition ${
                current?.id === h.id ? 'bg-neon-cyan/15 text-neon-cyan' : 'text-text-muted hover:text-text-primary'}`}>
              {h.run_at?.slice(0, 16).replace('T', ' ')} · {h.stats?.blocked ?? 0} blocked
            </button>
          ))}
        </div>
      </div>
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {current && (
        <div className="card space-y-2">
          <p className="text-sm text-text-muted">
            {current.stats.total} screened — <span style={{ color: LEVEL_COLOR.blocked }}>{current.stats.blocked} blocked</span>,{' '}
            <span style={{ color: LEVEL_COLOR.review }}>{current.stats.review} review</span>,{' '}
            <span style={{ color: LEVEL_COLOR.clear }}>{current.stats.clear} clear</span>
          </p>
          <div className="space-y-2">
            {current.results.map((r: any, i: number) => (
              <div key={i} className="rounded-lg border border-border bg-bg-secondary/40 p-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs break-all">{r.address}</span>
                  <span className="badge text-[10px] uppercase">{r.chain}</span>
                  <span className="badge text-[10px]" style={{ background: LEVEL_COLOR[r.level] + '22', color: LEVEL_COLOR[r.level] }}>{r.level}</span>
                  {r.role && <span className="badge text-[10px]">{r.role}</span>}
                </div>
                {r.findings.length > 0 && (
                  <ul className="mt-2 space-y-1 text-xs text-text-secondary">
                    {r.findings.map((f: any, j: number) => (
                      <li key={j}><span className="font-semibold uppercase text-[10px] mr-1" style={{ color: f.severity === 'critical' ? '#ff4052' : f.severity === 'high' ? '#ffd60a' : '#9a858c' }}>{f.severity}</span>
                        {f.detail} <span className="text-text-muted">· {f.source}</span></li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function TravelRuleTab({ pid, threshold }: { pid: string; threshold: number }) {
  const [bulk, setBulk] = useState('')
  const [result, setResult] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function evaluate() {
    const transfers = bulk.split('\n').map(s => s.trim()).filter(Boolean).map(line => {
      const [from, to, amount, chain] = line.split(/[\s,]+/)
      return { from, to, amount_usd: Number(amount) || 0, chain: chain || 'eth' }
    })
    if (!transfers.length) return
    setBusy(true); setErr('')
    try { setResult(await complyEvaluateTransfers(pid, transfers)) }
    catch (e) { setErr(friendlyError(e)) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-3">
      <div className="card space-y-2">
        <p className="text-xs text-text-muted">One transfer per line: <span className="font-mono">from to amount_usd [chain]</span> — threshold ${Number(threshold).toLocaleString()}</p>
        <textarea className="input h-24 font-mono text-xs" placeholder="0xsender 0xreceiver 5000 eth" value={bulk} onChange={e => setBulk(e.target.value)} />
        <button className="btn-primary flex items-center gap-2" onClick={evaluate} disabled={busy || !bulk.trim()}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : <FileCheck2 size={15} />} Evaluate batch
        </button>
      </div>
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {result && (
        <div className="card space-y-2">
          <p className="text-sm text-text-muted">{result.evaluated} evaluated · <span className="text-yellow-300">{result.flagged} flagged</span></p>
          {result.transfers.map((t: any, i: number) => (
            <div key={i} className="rounded-lg border border-border bg-bg-secondary/40 p-3 text-xs">
              <p className="font-mono break-all">{t.from} → {t.to} · ${Number(t.amount_usd).toLocaleString()}</p>
              <ul className="mt-1 space-y-0.5 text-text-secondary">
                {t.flags.map((fl: any, j: number) => <li key={j}><span className="badge text-[10px] mr-1">{fl.rule}</span>{fl.detail}</li>)}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ReportTab({ pid }: { pid: string }) {
  const [rep, setRep] = useState<any>(null)
  const [err, setErr] = useState('')
  useEffect(() => { complyReport(pid).then(setRep).catch(e => setErr(friendlyError(e))) }, [pid])
  if (err) return <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>
  if (!rep) return <div className="card text-sm text-text-muted">Building examiner report…</div>
  return (
    <div className="space-y-3">
      <div className="card space-y-3">
        <p className="text-sm font-semibold text-text-primary">Obligations — {rep.program.name} <span className="text-text-muted font-normal">({rep.generated_at.slice(0, 16).replace('T', ' ')} UTC)</span></p>
        {rep.obligations.map((ob: any) => {
          const meta = OB_STATUS[ob.status] || OB_STATUS.attention
          return (
            <div key={ob.id} className="rounded-lg border border-border bg-bg-secondary/40 p-3">
              <p className="flex items-center gap-2 text-sm font-medium text-text-primary">
                <meta.Icon size={15} style={{ color: meta.color }} /> {ob.name}
                <span className="badge text-[10px]" style={{ background: meta.color + '22', color: meta.color }}>{ob.status.replace('_', ' ')}</span>
              </p>
              <p className="text-xs text-text-muted mt-1">{ob.requirement}</p>
              <p className="text-xs text-text-secondary mt-1">Evidence: {ob.evidence}</p>
            </div>
          )
        })}
        <p className="text-[11px] text-text-muted italic">{rep.disclaimer}</p>
      </div>
    </div>
  )
}

function AuditTab({ pid }: { pid: string }) {
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => { complyAuditLog(pid).then(d => setRows(d.entries || [])).catch(() => {}) }, [pid])
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr className="text-text-muted text-left"><th className="p-2">Time (UTC)</th><th className="p-2">Action</th><th className="p-2">Detail</th><th className="p-2">Actor</th></tr></thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.id} className="border-t border-border text-xs">
              <td className="p-2 whitespace-nowrap">{(r.at || '').slice(0, 19).replace('T', ' ')}</td>
              <td className="p-2 font-medium">{r.action}</td>
              <td className="p-2 text-text-secondary">{r.detail || '—'}</td>
              <td className="p-2">{r.actor || '—'}</td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={4} className="p-4 text-center text-text-muted">No audit entries.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}
