import { FormEvent, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle, ArrowRight, Fingerprint, KeyRound, Loader2,
  LockKeyhole, Mail, ShieldCheck, UserPlus, Users, FlaskConical, Shield,
} from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import CyberAuthBackground from '../components/CyberAuthBackground'
import CryptoTxMap from '../components/CryptoTxMap'
import LanguagePicker from '../components/LanguagePicker'
import '../styles/auth-vault.css'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

const HASHES = [
  '0x71c4…9af', 'bc1q…4e2', 'TRX:swap', 'OFAC:clear', 'mixer:watch',
  '0x3ee1…585', 'ETH→BASE', 'cluster+7', 'demix:run', 'sanction:0',
  'hop 4/9', 'bridge:lz', 'usdt:flow', '0x9f2…d60', 'score:82',
]

export default function AuthScreen() {
  const { t } = useTranslation()
  const auth = useAuth()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [resetToken, setResetToken] = useState('')
  const [devToken, setDevToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [regType, setRegType] = useState<'researcher' | 'team_leader'>('researcher')
  const [teamName, setTeamName] = useState('')
  const [pending2FA, setPending2FA] = useState(false)
  const [pendingToken, setPendingToken] = useState('')
  const [twoFACode, setTwoFACode] = useState('')

  const title = useMemo(() => {
    if (auth.mode === 'register') return t('auth:modes.register')
    if (auth.mode === 'forgot') return t('auth:modes.forgot')
    if (auth.mode === 'reset') return t('auth:modes.reset')
    return t('auth:modes.login')
  }, [auth.mode, t])

  const kicker = auth.mode === 'forgot' ? t('auth:kicker.resetChannel')
    : auth.mode === 'reset' ? t('auth:kicker.credentialRotation') : t('auth:kicker.secureSession')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError(''); setNotice('')
    try {
      if (auth.mode === 'register') {
        if (password !== confirm) throw new Error(t('auth:errors.passwordsDoNotMatch'))
        if (regType === 'team_leader' && !teamName.trim()) throw new Error('Team name is required')
        await auth.signUp({ email, password, name, registration_type: regType, team_name: regType === 'team_leader' ? teamName : undefined })
      } else if (auth.mode === 'forgot') {
        const res = await auth.forgotPassword(email)
        setNotice(t('auth:notices.recoveryAccepted'))
        if (res.dev_reset_token) {
          setDevToken(res.dev_reset_token)
          setResetToken(res.dev_reset_token)
          auth.setMode('reset')
        }
      } else if (auth.mode === 'reset') {
        if (password !== confirm) throw new Error(t('auth:errors.passwordsDoNotMatch'))
        await auth.completeReset(resetToken, password)
        setNotice(t('auth:notices.passwordUpdated'))
        setPassword(''); setConfirm(''); setResetToken('')
      } else {
        const result = await auth.signIn(email, password)
        if (result.requires_2fa && result.pending_token) {
          setPending2FA(true)
          setPendingToken(result.pending_token)
          setBusy(false)
          return
        }
      }
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setBusy(false)
    }
  }

  async function submit2FA(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      await auth.signIn2FA(pendingToken, twoFACode)
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setBusy(false)
    }
  }

  const onSignup = auth.mode === 'register'

  return (
    <div className="cxv-root">
      <CyberAuthBackground />
      <div className="cxv-grid" />
      <div className="cxv-vignette" />

      {/* Side data streams */}
      <div className="cxv-stream cxv-stream-l" aria-hidden="true">
        {[...HASHES, ...HASHES].map((h, i) => <span key={`l-${i}`}>{h}</span>)}
      </div>
      <div className="cxv-stream cxv-stream-r" aria-hidden="true">
        {[...HASHES, ...HASHES].map((h, i) => <span key={`r-${i}`}>{h}</span>)}
      </div>

      {/* Floating intel chips */}
      <div className="cxv-chip cxv-chip-1" aria-hidden="true"><b>{t('auth:chips.txTrace')}</b><span>{t('auth:chips.hops', { count: 7 })}</span></div>
      <div className="cxv-chip cxv-chip-2" aria-hidden="true"><b>{t('auth:chips.amlScore')}</b><span>82 / 100</span></div>
      <div className="cxv-chip cxv-chip-3" aria-hidden="true"><b>{t('auth:chips.bridge')}</b><span>ETH → BASE</span></div>
      <div className="cxv-chip cxv-chip-4" aria-hidden="true"><b>{t('auth:chips.sanctions')}</b><span>{t('auth:chips.clear')}</span></div>

      <main className="cxv-console">
        {/* ── Brand stage (left) ── */}
        <section className="cxv-stage">
          <div className="cxv-logo-badge">
            <img src="/cryptx-logo-full.png" alt="CrypTX" />
          </div>
          <div className="cxv-brand">
            <h1>Cryp<span>TX</span></h1>
            <p className="cxv-tag">{t('auth:stage.tagline')}</p>
          </div>

          <CryptoTxMap />

          <p className="cxv-pitch">
            {t('auth:stage.pitch')}
          </p>

          <div className="cxv-signals" aria-hidden="true">
            <div className="cxv-signal" style={{ animationDelay: '0.1s' }}><i /> {t('auth:stage.signal1')}</div>
            <div className="cxv-signal" style={{ animationDelay: '0.25s' }}><i /> {t('auth:stage.signal2')}</div>
            <div className="cxv-signal" style={{ animationDelay: '0.4s' }}><i /> {t('auth:stage.signal3')}</div>
          </div>
        </section>

        {/* ── Access card (right) ── */}
        <section className="cxv-card-wrap">
        <div className="cxv-card">
          <div className="cxv-hud" aria-hidden="true">
            <span>{t('auth:hud.sessionVault')}</span>
            <span>{t('auth:hud.tokenRotation')}</span>
            <span>{t('auth:hud.amlAccess')}</span>
          </div>

          <div className="cxv-seg">
            <div className={`cxv-seg-pill${onSignup ? ' right' : ''}`} aria-hidden="true" />
            <button className={!onSignup ? 'on' : ''} onClick={() => auth.setMode('login')}>{t('auth:tabs.login')}</button>
            <button className={onSignup ? 'on' : ''} onClick={() => auth.setMode('register')}>{t('auth:tabs.signup')}</button>
          </div>

          {/* 2FA Verification Step */}
          {pending2FA ? (
            <form onSubmit={submit2FA} className="cxv-form">
              <div className="cxv-form-head" style={{ textAlign: 'center' }}>
                <Shield size={28} style={{ color: 'rgb(var(--accent-blue, 56 224 255))', marginBottom: 6 }} />
                <p className="cxv-kicker">Two-Factor Authentication</p>
                <h3>Enter your authenticator code</h3>
              </div>
              <label className="cxv-field">
                <KeyRound size={16} />
                <input
                  value={twoFACode}
                  onChange={e => setTwoFACode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="000000"
                  maxLength={6}
                  autoFocus
                  required
                  style={{ textAlign: 'center', fontSize: 20, letterSpacing: 8, fontFamily: "'Roboto Mono', monospace" }}
                />
              </label>
              {error && <div className="cxv-alert"><AlertTriangle size={14} /> {error}</div>}
              <button className="cxv-submit" disabled={busy || twoFACode.length !== 6}>
                {busy ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
                Verify
                {!busy && <ArrowRight size={15} />}
              </button>
              <div className="cxv-links">
                <button type="button" onClick={() => { setPending2FA(false); setPendingToken(''); setTwoFACode(''); setError('') }}>
                  {t('auth:links.backToLogin')}
                </button>
              </div>
            </form>
          ) : (
          <form onSubmit={submit} className="cxv-form">
            <div className="cxv-form-head">
              <p className="cxv-kicker">{kicker}</p>
              <h3>{title}</h3>
            </div>

            {auth.mode === 'register' && (
              <label className="cxv-field">
                <UserPlus size={16} />
                <input value={name} onChange={e => setName(e.target.value)} placeholder={t('auth:placeholders.analystName')} autoComplete="name" />
              </label>
            )}

            {auth.mode === 'register' && (
              <div className="cxv-role-select">
                <button
                  type="button"
                  className={`cxv-role-card${regType === 'researcher' ? ' active' : ''}`}
                  onClick={() => setRegType('researcher')}
                >
                  <FlaskConical size={18} />
                  <span>Researcher</span>
                  <small>Individual account</small>
                </button>
                <button
                  type="button"
                  className={`cxv-role-card${regType === 'team_leader' ? ' active' : ''}`}
                  onClick={() => setRegType('team_leader')}
                >
                  <Users size={18} />
                  <span>Team Leader</span>
                  <small>Manage a team</small>
                </button>
              </div>
            )}

            {auth.mode === 'register' && regType === 'team_leader' && (
              <label className="cxv-field">
                <Users size={16} />
                <input value={teamName} onChange={e => setTeamName(e.target.value)} placeholder="Team / Organization name" required />
              </label>
            )}

            {auth.mode !== 'reset' && (
              <label className="cxv-field">
                <Mail size={16} />
                <input value={email} onChange={e => setEmail(e.target.value)} placeholder={t('auth:placeholders.workEmail')} type="email" autoComplete="email" required />
              </label>
            )}

            {auth.mode === 'reset' && (
              <label className="cxv-field">
                <KeyRound size={16} />
                <input value={resetToken} onChange={e => setResetToken(e.target.value)} placeholder={t('auth:placeholders.resetToken')} required />
              </label>
            )}

            {auth.mode !== 'forgot' && (
              <label className="cxv-field">
                <LockKeyhole size={16} />
                <input value={password} onChange={e => setPassword(e.target.value)} placeholder={t('auth:placeholders.password')} type="password" autoComplete={auth.mode === 'login' ? 'current-password' : 'new-password'} required />
              </label>
            )}

            {(auth.mode === 'register' || auth.mode === 'reset') && (
              <label className="cxv-field">
                <Fingerprint size={16} />
                <input value={confirm} onChange={e => setConfirm(e.target.value)} placeholder={t('auth:placeholders.confirmPassword')} type="password" autoComplete="new-password" required />
              </label>
            )}

            {error && <div className="cxv-alert"><AlertTriangle size={14} /> {error}</div>}
            {notice && <div className="cxv-notice"><ShieldCheck size={14} /> {notice}</div>}
            {devToken && (
              <div className="cxv-devtoken">
                <span>{t('auth:devtoken.label')}</span>
                <code>{devToken}</code>
              </div>
            )}

            <button className="cxv-submit" disabled={busy}>
              {busy ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
              {auth.mode === 'register' ? t('auth:submit.register') : auth.mode === 'forgot' ? t('auth:submit.forgot') : auth.mode === 'reset' ? t('auth:submit.reset') : t('auth:submit.login')}
              {!busy && <ArrowRight size={15} />}
            </button>

            <div className="cxv-links">
              {auth.mode === 'login' && <button type="button" onClick={() => auth.setMode('forgot')}>{t('auth:links.forgotPassword')}</button>}
              {auth.mode === 'forgot' && <button type="button" onClick={() => auth.setMode('login')}>{t('auth:links.backToLogin')}</button>}
              {auth.mode !== 'reset' && <button type="button" onClick={() => auth.setMode('reset')}>{t('auth:links.haveResetToken')}</button>}
            </div>
          </form>
          )}

          {/* Language picker — useful before first login (no prefs UI reachable yet). */}
          <div className="cxv-lang">
            <LanguagePicker variant="full" />
          </div>
        </div>

        <p className="cxv-foot"><ShieldCheck size={13} /> {t('auth:foot')}</p>
        </section>
      </main>
    </div>
  )
}
