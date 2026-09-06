import { useState, useMemo } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft, Loader2, AlertCircle, FileText, Search, Filter,
  Download, Clock, Shield, User, Activity, ChevronLeft, ChevronRight,
  Calendar, RefreshCw,
} from 'lucide-react'
import { getCase, listCaseAudit, listCaseMembers, type AuditEntry } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { Case } from '../types'

const actionLabels: Record<string, { label: string; color: string }> = {
  'case.created':           { label: 'Case Created',       color: '#34D399' },
  'case.updated':           { label: 'Case Updated',       color: '#60A5FA' },
  'case.deleted':           { label: 'Case Deleted',       color: '#F87171' },
  'member.added':           { label: 'Member Added',       color: '#8B5CF6' },
  'member.removed':         { label: 'Member Removed',     color: '#F87171' },
  'member.role_changed':    { label: 'Role Changed',       color: '#FBBF24' },
  'address.added':          { label: 'Address Added',      color: '#34D399' },
  'address.removed':        { label: 'Address Removed',    color: '#F87171' },
  'note.added':             { label: 'Note Added',         color: '#60A5FA' },
  'note.deleted':           { label: 'Note Deleted',       color: '#F87171' },
  'task.created':           { label: 'Task Created',       color: '#F59E0B' },
  'task.updated':           { label: 'Task Updated',       color: '#60A5FA' },
  'task.deleted':           { label: 'Task Deleted',       color: '#F87171' },
  'task.message':           { label: 'Message Sent',       color: '#8B5CF6' },
  'deliverable.submitted':  { label: 'Deliverable Submitted', color: '#60A5FA' },
  'deliverable.reviewed':   { label: 'Deliverable Reviewed', color: '#FBBF24' },
}

const actionColor = (action: string) => actionLabels[action]?.color || '#9CA3AF'
const actionLabel = (action: string) => actionLabels[action]?.label || action

const badge = (color: string): React.CSSProperties => ({
  fontSize: 10, padding: '2px 8px', borderRadius: 6, fontWeight: 600,
  background: `${color}22`, color, border: `1px solid ${color}44`,
  display: 'inline-flex', alignItems: 'center', gap: 3,
})

const PAGE_SIZE = 50

export default function CaseAudit() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const auth = useAuth()

  const [actionFilter, setActionFilter] = useState('')
  const [userFilter, setUserFilter] = useState('')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [page, setPage] = useState(0)

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

  const { data: auditData, isLoading: auditLoading, refetch } = useQuery({
    queryKey: ['case-audit', id, actionFilter, userFilter, fromDate, toDate, page],
    queryFn: () => listCaseAudit(id!, {
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
      action: actionFilter || undefined,
      user_id: userFilter || undefined,
      from_ts: fromDate ? new Date(fromDate).toISOString() : undefined,
      to_ts: toDate ? new Date(toDate + 'T23:59:59').toISOString() : undefined,
    }),
    enabled: !!id,
    refetchInterval: 15000,
  })

  const entries = auditData?.entries ?? []
  const total = auditData?.total ?? 0
  const totalPages = Math.ceil(total / PAGE_SIZE)
  const members = membersData?.members ?? []

  const filteredEntries = useMemo(() => {
    if (!searchQuery) return entries
    const q = searchQuery.toLowerCase()
    return entries.filter(e =>
      e.user_name.toLowerCase().includes(q) ||
      e.action.toLowerCase().includes(q) ||
      e.target.toLowerCase().includes(q) ||
      e.detail.toLowerCase().includes(q)
    )
  }, [entries, searchQuery])

  const uniqueUsers = useMemo(() => {
    const map = new Map<string, string>()
    entries.forEach(e => { if (e.user_id) map.set(e.user_id, e.user_name || e.user_id) })
    return Array.from(map.entries())
  }, [entries])

  const handleExport = () => {
    const header = 'Timestamp,User,Role,Action,Target,Detail\n'
    const rows = entries.map(e =>
      `"${e.timestamp}","${e.user_name}","${e.user_role}","${e.action}","${e.target}","${e.detail}"`
    ).join('\n')
    const blob = new Blob([header + rows], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `case-audit-${id}-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (caseLoading) return (
    <div className="flex justify-center items-center py-20">
      <Loader2 className="animate-spin" size={28} style={{ color: '#ff5a6e' }} />
    </div>
  )

  if (!caseData) return (
    <div className="p-6 flex items-center gap-2 text-neon-red">
      <AlertCircle size={15} /> Case not found
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
            <ArrowLeft size={12} /> Back to Case
          </button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 700, color: 'rgb(var(--text-primary))', margin: 0 }}>
              {caseData.name} — Audit Log
            </h1>
            <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 11, color: 'rgb(var(--text-muted))' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                <Activity size={11} /> {total} total entries
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                <Clock size={11} /> Tracking all case activity
              </span>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => navigate(`/cases/${id}/tasks`)}
              className="btn-ghost" style={{ fontSize: 12 }}>
              <Clock size={13} /> Tasks
            </button>
            <button onClick={handleExport} className="btn-secondary" style={{ fontSize: 12 }}>
              <Download size={13} /> Export CSV
            </button>
          </div>
        </div>
        {/* Nav tabs */}
        <div style={{ display: 'flex', gap: 4, marginTop: 12 }}>
          <Link to={`/cases/${id}/tasks`} style={{
            padding: '6px 16px', fontSize: 12, fontWeight: 600, borderRadius: '6px 6px 0 0',
            background: 'transparent', color: 'rgb(var(--text-muted))',
            borderBottom: '2px solid transparent', textDecoration: 'none',
          }}>
            <Clock size={12} style={{ marginRight: 4, verticalAlign: -1 }} /> Tasks
          </Link>
          <Link to={`/cases/${id}/audit`} style={{
            padding: '6px 16px', fontSize: 12, fontWeight: 600, borderRadius: '6px 6px 0 0',
            background: 'rgb(var(--bg-card))', color: 'rgb(var(--text-primary))',
            borderBottom: '2px solid #F59E0B', textDecoration: 'none',
          }}>
            <FileText size={12} style={{ marginRight: 4, verticalAlign: -1 }} /> Audit
          </Link>
        </div>
      </div>

      {/* ── Filter Bar ─────────────────────────────────────────────────── */}
      <div style={{
        padding: '10px 24px',
        borderBottom: '1px solid rgb(var(--bg-border) / 0.3)',
        display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
        background: 'rgb(var(--bg-card) / 0.2)',
      }}>
        <div style={{ position: 'relative', flex: '0 0 200px' }}>
          <Search size={12} style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: 'rgb(var(--text-muted))' }} />
          <input value={searchQuery} onChange={e => { setSearchQuery(e.target.value); setPage(0) }}
            placeholder="Search audit log..."
            className="input" style={{ paddingLeft: 28, fontSize: 12, width: '100%' }} />
        </div>
        <select value={actionFilter} onChange={e => { setActionFilter(e.target.value); setPage(0) }}
          className="input" style={{ fontSize: 11, width: 160 }}>
          <option value="">All Actions</option>
          {Object.entries(actionLabels).map(([key, val]) => (
            <option key={key} value={key}>{val.label}</option>
          ))}
        </select>
        <select value={userFilter} onChange={e => { setUserFilter(e.target.value); setPage(0) }}
          className="input" style={{ fontSize: 11, width: 150 }}>
          <option value="">All Users</option>
          {uniqueUsers.map(([uid, name]) => (
            <option key={uid} value={uid}>{name}</option>
          ))}
        </select>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <Calendar size={11} style={{ color: 'rgb(var(--text-muted))' }} />
          <input type="date" value={fromDate} onChange={e => { setFromDate(e.target.value); setPage(0) }}
            className="input" style={{ fontSize: 11, width: 130 }} title="From date" />
          <span style={{ fontSize: 10, color: 'rgb(var(--text-muted))' }}>to</span>
          <input type="date" value={toDate} onChange={e => { setToDate(e.target.value); setPage(0) }}
            className="input" style={{ fontSize: 11, width: 130 }} title="To date" />
        </div>
        {(actionFilter || userFilter || fromDate || toDate || searchQuery) && (
          <button onClick={() => { setActionFilter(''); setUserFilter(''); setFromDate(''); setToDate(''); setSearchQuery(''); setPage(0) }}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgb(var(--text-muted))', fontSize: 11 }}>
            Clear
          </button>
        )}
        <button onClick={() => refetch()}
          style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: 'rgb(var(--text-muted))', display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {/* ── Audit Table ────────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 24px 24px' }}>
        {auditLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Loader2 size={20} className="animate-spin" style={{ color: '#F59E0B' }} />
          </div>
        ) : filteredEntries.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 60 }}>
            <FileText size={36} style={{ color: 'rgb(var(--text-muted))', opacity: 0.3, marginBottom: 12 }} />
            <p style={{ fontSize: 13, color: 'rgb(var(--text-muted))' }}>
              {total === 0 ? 'No audit entries yet. Actions on this case will be logged here.' : 'No entries match your filters.'}
            </p>
          </div>
        ) : (
          <>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgb(var(--bg-border) / 0.5)' }}>
                  <th style={thStyle}>Timestamp</th>
                  <th style={thStyle}>User</th>
                  <th style={thStyle}>Role</th>
                  <th style={thStyle}>Action</th>
                  <th style={thStyle}>Target</th>
                  <th style={{ ...thStyle, textAlign: 'left' }}>Detail</th>
                </tr>
              </thead>
              <tbody>
                {filteredEntries.map((entry, i) => (
                  <tr key={entry.id} style={{
                    borderBottom: '1px solid rgb(var(--bg-border) / 0.2)',
                    background: i % 2 === 0 ? 'transparent' : 'rgb(255 255 255 / 0.01)',
                  }}>
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}>
                        <Clock size={10} style={{ color: 'rgb(var(--text-muted))', flexShrink: 0 }} />
                        <span style={{ fontSize: 11, color: 'rgb(var(--text-secondary))', fontVariantNumeric: 'tabular-nums' }}>
                          {formatTimestamp(entry.timestamp)}
                        </span>
                      </div>
                    </td>
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div style={{
                          width: 22, height: 22, borderRadius: '50%',
                          background: 'linear-gradient(135deg, #8B5CF6, #6366F1)',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 9, fontWeight: 700, color: '#fff', flexShrink: 0,
                        }}>
                          {(entry.user_name || '?')[0].toUpperCase()}
                        </div>
                        <span style={{ fontSize: 11, color: 'rgb(var(--text-primary))', fontWeight: 500 }}>
                          {entry.user_name || 'System'}
                        </span>
                      </div>
                    </td>
                    <td style={tdStyle}>
                      <span style={badge(entry.user_role === 'admin' ? '#F87171' : entry.user_role === 'analyst' ? '#60A5FA' : '#9CA3AF')}>
                        <Shield size={9} /> {entry.user_role || '—'}
                      </span>
                    </td>
                    <td style={tdStyle}>
                      <span style={badge(actionColor(entry.action))}>
                        {actionLabel(entry.action)}
                      </span>
                    </td>
                    <td style={{ ...tdStyle, maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      <span style={{ fontSize: 11, color: 'rgb(var(--text-secondary))' }} title={entry.target}>
                        {entry.target || '—'}
                      </span>
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'left', maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      <span style={{ fontSize: 11, color: 'rgb(var(--text-muted))' }} title={entry.detail}>
                        {entry.detail || '—'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Pagination */}
            {totalPages > 1 && (
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                padding: '16px 0', marginTop: 8,
              }}>
                <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
                  className="btn-ghost" style={{ fontSize: 11, padding: '4px 8px' }}>
                  <ChevronLeft size={13} /> Prev
                </button>
                <span style={{ fontSize: 11, color: 'rgb(var(--text-muted))' }}>
                  Page {page + 1} of {totalPages} ({total} entries)
                </span>
                <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
                  className="btn-ghost" style={{ fontSize: 11, padding: '4px 8px' }}>
                  Next <ChevronRight size={13} />
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

const thStyle: React.CSSProperties = {
  padding: '8px 12px',
  textAlign: 'left',
  fontSize: 10,
  fontWeight: 600,
  color: 'rgb(var(--text-muted))',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  whiteSpace: 'nowrap',
}

const tdStyle: React.CSSProperties = {
  padding: '8px 12px',
  verticalAlign: 'middle',
}

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch {
    return ts
  }
}
