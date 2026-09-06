import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Building2, Download, FileText, Loader2, Scale, Send } from 'lucide-react'
import { generateSar, generateCtr, generateTravelRule, lookupVasp } from '../api/client'
import type { KyvResult, RegulatoryReport } from '../types'
import CinematicStage from '../components/CinematicStage'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

const SAR_CATEGORIES = [
  'Money laundering', 'Sanctions evasion', 'Fraud / scam', 'Ransomware',
  'Darknet marketplace', 'Mixer / tumbler use', 'Structuring', 'Stolen funds',
]

function ReportOutput({ report }: { report: RegulatoryReport }) {
  function download() {
    const blob = new Blob([report.markdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `${report.report_type.toLowerCase()}-${Date.now()}.md`; a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <div className="card">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-bold uppercase tracking-widest text-text-primary">{report.report_type} · {report.report_standard}</h3>
        <button className="btn-ghost text-xs" onClick={download}><Download size={13} /> Export .md</button>
      </div>
      <pre className="max-h-[480px] overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-bg-secondary p-4 text-xs leading-relaxed text-text-secondary">{report.markdown}</pre>
    </div>
  )
}

export default function RegulatoryReports() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<'sar' | 'ctr' | 'travel' | 'kyv'>('sar')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<RegulatoryReport | null>(null)

  // SAR
  const [sarSubject, setSarSubject] = useState('')
  const [sarChain, setSarChain] = useState('eth')
  const [sarNarrative, setSarNarrative] = useState('')
  const [sarCats, setSarCats] = useState<string[]>([])
  const [sarCps, setSarCps] = useState('')
  const [sarAmount, setSarAmount] = useState('')

  // CTR
  const [ctrSubject, setCtrSubject] = useState('')
  const [ctrTxs, setCtrTxs] = useState('[\n  {"hash": "0x..", "amount_usd": 7000, "asset": "ETH", "direction": "in"}\n]')

  // Travel rule
  const [trChain, setTrChain] = useState('eth')
  const [trAsset, setTrAsset] = useState('ETH')
  const [trAmount, setTrAmount] = useState('')
  const [trOrig, setTrOrig] = useState('')
  const [trBenef, setTrBenef] = useState('')

  // KYV
  const [kyvAddr, setKyvAddr] = useState('')
  const [kyv, setKyv] = useState<KyvResult | null>(null)

  async function run(fn: () => Promise<RegulatoryReport>) {
    setLoading(true); setError(null); setReport(null)
    try { setReport(await fn()) } catch (e) { setError(friendlyError(e)) } finally { setLoading(false) }
  }

  function toggleCat(c: string) {
    setSarCats(prev => prev.includes(c) ? prev.filter(x => x !== c) : [...prev, c])
  }

  async function runKyv() {
    if (!kyvAddr.trim()) return
    setLoading(true); setError(null); setKyv(null)
    try { setKyv(await lookupVasp(kyvAddr.trim())) } catch (e) { setError(friendlyError(e)) } finally { setLoading(false) }
  }

  const TABS = [
    { id: 'sar', label: 'SAR', icon: FileText },
    { id: 'ctr', label: 'CTR', icon: Scale },
    { id: 'travel', label: 'Travel Rule', icon: Send },
    { id: 'kyv', label: 'Know-Your-VASP', icon: Building2 },
  ] as const

  return (
    <div className="noscroll-page mx-auto max-w-5xl space-y-5 p-6">
      <div className="card overflow-hidden p-0">
        <div className="flex items-start gap-4 border-b border-border p-5" style={{ background: 'linear-gradient(135deg, rgba(255,64,82,0.1), rgba(255,59,107,0.06))' }}>
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-neon-cyan/35 bg-neon-cyan/10">
            <Scale size={22} className="text-neon-cyan" />
          </div>
          <div>
            <h1 className="text-display text-lg font-bold uppercase tracking-widest text-text-primary">{t('tools:regulatory.title')}</h1>
            <p className="mt-1 max-w-3xl text-sm text-text-secondary">Draft SAR, CTR, and Travel Rule filings auto-enriched with sanctions screening and VASP attribution. Drafts require compliance review before filing.</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-1 border-b border-border px-4 pt-3">
          {TABS.map(t => (
            <button key={t.id} onClick={() => { setTab(t.id); setReport(null); setError(null) }}
              className={`flex items-center gap-1.5 rounded-t-lg px-4 py-2 text-sm font-semibold ${tab === t.id ? 'bg-bg-secondary text-text-primary' : 'text-text-muted hover:text-text-secondary'}`}>
              <t.icon size={14} /> {t.label}
            </button>
          ))}
        </div>

        <CinematicStage variant="regulatory" icon={Scale} title={t('tools:regulatory.title')} subtitle="Draft SAR, CTR, and Travel Rule filings auto-enriched with sanctions screening and VASP attribution. Drafts require compliance review before filing." collapsed={false}>
        <div className="space-y-3">
          {tab === 'sar' && (
            <>
              <div className="grid gap-3 md:grid-cols-[1fr_120px]">
                <input className="input" placeholder="Subject address" value={sarSubject} onChange={e => setSarSubject(e.target.value)} />
                <input className="input" placeholder="chain" value={sarChain} onChange={e => setSarChain(e.target.value)} />
              </div>
              <div className="flex flex-wrap gap-2">
                {SAR_CATEGORIES.map(c => (
                  <button key={c} onClick={() => toggleCat(c)}
                    className={`rounded-full border px-3 py-1 text-xs ${sarCats.includes(c) ? 'border-neon-red/50 bg-neon-red/10 text-neon-red' : 'border-border text-text-muted'}`}>{c}</button>
                ))}
              </div>
              <input className="input" placeholder="Total amount USD" value={sarAmount} onChange={e => setSarAmount(e.target.value)} />
              <input className="input" placeholder="Counterparty addresses (comma-separated)" value={sarCps} onChange={e => setSarCps(e.target.value)} />
              <textarea className="input min-h-[90px] resize-y" placeholder="Narrative…" value={sarNarrative} onChange={e => setSarNarrative(e.target.value)} />
              <button className="btn-primary" disabled={loading || !sarSubject.trim()} onClick={() => run(() => generateSar({
                subject_address: sarSubject.trim(), chain: sarChain, narrative: sarNarrative,
                activity_categories: sarCats, total_amount_usd: Number(sarAmount) || 0,
                counterparties: sarCps.split(',').map(s => s.trim()).filter(Boolean),
              }))}>{loading ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />} Generate SAR</button>
            </>
          )}

          {tab === 'ctr' && (
            <>
              <input className="input" placeholder="Subject address" value={ctrSubject} onChange={e => setCtrSubject(e.target.value)} />
              <textarea className="input min-h-[140px] resize-y font-mono text-xs" value={ctrTxs} onChange={e => setCtrTxs(e.target.value)} />
              <button className="btn-primary" disabled={loading} onClick={() => run(() => {
                let txs: unknown[] = []
                try { txs = JSON.parse(ctrTxs) } catch { throw new Error('Transactions must be valid JSON array') }
                return generateCtr({ subject_address: ctrSubject.trim(), transactions: txs })
              })}>{loading ? <Loader2 size={14} className="animate-spin" /> : <Scale size={14} />} Generate CTR</button>
            </>
          )}

          {tab === 'travel' && (
            <>
              <div className="grid gap-3 md:grid-cols-3">
                <input className="input" placeholder="chain" value={trChain} onChange={e => setTrChain(e.target.value)} />
                <input className="input" placeholder="asset" value={trAsset} onChange={e => setTrAsset(e.target.value)} />
                <input className="input" placeholder="amount" value={trAmount} onChange={e => setTrAmount(e.target.value)} />
              </div>
              <input className="input" placeholder="Originator address" value={trOrig} onChange={e => setTrOrig(e.target.value)} />
              <input className="input" placeholder="Beneficiary address" value={trBenef} onChange={e => setTrBenef(e.target.value)} />
              <button className="btn-primary" disabled={loading || !trOrig.trim() || !trBenef.trim()} onClick={() => run(() => generateTravelRule({
                chain: trChain, asset: trAsset, amount: trAmount,
                originator: { address: trOrig.trim() }, beneficiary: { address: trBenef.trim() },
              }))}>{loading ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Generate Travel Rule</button>
            </>
          )}

          {tab === 'kyv' && (
            <>
              <div className="grid gap-3 md:grid-cols-[1fr_auto]">
                <input className="input" placeholder="Address to attribute" value={kyvAddr} onChange={e => setKyvAddr(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') runKyv() }} />
                <button className="btn-primary" disabled={loading || !kyvAddr.trim()} onClick={runKyv}>{loading ? <Loader2 size={14} className="animate-spin" /> : <Building2 size={14} />} Identify</button>
              </div>
              {kyv && (
                kyv.is_vasp && kyv.vasp ? (
                  <div className="rounded-lg border border-neon-cyan/40 bg-neon-cyan/5 p-4">
                    <p className="text-lg font-bold text-text-primary">{kyv.vasp.name}</p>
                    <p className="text-xs uppercase tracking-widest text-text-muted">{kyv.vasp.type} · {kyv.vasp.jurisdiction || kyv.vasp.country}</p>
                    {kyv.vasp.label && <p className="mt-2 text-sm text-text-secondary">{kyv.vasp.label}</p>}
                  </div>
                ) : (
                  <div className="rounded-lg border border-border bg-bg-secondary p-4 text-sm text-text-muted">No known VASP attribution for this address.</div>
                )
              )}
            </>
          )}
        </div>
        </CinematicStage>
      </div>

      {/* Form/results — grows & scrolls internally */}
      <div className="noscroll-grow space-y-5">
      {error && <div className="rounded-lg border border-neon-red/35 bg-neon-red/10 p-4 text-sm text-neon-red">{error}</div>}
      {report && <ReportOutput report={report} />}
      </div>
    </div>
  )
}
