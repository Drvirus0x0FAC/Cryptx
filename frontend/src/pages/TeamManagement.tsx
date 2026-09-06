import { FormEvent, useEffect, useState } from 'react'
import {
  AlertTriangle, CheckCircle, Copy, Loader2, Plus, RefreshCw, ShieldCheck, Trash2, Users, Shield,
} from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import {
  fetchTeamInfo, updateTeamName, createTeamMember, removeTeamMember, teamDisable2FA,
  type TeamInfo, type TeamMember,
} from '../api/client'
import '../styles/settings-cockpit.css'
import '../styles/profile-cockpit.css'

function fmtDate(value?: string | null) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function TeamManagement() {
  const auth = useAuth()
  const user = auth.user

  const [team, setTeam] = useState<TeamInfo | null>(null)
  const [members, setMembers] = useState<TeamMember[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')

  // Edit team name
  const [editingName, setEditingName] = useState(false)
  const [teamNameInput, setTeamNameInput] = useState('')

  // Create member form
  const [showCreate, setShowCreate] = useState(false)
  const [newEmail, setNewEmail] = useState('')
  const [newName, setNewName] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [createdPassword, setCreatedPassword] = useState('')

  async function loadTeam() {
    setLoading(true); setError('')
    try {
      const data = await fetchTeamInfo()
      setTeam(data.team)
      setMembers(data.members)
      setTeamNameInput(data.team.name)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally { setLoading(false) }
  }

  useEffect(() => { void loadTeam() }, [])

  async function saveTeamName(e: FormEvent) {
    e.preventDefault()
    setBusy('name'); setError(''); setNotice('')
    try {
      const res = await updateTeamName(teamNameInput)
      setTeam(res.team)
      setEditingName(false)
      setNotice('Team name updated.')
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy('') }
  }

  async function handleCreateMember(e: FormEvent) {
    e.preventDefault()
    setBusy('create'); setError(''); setNotice(''); setCreatedPassword('')
    try {
      const res = await createTeamMember({
        email: newEmail,
        name: newName,
        temp_password: newPassword || undefined,
      })
      setCreatedPassword(res.member.temp_password)
      setNewEmail(''); setNewName(''); setNewPassword('')
      setMembers(prev => [...prev, res.member])
      setNotice(`Team member "${res.member.name}" created.`)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy('') }
  }

  async function handleRemove(memberId: string, memberName: string) {
    if (!confirm(`Deactivate ${memberName}? They will lose access immediately.`)) return
    setBusy(memberId); setError(''); setNotice('')
    try {
      await removeTeamMember(memberId)
      setMembers(prev => prev.filter(m => m.id !== memberId))
      setNotice(`${memberName} has been deactivated.`)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy('') }
  }

  async function handleDisable2FA(memberId: string, memberName: string) {
    if (!confirm(`Disable 2FA for ${memberName}? They will no longer need an authenticator code to log in.`)) return
    setBusy(memberId); setError(''); setNotice('')
    try {
      await teamDisable2FA(memberId)
      setMembers(prev => prev.map(m => m.id === memberId ? { ...m, totp_enabled: false } : m))
      setNotice(`2FA disabled for ${memberName}.`)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy('') }
  }

  if (!user) return null

  if (loading) {
    return (
      <div className="cxset">
        <div className="cxset-head">
          <span className="cxset-head-icon"><Users size={22} /></span>
          <div><h1>Team Management</h1><p>Loading team data…</p></div>
        </div>
      </div>
    )
  }

  return (
    <div className="cxset">
      {/* Header */}
      <div className="cxset-head">
        <span className="cxset-head-icon"><Users size={22} /></span>
        <div>
          <h1>Team Management</h1>
          <p>{team?.name || 'Team'} · {members.length} member{members.length !== 1 ? 's' : ''}</p>
        </div>
        <div className="cxset-head-right" style={{ display: 'flex', gap: 8 }}>
          <button className="cxprof-hbtn" onClick={() => void loadTeam()}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      {(notice || error) && (
        <div className={`cxprof-notice ${error ? 'err' : 'ok'}`}>
          {error ? <AlertTriangle size={15} /> : <CheckCircle size={15} />}{error || notice}
        </div>
      )}

      {/* Team Info */}
      <section className="cxpanel" style={{ marginBottom: 16 }}>
        <div className="cxpanel-title"><span className="cxc">◈</span> Team Info</div>
        <div className="cxpanel-body">
          {editingName ? (
            <form onSubmit={saveTeamName} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input className="cxinput" value={teamNameInput} onChange={e => setTeamNameInput(e.target.value)} placeholder="Team name" style={{ flex: 1 }} />
              <button className="cxprof-savebtn" disabled={busy === 'name'} type="submit">
                {busy === 'name' ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />} Save
              </button>
              <button type="button" className="cxprof-hbtn" onClick={() => { setEditingName(false); setTeamNameInput(team?.name || '') }}>Cancel</button>
            </form>
          ) : (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <p style={{ fontSize: 18, fontWeight: 700, color: 'rgb(var(--text-primary))' }}>{team?.name}</p>
                <p style={{ fontSize: 12, color: 'rgb(var(--text-muted))', marginTop: 2 }}>
                  Plan: {team?.plan || 'investigator'} · Created: {fmtDate(team?.created_at)}
                </p>
              </div>
              <button className="cxprof-hbtn" onClick={() => setEditingName(true)}>Edit Name</button>
            </div>
          )}
        </div>
      </section>

      {/* Create Member */}
      <section className="cxpanel" style={{ marginBottom: 16 }}>
        <div className="cxpanel-title"><span className="cxc"><Plus size={11} /></span> Team Members</div>
        <div className="cxpanel-body">
          {!showCreate ? (
            <button className="cxprof-hbtn" onClick={() => { setShowCreate(true); setCreatedPassword('') }}>
              <Plus size={14} /> Create New Member
            </button>
          ) : (
            <form onSubmit={handleCreateMember}>
              {createdPassword ? (
                <div className="cxprof-notice ok" style={{ marginBottom: 12 }}>
                  <CheckCircle size={15} />
                  <div>
                    <p style={{ margin: 0, fontWeight: 600 }}>Member created! Share this temporary password:</p>
                    <code style={{
                      display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 6,
                      padding: '6px 12px', borderRadius: 8,
                      background: 'rgb(var(--accent-green) / 0.15)', border: '1px solid rgb(var(--accent-green) / 0.4)',
                      fontFamily: "'Roboto Mono', monospace", fontSize: 14, fontWeight: 700,
                      color: 'rgb(var(--accent-green))',
                    }}>
                      {createdPassword}
                      <button type="button" onClick={() => navigator.clipboard.writeText(createdPassword)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', padding: 0 }}>
                        <Copy size={13} />
                      </button>
                    </code>
                    <p style={{ margin: '6px 0 0', fontSize: 11, opacity: 0.8 }}>They will be required to change it on first login.</p>
                  </div>
                </div>
              ) : (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                    <div>
                      <label style={{ fontSize: 11, color: 'rgb(var(--text-muted))', marginBottom: 3, display: 'block' }}>Full name *</label>
                      <input className="cxinput" value={newName} onChange={e => setNewName(e.target.value)} placeholder="John Doe" required />
                    </div>
                    <div>
                      <label style={{ fontSize: 11, color: 'rgb(var(--text-muted))', marginBottom: 3, display: 'block' }}>Email *</label>
                      <input className="cxinput" type="email" value={newEmail} onChange={e => setNewEmail(e.target.value)} placeholder="john@example.com" required />
                    </div>
                  </div>
                  <div style={{ marginBottom: 10 }}>
                    <label style={{ fontSize: 11, color: 'rgb(var(--text-muted))', marginBottom: 3, display: 'block' }}>Temporary password (leave empty to auto-generate)</label>
                    <input className="cxinput" type="text" value={newPassword} onChange={e => setNewPassword(e.target.value)} placeholder="Auto-generated if empty" minLength={8} />
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button className="cxprof-savebtn" disabled={busy === 'create'} type="submit">
                      {busy === 'create' ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Create Member
                    </button>
                    <button type="button" className="cxprof-hbtn" onClick={() => { setShowCreate(false); setCreatedPassword('') }}>Cancel</button>
                  </div>
                </>
              )}
            </form>
          )}

          {/* Members list */}
          <div style={{ marginTop: 16 }}>
            {members.length === 0 ? (
              <p style={{ color: 'rgb(var(--text-muted))', fontSize: 13 }}>No team members yet.</p>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgb(var(--bg-border) / 0.5)', textAlign: 'left' }}>
                    <th style={{ padding: '8px 6px', color: 'rgb(var(--text-muted))', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Name</th>
                    <th style={{ padding: '8px 6px', color: 'rgb(var(--text-muted))', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Email</th>
                    <th style={{ padding: '8px 6px', color: 'rgb(var(--text-muted))', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Role</th>
                    <th style={{ padding: '8px 6px', color: 'rgb(var(--text-muted))', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Status</th>
                    <th style={{ padding: '8px 6px', color: 'rgb(var(--text-muted))', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em' }}>2FA</th>
                    <th style={{ padding: '8px 6px', color: 'rgb(var(--text-muted))', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Joined</th>
                    <th style={{ padding: '8px 6px' }} />
                  </tr>
                </thead>
                <tbody>
                  {members.map(m => (
                    <tr key={m.id} style={{ borderBottom: '1px solid rgb(var(--bg-border) / 0.3)' }}>
                      <td style={{ padding: '10px 6px', fontWeight: 500 }}>{m.name || '—'}</td>
                      <td style={{ padding: '10px 6px', color: 'rgb(var(--text-muted))' }}>{m.email}</td>
                      <td style={{ padding: '10px 6px' }}>
                        <span style={{
                          fontSize: 11, padding: '2px 8px', borderRadius: 6,
                          background: m.org_role === 'org_admin' ? 'rgb(var(--cxv-acc) / 0.15)' : 'rgb(255 255 255 / 0.05)',
                          color: m.org_role === 'org_admin' ? 'rgb(var(--cxv-acc))' : 'rgb(var(--text-muted))',
                        }}>
                          {m.org_role || 'analyst'}
                        </span>
                      </td>
                      <td style={{ padding: '10px 6px' }}>
                        <span style={{
                          fontSize: 11, padding: '2px 8px', borderRadius: 6,
                          background: m.is_active ? 'rgb(var(--accent-green) / 0.15)' : 'rgb(var(--cxv-brand) / 0.15)',
                          color: m.is_active ? 'rgb(var(--accent-green))' : 'rgb(var(--cxv-brand))',
                        }}>
                          {m.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td style={{ padding: '10px 6px', textAlign: 'center' }}>
                        <span style={{
                          fontSize: 11, padding: '2px 8px', borderRadius: 6,
                          background: m.totp_enabled ? 'rgb(var(--accent-green) / 0.15)' : 'rgb(var(--text-muted) / 0.15)',
                          color: m.totp_enabled ? 'rgb(var(--accent-green))' : 'rgb(var(--text-muted))',
                        }}>
                          {m.totp_enabled ? 'ON' : 'OFF'}
                        </span>
                        {m.totp_enabled && m.id !== user.id && (
                          <button
                            style={{ marginLeft: 4, background: 'none', border: 'none', cursor: 'pointer', color: 'rgb(var(--cxv-brand))', padding: 2, verticalAlign: 'middle' }}
                            onClick={() => void handleDisable2FA(m.id, m.name || m.email)}
                            disabled={busy === m.id}
                            title="Disable 2FA for this member"
                          >
                            {busy === m.id ? <Loader2 size={10} className="animate-spin" /> : <Shield size={10} />}
                          </button>
                        )}
                      </td>
                      <td style={{ padding: '10px 6px', color: 'rgb(var(--text-muted))', fontSize: 12 }}>{fmtDate(m.created_at)}</td>
                      <td style={{ padding: '10px 6px', textAlign: 'right' }}>
                        {m.id !== user.id && m.is_active && (
                          <button
                            className="cxprof-hbtn"
                            style={{ color: 'rgb(var(--cxv-brand))' }}
                            onClick={() => void handleRemove(m.id, m.name || m.email)}
                            disabled={busy === m.id}
                          >
                            {busy === m.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}
