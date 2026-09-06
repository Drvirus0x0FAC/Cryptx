import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  FileCode2, Loader2, ShieldAlert, Fingerprint, Radar, Bug, AlertTriangle, CheckCircle2,
} from 'lucide-react'
import {
  scanContract, fingerprintContract, compareContracts, reconstructIncident, approvalExposure,
} from '../api/client'
import CinematicStage from '../components/CinematicStage'

type Tab = 'scan' | 'approvals' | 'similarity' | 'incident'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}
function sevColor(s?: string) {
  if (s === 'critical') return '#ff4052'
  if (s === 'high') return '#ff7a18'
  if (s === 'medium') return '#ffd60a'
  if (s === 'low') return '#34D399'
  return '#9a858c'
}
function parseJSON<T>(s: string, fallback: T): T {
  try { return s.trim() ? JSON.parse(s) : fallback } catch { return fallback }
}

const TABS: { id: Tab; label: string; icon: typeof FileCode2 }[] = [
  { id: 'scan', label: 'Contract Risk Scan', icon: ShieldAlert },
  { id: 'approvals', label: 'Approval Exposure', icon: AlertTriangle },
  { id: 'similarity', label: 'Bytecode Similarity', icon: Fingerprint },
  { id: 'incident', label: 'Incident Post-Mortem', icon: Bug },
]

export default function ContractForensics() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('scan')

  return (
    <div className="noscroll-page p-6 max-w-7xl mx-auto space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
          <FileCode2 size={22} className="text-neon-cyan" /> Smart-Contract Forensics
        </h1>
        <p className="text-sm text-text-muted mt-1">
          Local, evidence-first static analysis — malicious-pattern scanning, wallet approval exposure,
          attacker-contract clustering, and exploit reconstruction. Leads, not claims.
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
      <CinematicStage variant="contract" icon={FileCode2} title="Smart-Contract Forensics" subtitle="Local, evidence-first static analysis — malicious-pattern scanning, wallet approval exposure, attacker-contract clustering, and exploit reconstruction. Leads, not claims." collapsed={false}>
        {tab === 'scan' && <ScanTab />}
        {tab === 'approvals' && <ApprovalsTab />}
        {tab === 'similarity' && <SimilarityTab />}
        {tab === 'incident' && <IncidentTab />}
      </CinematicStage>
      </div>
    </div>
  )
}

function ScanTab() {
  const [address, setAddress] = useState('')
  const [chain, setChain] = useState('eth')
  const [bytecode, setBytecode] = useState('')
  const [source, setSource] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [res, setRes] = useState<any>(null)

  async function run() {
    setLoading(true); setErr(''); setRes(null)
    try { setRes(await scanContract({ address, chain, bytecode, source })) }
    catch (e) { setErr(friendlyError(e)) }
    finally { setLoading(false) }
  }

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="grid gap-3 md:grid-cols-2">
          <input className="input" placeholder="Contract address (optional)" value={address} onChange={e => setAddress(e.target.value)} />
          <input className="input" placeholder="Chain (eth, bsc, …)" value={chain} onChange={e => setChain(e.target.value)} />
        </div>
        <textarea className="input font-mono text-xs h-24" placeholder="Deployed bytecode 0x… (recovers function selectors + opcode heuristics)"
          value={bytecode} onChange={e => setBytecode(e.target.value)} />
        <textarea className="input font-mono text-xs h-24" placeholder="Verified Solidity source (optional — keyword pattern scan)"
          value={source} onChange={e => setSource(e.target.value)} />
        <button className="btn-primary w-full justify-center flex items-center gap-2" onClick={run} disabled={loading || (!bytecode && !source)}>
          {loading ? <Loader2 size={16} className="animate-spin" /> : <ShieldAlert size={16} />} Scan contract
        </button>
      </div>

      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {res && (
        <div className="card space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-lg font-bold" style={{ color: res.risk_score >= 55 ? '#ff4052' : res.risk_score >= 30 ? '#ffd60a' : '#34D399' }}>
              {res.verdict}
            </span>
            <span className="badge" style={{ background: sevColor(res.risk_score >= 55 ? 'high' : 'medium') + '22', color: sevColor(res.risk_score >= 55 ? 'high' : 'medium') }}>
              Risk {res.risk_score}/100
            </span>
          </div>
          {res.honeypot_suspect && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-2 text-sm text-red-300 flex items-center gap-2">
              <AlertTriangle size={14} /> Honeypot suspect — multiple sell-restriction / fee / blacklist controls present.
            </div>
          )}
          <div className="space-y-2">
            {(res.findings || []).map((f: any, i: number) => (
              <div key={i} className="rounded-lg border border-border bg-bg-secondary/40 p-3">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-text-primary">{f.title}</span>
                  <span className="badge text-[10px]" style={{ background: sevColor(f.severity) + '22', color: sevColor(f.severity) }}>{f.severity} · {f.method}</span>
                </div>
                <p className="text-sm text-text-secondary mt-1">{f.detail}</p>
                <p className="text-xs font-mono text-text-muted mt-1">{f.evidence}</p>
              </div>
            ))}
            {(res.findings || []).length === 0 && <p className="text-sm text-text-muted">No flagged patterns in supplied artifacts.</p>}
          </div>
          <p className="text-xs text-text-muted border-t border-border pt-2">{res.disclaimer}</p>
        </div>
      )}
    </div>
  )
}

function ApprovalsTab() {
  const [subject, setSubject] = useState('')
  const [approvals, setApprovals] = useState('[\n  {"token":"USDT","token_symbol":"USDT","spender":"0x…","amount":"infinite"}\n]')
  const [bad, setBad] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [res, setRes] = useState<any>(null)

  async function run() {
    setLoading(true); setErr(''); setRes(null)
    try {
      setRes(await approvalExposure({
        approvals: parseJSON(approvals, []),
        malicious_spenders: bad.split(/[\s,]+/).filter(Boolean),
      }))
    } catch (e) { setErr(friendlyError(e)) } finally { setLoading(false) }
  }

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <input className="input" placeholder="Wallet address (optional label)" value={subject} onChange={e => setSubject(e.target.value)} />
        <textarea className="input font-mono text-xs h-40" value={approvals} onChange={e => setApprovals(e.target.value)}
          placeholder='[{"token":"USDT","spender":"0x…","amount":"infinite","is_nft":false}]' />
        <input className="input font-mono text-xs" placeholder="Known-malicious spender addresses (comma/space separated)" value={bad} onChange={e => setBad(e.target.value)} />
        <button className="btn-primary w-full justify-center flex items-center gap-2" onClick={run} disabled={loading}>
          {loading ? <Loader2 size={16} className="animate-spin" /> : <AlertTriangle size={16} />} Compute exposure
        </button>
      </div>
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {res && (
        <div className="card space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-lg font-bold" style={{ color: res.exposure_score >= 40 ? '#ff4052' : '#ffd60a' }}>{res.verdict}</span>
            <span className="badge">Exposure {res.exposure_score}/100</span>
            <span className="badge">{res.infinite_approvals} infinite</span>
            <span className="badge">{res.flagged_malicious} flagged</span>
          </div>
          <div className="space-y-2">
            {(res.approvals || []).map((a: any, i: number) => (
              <div key={i} className="rounded-lg border border-border bg-bg-secondary/40 p-3 flex items-start justify-between gap-3">
                <div>
                  <span className="font-semibold text-text-primary">{a.token_symbol || a.token || 'TOKEN'}</span>
                  <span className="text-xs font-mono text-text-muted ml-2">→ {a.spender}</span>
                  <p className="text-sm text-text-secondary mt-1">{a.recommendation}</p>
                </div>
                <span className="badge shrink-0" style={{ background: sevColor(a.severity) + '22', color: sevColor(a.severity) }}>
                  {a.infinite ? 'infinite' : 'bounded'}{a.flagged_malicious ? ' · flagged' : ''}
                </span>
              </div>
            ))}
          </div>
          <p className="text-xs text-text-muted border-t border-border pt-2">{res.disclaimer}</p>
        </div>
      )}
    </div>
  )
}

function SimilarityTab() {
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [res, setRes] = useState<any>(null)
  const [fp, setFp] = useState<any>(null)

  async function run() {
    setLoading(true); setErr(''); setRes(null); setFp(null)
    try {
      const [cmp, fingerprint] = await Promise.all([
        compareContracts({ bytecode: a, other_bytecode: b }),
        fingerprintContract(a),
      ])
      setRes(cmp.pairwise); setFp(fingerprint)
    } catch (e) { setErr(friendlyError(e)) } finally { setLoading(false) }
  }

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <p className="text-sm text-text-muted">Compare two deployed contracts (opcode distribution + function-selector set) to link an attacker's deployment family.</p>
        <textarea className="input font-mono text-xs h-20" placeholder="Contract A bytecode 0x…" value={a} onChange={e => setA(e.target.value)} />
        <textarea className="input font-mono text-xs h-20" placeholder="Contract B bytecode 0x…" value={b} onChange={e => setB(e.target.value)} />
        <button className="btn-primary w-full justify-center flex items-center gap-2" onClick={run} disabled={loading || !a || !b}>
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Fingerprint size={16} />} Compare
        </button>
      </div>
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {res && (
        <div className="card space-y-3">
          <div className="text-center">
            <div className="text-4xl font-bold" style={{ color: res.similarity >= 0.75 ? '#ff4052' : res.similarity >= 0.5 ? '#ffd60a' : '#34D399' }}>
              {(res.similarity * 100).toFixed(1)}%
            </div>
            <div className="text-sm text-text-muted">{res.verdict}</div>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-lg border border-border p-2"><span className="text-text-muted">Opcode cosine</span><div className="font-mono">{res.opcode_cosine}</div></div>
            <div className="rounded-lg border border-border p-2"><span className="text-text-muted">Selector Jaccard</span><div className="font-mono">{res.selector_jaccard}</div></div>
          </div>
          {!!(res.shared_selectors || []).length && (
            <div><span className="text-text-muted text-sm">Shared selectors:</span>
              <div className="flex flex-wrap gap-1 mt-1">{res.shared_selectors.map((s: string) => <span key={s} className="badge font-mono text-[10px]">0x{s}</span>)}</div>
            </div>
          )}
          {fp && <p className="text-xs text-text-muted">A: {fp.size_bytes} bytes · {fp.selector_count} public selectors.</p>}
        </div>
      )}
    </div>
  )
}

function IncidentTab() {
  const [contract, setContract] = useState('')
  const [attacker, setAttacker] = useState('')
  const [txs, setTxs] = useState('[\n  {"hash":"0x…","from":"0x…","to":"0x…","timestamp":1710000000,"method":"flashLoan","value_usd":1200000}\n]')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [res, setRes] = useState<any>(null)

  async function run() {
    setLoading(true); setErr(''); setRes(null)
    try { setRes(await reconstructIncident({ txs: parseJSON(txs, []), contract, attacker })) }
    catch (e) { setErr(friendlyError(e)) } finally { setLoading(false) }
  }

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="grid gap-3 md:grid-cols-2">
          <input className="input" placeholder="Victim contract address" value={contract} onChange={e => setContract(e.target.value)} />
          <input className="input" placeholder="Attacker EOA (optional)" value={attacker} onChange={e => setAttacker(e.target.value)} />
        </div>
        <textarea className="input font-mono text-xs h-40" value={txs} onChange={e => setTxs(e.target.value)} />
        <button className="btn-primary w-full justify-center flex items-center gap-2" onClick={run} disabled={loading}>
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Radar size={16} />} Reconstruct incident
        </button>
      </div>
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}
      {res && (
        <div className="card space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-lg font-bold text-neon-cyan">{res.incident_type}</span>
            {res.estimated_drained_usd > 0 && <span className="badge">≈ ${Number(res.estimated_drained_usd).toLocaleString()} moved</span>}
            {(res.signatures || []).map((s: string) => <span key={s} className="badge text-[10px]">{s}</span>)}
          </div>
          <ol className="space-y-2 border-l border-border pl-4">
            {(res.timeline || []).map((ev: any, i: number) => (
              <li key={i} className="text-sm">
                <span className="badge text-[10px] mr-2">{ev.phase}</span>
                <span className="text-text-secondary">{ev.detail}</span>
                {ev.hash && <span className="text-xs font-mono text-text-muted ml-2">{String(ev.hash).slice(0, 14)}…</span>}
              </li>
            ))}
          </ol>
          {res.laundering_handoff && (
            <div className="rounded-lg border border-neon-cyan/40 bg-neon-cyan/10 p-2 text-sm flex items-center gap-2">
              <CheckCircle2 size={14} className="text-neon-cyan" /> Laundering hand-off: <span className="font-mono">{res.laundering_handoff}</span>
            </div>
          )}
          <p className="text-xs text-text-muted">{res.next_step}</p>
        </div>
      )}
    </div>
  )
}
