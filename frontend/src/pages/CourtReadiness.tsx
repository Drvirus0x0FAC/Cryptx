import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Scale, Loader2, FileCheck2, ShieldCheck, Stamp } from 'lucide-react'
import { daubertMethods, buildDaubertDossier, notarizeExhibit, verifyNotarizationChain } from '../api/client'
import CinematicStage from '../components/CinematicStage'

type Tab = 'dossier' | 'notarize'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

export default function CourtReadiness() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('dossier')
  return (
    <div className="noscroll-page p-6 max-w-7xl mx-auto space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
          <Scale size={22} className="text-neon-cyan" /> Court Readiness &amp; Evidentiary Depth
        </h1>
        <p className="text-sm text-text-muted mt-1">
          Turn what you compute into convictions — a Daubert methodology appendix for every heuristic applied,
          plus tamper-evident notarization of exhibits.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {([['dossier', 'Daubert Dossier', FileCheck2], ['notarize', 'Notarize & Verify', Stamp]] as const).map(([id, label, Icon]) => (
          <button key={id} onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
              tab === id ? 'bg-neon-cyan/15 text-neon-cyan' : 'text-text-muted hover:text-text-primary'}`}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>
      <div className="noscroll-grow">
      <CinematicStage variant="court" icon={Scale} title="Court Readiness & Evidentiary Depth" subtitle="Turn what you compute into convictions — a Daubert methodology appendix for every heuristic applied, plus tamper-evident notarization of exhibits." collapsed={false}>
        {tab === 'dossier' && <DossierTab />}
        {tab === 'notarize' && <NotarizeTab />}
      </CinematicStage>
      </div>
    </div>
  )
}

function DossierTab() {
  const [methods, setMethods] = useState<any[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [caseRef, setCaseRef] = useState('')
  const [analyst, setAnalyst] = useState('')
  const [subject, setSubject] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(''); const [res, setRes] = useState<any>(null)

  useEffect(() => { daubertMethods().then(d => setMethods(d.methods || [])).catch(() => {}) }, [])

  function toggle(id: string) {
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }
  async function run() {
    setLoading(true); setErr(''); setRes(null)
    try { setRes(await buildDaubertDossier({ case_ref: caseRef, methods_used: [...selected], analyst, subject })) }
    catch (e) { setErr(friendlyError(e)) } finally { setLoading(false) }
  }
  function openHtml() {
    // Fetch the print-ready HTML appendix and open it in a new tab.
    fetch('/api/daubert/dossier/html', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case_ref: caseRef, methods_used: [...selected], analyst, subject }),
    }).then(r => r.text()).then(html => {
      const w = window.open('', '_blank'); if (w) { w.document.write(html); w.document.close() }
    }).catch(() => {})
  }

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="grid gap-3 md:grid-cols-3">
          <input className="input" placeholder="Case reference" value={caseRef} onChange={e => setCaseRef(e.target.value)} />
          <input className="input" placeholder="Analyst" value={analyst} onChange={e => setAnalyst(e.target.value)} />
          <input className="input" placeholder="Subject (optional)" value={subject} onChange={e => setSubject(e.target.value)} />
        </div>
        <div>
          <p className="text-sm text-text-muted mb-2">Select the methods relied upon in this case:</p>
          <div className="grid gap-2 md:grid-cols-2">
            {methods.map(m => (
              <label key={m.id} className={`flex items-start gap-2 rounded-lg border p-2 cursor-pointer text-sm ${
                selected.has(m.id) ? 'border-neon-cyan/60 bg-neon-cyan/10' : 'border-border'}`}>
                <input type="checkbox" checked={selected.has(m.id)} onChange={() => toggle(m.id)} className="mt-1" />
                <div><span className="font-semibold text-text-primary">{m.name}</span>
                  <p className="text-xs text-text-muted">{m.technique}</p></div>
              </label>
            ))}
          </div>
        </div>
        <div className="flex gap-2">
          <button className="btn-primary flex-1 justify-center flex items-center gap-2" onClick={run} disabled={loading || !caseRef || !selected.size}>
            {loading ? <Loader2 size={16} className="animate-spin" /> : <FileCheck2 size={16} />} Build dossier
          </button>
          <button className="btn-secondary flex items-center gap-2" onClick={openHtml} disabled={!caseRef || !selected.size}>
            <Scale size={16} /> Open print-ready HTML
          </button>
        </div>
      </div>
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {res && (
        <div className="card space-y-3">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-text-primary">Admissibility appendix · {res.methods.length} methods</span>
            <span className="badge">Daubert 4-factor</span>
          </div>
          {res.methods.map((m: any) => (
            <div key={m.id} className="rounded-lg border border-border bg-bg-secondary/40 p-3">
              <div className="font-semibold text-neon-cyan">{m.name}</div>
              <p className="text-xs text-text-secondary italic mb-2">{m.technique}</p>
              <div className="grid gap-1 text-xs md:grid-cols-2">
                <div><span className="text-text-muted">Testability: </span>{m.daubert.testability}</div>
                <div><span className="text-text-muted">Peer review: </span>{m.daubert.peer_review}</div>
                <div><span className="text-text-muted">Error rate: </span>{m.daubert.known_error_rate}</div>
                <div><span className="text-text-muted">General acceptance: </span>{m.daubert.general_acceptance}</div>
              </div>
            </div>
          ))}
          <p className="text-xs font-mono text-text-muted break-all border-t border-border pt-2">SHA-256: {res.content_sha256}</p>
        </div>
      )}
    </div>
  )
}

function NotarizeTab() {
  const [label, setLabel] = useState('')
  const [payload, setPayload] = useState('{\n  "exhibit": "graph_export.pdf",\n  "hash": "…"\n}')
  const [records, setRecords] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(''); const [verify, setVerify] = useState<any>(null)

  async function add() {
    setLoading(true); setErr('')
    try {
      let p: any; try { p = JSON.parse(payload) } catch { p = payload }
      const prev = records.length ? records[records.length - 1].chain_hash : ''
      const rec = await notarizeExhibit({ payload: p, prev_hash: prev, label })
      setRecords(r => [...r, rec]); setVerify(null); setLabel('')
    } catch (e) { setErr(friendlyError(e)) } finally { setLoading(false) }
  }
  async function check() {
    try { setVerify(await verifyNotarizationChain(records)) } catch (e) { setErr(friendlyError(e)) }
  }

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <p className="text-sm text-text-muted">Each exhibit is SHA-256 hashed, UTC-timestamped, and chained to the previous record. Any edit or reorder breaks the chain.</p>
        <input className="input" placeholder="Exhibit label (e.g. Nexus graph export)" value={label} onChange={e => setLabel(e.target.value)} />
        <textarea className="input font-mono text-xs h-28" value={payload} onChange={e => setPayload(e.target.value)} />
        <div className="flex gap-2">
          <button className="btn-primary flex-1 justify-center flex items-center gap-2" onClick={add} disabled={loading}>
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Stamp size={16} />} Notarize exhibit
          </button>
          <button className="btn-secondary flex items-center gap-2" onClick={check} disabled={!records.length}>
            <ShieldCheck size={16} /> Verify chain
          </button>
        </div>
      </div>
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {verify && (
        <div className={`card text-sm ${verify.valid ? 'border-green-500/40 text-green-300' : 'border-red-500/40 text-red-300'}`}>
          {verify.verdict}
        </div>
      )}
      {records.map((r, i) => (
        <div key={i} className="card space-y-1 text-xs">
          <div className="flex items-center justify-between"><span className="font-semibold text-text-primary">#{i + 1} {r.label || 'exhibit'}</span><span className="text-text-muted">{r.timestamp_utc}</span></div>
          <div className="font-mono text-text-muted break-all">content: {r.content_sha256}</div>
          <div className="font-mono text-neon-cyan break-all">chain: {r.chain_hash}</div>
        </div>
      ))}
    </div>
  )
}
