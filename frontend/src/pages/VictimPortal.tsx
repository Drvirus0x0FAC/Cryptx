/**
 * Victim Intake Portal — PUBLIC page (no auth required).
 * Lets victims of crypto fraud submit a report. Shows aggregate scam stats.
 *
 * Route: /portal/report  (public)
 */
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { ShieldAlert, Send, CheckCircle, TrendingDown, Users, Loader2 } from 'lucide-react'
import { publicVictimReport, publicScamStats } from '../api/client'

export default function VictimPortal() {
  const { t } = useTranslation()
  const [form, setForm] = useState({
    scam_type: 'phishing', scammer_address: '', victim_address: '', amount_usd: 0,
    token: '', chain: 'ETH', incident_date: '', description: '',
    contact_name: '', contact_email: '', jurisdiction: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')
  const [stats, setStats] = useState<{ total_reports: number; total_damage_usd: number; top_scam_types: { type: string; count: number }[]; scam_types: string[] } | null>(null)

  useEffect(() => {
    publicScamStats().then(setStats).catch(() => {})
  }, [])

  async function submit() {
    if (!form.scammer_address.trim()) { setError('Scammer address is required.'); return }
    setSubmitting(true); setError('')
    try {
      await publicVictimReport({ ...form, amount_usd: Number(form.amount_usd) || 0 })
      setDone(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Submission failed')
    } finally {
      setSubmitting(false)
    }
  }

  if (done) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6"
        style={{ background: 'linear-gradient(135deg,rgb(var(--bg-primary)),rgb(var(--bg-secondary)))' }}>
        <div className="card-cyber max-w-md text-center space-y-4">
          <CheckCircle size={48} style={{ color: '#34D399', margin: '0 auto' }} />
          <h2 className="text-xl font-bold" style={{ color: 'inherit' }}>Report Received</h2>
          <p className="text-text-secondary text-sm">
            Your report has been logged. An analyst will review it and, if it matches an active
            investigation, your information will be linked to that case.
          </p>
          <button onClick={() => { setDone(false); setForm({ ...form, scammer_address: '', description: '' }) }}
            className="btn-ghost">
            Submit Another Report
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen p-6" style={{ background: 'linear-gradient(135deg,rgb(var(--bg-primary)),rgb(var(--bg-secondary)))' }}>
      <div className="max-w-3xl mx-auto space-y-6">
        {/* Header */}
        <div className="text-center space-y-2">
          <div className="w-14 h-14 rounded-xl flex items-center justify-center mx-auto"
            style={{ background: 'rgba(220,38,38,0.15)', border: '1px solid rgba(220,38,38,0.4)' }}>
            <ShieldAlert size={28} style={{ color: '#dc2626' }} />
          </div>
          <h1 className="text-2xl font-bold" style={{ color: 'inherit' }}>Report Crypto Fraud</h1>
          <p className="text-text-secondary text-sm">
            Help investigators track scammers. Your report is confidential and may help recover funds.
          </p>
        </div>

        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-3 gap-3">
            <div className="card-cyber text-center">
              <Users size={16} className="mx-auto mb-1" style={{ color: '#60A5FA' }} />
              <div className="text-lg font-bold" style={{ color: '#60A5FA' }}>{stats.total_reports}</div>
              <div className="text-[10px] text-text-muted uppercase">Reports</div>
            </div>
            <div className="card-cyber text-center">
              <TrendingDown size={16} className="mx-auto mb-1" style={{ color: '#F87171' }} />
              <div className="text-lg font-bold" style={{ color: '#F87171' }}>${stats.total_damage_usd.toLocaleString()}</div>
              <div className="text-[10px] text-text-muted uppercase">Damages</div>
            </div>
            <div className="card-cyber text-center">
              <ShieldAlert size={16} className="mx-auto mb-1" style={{ color: '#FBBF24' }} />
              <div className="text-lg font-bold" style={{ color: '#FBBF24' }}>{stats.top_scam_types.length}</div>
              <div className="text-[10px] text-text-muted uppercase">Scam Types</div>
            </div>
          </div>
        )}

        {/* Form */}
        <div className="card-cyber space-y-4">
          <div className="grid md:grid-cols-2 gap-3">
            <Field label="Scam Type *">
              <select value={form.scam_type} onChange={e => setForm({ ...form, scam_type: e.target.value })} className="input">
                {(stats?.scam_types || ['phishing','pig_butchering','investment_fraud','wallet_drainer','rug_pull','romance_scam','exchange_fraud','nft_fraud','other']).map(t => (
                  <option key={t} value={t}>{t.replace(/_/g,' ').replace(/\b\w/g, c => c.toUpperCase())}</option>
                ))}
              </select>
            </Field>
            <Field label="Chain">
              <select value={form.chain} onChange={e => setForm({ ...form, chain: e.target.value })} className="input">
                {['ETH','BTC','TRX','SOL','BSC','MATIC','BNB'].map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Scammer's Address *">
            <input value={form.scammer_address} onChange={e => setForm({ ...form, scammer_address: e.target.value })}
              placeholder="0x... or bc1... or T..." className="input font-mono text-xs" />
          </Field>
          <div className="grid md:grid-cols-2 gap-3">
            <Field label="Your Address (optional)">
              <input value={form.victim_address} onChange={e => setForm({ ...form, victim_address: e.target.value })}
                placeholder="Your wallet address" className="input font-mono text-xs" />
            </Field>
            <Field label="Amount Lost (USD)">
              <input type="number" value={form.amount_usd || ''} onChange={e => setForm({ ...form, amount_usd: Number(e.target.value) })}
                placeholder="0" className="input" />
            </Field>
          </div>
          <div className="grid md:grid-cols-2 gap-3">
            <Field label="Incident Date">
              <input type="date" value={form.incident_date} onChange={e => setForm({ ...form, incident_date: e.target.value })} className="input" />
            </Field>
            <Field label="Token (if known)">
              <input value={form.token} onChange={e => setForm({ ...form, token: e.target.value })}
                placeholder="USDT, ETH, ..." className="input" />
            </Field>
          </div>
          <Field label="What happened?">
            <textarea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })}
              placeholder="Describe the scam — how you were contacted, what was promised, how funds were sent..."
              rows={4} className="input resize-none" />
          </Field>
          <div className="grid md:grid-cols-3 gap-3">
            <Field label="Your Name (optional)">
              <input value={form.contact_name} onChange={e => setForm({ ...form, contact_name: e.target.value })} className="input" />
            </Field>
            <Field label="Email (optional)">
              <input value={form.contact_email} onChange={e => setForm({ ...form, contact_email: e.target.value })} className="input" />
            </Field>
            <Field label="Country">
              <input value={form.jurisdiction} onChange={e => setForm({ ...form, jurisdiction: e.target.value })}
                placeholder="e.g. United States" className="input" />
            </Field>
          </div>

          {error && <p className="text-neon-red text-xs">⚠ {error}</p>}

          <button onClick={submit} disabled={submitting} className="btn-primary w-full">
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            Submit Report
          </button>
        </div>
        <p className="text-center text-[10px] text-text-muted">
          🔒 Your contact details are only visible to analysts reviewing reports. They are never shared publicly.
        </p>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-[11px] uppercase tracking-wider text-text-muted block mb-1">{label}</label>
      {children}
    </div>
  )
}
