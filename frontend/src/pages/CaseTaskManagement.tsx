import { useState, useRef, useEffect, useMemo } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft, Loader2, AlertCircle, Users, Shield, Eye, Plus, Trash2,
  Clock, MessageSquare, Package, Send, CheckCircle2, XCircle,
  AlertTriangle, Calendar, RefreshCw, ChevronDown, ChevronUp,
  Filter, Search, UserPlus, ShieldCheck, BarChart3, Activity,
  FileText, ChevronRight, MoreVertical,
} from 'lucide-react'
import {
  getCase,
  listCaseMembers, addCaseMember, updateCaseMemberRole, removeCaseMember,
  listCaseTasks, createCaseTask, updateCaseTask, deleteCaseTask,
  listTaskMessages, sendTaskMessage,
  listTaskDeliverables, submitDeliverable, reviewDeliverable,
  listTeamMembers,
  type CaseMember, type CaseTask, type TaskMessage, type TaskDeliverable, type TeamMember,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { Case } from '../types'

// ── Style helpers ─────────────────────────────────────────────────────────────

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
const badge = (color: string): React.CSSProperties => ({
  fontSize: 10, padding: '2px 8px', borderRadius: 6, fontWeight: 600,
  background: `${color}22`, color, border: `1px solid ${color}44`,
  display: 'inline-flex', alignItems: 'center', gap: 3,
})

export default function CaseTaskManagement() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const auth = useAuth()
  const { t } = useTranslation()

  const [selectedTask, setSelectedTask] = useState<CaseTask | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [filterStatus, setFilterStatus] = useState('')
  const [filterPriority, setFilterPriority] = useState('')
  const [filterAssignee, setFilterAssignee] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [showTeamPanel, setShowTeamPanel] = useState(true)

  const { data: caseData, isLoading: caseLoading } = useQuery<Case>({
    queryKey: ['case', id],
    queryFn: () => getCase(id!),
    enabled: !!id,
  })

  const { data: membersData } = useQuery({
    queryKey: ['case-members', id],
    queryFn: () => listCaseMembers(id!),
    enabled: !!id,
  })

  const { data: tasksData, isLoading: tasksLoading } = useQuery({
    queryKey: ['case-tasks', id],
    queryFn: () => listCaseTasks(id!),
    enabled: !!id,
    refetchInterval: 10000,
  })

  const { data: teamData } = useQuery({
    queryKey: ['team-members'],
    queryFn: listTeamMembers,
  })

  const isOwner = auth.user?.id === caseData?.owner_id || (auth.user?.role || '') === 'admin'
  const tasks = tasksData?.tasks ?? []
  const members = membersData?.members ?? []
  const teamMembers = teamData?.members ?? []

  const filteredTasks = useMemo(() => {
    return tasks.filter(t => {
      if (filterStatus && t.status !== filterStatus) return false
      if (filterPriority && t.priority !== filterPriority) return false
      if (filterAssignee && t.assigned_to !== filterAssignee) return false
      if (searchQuery) {
        const q = searchQuery.toLowerCase()
        if (!t.title.toLowerCase().includes(q) && !t.description.toLowerCase().includes(q)) return false
      }
      return true
    })
  }, [tasks, filterStatus, filterPriority, filterAssignee, searchQuery])

  const stats = useMemo(() => ({
    total: tasks.length,
    open: tasks.filter(t => t.status === 'open').length,
    inProgress: tasks.filter(t => t.status === 'in_progress').length,
    done: tasks.filter(t => t.status === 'done' || t.status === 'closed').length,
    overdue: tasks.filter(t => t.due_date && new Date(t.due_date) < new Date() && t.status !== 'done' && t.status !== 'closed').length,
  }), [tasks])

  if (caseLoading) return (
    <div className="flex justify-center items-center py-20">
      <Loader2 className="animate-spin" size={28} style={{ color: '#ff5a6e' }} />
    </div>
  )

  if (!caseData) return (
    <div className="p-6 flex items-center gap-2 text-neon-red">
      <AlertCircle size={15} /> {t('tools:caseTask.caseNotFound')}
    </div>
  )

  return (
    <div className="noscroll-page flex flex-col h-full">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div style={{
        padding: '16px 24px',
        borderBottom: '1px solid rgb(var(--bg-border) / 0.5)',
        background: 'rgb(var(--bg-card) / 0.4)',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <button onClick={() => navigate(`/cases/${id}`)}
            style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'none', border: 'none', cursor: 'pointer', color: 'rgb(var(--text-muted))', fontSize: 12 }}>
            <ArrowLeft size={12} /> {t('tools:caseTask.backToCase')}
          </button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 700, color: 'rgb(var(--text-primary))', margin: 0 }}>
              {caseData.name} — {t('tools:caseTask.title')}
            </h1>
            <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 11, color: 'rgb(var(--text-muted))' }}>
              <span style={badge(statusColor('open'))}>{t('tools:caseTask.stats.open', { count: stats.open })}</span>
              <span style={badge(statusColor('in_progress'))}>{t('tools:caseTask.stats.inProgress', { count: stats.inProgress })}</span>
              <span style={badge(statusColor('done'))}>{t('tools:caseTask.stats.done', { count: stats.done })}</span>
              {stats.overdue > 0 && <span style={badge('#F87171')}>{t('tools:caseTask.stats.overdue', { count: stats.overdue })}</span>}
              <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                <Users size={11} /> {t('tools:caseTask.stats.members', { count: members.length })}
              </span>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => navigate(`/cases/${id}/audit`)}
              className="btn-ghost" style={{ fontSize: 12 }}>
              <FileText size={13} /> {t('tools:caseTask.auditLog')}
            </button>
            {isOwner && (
              <button onClick={() => setShowCreate(true)}
                className="btn-secondary" style={{ fontSize: 12 }}>
                <Plus size={13} /> {t('tools:caseTask.newTask')}
              </button>
            )}
          </div>
        </div>
        {/* Nav tabs */}
        <div style={{ display: 'flex', gap: 4, marginTop: 12 }}>
          <Link to={`/cases/${id}/tasks`} style={{
            padding: '6px 16px', fontSize: 12, fontWeight: 600, borderRadius: '6px 6px 0 0',
            background: 'rgb(var(--bg-card))', color: 'rgb(var(--text-primary))',
            borderBottom: '2px solid #F59E0B', textDecoration: 'none',
          }}>
            <Clock size={12} style={{ marginRight: 4, verticalAlign: -1 }} /> {t('tools:caseTask.tabs.tasks')}
          </Link>
          <Link to={`/cases/${id}/audit`} style={{
            padding: '6px 16px', fontSize: 12, fontWeight: 600, borderRadius: '6px 6px 0 0',
            background: 'transparent', color: 'rgb(var(--text-muted))',
            borderBottom: '2px solid transparent', textDecoration: 'none',
          }}>
            <FileText size={12} style={{ marginRight: 4, verticalAlign: -1 }} /> {t('tools:caseTask.tabs.audit')}
          </Link>
        </div>
      </div>

      {/* ── Main Content ───────────────────────────────────────────────── */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Left: Team Panel */}
        {showTeamPanel && (
          <div style={{
            width: 260, flexShrink: 0,
            borderRight: '1px solid rgb(var(--bg-border) / 0.5)',
            overflowY: 'auto', padding: 16,
            background: 'rgb(var(--bg-card) / 0.2)',
          }}>
            <TeamSidebar
              caseId={id!}
              isOwner={isOwner}
              members={members}
              teamMembers={teamMembers}
            />
          </div>
        )}

        {/* Center: Task List */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Filter bar */}
          <div style={{
            padding: '10px 16px',
            borderBottom: '1px solid rgb(var(--bg-border) / 0.3)',
            display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
          }}>
            <div style={{ position: 'relative', flex: '0 0 200px' }}>
              <Search size={12} style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: 'rgb(var(--text-muted))' }} />
              <input
                value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                placeholder={t('tools:caseTask.filters.searchPh')}
                className="input" style={{ paddingLeft: 28, fontSize: 12, width: '100%' }}
              />
            </div>
            <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
              className="input" style={{ fontSize: 11, width: 120 }}>
              <option value="">{t('tools:caseTask.filters.allStatus')}</option>
              <option value="open">{t('tools:caseTask.status.open')}</option>
              <option value="in_progress">{t('tools:caseTask.status.in_progress')}</option>
              <option value="done">{t('tools:caseTask.status.done')}</option>
              <option value="closed">{t('tools:caseTask.status.closed')}</option>
            </select>
            <select value={filterPriority} onChange={e => setFilterPriority(e.target.value)}
              className="input" style={{ fontSize: 11, width: 120 }}>
              <option value="">{t('tools:caseTask.filters.allPriority')}</option>
              <option value="urgent">{t('tools:caseTask.priority.urgent')}</option>
              <option value="high">{t('tools:caseTask.priority.high')}</option>
              <option value="medium">{t('tools:caseTask.priority.medium')}</option>
              <option value="low">{t('tools:caseTask.priority.low')}</option>
            </select>
            <select value={filterAssignee} onChange={e => setFilterAssignee(e.target.value)}
              className="input" style={{ fontSize: 11, width: 140 }}>
              <option value="">{t('tools:caseTask.filters.allAssignees')}</option>
              {members.map(m => (
                <option key={m.user_id} value={m.user_id}>{m.email}</option>
              ))}
            </select>
            {(filterStatus || filterPriority || filterAssignee || searchQuery) && (
              <button onClick={() => { setFilterStatus(''); setFilterPriority(''); setFilterAssignee(''); setSearchQuery('') }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgb(var(--text-muted))', fontSize: 11 }}>
                {t('tools:caseTask.filters.clear')}
              </button>
            )}
            <button onClick={() => setShowTeamPanel(!showTeamPanel)}
              style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: 'rgb(var(--text-muted))', fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
              <Users size={12} /> {showTeamPanel ? 'Hide' : 'Show'} Team
            </button>
          </div>

          {/* Task list */}
          <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
            {tasksLoading ? (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <Loader2 size={20} className="animate-spin" style={{ color: '#F59E0B' }} />
              </div>
            ) : filteredTasks.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <Clock size={32} style={{ color: 'rgb(var(--text-muted))', opacity: 0.3, marginBottom: 12 }} />
                <p style={{ fontSize: 13, color: 'rgb(var(--text-muted))' }}>
                  {tasks.length === 0 ? 'No tasks assigned yet.' : 'No tasks match your filters.'}
                </p>
                {isOwner && tasks.length === 0 && (
                  <button onClick={() => setShowCreate(true)} className="btn-secondary" style={{ marginTop: 12, fontSize: 12 }}>
                    <Plus size={13} /> Create First Task
                  </button>
                )}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {filteredTasks.map(task => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    isSelected={selectedTask?.id === task.id}
                    onClick={() => setSelectedTask(selectedTask?.id === task.id ? null : task)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right: Task Detail Panel */}
        {selectedTask && (
          <div style={{
            width: 420, flexShrink: 0,
            borderLeft: '1px solid rgb(var(--bg-border) / 0.5)',
            overflowY: 'auto',
            background: 'rgb(var(--bg-card) / 0.3)',
          }}>
            <TaskDetailPanel
              caseId={id!}
              task={selectedTask}
              isOwner={isOwner}
              onClose={() => setSelectedTask(null)}
              onUpdate={(updated) => {
                setSelectedTask(prev => prev ? { ...prev, ...updated } : null)
                qc.invalidateQueries({ queryKey: ['case-tasks', id] })
              }}
            />
          </div>
        )}
      </div>

      {/* Create Task Modal */}
      {showCreate && (
        <CreateTaskModal
          caseId={id!}
          members={members}
          teamMembers={teamMembers}
          isOwner={isOwner}
          onClose={() => setShowCreate(false)}
        />
      )}
    </div>
  )
}

// ── Team Sidebar ──────────────────────────────────────────────────────────────

function TeamSidebar({ caseId, isOwner, members, teamMembers }: {
  caseId: string; isOwner: boolean
  members: CaseMember[]; teamMembers: TeamMember[]
}) {
  const qc = useQueryClient()
  const { t } = useTranslation()
  const [showAdd, setShowAdd] = useState(false)
  const [addEmail, setAddEmail] = useState('')
  const [addRole, setAddRole] = useState<'full_access' | 'reviewer'>('full_access')

  const assignedEmails = new Set(members.map(m => m.email))
  const available = teamMembers.filter(m => m.is_active && !assignedEmails.has(m.email))

  const addMut = useMutation({
    mutationFn: () => addCaseMember(caseId, addEmail, addRole),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['case-members', caseId] }); setAddEmail(''); setShowAdd(false) },
  })
  const removeMut = useMutation({
    mutationFn: (userId: string) => removeCaseMember(caseId, userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['case-members', caseId] }),
  })
  const roleMut = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: 'full_access' | 'reviewer' }) => updateCaseMemberRole(caseId, userId, role),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['case-members', caseId] }),
  })

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h3 style={{ fontSize: 12, fontWeight: 700, color: 'rgb(var(--text-primary))', margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
          <Users size={13} style={{ color: '#8B5CF6' }} /> {t('tools:caseDetail.team.title', { count: members.length })}
        </h3>
        {isOwner && (
          <button onClick={() => setShowAdd(!showAdd)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#8B5CF6', padding: 2 }}>
            <UserPlus size={13} />
          </button>
        )}
      </div>

      {showAdd && isOwner && (
        <div style={{ padding: 10, borderRadius: 8, background: 'rgb(255 255 255 / 0.03)', border: '1px solid rgb(var(--bg-border) / 0.4)', marginBottom: 10 }}>
          {available.length === 0 ? (
            <p style={{ fontSize: 11, color: 'rgb(var(--text-muted))' }}>{t('tools:caseDetail.team.allAssignedShort')}</p>
          ) : (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginBottom: 8, maxHeight: 150, overflowY: 'auto' }}>
                {available.map(tm => (
                  <button key={tm.id} onClick={() => setAddEmail(tm.email)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6, padding: '5px 8px', borderRadius: 6,
                      border: addEmail === tm.email ? '1px solid #8B5CF6' : '1px solid transparent',
                      background: addEmail === tm.email ? 'rgb(139 92 246 / 0.1)' : 'transparent',
                      cursor: 'pointer', textAlign: 'left', color: 'rgb(var(--text-primary))', fontSize: 11,
                    }}>
                    {tm.name || tm.email}
                  </button>
                ))}
              </div>
              {addEmail && (
                <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
                  <button onClick={() => setAddRole('full_access')} style={badge(addRole === 'full_access' ? '#34D399' : '#555')}>
                    <Shield size={9} /> {t('tools:caseDetail.team.full')}
                  </button>
                  <button onClick={() => setAddRole('reviewer')} style={badge(addRole === 'reviewer' ? '#60A5FA' : '#555')}>
                    <Eye size={9} /> {t('tools:caseDetail.team.rev')}
                  </button>
                </div>
              )}
              <div style={{ display: 'flex', gap: 4 }}>
                <button onClick={() => addMut.mutate()} disabled={!addEmail || addMut.isPending}
                  className="btn-secondary" style={{ fontSize: 10, flex: 1 }}>
                  {addMut.isPending ? <Loader2 size={10} className="animate-spin" /> : <Plus size={10} />} {t('tools:caseDetail.team.assign')}
                </button>
                <button onClick={() => { setShowAdd(false); setAddEmail('') }} className="btn-ghost" style={{ fontSize: 10 }}>{t('tools:caseDetail.team.cancel')}</button>
              </div>
            </>
          )}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {members.map(m => (
          <div key={m.user_id} style={{
            padding: '8px 10px', borderRadius: 8,
            background: 'rgb(255 255 255 / 0.03)',
            border: '1px solid rgb(var(--bg-border) / 0.3)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%',
                background: 'linear-gradient(135deg, #8B5CF6, #6366F1)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 11, fontWeight: 700, color: '#fff', flexShrink: 0,
              }}>
                {(m.email || '?')[0].toUpperCase()}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'rgb(var(--text-primary))', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {m.email}
                </div>
                <div style={{ fontSize: 9, color: 'rgb(var(--text-muted))' }}>
                  {m.added_at ? new Date(m.added_at).toLocaleDateString() : '—'}
                </div>
              </div>
              <span style={badge(m.case_role === 'reviewer' ? '#60A5FA' : '#34D399')}>
                {m.case_role === 'reviewer' ? <><Eye size={9} /> {t('tools:caseDetail.team.rev')}</> : <><Shield size={9} /> {t('tools:caseDetail.team.full')}</>}
              </span>
            </div>
            {isOwner && (
              <div style={{ display: 'flex', gap: 4, marginTop: 6, justifyContent: 'flex-end' }}>
                <button onClick={() => roleMut.mutate({ userId: m.user_id, role: m.case_role === 'reviewer' ? 'full_access' : 'reviewer' })}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgb(var(--text-muted))', padding: 2 }} title={t('tools:caseDetail.team.toggleRole')}>
                  <RefreshCw size={10} />
                </button>
                <button onClick={() => { if (confirm(t('tools:caseDetail.team.removeConfirm'))) removeMut.mutate(m.user_id) }}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgb(var(--text-muted))', padding: 2 }} title={t('tools:caseDetail.team.remove')}>
                  <Trash2 size={10} />
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Task Card ─────────────────────────────────────────────────────────────────

function TaskCard({ task, isSelected, onClick }: { task: CaseTask; isSelected: boolean; onClick: () => void }) {
  const { t } = useTranslation()
  const isOverdue = task.due_date && new Date(task.due_date) < new Date() && task.status !== 'done' && task.status !== 'closed'

  return (
    <div onClick={onClick} style={{
      padding: '12px 16px', borderRadius: 10, cursor: 'pointer',
      background: isSelected ? 'rgb(var(--bg-card) / 0.8)' : 'rgb(255 255 255 / 0.02)',
      border: isSelected ? '1px solid #F59E0B55' : '1px solid rgb(var(--bg-border) / 0.3)',
      transition: 'all 0.15s',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={badge(priorityColor(task.priority))}>{task.priority}</span>
        <span style={badge(statusColor(task.status))}>{task.status.replace('_', ' ')}</span>
        <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: 'rgb(var(--text-primary))' }}>{task.title}</span>
        {isOverdue && <span style={badge('#F87171')}><AlertTriangle size={9} /> {t('tools:caseTask.taskCard.overdue')}</span>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 11, color: 'rgb(var(--text-muted))' }}>
        <span>{t('tools:caseTask.taskCard.assigned')} <span style={{ color: 'rgb(var(--text-secondary))' }}>{task.assignee_name || task.assigned_to}</span></span>
        {task.due_date && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            <Calendar size={10} /> {new Date(task.due_date).toLocaleDateString()}
          </span>
        )}
        {task.description && (
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 200 }}>
            {task.description}
          </span>
        )}
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 3 }}>
          <ChevronRight size={12} style={{ color: isSelected ? '#F59E0B' : 'rgb(var(--text-muted))' }} />
        </span>
      </div>
    </div>
  )
}

// ── Task Detail Panel ─────────────────────────────────────────────────────────

function TaskDetailPanel({ caseId, task, isOwner, onClose, onUpdate }: {
  caseId: string; task: CaseTask; isOwner: boolean; onClose: () => void
  onUpdate: (updates: Partial<CaseTask>) => void
}) {
  const auth = useAuth()
  const qc = useQueryClient()
  const { t } = useTranslation()
  const [tab, setTab] = useState<'chat' | 'deliverables'>('chat')
  const [chatMsg, setChatMsg] = useState('')
  const chatEndRef = useRef<HTMLDivElement>(null)

  const [showDeliverForm, setShowDeliverForm] = useState(false)
  const [delTitle, setDelTitle] = useState('')
  const [delDesc, setDelDesc] = useState('')
  const [delContent, setDelContent] = useState('')
  const [reviewNote, setReviewNote] = useState('')

  const { data: messagesData } = useQuery({
    queryKey: ['task-messages', caseId, task.id],
    queryFn: () => listTaskMessages(caseId, task.id),
    refetchInterval: 5000,
  })
  const { data: deliverablesData } = useQuery({
    queryKey: ['task-deliverables', caseId, task.id],
    queryFn: () => listTaskDeliverables(caseId, task.id),
    refetchInterval: 10000,
  })

  const sendMut = useMutation({
    mutationFn: () => sendTaskMessage(caseId, task.id, chatMsg),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['task-messages', caseId, task.id] }); setChatMsg('') },
  })
  const statusMut = useMutation({
    mutationFn: (status: string) => updateCaseTask(caseId, task.id, { status }),
    onSuccess: (_, status) => onUpdate({ status: status as CaseTask['status'] }),
  })
  const deleteMut = useMutation({
    mutationFn: () => deleteCaseTask(caseId, task.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['case-tasks', caseId] }); onClose() },
  })
  const deliverMut = useMutation({
    mutationFn: () => submitDeliverable(caseId, task.id, { title: delTitle, description: delDesc, content: delContent }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['task-deliverables', caseId, task.id] }); setDelTitle(''); setDelDesc(''); setDelContent(''); setShowDeliverForm(false) },
  })
  const reviewMut = useMutation({
    mutationFn: ({ delId, status }: { delId: string; status: 'approved' | 'rejected' | 'revision_requested' }) =>
      reviewDeliverable(caseId, task.id, delId, { status, review_note: reviewNote }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['task-deliverables', caseId, task.id] }); setReviewNote('') },
  })

  const messages = messagesData?.messages ?? []
  const deliverables = deliverablesData?.deliverables ?? []
  const isAssignee = auth.user?.id === task.assigned_to
  const canEdit = isOwner || isAssignee

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages.length])

  const tabBtn = (active: boolean): React.CSSProperties => ({
    padding: '6px 14px', fontSize: 11, fontWeight: 600, borderRadius: '6px 6px 0 0',
    border: 'none', cursor: 'pointer',
    background: active ? 'rgb(var(--bg-card))' : 'transparent',
    color: active ? 'rgb(var(--text-primary))' : 'rgb(var(--text-muted))',
    borderBottom: active ? '2px solid #F59E0B' : '2px solid transparent',
  })

  return (
    <div style={{ padding: 16 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'start', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: 'rgb(var(--text-primary))', margin: 0 }}>{task.title}</h3>
          <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
            <span style={badge(priorityColor(task.priority))}>{task.priority}</span>
            <span style={badge(statusColor(task.status))}>{task.status.replace('_', ' ')}</span>
          </div>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgb(var(--text-muted))' }}>
          <XCircle size={16} />
        </button>
      </div>

      {/* Meta */}
      <div style={{ fontSize: 11, color: 'rgb(var(--text-muted))', display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12, padding: '8px 10px', borderRadius: 8, background: 'rgb(255 255 255 / 0.02)' }}>
        <div>{t('tools:caseTask.detail.assignedTo')} <span style={{ color: 'rgb(var(--text-secondary))' }}>{task.assignee_name || task.assigned_to}</span></div>
        <div>{t('tools:caseTask.detail.createdBy')} <span style={{ color: 'rgb(var(--text-secondary))' }}>{task.assigner_name || task.assigned_by}</span></div>
        {task.due_date && <div>{t('tools:caseTask.detail.due')} <span style={{ color: 'rgb(var(--text-secondary))' }}>{new Date(task.due_date).toLocaleDateString()}</span></div>}
        <div>{t('tools:caseTask.detail.created')} <span style={{ color: 'rgb(var(--text-secondary))' }}>{new Date(task.created_at).toLocaleString()}</span></div>
      </div>

      {/* Status controls */}
      {canEdit && (
        <div style={{ display: 'flex', gap: 4, marginBottom: 12, flexWrap: 'wrap' }}>
          {['open', 'in_progress', 'done', 'closed'].map(s => (
            <button key={s} onClick={() => statusMut.mutate(s)}
              style={{
                ...badge(statusColor(s)), cursor: 'pointer',
                opacity: task.status === s ? 1 : 0.5,
                outline: task.status === s ? `2px solid ${statusColor(s)}` : 'none',
                outlineOffset: 1,
              }}>
              {s.replace('_', ' ')}
            </button>
          ))}
          {isOwner && (
            <button onClick={() => { if (confirm(t('tools:caseTask.detail.deleteConfirm'))) deleteMut.mutate() }}
              style={{ ...badge('#F87171'), cursor: 'pointer', marginLeft: 'auto' }}>
              <Trash2 size={9} /> {t('tools:caseTask.detail.delete')}
            </button>
          )}
        </div>
      )}

      {task.description && (
        <p style={{ fontSize: 12, color: 'rgb(var(--text-secondary))', marginBottom: 12, lineHeight: 1.5, padding: '8px 10px', borderRadius: 8, background: 'rgb(255 255 255 / 0.02)' }}>
          {task.description}
        </p>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 0 }}>
        <button style={tabBtn(tab === 'chat')} onClick={() => setTab('chat')}>
          <MessageSquare size={10} style={{ marginRight: 4, verticalAlign: -1 }} /> {t('tools:caseTask.detail.chat')}
        </button>
        <button style={tabBtn(tab === 'deliverables')} onClick={() => setTab('deliverables')}>
          <Package size={10} style={{ marginRight: 4, verticalAlign: -1 }} /> {t('tools:caseTask.detail.deliverables', { count: deliverables.length })}
        </button>
      </div>

      <div style={{ background: 'rgb(var(--bg-card) / 0.4)', borderRadius: '0 8px 8px 8px', padding: 12, border: '1px solid rgb(var(--bg-border) / 0.3)' }}>
        {tab === 'chat' ? (
          <>
            <div style={{ maxHeight: 300, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 8 }}>
              {messages.length === 0 ? (
                <p style={{ fontSize: 11, color: 'rgb(var(--text-muted))', textAlign: 'center', padding: 20 }}>
                  {t('tools:caseTask.detail.noMessages')}
                </p>
              ) : (
                messages.map(msg => {
                  const isMe = msg.user_id === auth.user?.id
                  return (
                    <div key={msg.id} style={{ display: 'flex', flexDirection: 'column', alignItems: isMe ? 'flex-end' : 'flex-start' }}>
                      <div style={{
                        maxWidth: '85%', padding: '8px 12px', borderRadius: 10,
                        background: isMe ? 'rgb(139 92 246 / 0.15)' : 'rgb(255 255 255 / 0.05)',
                        border: `1px solid ${isMe ? 'rgb(139 92 246 / 0.3)' : 'rgb(var(--bg-border) / 0.3)'}`,
                      }}>
                        <div style={{ fontSize: 10, color: isMe ? '#A78BFA' : 'rgb(var(--text-muted))', marginBottom: 2 }}>
                          {msg.user_name || 'Unknown'}
                        </div>
                        <div style={{ fontSize: 12, color: 'rgb(var(--text-primary))', lineHeight: 1.4 }}>{msg.message}</div>
                      </div>
                      <span style={{ fontSize: 9, color: 'rgb(var(--text-muted))', marginTop: 2, padding: '0 4px' }}>
                        {new Date(msg.created_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                  )
                })
              )}
              <div ref={chatEndRef} />
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <input className="input" value={chatMsg} onChange={e => setChatMsg(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && chatMsg.trim()) sendMut.mutate() }}
                placeholder={t('tools:caseTask.detail.typeMsgPh')} style={{ flex: 1, fontSize: 12 }} />
              <button onClick={() => sendMut.mutate()} disabled={!chatMsg.trim() || sendMut.isPending}
                className="btn-secondary" style={{ padding: '6px 10px' }}>
                {sendMut.isPending ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
              </button>
            </div>
          </>
        ) : (
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 8 }}>
              {deliverables.length === 0 ? (
                <p style={{ fontSize: 11, color: 'rgb(var(--text-muted))', textAlign: 'center', padding: 16 }}>
                  {t('tools:caseTask.detail.noDeliverables')}
                </p>
              ) : (
                deliverables.map(del => (
                  <div key={del.id} style={{
                    padding: 10, borderRadius: 8,
                    background: 'rgb(255 255 255 / 0.03)',
                    border: '1px solid rgb(var(--bg-border) / 0.3)',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'rgb(var(--text-primary))', flex: 1 }}>{del.title}</span>
                      <span style={badge(deliverableStatusColor(del.status))}>{del.status.replace('_', ' ')}</span>
                    </div>
                    {del.description && <p style={{ fontSize: 11, color: 'rgb(var(--text-secondary))', margin: '2px 0' }}>{del.description}</p>}
                    {del.content && (
                      <div style={{ marginTop: 6, padding: 8, borderRadius: 6, background: 'rgb(0 0 0 / 0.2)', fontSize: 11, color: 'rgb(var(--text-secondary))', whiteSpace: 'pre-wrap', maxHeight: 100, overflowY: 'auto' }}>
                        {del.content}
                      </div>
                    )}
                    {del.review_note && (
                      <div style={{ marginTop: 6, padding: '4px 8px', borderRadius: 4, background: 'rgb(var(--bg-border) / 0.2)', fontSize: 10, color: 'rgb(var(--text-muted))' }}>
                        {t('tools:caseTask.detail.review')} {del.review_note}
                      </div>
                    )}
                    {isOwner && del.status === 'submitted' && (
                      <div style={{ marginTop: 8, display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
                        <input className="input" placeholder={t('tools:caseTask.detail.reviewNotePh')} value={reviewNote} onChange={e => setReviewNote(e.target.value)}
                          style={{ flex: 1, fontSize: 10, padding: '4px 8px' }} />
                        <button onClick={() => reviewMut.mutate({ delId: del.id, status: 'approved' })}
                          style={{ ...badge('#34D399'), cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 3 }}>
                          <CheckCircle2 size={10} /> {t('tools:caseTask.detail.approve')}
                        </button>
                        <button onClick={() => reviewMut.mutate({ delId: del.id, status: 'revision_requested' })}
                          style={{ ...badge('#FB923C'), cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 3 }}>
                          <AlertTriangle size={10} /> {t('tools:caseTask.detail.revise')}
                        </button>
                        <button onClick={() => reviewMut.mutate({ delId: del.id, status: 'rejected' })}
                          style={{ ...badge('#F87171'), cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 3 }}>
                          <XCircle size={10} /> {t('tools:caseTask.detail.reject')}
                        </button>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
            {canEdit && (
              showDeliverForm ? (
                <div style={{ padding: 10, borderRadius: 8, background: 'rgb(255 255 255 / 0.03)', border: '1px solid rgb(var(--bg-border) / 0.4)' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <input className="input" placeholder={t('tools:caseTask.detail.titlePh')} value={delTitle} onChange={e => setDelTitle(e.target.value)} style={{ fontSize: 11 }} />
                    <input className="input" placeholder={t('tools:caseTask.detail.descPh')} value={delDesc} onChange={e => setDelDesc(e.target.value)} style={{ fontSize: 11 }} />
                    <textarea className="input" placeholder={t('tools:caseTask.detail.contentPh')} value={delContent} onChange={e => setDelContent(e.target.value)} rows={3} style={{ fontSize: 11, resize: 'vertical' }} />
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button onClick={() => deliverMut.mutate()} disabled={!delTitle.trim() || deliverMut.isPending}
                        className="btn-secondary" style={{ fontSize: 11 }}>
                        {deliverMut.isPending ? <Loader2 size={11} className="animate-spin" /> : <Package size={11} />} {t('tools:caseTask.detail.submit')}
                      </button>
                      <button onClick={() => setShowDeliverForm(false)} className="btn-ghost" style={{ fontSize: 11 }}>{t('tools:caseTask.detail.cancel')}</button>
                    </div>
                  </div>
                </div>
              ) : (
                <button onClick={() => setShowDeliverForm(true)} className="btn-ghost" style={{ fontSize: 11, width: '100%' }}>
                  <Package size={11} /> {t('tools:caseTask.detail.submitDeliverable')}
                </button>
              )
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── Create Task Modal ─────────────────────────────────────────────────────────

function CreateTaskModal({ caseId, members, teamMembers, isOwner, onClose }: {
  caseId: string; members: CaseMember[]; teamMembers: TeamMember[]; isOwner: boolean; onClose: () => void
}) {
  const qc = useQueryClient()
  const { t } = useTranslation()
  const [title, setTitle] = useState('')
  const [desc, setDesc] = useState('')
  const [assignee, setAssignee] = useState('')
  const [priority, setPriority] = useState('medium')
  const [dueDate, setDueDate] = useState('')

  const assignableMembers = isOwner
    ? teamMembers.filter(m => m.is_active && members.some(cm => cm.user_id === m.id))
    : members.map(m => ({ id: m.user_id, email: m.email, name: m.email } as TeamMember))

  const createMut = useMutation({
    mutationFn: () => createCaseTask(caseId, { title, description: desc, assigned_to: assignee, priority, due_date: dueDate }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['case-tasks', caseId] }); onClose() },
  })

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'rgb(0 0 0 / 0.6)', backdropFilter: 'blur(4px)',
    }} onClick={onClose}>
      <div style={{
        width: 480, maxHeight: '80vh', overflowY: 'auto',
        padding: 24, borderRadius: 16,
        background: 'rgb(var(--bg-card, 18 22 30))',
        border: '1px solid rgb(var(--bg-border, 40 44 55) / 0.6)',
        boxShadow: '0 24px 64px rgb(0 0 0 / 0.5)',
      }} onClick={e => e.stopPropagation()}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: 'rgb(var(--text-primary))', margin: '0 0 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <Plus size={16} style={{ color: '#F59E0B' }} /> {t('tools:caseTask.create.title')}
        </h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <label style={{ fontSize: 11, color: 'rgb(var(--text-muted))', marginBottom: 4, display: 'block' }}>{t('tools:caseTask.create.titleLabel')}</label>
            <input className="input" value={title} onChange={e => setTitle(e.target.value)} placeholder={t('tools:caseTask.create.taskTitlePh')} style={{ fontSize: 13 }} />
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'rgb(var(--text-muted))', marginBottom: 4, display: 'block' }}>{t('tools:caseTask.create.descLabel')}</label>
            <textarea className="input" value={desc} onChange={e => setDesc(e.target.value)} placeholder={t('tools:caseTask.create.taskDescPh')} rows={3} style={{ fontSize: 13, resize: 'vertical' }} />
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 11, color: 'rgb(var(--text-muted))', marginBottom: 4, display: 'block' }}>{t('tools:caseTask.create.assigneeLabel')}</label>
              <select className="input" value={assignee} onChange={e => setAssignee(e.target.value)} style={{ fontSize: 12 }}>
                <option value="">{t('tools:caseTask.create.selectAssignee')}</option>
                {assignableMembers.map(m => (
                  <option key={m.id} value={m.id}>{m.name || m.email}</option>
                ))}
              </select>
            </div>
            <div style={{ width: 130 }}>
              <label style={{ fontSize: 11, color: 'rgb(var(--text-muted))', marginBottom: 4, display: 'block' }}>{t('tools:caseTask.create.priorityLabel')}</label>
              <select className="input" value={priority} onChange={e => setPriority(e.target.value)} style={{ fontSize: 12 }}>
                <option value="low">{t('tools:caseTask.priority.low')}</option>
                <option value="medium">{t('tools:caseTask.priority.medium')}</option>
                <option value="high">{t('tools:caseTask.priority.high')}</option>
                <option value="urgent">{t('tools:caseTask.priority.urgent')}</option>
              </select>
            </div>
          </div>
          <div>
            <label style={{ fontSize: 11, color: 'rgb(var(--text-muted))', marginBottom: 4, display: 'block' }}>{t('tools:caseTask.create.dueDateLabel')}</label>
            <input type="date" className="input" value={dueDate} onChange={e => setDueDate(e.target.value)} style={{ fontSize: 12 }} />
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button onClick={() => createMut.mutate()} disabled={!title.trim() || !assignee || createMut.isPending}
              className="btn-secondary" style={{ flex: 1 }}>
              {createMut.isPending ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} {t('tools:caseTask.create.createBtn')}
            </button>
            <button onClick={onClose} className="btn-ghost">{t('tools:caseTask.create.cancel')}</button>
          </div>
        </div>
      </div>
    </div>
  )
}
