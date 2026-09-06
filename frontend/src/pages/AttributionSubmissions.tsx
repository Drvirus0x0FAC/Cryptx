/**
 * AttributionSubmissions - the label-growth loop.
 * Analysts submit address→entity attributions with evidence; reviewers approve
 * (→ enters the attribution engine with provenance) or reject. Every action is audited.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Fingerprint, Plus, Loader2, Check, X, Clock, ThumbsUp, ThumbsDown, Trash2,
} from 'lucide-react'
import {
  listSubmissions, submitAttribution, reviewSubmission, type AttributionSubmission,
} from '../api/boards'
import FeedIngestionPanel from '../components/FeedIngestionPanel'
import CinematicStage from '../components/CinematicStage'

const CATEGORIES = ['unknown', 'exchange', 'mixer', 'scam', 'ransomware', 'darknet', 'sanctioned', 'defi', 'gambling', 'bridge', 'service', 'individual']

export default function AttributionSubmissions() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [tab, setTab] = useState<'pending' | 'approved' | 'rejected'>('pending')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ address: '', chain: '', category: 'unknown', actor: '', label: '', source: '', confidence: 0.6, note: '' })
  const [evidence, setEvidence] = useState<Array<{ type: string; value: string; ref: string }>>([{ type: 'url', value: '', ref: '' }])
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({})

  const { data, isLoading } = useQuery({ queryKey: ['attr-subs', tab], queryFn: () => listSubmissions(tab) })
  const stats = data?.stats

  const submitMut = useMutation({
    mutationFn: () => submitAttribution({ ...form, evidence: evidence.filter((e) => e.value.trim()) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['attr-subs'] })
      setShowForm(false)
      setForm({ address: '', chain: '', category: 'unknown', actor: '', label: '', source: '', confidence: 0.6, note: '' })
      setEvidence([{ type: 'url', value: '', ref: '' }])
    },
  })
  const reviewMut = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'approve' | 'reject' }) => reviewSubmission(id, action, reviewNotes[id] || ''),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['attr-subs'] }),
  })

  const canSubmit = form.address.trim() && (form.actor.trim() || form.label.trim()) && evidence.some((e) => e.value.trim())

  return (
    <div className="noscroll-page p-6 max-w-5xl mx-auto space-y-5 page-enter">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center"
            style={{ background: 'rgba(0,212,126,0.10)', border: '1px solid rgba(0,212,126,0.3)' }}>
            <Fingerprint size={16} style={{ color: '#00d47e' }} />
          </div>
          <div>
            <h1 className="text-display text-sm font-bold tracking-widest uppercase" style={{ color: '#eefff6' }}>{t('tools:attrSubmissions.title')}</h1>
            <p className="text-text-secondary text-xs mt-0.5">Submit address→entity labels with evidence · reviewer sign-off feeds the attribution engine</p>
          </div>
        </div>
        <button className="btn-primary" onClick={() => setShowForm(true)}><Plus size={14} /> Submit attribution</button>
      </div>

      {/* Submissions list — grows & scrolls internally */}
      <div className="noscroll-grow space-y-5">
      {stats && (
        <div className="grid grid-cols-4 gap-3">
          {([['pending', stats.pending, Clock], ['approved', stats.approved, ThumbsUp], ['rejected', stats.rejected, ThumbsDown]] as const).map(([k, n, Icon]) => (
            <button key={k} onClick={() => setTab(k)} className={`card-cyber !p-3 text-left ${tab === k ? '!border-neon-cyan/60' : ''}`}>
              <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-text-muted"><Icon size={11} /> {k}</div>
              <div className="text-xl font-bold text-text-primary">{n}</div>
            </button>
          ))}
          <div className="card-cyber !p-3">
            <div className="text-[10px] uppercase tracking-widest text-text-muted">Total</div>
            <div className="text-xl font-bold text-text-primary">{stats.total}</div>
          </div>
        </div>
      )}

      {/* V2 F5: Bulk feed ingestion (Etherscan labels / Chainabuse / OFAC / curated clusters) */}
      <div className="card-cyber p-4">
        <FeedIngestionPanel />
      </div>

      {showForm && (
        <CinematicStage variant="submissions" icon={Fingerprint} kicker="INTAKE" title="New Attribution Submission" collapsed={false}>
        <div className="space-y-3 animate-slide-up">
          <div className="flex items-center justify-between">
            <h3 className="card-title">New attribution submission</h3>
            <button onClick={() => setShowForm(false)} className="text-text-muted hover:text-text-primary"><X size={14} /></button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input className="input font-mono" placeholder="Address *" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
            <input className="input" placeholder="Chain (eth / btc / tron…)" value={form.chain} onChange={(e) => setForm({ ...form, chain: e.target.value })} />
            <input className="input" placeholder="Actor / entity (e.g. Lazarus Group) *" value={form.actor} onChange={(e) => setForm({ ...form, actor: e.target.value })} />
            <input className="input" placeholder="Label (e.g. Binance hot wallet 7)" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
            <select className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <input className="input" placeholder="Source (where you learned this)" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} />
          </div>
          <label className="block text-[10px] text-text-muted">Confidence: {form.confidence.toFixed(2)}
            <input type="range" min={0.1} max={1} step={0.05} className="w-full" value={form.confidence}
              onChange={(e) => setForm({ ...form, confidence: Number(e.target.value) })} />
          </label>
          <div className="space-y-2">
            <span className="text-[10px] uppercase tracking-widest text-text-muted">Evidence * (at least one item)</span>
            {evidence.map((ev, i) => (
              <div key={i} className="flex gap-2">
                <select className="input !w-32 !py-1.5 !text-xs" value={ev.type}
                  onChange={(e) => setEvidence(evidence.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)))}>
                  {['url', 'transaction', 'screenshot', 'court_record', 'osint_post', 'exchange_response', 'other'].map((t) => <option key={t}>{t}</option>)}
                </select>
                <input className="input flex-1 !py-1.5 !text-xs" placeholder="Value (URL, tx hash, document ref…)"
                  value={ev.value} onChange={(e) => setEvidence(evidence.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
                <input className="input flex-1 !py-1.5 !text-xs" placeholder="Context / reference"
                  value={ev.ref} onChange={(e) => setEvidence(evidence.map((x, j) => (j === i ? { ...x, ref: e.target.value } : x)))} />
                <button className="btn-ghost !px-2" onClick={() => setEvidence(evidence.filter((_, j) => j !== i))} disabled={evidence.length === 1}><Trash2 size={12} /></button>
              </div>
            ))}
            <button className="btn-ghost !py-1 !text-xs" onClick={() => setEvidence([...evidence, { type: 'url', value: '', ref: '' }])}><Plus size={11} /> Add evidence item</button>
          </div>
          <textarea className="input resize-none" rows={2} placeholder="Analyst note (optional)" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          <button className="btn-primary" disabled={!canSubmit || submitMut.isPending} onClick={() => submitMut.mutate()}>
            {submitMut.isPending && <Loader2 size={13} className="animate-spin" />} Submit for review
          </button>
          {submitMut.isError && <p className="text-xs text-red-400">{(submitMut.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Submission failed'}</p>}
        </div>
        </CinematicStage>
      )}

      {isLoading ? (
        <div className="flex items-center gap-2 text-text-muted text-xs p-6"><Loader2 size={14} className="animate-spin" /> Loading…</div>
      ) : (data?.submissions || []).length === 0 ? (
        <div className="card-cyber text-center py-8 text-xs text-text-muted">No {tab} submissions.</div>
      ) : (
        <div className="space-y-3">
          {(data?.submissions || []).map((s: AttributionSubmission) => (
            <div key={s.id} className="card-cyber !py-3 space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <code className="text-[10px] text-text-secondary">{s.address}</code>
                {s.chain && <span className="text-[9px] px-1.5 py-0.5 rounded bg-bg-secondary uppercase">{s.chain}</span>}
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-bg-secondary">{s.category}</span>
                <span className="text-[9px] text-text-muted">conf {s.confidence}</span>
                <div className="flex-1" />
                <span className="text-[9px] text-text-muted">by {s.submitted_by} · {String(s.submitted_at).slice(0, 16).replace('T', ' ')}</span>
              </div>
              <p className="text-xs text-text-primary font-semibold">{s.actor || s.label}{s.actor && s.label ? ` - ${s.label}` : ''}</p>
              {s.source && <p className="text-[11px] text-text-secondary">Source: {s.source}</p>}
              {s.evidence.length > 0 && (
                <div className="text-[10px] text-text-muted space-y-0.5">
                  {s.evidence.map((ev, i) => <p key={i}>• [{ev.type}] {ev.value}{ev.ref ? ` - ${ev.ref}` : ''}</p>)}
                </div>
              )}
              {s.status === 'pending' ? (
                <div className="flex items-center gap-2 pt-1 border-t border-bg-border/50">
                  <input className="input !py-1 !text-xs flex-1" placeholder="Review note (optional)"
                    value={reviewNotes[s.id] || ''} onChange={(e) => setReviewNotes({ ...reviewNotes, [s.id]: e.target.value })} />
                  <button className="btn-ghost !py-1 !text-emerald-400" disabled={reviewMut.isPending}
                    onClick={() => reviewMut.mutate({ id: s.id, action: 'approve' })}><Check size={12} /> Approve</button>
                  <button className="btn-ghost !py-1 !text-red-400" disabled={reviewMut.isPending}
                    onClick={() => reviewMut.mutate({ id: s.id, action: 'reject' })}><X size={12} /> Reject</button>
                </div>
              ) : (
                <p className={`text-[10px] ${s.status === 'approved' ? 'text-emerald-400' : 'text-red-400'}`}>
                  {s.status} by {s.reviewed_by} · {String(s.reviewed_at).slice(0, 16).replace('T', ' ')}
                  {s.review_note && ` - ${s.review_note}`}
                  {s.resulting_attr_id && ` · attribution ${s.resulting_attr_id.slice(0, 8)}…`}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
      </div>
    </div>
  )
}
