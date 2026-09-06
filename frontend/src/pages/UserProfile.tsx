import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { createPortal } from 'react-dom'
import {
  AlertTriangle, BadgeCheck, CheckCircle, Copy, Fingerprint, KeyRound, Loader2,
  LogOut, Mail, Monitor, RefreshCw, RotateCcw, ShieldCheck, Clock3, Trash2, UserRound, Users, X, Shield, QrCode,
} from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { adminListUsers, adminSetRole, adminSetActive, setup2FA, enable2FA, disable2FA } from '../api/client'
import type { AuthSessionInfo, AdminUser } from '../api/client'
import { getPrefs, setPrefs, type CryptxPrefs } from '../lib/prefs'
import '../styles/settings-cockpit.css'
import '../styles/profile-cockpit.css'

/* ── Helpers ─────────────────────────────────────────────────────────────── */
function fmt(value?: string | null) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
function monthYear(value?: string | null) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString(undefined, { month: 'short', year: 'numeric' })
}
function daysSince(value?: string | null) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return `${Math.max(0, Math.floor((Date.now() - d.getTime()) / 86_400_000))}d`
}
function uaLabel(ua: string) {
  if (!ua) return 'Unknown client'
  if (/Edg\//i.test(ua)) return 'Microsoft Edge'
  if (/Chrome\//i.test(ua)) return 'Chrome'
  if (/Firefox\//i.test(ua)) return 'Firefox'
  if (/Safari\//i.test(ua)) return 'Safari'
  return ua.slice(0, 34)
}
function shortId(id: string) { return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-6)}` : id }

const ACCENTS: Record<string, [string, string]> = {
  emerald: ['#46f0a0', '#38e0ff'],
  crimson: ['#ff527d', '#b91c3c'],
  violet: ['#8b5cf6', '#38e0ff'],
  amber: ['#ffb020', '#ff527d'],
}

interface ProfileExtras {
  title: string; signature: string; accent: string
  notifyEmail: boolean; notifyMonitor: boolean; notifyDesktop: boolean
}
const PROFILE_KEY = 'cryptx_profile'
function getExtras(): ProfileExtras {
  const base: ProfileExtras = { title: '', signature: '', accent: 'emerald', notifyEmail: true, notifyMonitor: true, notifyDesktop: false }
  try { return { ...base, ...JSON.parse(localStorage.getItem(PROFILE_KEY) || '{}') } } catch { return base }
}
function saveExtras(p: ProfileExtras) { try { localStorage.setItem(PROFILE_KEY, JSON.stringify(p)) } catch { /* ignore */ } }

function clearances(role?: string | null): string[] {
  const r = (role || 'analyst').toLowerCase()
  if (r === 'admin') return ['Admin Console', 'Full API', 'Case Write', 'Evidence Seal', 'Regulatory Filing']
  if (r === 'viewer') return ['Read-Only']
  return ['Full API', 'Case Write', 'Evidence Seal']
}

/* ── Reusable small controls (match cockpit) ─────────────────────────────── */
function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return <button type="button" className={`cxtoggle${on ? ' on' : ''}`} onClick={() => onChange(!on)} aria-pressed={on} />
}
function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { v: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="cxseg">
      {options.map(o => <button key={o.v} className={value === o.v ? 'active' : ''} onClick={() => onChange(o.v)}>{o.label}</button>)}
    </div>
  )
}

export default function UserProfile() {
  const { t } = useTranslation()
  const auth = useAuth()
  const user = auth.user

  const [extras, setExtras] = useState<ProfileExtras>(() => getExtras())
  const [name, setName] = useState(user?.name || '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [sessions, setSessions] = useState<AuthSessionInfo[]>([])
  const [currentSessionId, setCurrentSessionId] = useState(auth.session?.id || '')
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [adminOpen, setAdminOpen] = useState(false)
  const [isAdmin, setIsAdmin] = useState(false)

  // 2FA state
  const [totpEnabled, setTotpEnabled] = useState(user?.totp_enabled || false)
  const [totpSetup, setTotpSetup] = useState<{ secret: string; uri: string; qr_svg: string } | null>(null)
  const [totpCode, setTotpCode] = useState('')
  const [totpBusy, setTotpBusy] = useState(false)

  // workspace prefs (persisted like Settings)
  const [prefs, setPrefsState] = useState<CryptxPrefs>(() => getPrefs())
  const [theme, setTheme] = useState<'dark' | 'light'>(() => (localStorage.getItem('theme') as 'dark' | 'light') || 'dark')
  const [density, setDensity] = useState<'comfortable' | 'compact'>(() => (localStorage.getItem('density') as 'comfortable' | 'compact') || 'comfortable')
  useEffect(() => { document.documentElement.classList.toggle('light', theme === 'light'); localStorage.setItem('theme', theme) }, [theme])
  useEffect(() => { document.documentElement.setAttribute('data-density', density); localStorage.setItem('density', density) }, [density])

  const activeSessions = useMemo(() => sessions.filter(s => !s.revoked_at), [sessions])
  const revokedSessions = useMemo(() => sessions.filter(s => s.revoked_at), [sessions])
  const orderedSessions = useMemo(() => [...sessions].sort((a, b) => {
    if (a.id === currentSessionId) return -1
    if (b.id === currentSessionId) return 1
    return new Date(b.last_seen_at || 0).getTime() - new Date(a.last_seen_at || 0).getTime()
  }), [sessions, currentSessionId])
  const currentSession = useMemo(() => sessions.find(s => s.id === currentSessionId), [sessions, currentSessionId])

  async function loadSessions() {
    setLoadingSessions(true); setError('')
    try {
      const data = await auth.listSessions()
      setSessions(data.sessions); setCurrentSessionId(data.current_session_id)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setLoadingSessions(false) }
  }

  useEffect(() => { setName(user?.name || '') }, [user?.name])
  useEffect(() => { void loadSessions() /* eslint-disable-next-line */ }, [])
  useEffect(() => { adminListUsers().then(() => setIsAdmin(true)).catch(() => setIsAdmin(false)) }, [])

  function patchExtras(patch: Partial<ProfileExtras>, persist = false) {
    setExtras(x => { const n = { ...x, ...patch }; if (persist) saveExtras(n); return n })
  }
  function updatePref(patch: Partial<CryptxPrefs>) { setPrefsState(setPrefs(patch)) }

  async function saveProfile(e: FormEvent) {
    e.preventDefault()
    setBusy('profile'); setError(''); setNotice('')
    try { await auth.updateProfile({ name }); saveExtras(extras); setNotice('Profile updated.') }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy('') }
  }
  async function rotatePassword(e: FormEvent) {
    e.preventDefault()
    if (newPassword !== confirmPassword) { setError('New passwords do not match.'); return }
    setBusy('password'); setError(''); setNotice('')
    try {
      await auth.changePassword({ current_password: currentPassword, new_password: newPassword })
      setCurrentPassword(''); setNewPassword(''); setConfirmPassword('')
      setNotice('Password changed. Other sessions were revoked; this browser got a fresh session.')
      await loadSessions()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy('') }
  }
  async function revoke(sessionId: string) {
    setBusy(sessionId); setError(''); setNotice('')
    try { await auth.revokeSession(sessionId); setNotice('Session revoked.'); await loadSessions() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy('') }
  }
  async function revokeOthers() {
    setBusy('others'); setError(''); setNotice('')
    try { await auth.logoutOthers(); setNotice('Other active sessions revoked.'); await loadSessions() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy('') }
  }

  // 2FA handlers
  const isTeamMember = user?.registration_type === 'researcher' && !!user?.org_id && user?.org_role !== 'org_admin'

  async function handleTotpSetup() {
    setTotpBusy(true); setError('')
    try {
      const data = await setup2FA()
      setTotpSetup(data)
      setTotpCode('')
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setTotpBusy(false) }
  }

  async function handleTotpEnable(e: FormEvent) {
    e.preventDefault()
    setTotpBusy(true); setError('')
    try {
      await enable2FA(totpCode)
      setTotpEnabled(true)
      setTotpSetup(null)
      setTotpCode('')
      setNotice('Two-factor authentication enabled.')
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setTotpBusy(false) }
  }

  async function handleTotpDisable(e: FormEvent) {
    e.preventDefault()
    setTotpBusy(true); setError('')
    try {
      await disable2FA(totpCode)
      setTotpEnabled(false)
      setTotpCode('')
      setNotice('Two-factor authentication disabled.')
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setTotpBusy(false) }
  }

  if (!user) return null

  const initials = (user.name || user.email).slice(0, 2).toUpperCase()
  const grad = ACCENTS[extras.accent] || ACCENTS.emerald
  const dirty = name !== (user.name || '') || JSON.stringify(extras) !== JSON.stringify(getExtras())

  return (
    <div className="cxset cxprof">
      <div className="cxprof-inner">
        {/* Header */}
        <div className="cxset-head">
          <span className="cxset-head-icon"><UserRound size={22} /></span>
          <div>
            <h1>Investigator Profile</h1>
            <p>Account · identity · security · sessions</p>
          </div>
          <div className="cxset-head-right">
            {isAdmin && <button className="cxprof-hbtn" onClick={() => setAdminOpen(true)}><Users size={14} /> Admin Console</button>}
            <button className="cxprof-hbtn" onClick={() => void navigator.clipboard.writeText(user.id)}><Copy size={14} /> User ID</button>
            <button className="cxprof-hbtn logout" onClick={() => void auth.signOut()}><LogOut size={14} /> Logout</button>
          </div>
        </div>

        {(notice || error) && (
          <div className={`cxprof-notice ${error ? 'err' : 'ok'}`}>
            {error ? <AlertTriangle size={15} /> : <CheckCircle size={15} />}{error || notice}
          </div>
        )}

        <div className="cxprof-grid">
          {/* ── IDENTITY ── */}
          <section className="cxpanel cxprof-area-id">
            <div className="cxpanel-title"><span className="cxc">◈</span> Identity</div>
            <div className="cxpanel-body">
              <div className="cxprof-idhead">
                <span className="cxprof-avatar" style={{ background: `linear-gradient(135deg, ${grad[0]}, ${grad[1]})` }}>{initials}</span>
                <div style={{ minWidth: 0 }}>
                  <p className="cxprof-name">{user.name || 'Unnamed analyst'}</p>
                  <p className="cxprof-role">{extras.title || `${(user.role || 'analyst')} · Blockchain Investigator`}</p>
                  <p className="cxprof-email">{user.email}</p>
                </div>
              </div>
              <div className="cxprof-accents">
                {Object.entries(ACCENTS).map(([k, g]) => (
                  <button key={k} className={`cxprof-swatch${extras.accent === k ? ' active' : ''}`} title={k}
                    style={{ background: `linear-gradient(135deg, ${g[0]}, ${g[1]})` }}
                    onClick={() => patchExtras({ accent: k })} />
                ))}
              </div>
              <div className="cxprof-stats">
                <div className="cxprof-stat"><div className="k">Role</div><div className="v cyan">{(user.role || 'analyst').toUpperCase()}</div></div>
                <div className="cxprof-stat"><div className="k">Member since</div><div className="v plain">{monthYear(user.created_at)}</div></div>
              </div>
              <div className="cxpanel-title" style={{ margin: '13px 0 8px' }}><BadgeCheck size={11} className="cxc" /> Clearances</div>
              <div className="cxprof-badges">{clearances(user.role).map(c => <span key={c} className="cxprof-badge">{c}</span>)}</div>
            </div>
          </section>

          {/* ── EDIT PROFILE ── */}
          <section className="cxpanel cxprof-area-edit">
            <div className="cxpanel-title"><span className="cxc"><PenIcon /></span> Edit Profile</div>
            <div className="cxpanel-body">
              <form onSubmit={saveProfile}>
                <div className="cxprof-field"><label>Display name</label>
                  <input className="cxinput" value={name} onChange={e => setName(e.target.value)} placeholder="Investigator name" /></div>
                <div className="cxprof-field"><label>Title / rank</label>
                  <input className="cxinput" value={extras.title} onChange={e => patchExtras({ title: e.target.value })} placeholder="e.g. Senior Blockchain Investigator" /></div>
                <div className="cxprof-field"><label>Report signature</label>
                  <input className="cxinput" value={extras.signature} onChange={e => patchExtras({ signature: e.target.value })} placeholder="Name shown on generated reports" /></div>
                <button className="cxprof-savebtn" disabled={busy === 'profile' || !dirty}>
                  {busy === 'profile' ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />} Save Identity
                </button>
              </form>
            </div>
          </section>

          {/* ── SECURITY ── */}
          <section className="cxpanel cxprof-area-sec">
            <div className="cxpanel-title"><span className="cxc"><KeyRound size={11} /></span> Security</div>
            <div className="cxpanel-body">
              <form onSubmit={rotatePassword} className="cxprof-pwstack">
                <input className="cxinput" type="password" value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} placeholder="Current password" required />
                <input className="cxinput" type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} placeholder="New password" required />
                <input className="cxinput" type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} placeholder="Confirm new password" required />
                <button className="cxprof-secbtn" disabled={busy === 'password'}>
                  {busy === 'password' ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />} Change Password
                </button>
              </form>
              <div className="cxprof-inforow" style={{ marginTop: 8 }}>
                <span className="cxprof-infok"><Shield size={13} /> Two-factor auth (2FA)</span>
                <span className={`cxprof-statuspill ${totpEnabled ? 'on' : 'off'}`}>
                  {totpEnabled ? 'ENABLED' : 'NOT ENABLED'}
                </span>
              </div>

              {/* 2FA Setup/Enable */}
              {!totpEnabled && !totpSetup && (
                <button className="cxprof-secbtn" style={{ marginTop: 9 }} onClick={handleTotpSetup} disabled={totpBusy}>
                  {totpBusy ? <Loader2 size={13} className="animate-spin" /> : <QrCode size={13} />}
                  Set up 2FA with authenticator app
                </button>
              )}

              {/* 2FA QR + verify code */}
              {totpSetup && (
                <div style={{ marginTop: 10, padding: 12, borderRadius: 8, background: 'rgb(255 255 255 / 0.03)', border: '1px solid rgb(var(--bg-border) / 0.4)' }}>
                  <p style={{ fontSize: 11, color: 'rgb(var(--text-muted))', marginBottom: 8 }}>
                    Scan this QR code with your authenticator app (Google Authenticator, Authy, etc.), then enter the 6-digit code below:
                  </p>
                  {totpSetup.qr_svg ? (
                    <div dangerouslySetInnerHTML={{ __html: totpSetup.qr_svg }} style={{ display: 'flex', justifyContent: 'center', marginBottom: 8 }} />
                  ) : (
                    <p style={{ fontSize: 10, fontFamily: 'monospace', wordBreak: 'break-all', marginBottom: 8, color: 'rgb(var(--text-secondary))' }}>
                      Secret: {totpSetup.secret}
                    </p>
                  )}
                  <form onSubmit={handleTotpEnable} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <input
                      className="cxinput"
                      value={totpCode}
                      onChange={e => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                      placeholder="000000"
                      maxLength={6}
                      style={{ flex: 1, textAlign: 'center', fontFamily: "'Roboto Mono', monospace", fontSize: 14, letterSpacing: 4 }}
                      required
                    />
                    <button className="cxprof-secbtn" disabled={totpBusy || totpCode.length !== 6} type="submit">
                      {totpBusy ? <Loader2 size={13} className="animate-spin" /> : <ShieldCheck size={13} />} Verify & Enable
                    </button>
                    <button className="cxprof-secbtn" style={{ opacity: 0.6 }} onClick={() => { setTotpSetup(null); setTotpCode('') }} type="button">Cancel</button>
                  </form>
                </div>
              )}

              {/* 2FA Disable */}
              {totpEnabled && (
                <div style={{ marginTop: 10 }}>
                  {isTeamMember ? (
                    <p style={{ fontSize: 11, color: 'rgb(var(--text-muted))', fontStyle: 'italic' }}>
                      2FA is enforced by your team leader. Contact them to disable it.
                    </p>
                  ) : (
                    <form onSubmit={handleTotpDisable} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <input
                        className="cxinput"
                        value={totpCode}
                        onChange={e => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                        placeholder="Enter 2FA code to disable"
                        maxLength={6}
                        style={{ flex: 1, textAlign: 'center', fontFamily: "'Roboto Mono', monospace", fontSize: 13, letterSpacing: 4 }}
                        required
                      />
                      <button className="cxprof-secbtn danger" disabled={totpBusy || totpCode.length !== 6} type="submit">
                        {totpBusy ? <Loader2 size={13} className="animate-spin" /> : <X size={13} />} Disable 2FA
                      </button>
                    </form>
                  )}
                </div>
              )}

              <button className="cxprof-secbtn danger" style={{ marginTop: 9 }} onClick={revokeOthers} disabled={busy === 'others'}>
                {busy === 'others' ? <Loader2 size={13} className="animate-spin" /> : <LogOut size={13} />} Sign out all other sessions
              </button>
            </div>
          </section>

          {/* ── ACCOUNT & ACTIVITY (new) ── */}
          <section className="cxpanel cxprof-area-acct">
            <div className="cxpanel-title"><span className="cxc"><Fingerprint size={11} /></span> Account &amp; Activity</div>
            <div className="cxpanel-body">
              <div className="cxprof-inforow">
                <span className="cxprof-infok"><Fingerprint size={13} /> User ID</span>
                <span className="cxprof-infov">{shortId(user.id)}
                  <button className="cxprof-copy" title="Copy" onClick={() => void navigator.clipboard.writeText(user.id)}><Copy size={12} /></button>
                </span>
              </div>
              <div className="cxprof-inforow">
                <span className="cxprof-infok"><Mail size={13} /> Email</span>
                <span className="cxprof-infov" title={user.email}>{user.email}</span>
              </div>
              <div className="cxprof-inforow">
                <span className="cxprof-infok"><Clock3 size={13} /> Account age</span>
                <span className="cxprof-infov">{daysSince(user.created_at)}</span>
              </div>
              <div className="cxprof-inforow">
                <span className="cxprof-infok"><Monitor size={13} /> Sessions</span>
                <span className="cxprof-infov"><b style={{ color: 'rgb(var(--cx-green))' }}>{activeSessions.length}</b> active · {sessions.length} total</span>
              </div>
              <div className="cxprof-inforow">
                <span className="cxprof-infok"><LogOut size={13} /> Last login</span>
                <span className="cxprof-infov">{fmt(user.last_login_at)}</span>
              </div>
              <div className="cxprof-inforow">
                <span className="cxprof-infok"><Monitor size={13} /> This device</span>
                <span className="cxprof-infov">{currentSession ? currentSession.ip_address || 'unknown IP' : '—'}</span>
              </div>
            </div>
          </section>

          {/* ── PREFERENCES (new) ── */}
          <section className="cxpanel cxprof-area-pref">
            <div className="cxpanel-title"><span className="cxc"><Monitor size={11} /></span> Preferences</div>
            <div className="cxpanel-body">
              <div className="cxrow"><div className="cxrow-label">Theme</div>
                <Segmented value={theme} options={[{ v: 'dark', label: 'DARK' }, { v: 'light', label: 'LIGHT' }]} onChange={setTheme} /></div>
              <div className="cxrow"><div className="cxrow-label">Density</div>
                <Segmented value={density} options={[{ v: 'comfortable', label: 'COMFORT' }, { v: 'compact', label: 'COMPACT' }]} onChange={setDensity} /></div>
              <div className="cxrow"><div><div className="cxrow-label">Email on alerts</div><div className="cxrow-sub">Case &amp; risk notifications</div></div>
                <Toggle on={extras.notifyEmail} onChange={v => patchExtras({ notifyEmail: v }, true)} /></div>
              <div className="cxrow"><div><div className="cxrow-label">Monitor alerts</div><div className="cxrow-sub">Wallet Monitor hits</div></div>
                <Toggle on={extras.notifyMonitor} onChange={v => patchExtras({ notifyMonitor: v }, true)} /></div>
              <div className="cxrow"><div><div className="cxrow-label">Desktop notifications</div></div>
                <Toggle on={extras.notifyDesktop} onChange={v => patchExtras({ notifyDesktop: v }, true)} /></div>
              <div className="cxrow"><div><div className="cxrow-label">Interface animations</div></div>
                <Toggle on={prefs.animations} onChange={v => updatePref({ animations: v })} /></div>
            </div>
          </section>

          {/* ── SESSION AUDIT TRAIL (compact) ── */}
          <section className="cxpanel cxprof-area-ses">
            <div className="cxprof-seshead">
              <div className="cxpanel-title" style={{ margin: 0 }}><span className="cxc">◈</span> Sessions
                <small style={{ marginLeft: 6 }}>{activeSessions.length} active · {revokedSessions.length} revoked</small>
              </div>
              <div className="actions">
                <button className="cxprof-mini" onClick={loadSessions} disabled={loadingSessions}>
                  {loadingSessions ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />} Refresh
                </button>
              </div>
            </div>
            <div className="cxpanel-body scrollable">
              <div className="cxprof-audit">
                {orderedSessions.map(session => {
                  const current = session.id === currentSessionId
                  const revoked = Boolean(session.revoked_at)
                  return (
                    <div key={session.id} className={`cxprof-event${current ? ' current' : ''}${revoked ? ' revoked' : ''}`}>
                      <div className="cxprof-event-body">
                        <div className="cxprof-event-top">
                          <span className="cxprof-event-client">{uaLabel(session.user_agent)}</span>
                          {current && <span className="cxprof-tag current">CURRENT</span>}
                          {revoked && <span className="cxprof-tag revoked">REVOKED</span>}
                        </div>
                        <div className="cxprof-event-meta">{session.ip_address || 'unknown IP'} · {fmt(session.last_seen_at)}</div>
                      </div>
                      {!current && !revoked && (
                        <button className="cxprof-revoke" disabled={busy === session.id} onClick={() => revoke(session.id)}>
                          {busy === session.id ? <Loader2 size={10} className="animate-spin" /> : <Trash2 size={10} />}
                        </button>
                      )}
                    </div>
                  )
                })}
                {sessions.length === 0 && !loadingSessions && (
                  <div className="cxrow-sub" style={{ padding: '16px 4px' }}>No sessions returned yet.</div>
                )}
              </div>
            </div>
          </section>
        </div>
      </div>

      {adminOpen && <AdminModal currentUserId={user.id} onClose={() => setAdminOpen(false)} />}
    </div>
  )
}

/* tiny inline pen glyph so we don't depend on an extra icon export */
function PenIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  )
}

/* ── Admin console (portaled modal) ──────────────────────────────────────── */
function AdminModal({ currentUserId, onClose }: { currentUserId: string; onClose: () => void }) {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [roles, setRoles] = useState<string[]>(['admin', 'analyst', 'viewer'])
  const [err, setErr] = useState('')

  async function load() {
    try {
      const data = await adminListUsers()
      setUsers(data.users)
      if (data.roles?.length) setRoles(data.roles)
    } catch (e) { setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to load users') }
  }
  useEffect(() => { void load() }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function changeRole(u: AdminUser, role: string) {
    setErr('')
    try { await adminSetRole(u.id, role); await load() }
    catch (e) { setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Role change failed') }
  }
  async function toggleActive(u: AdminUser) {
    setErr('')
    try { await adminSetActive(u.id, !u.is_active); await load() }
    catch (e) { setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Update failed') }
  }

  return createPortal(
    <div className="cxmodal-back" onClick={onClose}>
      <div className="cxmodal" style={{ maxWidth: 720 }} onClick={e => e.stopPropagation()}>
        <div className="cxmodal-head">
          <span className="ic"><Users size={18} /></span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3>Team &amp; Roles</h3>
            <div className="env">admin: full control · analyst: investigate &amp; write · viewer: read-only</div>
          </div>
          <button className="x" onClick={onClose}><X size={16} /></button>
        </div>
        {err && <p style={{ fontSize: 12, color: 'rgb(var(--cx-red))', margin: '0 0 8px' }}>{err}</p>}
        <div className="cxadmin-modal-body">
          <table className="cxadmin-table">
            <thead><tr><th>User</th><th>Email</th><th>Role</th><th>Status</th><th>Last login</th></tr></thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id}>
                  <td style={{ color: 'rgb(var(--text-bright))', fontWeight: 600 }}>{u.name || '—'}{u.id === currentUserId && <span style={{ color: 'rgb(var(--text-muted))' }}> (you)</span>}</td>
                  <td style={{ fontFamily: "'Roboto Mono',monospace", fontSize: 11 }}>{u.email}</td>
                  <td>
                    <select className="cxselect" value={u.role} disabled={u.id === currentUserId} onChange={e => changeRole(u, e.target.value)}>
                      {roles.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                  <td>
                    <button className={`cxprof-statuspill ${u.is_active ? 'on' : 'off'}`} style={{ cursor: u.id === currentUserId ? 'default' : 'pointer' }}
                      disabled={u.id === currentUserId} onClick={() => toggleActive(u)}>
                      {u.is_active ? 'ACTIVE' : 'DEACTIVATED'}
                    </button>
                  </td>
                  <td style={{ fontSize: 11, color: 'rgb(var(--text-muted))' }}>{fmt(u.last_login_at)}</td>
                </tr>
              ))}
              {users.length === 0 && <tr><td colSpan={5} style={{ color: 'rgb(var(--text-muted))', textAlign: 'center', padding: 20 }}>No users.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>,
    document.body,
  )
}
