import { useState, useRef, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  FolderOpen, Plus, Trash2, AlertCircle, Loader2,
  FileText, Search, StickyNote, ArrowLeft, Download,
  RefreshCw, ExternalLink, ShieldAlert, LayoutDashboard, ChevronRight,
  Users, Shield, Eye, Clock, AlertTriangle, ChevronDown, ChevronUp,
} from 'lucide-react'
import {
  getCase, addAddressToCase, removeAddressFromCase,
  addNote, deleteNote, lookupAddress, scoreRisk, updateCase,
  listCaseMembers, addCaseMember, updateCaseMemberRole, removeCaseMember,
  listTeamMembers,
  type CaseMember, type TeamMember,
} from '../api/client'
import { listBoards, createBoard } from '../api/boards'
import type { Case, AddressIntel, RiskScore } from '../types'
import type { BoardMeta } from '../api/boards'
import RiskGauge from '../components/RiskGauge'
import CategoryBadges from '../components/CategoryBadges'
import RiskSignalList from '../components/RiskSignalList'
import CaseQaChat from '../components/CaseQaChat'
import CustodyReportButton from '../components/CustodyReportButton'
import CollabPresenceIndicator from '../components/CollabPresence'
import { useAuth } from '../auth/AuthContext'

function scoreColor(s: number) {
  if (s >= 80) return '#F87171'
  if (s >= 60) return '#FBBF24'
  if (s >= 40) return '#FBBF24'
  if (s >= 20) return '#FBBF24'
  return '#34D399'
}

const panelStyle: React.CSSProperties = {
  border: '1px solid rgb(var(--bg-border, 40 44 55) / 0.5)',
  borderRadius: 12,
  background: 'rgb(var(--bg-card, 18 22 30) / 0.6)',
  padding: 16,
}

const badgeStyle = (color: string): React.CSSProperties => ({
  fontSize: 10,
  padding: '2px 8px',
  borderRadius: 6,
  fontWeight: 600,
  background: `${color}22`,
  color,
  border: `1px solid ${color}44`,
})

const priorityColor = (p: string) => {
  if (p === 'urgent') return '#F87171'
  if (p === 'high') return '#FB923C'
  if (p === 'medium') return '#FBBF24'
  return '#34D399'
}

const statusColor = (s: string) => {
  if (s === 'open') return '#60A5FA'
  if (s === 'in_progress') return '#FBBF24'
  if (s === 'done' || s === 'closed') return '#34D399'
  return '#9CA3AF'
}

const deliverableStatusColor = (s: string) => {
  if (s === 'approved') return '#34D399'
  if (s === 'rejected') return '#F87171'
  if (s === 'revision_requested') return '#FB923C'
  if (s === 'submitted') return '#60A5FA'
  return '#9CA3AF'
}

export default function CaseDetail() {
  const { t } = useTranslation()
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const auth = useAuth()

  const [newAddr,   setNewAddr]   = useState('')
  const [newLabel,  setNewLabel]  = useState('')
  const [noteText,  setNoteText]  = useState('')
  const [screenedIntel, setIntel] = useState<Record<string, { intel: AddressIntel; risk: RiskScore }>>({})
  const [loading,   setLoading]   = useState<Record<string, boolean>>({})
  const [openAddr,  setOpenAddr]  = useState<string | null>(null)

  const { data: caseData, isLoading, error } = useQuery<Case>({
    queryKey: ['case', id],
    queryFn: () => getCase(id!),
    enabled: !!id,
  })

  const addAddrMut = useMutation({
    mutationFn: () => addAddressToCase(id!, { address: newAddr.trim(), label: newLabel.trim() }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['case', id] }); setNewAddr(''); setNewLabel('') },
  })

  const removeAddrMut = useMutation({
    mutationFn: (addr: string) => removeAddressFromCase(id!, addr),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['case', id] }),
  })

  const addNoteMut = useMutation({
    mutationFn: () => addNote(id!, noteText.trim()),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['case', id] }); setNoteText('') },
  })

  const deleteNoteMut = useMutation({
    mutationFn: (nid: number) => deleteNote(id!, nid),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['case', id] }),
  })

  const handleScreen = async (addr: string) => {
    setLoading((p) => ({ ...p, [addr]: true }))
    try {
      const intel = await lookupAddress(addr)
      const risk  = await scoreRisk(intel)
      setIntel((p) => ({ ...p, [addr]: { intel, risk } }))
      await addAddressToCase(id!, { address: addr, chain: intel.chain, risk_score: risk.score, risk_level: risk.risk_level })
      qc.invalidateQueries({ queryKey: ['case', id] })
    } catch (e) {
      console.error(e)
    } finally {
      setLoading((p) => ({ ...p, [addr]: false }))
    }
  }

  if (isLoading) return (
    <div className="flex justify-center py-20">
      <Loader2 className="animate-spin" size={28} style={{ color: '#ff5a6e' }} />
    </div>
  )

  if (error || !caseData) return (
    <div className="p-6 flex items-center gap-2 text-neon-red">
      <AlertCircle size={15} /> {t('tools:caseDetail.notFound')}
    </div>
  )

  const addresses = caseData.addresses ?? []
  const notes     = caseData.notes ?? []
  const isOwner = auth.user?.id === caseData.owner_id || (auth.user?.role || '') === 'admin'

  return (
    <div className="noscroll-page p-6 max-w-5xl mx-auto space-y-6 page-enter">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <button
            onClick={() => navigate('/cases')}
            className="flex items-center gap-1 text-text-muted hover:text-neon-cyan text-xs mb-2 transition-colors"
          >
            <ArrowLeft size={12} />
            {t('tools:caseDetail.allCases')}
          </button>
          <h1 className="text-display text-base font-bold tracking-wide" style={{ color: 'inherit' }}>
            {caseData.name}
          </h1>
          {caseData.description && (
            <p className="text-text-secondary text-sm mt-1">{caseData.description}</p>
          )}
          <div className="flex items-center gap-3 mt-2 text-[11px] text-text-muted text-tech">
            <span className="badge badge-green">{caseData.status}</span>
            <span>{t('tools:caseDetail.created', { date: new Date(caseData.created_at).toLocaleDateString() })}</span>
            <span>{t('tools:caseDetail.addressCount', { count: addresses.length })}</span>
          </div>
          <div className="mt-2"><CollabPresenceIndicator caseId={caseData.id} /></div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex gap-2">
            <button
              onClick={() => navigate(`/cases/${caseData.id}/tasks`)}
              className="btn-secondary"
            >
              <Clock size={14} />
              {t('tools:caseDetail.taskManagement')}
            </button>
            <button
              onClick={() => navigate(`/cases/${caseData.id}/audit`)}
              className="btn-ghost"
            >
              <FileText size={14} />
              {t('tools:caseDetail.auditLog')}
            </button>
          </div>
          <button
            onClick={() => navigate(`/reports?case=${encodeURIComponent(caseData.id)}&type=forensic&auto=1`)}
            className="btn-secondary"
          >
            <FileText size={14} />
            {t('tools:caseDetail.forensicReport')}
          </button>
          <button
            onClick={() => navigate(`/reports?case=${encodeURIComponent(caseData.id)}`)}
            className="btn-ghost"
          >
            <Download size={14} />
            {t('tools:caseDetail.exportReport')}
          </button>
          <CustodyReportButton caseId={caseData.id} />
        </div>
      </div>

      {/* Content */}
      <div className="noscroll-grow space-y-6">

      {/* ── Team & Assignees Panel ─────────────────────────────────── */}
      <CaseTeamPanel caseId={caseData.id} isOwner={isOwner} />

      {/* V2 F10: AI Q&A */}
      <CaseQaChat caseId={caseData.id} />

      {/* Add address */}
      <div className="card-cyber">
        <h3 className="card-title">{t('tools:caseDetail.addAddress.title')}</h3>
        <div className="flex gap-3">
          <input
            value={newAddr}
            onChange={(e) => setNewAddr(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && newAddr.trim() && addAddrMut.mutate()}
            placeholder={t('tools:caseDetail.addAddress.addrPh')}
            className="input flex-1"
          />
          <input
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            placeholder={t('tools:caseDetail.addAddress.labelPh')}
            className="input w-36"
          />
          <button
            onClick={() => addAddrMut.mutate()}
            disabled={!newAddr.trim() || addAddrMut.isPending}
            className="btn-secondary"
          >
            {addAddrMut.isPending ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
            {t('tools:caseDetail.addAddress.addBtn')}
          </button>
        </div>
      </div>

      {/* Addresses list */}
      <div>
        <h3 className="card-title">{t('tools:caseDetail.addresses.title', { count: addresses.length })}</h3>
        {addresses.length === 0 ? (
          <p className="text-text-muted text-sm">{t('tools:caseDetail.addresses.empty')}</p>
        ) : (
          <div className="space-y-2">
            {addresses.map((a) => {
              const screened  = screenedIntel[a.address]
              const isLoad_   = loading[a.address]
              const isOpen    = openAddr === a.address
              const sc        = a.risk_score
              return (
                <div key={a.address}
                  className="card overflow-hidden p-0 hover:border-neon-cyan/15 transition-all">
                  <div className="p-4 flex items-center gap-4">
                    {sc >= 0 ? (
                      <div className="text-center min-w-[52px]">
                        <div className="text-display text-xl font-bold"
                          style={{ color: scoreColor(sc), textShadow: `0 0 8px ${scoreColor(sc)}55` }}>
                          {sc}
                        </div>
                        <div className="text-[10px] text-text-muted text-tech">/100</div>
                      </div>
                    ) : (
                      <div className="text-center min-w-[52px] text-text-muted">
                        <ShieldAlert size={20} className="mx-auto" />
                        <div className="text-[10px]">{t('tools:caseDetail.addresses.unscored')}</div>
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-tech text-[11px] text-neon-cyan truncate">{a.address}</div>
                      <div className="flex items-center gap-2 mt-1 text-[11px]">
                        {a.chain && <span className="badge badge-muted uppercase">{a.chain}</span>}
                        {a.label && <span className="text-text-secondary">{a.label}</span>}
                        {a.risk_level && (
                          <span className="text-tech font-bold"
                            style={{ color: scoreColor(sc >= 0 ? sc : 0) }}>
                            {a.risk_level}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button onClick={() => handleScreen(a.address)} disabled={isLoad_}
                        className="btn-ghost py-1 px-2 text-[11px]">
                        {isLoad_ ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
                        {sc >= 0 ? t('tools:caseDetail.addresses.rescan') : t('tools:caseDetail.addresses.screen')}
                      </button>
                      <Link to={`/intel?address=${encodeURIComponent(a.address)}`}
                        className="p-1.5 text-text-muted hover:text-neon-cyan transition-colors" title={t('tools:caseDetail.addresses.fullIntel')}>
                        <ExternalLink size={13} />
                      </Link>
                      {screened && (
                        <button onClick={() => setOpenAddr(isOpen ? null : a.address)}
                          className="p-1.5 text-text-muted hover:text-neon-cyan transition-colors">
                          <Search size={13} />
                        </button>
                      )}
                      <button onClick={() => removeAddrMut.mutate(a.address)}
                        className="p-1.5 text-text-muted hover:text-neon-red transition-colors">
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                  {isOpen && screened && (
                    <div className="border-t border-bg-border p-4 grid grid-cols-1 md:grid-cols-3 gap-6"
                      style={{ background: 'rgba(1,10,19,0.5)' }}>
                      <div className="flex justify-center">
                        <RiskGauge score={screened.risk.score} level={screened.risk.risk_level} size={140} />
                      </div>
                      <div>
                        <CategoryBadges categories={screened.risk.categories} />
                        <div className="mt-4 space-y-1.5 text-[11px]">
                          {[
                            [t('tools:caseDetail.addresses.riskChain'),     screened.intel.chain],
                            [t('tools:caseDetail.addresses.riskBalance'),   `${screened.intel.balance} ${screened.intel.balance_unit}`],
                            [t('tools:caseDetail.addresses.riskTxs'),       screened.intel.tx_count],
                          ].map(([k, v]) => (
                            <div key={k as string} className="flex gap-2">
                              <span className="text-text-muted w-24">{k}:</span>
                              <span className="text-text-primary text-tech">{v}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                      <div>
                        <RiskSignalList signals={screened.risk.signals} compact />
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Notes */}
      <div className="space-y-3">
        <h3 className="card-title flex items-center gap-2">
          <StickyNote size={13} style={{ color: '#FBBF24' }} />
          {t('tools:caseDetail.notes.title', { count: notes.length })}
        </h3>
        <div className="flex gap-3">
          <textarea
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            placeholder={t('tools:caseDetail.notes.placeholder')}
            rows={2}
            className="input flex-1 resize-none"
          />
          <button
            onClick={() => addNoteMut.mutate()}
            disabled={!noteText.trim() || addNoteMut.isPending}
            className="btn-secondary self-start"
          >
            {addNoteMut.isPending ? <Loader2 size={13} className="animate-spin" /> : t('tools:caseDetail.notes.addBtn')}
          </button>
        </div>
        <div className="space-y-2">
          {notes.map((n) => (
            <div key={n.id}
              className="flex gap-3 border border-neon-amber/20 bg-neon-amber/5 rounded-lg p-3">
              <div className="flex-1">
                <div className="text-text-primary text-sm whitespace-pre-wrap">{n.note}</div>
                <div className="text-[10px] text-text-muted mt-1 text-tech">{n.created_at}</div>
              </div>
              <button onClick={() => deleteNoteMut.mutate(n.id)}
                className="text-text-muted hover:text-neon-red self-start transition-colors">
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      </div>

      <CaseBoardsPanel caseId={caseData.id} />
      </div>
    </div>
  )
}

// ── Team & Assignee Panel ─────────────────────────────────────────────────────
function CaseTeamPanel({ caseId, isOwner }: { caseId: string; isOwner: boolean }) {
  const auth = useAuth()
  const qc = useQueryClient()
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [addEmail, setAddEmail] = useState('')
  const [addRole, setAddRole] = useState<'full_access' | 'reviewer'>('full_access')
  const [changingRole, setChangingRole] = useState<string | null>(null)

  const { data: members, isLoading } = useQuery({
    queryKey: ['case-members', caseId],
    queryFn: () => listCaseMembers(caseId),
  })

  const { data: teamData } = useQuery({
    queryKey: ['team-members'],
    queryFn: listTeamMembers,
    enabled: isOwner && showAdd,
  })

  const addMut = useMutation({
    mutationFn: () => addCaseMember(caseId, addEmail, addRole),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['case-members', caseId] })
      setAddEmail(''); setShowAdd(false)
    },
  })

  const roleMut = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: 'full_access' | 'reviewer' }) =>
      updateCaseMemberRole(caseId, userId, role),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['case-members', caseId] })
      setChangingRole(null)
    },
  })

  const removeMut = useMutation({
    mutationFn: (userId: string) => removeCaseMember(caseId, userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['case-members', caseId] }),
  })

  const memberList = members?.members ?? []
  const teamMembers = teamData?.members ?? []
  const assignedEmails = new Set(memberList.map(m => m.email))
  const availableMembers = teamMembers.filter(m => m.is_active && !assignedEmails.has(m.email))

  return (
    <div style={panelStyle}>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Users size={15} style={{ color: '#8B5CF6' }} />
          <span style={{ fontSize: 13, fontWeight: 700, color: 'rgb(var(--text-primary))' }}>
            Team Assignees
          </span>
          <span style={badgeStyle('#8B5CF6')}>{memberList.length} assigned</span>
        </div>
        {expanded ? <ChevronUp size={14} style={{ color: 'rgb(var(--text-muted))' }} /> : <ChevronDown size={14} style={{ color: 'rgb(var(--text-muted))' }} />}
      </button>

      {expanded && (
        <div style={{ marginTop: 12 }}>
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: 16 }}><Loader2 size={16} className="animate-spin" style={{ color: '#8B5CF6' }} /></div>
          ) : (
            <>
              {/* Member list */}
              {memberList.length === 0 ? (
                <p style={{ fontSize: 12, color: 'rgb(var(--text-muted))', textAlign: 'center', padding: 12 }}>
                  No team members assigned to this case yet.
                </p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
                  {memberList.map(m => (
                    <div key={m.user_id} style={{
                      display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px',
                      borderRadius: 8, background: 'rgb(255 255 255 / 0.03)',
                      border: '1px solid rgb(var(--bg-border) / 0.3)',
                    }}>
                      <div style={{
                        width: 28, height: 28, borderRadius: '50%',
                        background: 'linear-gradient(135deg, #8B5CF6, #6366F1)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 11, fontWeight: 700, color: '#fff', flexShrink: 0,
                      }}>
                        {(m.email || '?')[0].toUpperCase()}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: 'rgb(var(--text-primary))' }}>{m.email}</div>
                        <div style={{ fontSize: 10, color: 'rgb(var(--text-muted))' }}>
                          Added {m.added_at ? new Date(m.added_at).toLocaleDateString() : '—'}
                        </div>
                      </div>
                      {/* Role badge / changer */}
                      {isOwner ? (
                        changingRole === m.user_id ? (
                          <div style={{ display: 'flex', gap: 4 }}>
                            <button
                              onClick={() => { roleMut.mutate({ userId: m.user_id, role: 'full_access' }); }}
                              style={{ ...badgeStyle('#34D399'), cursor: 'pointer', border: '1px solid #34D39944' }}
                            >
                              <Shield size={9} style={{ marginRight: 2 }} />Full
                            </button>
                            <button
                              onClick={() => { roleMut.mutate({ userId: m.user_id, role: 'reviewer' }); }}
                              style={{ ...badgeStyle('#60A5FA'), cursor: 'pointer', border: '1px solid #60A5FA44' }}
                            >
                              <Eye size={9} style={{ marginRight: 2 }} />Review
                            </button>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={badgeStyle(m.case_role === 'reviewer' ? '#60A5FA' : '#34D399')}>
                              {m.case_role === 'reviewer' ? (
                                <><Eye size={9} style={{ marginRight: 3, verticalAlign: -1 }} />{t('tools:caseDetail.team.reviewer')}</>
                              ) : (
                                <><Shield size={9} style={{ marginRight: 3, verticalAlign: -1 }} />{t('tools:caseDetail.team.fullAccess')}</>
                              )}
                            </span>
                            <button
                              onClick={() => setChangingRole(m.user_id)}
                              style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgb(var(--text-muted))', padding: 2 }}
                              title={t('tools:caseDetail.team.changeRole')}
                            >
                              <RefreshCw size={11} />
                            </button>
                            <button
                              onClick={() => { if (confirm(t('tools:caseDetail.team.removeConfirm'))) removeMut.mutate(m.user_id) }}
                              style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgb(var(--text-muted))', padding: 2 }}
                              title={t('tools:caseDetail.team.removeFromCase')}
                            >
                              <Trash2 size={11} />
                            </button>
                          </div>
                        )
                      ) : (
                        <span style={badgeStyle(m.case_role === 'reviewer' ? '#60A5FA' : '#34D399')}>
                          {m.case_role === 'reviewer' ? t('tools:caseDetail.team.reviewer') : t('tools:caseDetail.team.fullAccess')}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Add member */}
              {isOwner && (
                showAdd ? (
                  <div style={{ padding: 10, borderRadius: 8, background: 'rgb(255 255 255 / 0.03)', border: '1px solid rgb(var(--bg-border) / 0.4)' }}>
                    <p style={{ fontSize: 11, color: 'rgb(var(--text-muted))', marginBottom: 8 }}>{t('tools:caseDetail.team.selectMember')}</p>
                    {availableMembers.length === 0 ? (
                      <p style={{ fontSize: 11, color: 'rgb(var(--text-muted))' }}>{t('tools:caseDetail.team.allAssigned')}</p>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
                        {availableMembers.map(tm => (
                          <button
                            key={tm.id}
                            onClick={() => setAddEmail(tm.email)}
                            style={{
                              display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px',
                              borderRadius: 6, border: addEmail === tm.email ? '1px solid #8B5CF6' : '1px solid transparent',
                              background: addEmail === tm.email ? 'rgb(139 92 246 / 0.1)' : 'transparent',
                              cursor: 'pointer', textAlign: 'left', color: 'rgb(var(--text-primary))',
                            }}
                          >
                            <span style={{ fontSize: 12 }}>{tm.name || tm.email}</span>
                            <span style={{ fontSize: 10, color: 'rgb(var(--text-muted))' }}>{tm.email}</span>
                          </button>
                        ))}
                      </div>
                    )}
                    {addEmail && (
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 8 }}>
                        <span style={{ fontSize: 11, color: 'rgb(var(--text-muted))' }}>{t('tools:caseDetail.team.role')}</span>
                        <button
                          onClick={() => setAddRole('full_access')}
                          style={badgeStyle(addRole === 'full_access' ? '#34D399' : '#555')}
                        >
                          <Shield size={9} style={{ marginRight: 2 }} />{t('tools:caseDetail.team.fullAccess')}
                        </button>
                        <button
                          onClick={() => setAddRole('reviewer')}
                          style={badgeStyle(addRole === 'reviewer' ? '#60A5FA' : '#555')}
                        >
                          <Eye size={9} style={{ marginRight: 2 }} />{t('tools:caseDetail.team.reviewer')}
                        </button>
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
                      <button
                        onClick={() => addMut.mutate()}
                        disabled={!addEmail || addMut.isPending}
                        className="btn-secondary"
                        style={{ fontSize: 11 }}
                      >
                        {addMut.isPending ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
                        {t('tools:caseDetail.team.assign')}
                      </button>
                      <button onClick={() => { setShowAdd(false); setAddEmail('') }} className="btn-ghost" style={{ fontSize: 11 }}>{t('tools:caseDetail.team.cancel')}</button>
                    </div>
                  </div>
                ) : (
                  <button onClick={() => setShowAdd(true)} className="btn-ghost" style={{ fontSize: 11, width: '100%' }}>
                    <Plus size={11} /> Assign Team Member
                  </button>
                )
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Boards linked to this case ─────────────────────────────────────────────────
function CaseBoardsPanel({ caseId }: { caseId: string }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data: boards = [], isLoading } = useQuery<BoardMeta[]>({
    queryKey: ['boards', 'case', caseId],
    queryFn: () => listBoards('', caseId),
  })

  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')

  const createMut = useMutation({
    mutationFn: () => createBoard(newName.trim(), { case_id: caseId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['boards'] })
      setCreating(false); setNewName('')
    },
  })

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="card-title flex items-center gap-2">
          <LayoutDashboard size={13} style={{ color: '#60A5FA' }} />
          {t('tools:caseDetail.boards.title', { count: boards.length })}
        </h3>
        <button onClick={() => setCreating(!creating)} className="btn-ghost text-xs">
          <Plus size={12} /> {t('tools:caseDetail.boards.newBoard')}
        </button>
      </div>

      {creating && (
        <div className="card-cyber space-y-2 animate-slide-up">
          <input
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder={t('tools:caseDetail.boards.namePh')}
            className="input"
            onKeyDown={e => { if (e.key === 'Enter' && newName.trim()) createMut.mutate() }}
            autoFocus
          />
          <button onClick={() => createMut.mutate()} disabled={!newName.trim() || createMut.isPending}
            className="btn-primary text-xs">
            {createMut.isPending && <Loader2 size={12} className="animate-spin" />}
            {t('tools:caseDetail.boards.createLink')}
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="text-text-muted text-xs py-4"><Loader2 size={13} className="animate-spin inline mr-2" />{t('tools:caseDetail.boards.loading')}</div>
      ) : boards.length === 0 ? (
        <div className="card-cyber text-center py-6">
          <LayoutDashboard size={20} className="mx-auto mb-2 opacity-40" style={{ color: '#60A5FA' }} />
          <p className="text-text-muted text-xs">{t('tools:caseDetail.boards.empty')}</p>
          <p className="text-text-muted text-[10px] mt-1">{t('tools:caseDetail.boards.emptyHint')}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {boards.map(b => (
            <div key={b.id} className="card-cyber group cursor-pointer hover:border-neon-cyan/40 transition-colors"
              onClick={() => navigate(`/boards/${b.id}`)}>
              <div className="flex items-start justify-between gap-2">
                <h4 className="text-xs font-bold text-text-primary truncate">{b.name}</h4>
                <ChevronRight size={13} className="text-text-muted shrink-0 group-hover:text-neon-cyan" />
              </div>
              {b.description && <p className="text-[10px] text-text-secondary mt-1 line-clamp-2">{b.description}</p>}
              <div className="flex items-center gap-3 mt-2 text-[10px] text-text-muted">
                <span>{t('tools:caseDetail.boards.pins', { count: b.node_count ?? 0 })}</span>
                <span>{t('tools:caseDetail.boards.links', { count: b.edge_count ?? 0 })}</span>
                {(b.open_comments ?? 0) > 0 && <span className="text-amber-400">{t('tools:caseDetail.boards.comments', { count: b.open_comments })}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
