import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Archive, Plus, Trash2, FileText, AlertTriangle,
  Shield, TrendingUp, BarChart2, Search,
  Clock, Hash, Download, Edit3, X, ChevronDown, ChevronRight,
  type LucideIcon,
} from 'lucide-react'
import { useParams } from 'react-router-dom'
import CinematicStage from '../components/CinematicStage'
import {
  listEvidence, saveEvidence, deleteEvidence,
  annotateEvidence, evidenceSummary, evidenceAuditLog,
  verifyCustodyChain,
} from '../api/client'
import type { CustodyVerifyResult } from '../api/client'
import type { EvidenceRecord, EvidenceSummary, AuditLogEntry } from '../types'

const TYPE_ICONS: Record<string, LucideIcon> = {
  graph_snapshot:  BarChart2,
  tx_snapshot:     Hash,
  address_intel:   Search,
  cluster_report:  Shield,
  cashout_report:  TrendingUp,
  path_report:     BarChart2,
  timeline:        Clock,
  raw_api:         FileText,
  analyst_note:    FileText,
}

const TYPE_COLORS: Record<string, string> = {
  graph_snapshot:  'text-neon-cyan',
  tx_snapshot:     'text-purple-400',
  address_intel:   'text-red-400',
  cluster_report:  'text-orange-400',
  cashout_report:  'text-red-400',
  path_report:     'text-yellow-400',
  timeline:        'text-neon-green',
  raw_api:         'text-text-muted',
  analyst_note:    'text-text-secondary',
}

function qualityColor(q: number) {
  if (q >= 85) return 'text-neon-green'
  if (q >= 65) return 'text-yellow-400'
  return 'text-text-muted'
}

function QualityBar({ score }: { score: number }) {
  const color = score >= 85 ? '#ff5a6e' : score >= 65 ? '#ffd60a' : '#636366'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 bg-bg-border rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${score}%`, background: color }} />
      </div>
      <span className={`text-[10px] font-bold ${qualityColor(score)}`}>{score}</span>
    </div>
  )
}

// ── Evidence card ─────────────────────────────────────────────────────────────

function EvidenceCard({
  record,
  caseId,
  onDelete,
  onAnnotated,
}: {
  record: EvidenceRecord
  caseId: string
  onDelete: (id: string) => void
  onAnnotated: (updated: EvidenceRecord) => void
}) {
  const [open,     setOpen]     = useState(false)
  const [editing,  setEditing]  = useState(false)
  const [notes,    setNotes]    = useState(record.analyst_notes || '')
  const [tagInput, setTagInput] = useState((record.tags || []).join(', '))
  const [saving,   setSaving]   = useState(false)
  const [auditLog, setAuditLog] = useState<AuditLogEntry[] | null>(null)
  const [showAudit, setShowAudit] = useState(false)
  const { t } = useTranslation()

  const TypeIcon: LucideIcon = TYPE_ICONS[record.evidence_type] || FileText
  const typeColor = TYPE_COLORS[record.evidence_type] || 'text-text-muted'

  const saveAnnotations = useCallback(async () => {
    setSaving(true)
    try {
      const tags = tagInput.split(',').map(t => t.trim()).filter(Boolean)
      const res = await annotateEvidence(caseId, record.id, { notes, tags })
      onAnnotated(res.evidence)
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }, [caseId, record.id, notes, tagInput, onAnnotated])

  const loadAudit = useCallback(async () => {
    if (!showAudit) {
      const res = await evidenceAuditLog(caseId, record.id)
      setAuditLog(res.audit_log)
    }
    setShowAudit(s => !s)
  }, [caseId, record.id, showAudit])

  function downloadContent() {
    const blob = new Blob([JSON.stringify(record, null, 2)], { type: 'application/json' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `evidence-${record.id}-${record.evidence_type}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="rounded-lg border border-bg-border bg-bg-elevated overflow-hidden">
      {/* Header row */}
      <button
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-bg-hover transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <TypeIcon size={14} className={`shrink-0 ${typeColor}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-text-primary truncate">{record.title}</span>
            <span className={`text-[9px] uppercase tracking-wide font-bold ${typeColor}`}>
              {record.evidence_type.replace(/_/g, ' ')}
            </span>
            {record.subject && (
              <span className="text-[10px] text-text-muted font-mono">{record.subject.slice(0, 12)}…</span>
            )}
          </div>
          <div className="mt-0.5">
            <QualityBar score={record.quality_score} />
          </div>
        </div>
        <span className="text-[10px] text-text-muted shrink-0">{record.created_at.slice(0, 10)}</span>
        {open
          ? <ChevronDown size={13} className="text-text-muted" />
          : <ChevronRight size={13} className="text-text-muted" />
        }
      </button>

      {/* Expanded */}
      {open && (
        <div className="border-t border-bg-border px-4 py-3 space-y-3">
          {/* Tags */}
          {record.tags && record.tags.length > 0 && !editing && (
            <div className="flex flex-wrap gap-1">
              {record.tags.map(t => (
                <span key={t} className="text-[9px] px-2 py-0.5 rounded-full bg-neon-cyan/10 border border-neon-cyan/20 text-neon-cyan">
                  {t}
                </span>
              ))}
            </div>
          )}

          {/* Analyst notes */}
          {record.analyst_notes && !editing && (
            <div className="text-[11px] text-text-secondary italic">"{record.analyst_notes}"</div>
          )}

          {/* Edit form */}
          {editing && (
            <div className="space-y-2">
              <textarea
                className="input w-full text-xs h-20 resize-none"
                placeholder={t('tools:evidenceVault.card.notesPlaceholder')}
                value={notes}
                onChange={e => setNotes(e.target.value)}
              />
              <input
                className="input w-full text-xs"
                placeholder={t('tools:evidenceVault.card.tagsPlaceholder')}
                value={tagInput}
                onChange={e => setTagInput(e.target.value)}
              />
              <div className="flex gap-2">
                <button onClick={saveAnnotations} disabled={saving} className="btn-primary text-xs px-3 py-1.5">
                  {saving ? t('tools:evidenceVault.card.saving') : t('tools:evidenceVault.card.save')}
                </button>
                <button onClick={() => setEditing(false)} className="btn-secondary text-xs px-3 py-1.5">
                  {t('tools:evidenceVault.card.cancel')}
                </button>
              </div>
            </div>
          )}

          {/* Hash */}
          <div className="flex items-center gap-2 text-[10px] text-text-muted font-mono">
            <Hash size={10} />
            <span className="truncate">{record.content_hash}</span>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 flex-wrap">
            {!editing && (
              <button
                onClick={() => setEditing(true)}
                className="flex items-center gap-1 text-[10px] text-text-muted hover:text-neon-cyan transition-colors"
              >
                <Edit3 size={11} /> {t('tools:evidenceVault.card.annotate')}
              </button>
            )}
            <button
              onClick={downloadContent}
              className="flex items-center gap-1 text-[10px] text-text-muted hover:text-neon-cyan transition-colors"
            >
              <Download size={11} /> {t('tools:evidenceVault.card.export')}
            </button>
            <button
              onClick={loadAudit}
              className="flex items-center gap-1 text-[10px] text-text-muted hover:text-neon-cyan transition-colors"
            >
              <Clock size={11} /> {showAudit ? t('tools:evidenceVault.card.hide') : t('tools:evidenceVault.card.auditLog')}
            </button>
            <button
              onClick={() => onDelete(record.id)}
              className="flex items-center gap-1 text-[10px] text-red-500 hover:text-red-400 transition-colors ml-auto"
            >
              <Trash2 size={11} /> {t('tools:evidenceVault.card.delete')}
            </button>
          </div>

          {/* Audit log */}
          {showAudit && auditLog && (
            <div className="rounded bg-bg-primary border border-bg-border p-2 space-y-1">
              {auditLog.map(entry => (
                <div key={entry.id} className="text-[10px] text-text-muted flex items-start gap-2">
                  <span className="text-text-dim shrink-0">{entry.timestamp.slice(0, 19)}</span>
                  <span className="text-text-secondary">{entry.actor}</span>
                  <span>{entry.action}</span>
                  {entry.detail && <span className="text-text-dim">- {entry.detail}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Save dialog ───────────────────────────────────────────────────────────────

function SaveDialog({
  caseId,
  onSaved,
  onClose,
}: {
  caseId: string
  onSaved: (r: EvidenceRecord) => void
  onClose: () => void
}) {
  const [type,    setType]    = useState('analyst_note')
  const [title,   setTitle]   = useState('')
  const [subject, setSubject] = useState('')
  const [content, setContent] = useState('')
  const [notes,   setNotes]   = useState('')
  const [tags,    setTags]    = useState('')
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState('')
  const { t } = useTranslation()

  const save = useCallback(async () => {
    if (!title.trim()) { setError(t('tools:evidenceVault.dialog.titleRequired')); return }
    setSaving(true); setError('')
    try {
      let contentObj: unknown = { text: content }
      if (content.trim().startsWith('{') || content.trim().startsWith('[')) {
        try { contentObj = JSON.parse(content) } catch { /* use string */ }
      }
      const res = await saveEvidence(caseId, {
        evidence_type:  type,
        title:          title.trim(),
        content:        contentObj as Record<string, unknown>,
        subject:        subject.trim(),
        tags:           tags.split(',').map(t => t.trim()).filter(Boolean),
        analyst_notes:  notes.trim(),
      })
      onSaved(res.evidence)
    } catch (e: unknown) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }, [caseId, type, title, subject, content, notes, tags, onSaved, t])

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="w-full max-w-lg bg-bg-elevated border border-bg-border rounded-xl shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-bg-border">
          <h2 className="text-sm font-semibold text-text-primary">{t('tools:evidenceVault.dialog.title')}</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary">
            <X size={16} />
          </button>
        </div>
        <div className="p-5 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[10px] text-text-muted mb-1">{t('tools:evidenceVault.dialog.type')}</label>
              <select className="input w-full text-xs" value={type} onChange={e => setType(e.target.value)}>
                {['analyst_note','graph_snapshot','tx_snapshot','address_intel',
                  'cluster_report','cashout_report','path_report','timeline','raw_api'].map(ty => (
                  <option key={ty} value={ty}>{ty.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[10px] text-text-muted mb-1">{t('tools:evidenceVault.dialog.subjectAddress')}</label>
              <input className="input w-full text-xs font-mono" placeholder={t('tools:evidenceVault.dialog.subjectPlaceholder')} value={subject} onChange={e => setSubject(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="block text-[10px] text-text-muted mb-1">{t('tools:evidenceVault.dialog.titleField')}</label>
            <input className="input w-full text-xs" placeholder={t('tools:evidenceVault.dialog.titlePlaceholder')} value={title} onChange={e => setTitle(e.target.value)} />
          </div>
          <div>
            <label className="block text-[10px] text-text-muted mb-1">{t('tools:evidenceVault.dialog.content')}</label>
            <textarea className="input w-full h-28 text-[10px] font-mono resize-none" placeholder={t('tools:evidenceVault.dialog.contentPlaceholder')} value={content} onChange={e => setContent(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[10px] text-text-muted mb-1">{t('tools:evidenceVault.dialog.tags')}</label>
              <input className="input w-full text-xs" placeholder={t('tools:evidenceVault.dialog.tagsPlaceholder')} value={tags} onChange={e => setTags(e.target.value)} />
            </div>
            <div>
              <label className="block text-[10px] text-text-muted mb-1">{t('tools:evidenceVault.dialog.analystNotes')}</label>
              <input className="input w-full text-xs" placeholder={t('tools:evidenceVault.dialog.notesPlaceholder')} value={notes} onChange={e => setNotes(e.target.value)} />
            </div>
          </div>
          {error && <div className="text-[11px] text-red-400 flex items-center gap-1"><AlertTriangle size={11} />{error}</div>}
        </div>
        <div className="flex gap-2 px-5 pb-5">
          <button onClick={save} disabled={saving} className="btn-primary flex-1 text-xs py-2">
            {saving ? t('tools:evidenceVault.card.saving') : t('tools:evidenceVault.dialog.save')}
          </button>
          <button onClick={onClose} className="btn-secondary px-4 text-xs">{t('tools:evidenceVault.dialog.cancel')}</button>
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function EvidenceVault() {
  // caseId from URL or let user pick
  const { t } = useTranslation()
  const { id: urlCaseId } = useParams<{ id?: string }>()
  const [caseId,   setCaseId]   = useState(urlCaseId || '')
  const [records,  setRecords]  = useState<EvidenceRecord[]>([])
  const [summary,  setSummary]  = useState<EvidenceSummary | null>(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState('')
  const [showSave, setShowSave] = useState(false)
  const [query,    setQuery]    = useState('')

  const load = useCallback(async () => {
    if (!caseId.trim()) return
    setLoading(true); setError('')
    try {
      const [listRes, sumRes] = await Promise.all([
        listEvidence(caseId.trim()),
        evidenceSummary(caseId.trim()),
      ])
      setRecords(listRes.evidence)
      setSummary(sumRes.summary)
    } catch (e: unknown) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [caseId])

  useEffect(() => { if (caseId) load() }, [caseId, load])

  const handleDelete = useCallback(async (id: string) => {
    if (!confirm(t('tools:evidenceVault.deleteConfirm'))) return
    await deleteEvidence(caseId, id)
    setRecords(prev => prev.filter(r => r.id !== id))
    load()
  }, [caseId, load, t])

  const handleAnnotated = useCallback((updated: EvidenceRecord) => {
    setRecords(prev => prev.map(r => r.id === updated.id ? updated : r))
  }, [])

  const filtered = records.filter(r => {
    if (!query) return true
    const q = query.toLowerCase()
    return r.title.toLowerCase().includes(q) || r.subject.toLowerCase().includes(q) ||
           r.evidence_type.includes(q) || r.tags.some(t => t.toLowerCase().includes(q))
  })

  return (
    <div className="noscroll-page p-6 space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center"
          style={{ background: 'linear-gradient(135deg, rgba(255,159,10,0.15), rgba(255,45,85,0.1))', border: '1px solid rgba(255,159,10,0.3)' }}>
          <Archive size={18} style={{ color: '#FBBF24' }} />
        </div>
        <div className="flex-1">
          <h1 className="text-lg font-bold text-text-primary">{t('tools:evidenceVault.title')}</h1>
          <p className="text-[11px] text-text-muted">{t('tools:evidenceVault.subtitle')}</p>
        </div>
        <CustodyVerifyButton caseId={caseId} />
      </div>

      {/* Case picker */}
      <CinematicStage
        variant="evidence"
        icon={Archive}
        collapsed={!!records && records.length > 0}
      >
        <div className="flex items-center gap-3">
          <input
            className="input flex-1 text-xs font-mono"
            placeholder={t('tools:evidenceVault.casePlaceholder')}
            value={caseId}
            onChange={e => setCaseId(e.target.value)}
            onBlur={load}
            onKeyDown={e => e.key === 'Enter' && load()}
          />
          <button onClick={load} disabled={loading} className="btn-primary text-xs px-4 py-2">
            {loading ? '…' : t('tools:evidenceVault.load')}
          </button>
          <button
            onClick={() => setShowSave(true)}
            disabled={!caseId.trim()}
            className="btn-secondary text-xs px-4 py-2 flex items-center gap-1.5"
          >
            <Plus size={13} /> {t('tools:evidenceVault.saveArtifact')}
          </button>
        </div>
      </CinematicStage>

      {error && (
        <div className="text-[11px] text-red-400 flex items-center gap-1">
          <AlertTriangle size={11} /> {error}
        </div>
      )}

      {/* Summary cards + search + records list — grows & scrolls internally */}
      <div className="noscroll-grow space-y-6">
      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="rounded-lg border border-bg-border bg-bg-elevated px-3 py-2.5 text-center">
            <div className="text-xl font-bold text-neon-cyan">{summary.total}</div>
            <div className="text-[10px] text-text-muted uppercase">{t('tools:evidenceVault.summary.artifacts')}</div>
          </div>
          <div className="rounded-lg border border-bg-border bg-bg-elevated px-3 py-2.5 text-center">
            <div className={`text-xl font-bold ${qualityColor(summary.avg_quality)}`}>{summary.avg_quality.toFixed(0)}</div>
            <div className="text-[10px] text-text-muted uppercase">{t('tools:evidenceVault.summary.avgQuality')}</div>
          </div>
          <div className="col-span-2 rounded-lg border border-bg-border bg-bg-elevated px-3 py-2.5">
            <div className="text-[10px] text-text-muted uppercase mb-2">{t('tools:evidenceVault.summary.byType')}</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(summary.by_type).map(([t, d]) => (
                <span key={t} className="text-[10px] text-text-secondary">
                  <span className={TYPE_COLORS[t] || 'text-text-muted'}>
                    {t.replace(/_/g, ' ')}
                  </span>
                  {' '}({d.count})
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Search */}
      {records.length > 0 && (
        <div className="relative">
          <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            className="input w-full pl-8 text-xs"
            placeholder={t('tools:evidenceVault.filterPlaceholder')}
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
        </div>
      )}

      {/* Records */}
      {filtered.length > 0 ? (
        <div className="space-y-2">
          {filtered.map(r => (
            <EvidenceCard
              key={r.id}
              record={r}
              caseId={caseId}
              onDelete={handleDelete}
              onAnnotated={handleAnnotated}
            />
          ))}
        </div>
      ) : caseId && !loading ? (
        <div className="text-center py-12 text-text-muted text-sm">
          {t('tools:evidenceVault.emptyWithCase')}
        </div>
      ) : !caseId ? (
        <div className="text-center py-12 text-text-muted text-sm">
          {t('tools:evidenceVault.emptyNoCase')}
        </div>
      ) : null}
      </div>

      {/* Save dialog */}
      {showSave && (
        <SaveDialog
          caseId={caseId}
          onSaved={record => { setRecords(prev => [record, ...prev]); setShowSave(false); load() }}
          onClose={() => setShowSave(false)}
        />
      )}
    </div>
  )
}

/* ── Chain-of-custody verification ────────────────────────────────────────── */
function CustodyVerifyButton({ caseId }: { caseId: string }) {
  const { t } = useTranslation()
  const [verifying, setVerifying] = useState(false)
  const [result, setResult] = useState<CustodyVerifyResult | null>(null)

  async function verify() {
    setVerifying(true)
    try {
      setResult(await verifyCustodyChain(caseId.trim()))
    } catch {
      setResult(null)
    } finally {
      setVerifying(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      {result && (
        <span
          className="text-[11px] font-semibold"
          style={{ color: result.valid ? '#34D399' : '#ff5d86' }}
          title={result.valid
            ? t('tools:evidenceVault.custody.tipValid', { tip: `${result.chain_tip.slice(0, 16)}…`, at: result.verified_at })
            : result.problems.map(p => t('tools:evidenceVault.custody.tipInvalid', { title: p.title, error: p.error })).join('; ')}
        >
          {result.valid
            ? t('tools:evidenceVault.custody.chainIntact', { count: result.records_checked })
            : t('tools:evidenceVault.custody.chainBroken', { count: result.problems.length })}
        </span>
      )}
      <button className="btn-secondary text-xs" onClick={verify} disabled={verifying}>
        {verifying ? t('tools:evidenceVault.custody.verifying') : t('tools:evidenceVault.custody.verify')}
      </button>
    </div>
  )
}
