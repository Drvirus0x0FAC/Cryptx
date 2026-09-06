/**
 * BootScreen — Cinematic "Cyber Command Center" pre-login splash.
 *
 * Plays every time an unauthenticated user visits the app. Runs a staggered
 * system-initialization sequence (radar sweep, hash rain, boot log, progress
 * bar), then reveals a "START CRYPTX" button. The user must click it to
 * proceed to the login screen — there is no auto-redirect.
 *
 * Props:
 *   onComplete — called when the user clicks START CRYPTX (transitions to AuthScreen)
 *   onOpenDocs — called when the user clicks READ CRYPTX DOCS (opens the User Guide)
 */
import { useState, useEffect, useRef, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowRight, Check, Loader2, Lock, ShieldCheck, Power, BookOpen } from 'lucide-react'
import '../styles/boot-screen.css'

/* ── Boot sequence steps (staggered, ~4.5s total) ────────────────────────────
 * `labelKey` resolves via the `components:boot.steps.*` translations; `badge`
 * is a short uppercase token kept as-is across languages for the cyber look. */
const BOOT_STEPS = [
  { labelKey: 'components:boot.steps.kernel',  badge: null },
  { labelKey: 'components:boot.steps.chains',   badge: 'CHAINS' },
  { labelKey: 'components:boot.steps.aml',      badge: 'AML' },
  { labelKey: 'components:boot.steps.evidence', badge: 'EVIDENCE' },
  { labelKey: 'components:boot.steps.tunnel',   badge: 'NET' },
  { labelKey: 'components:boot.steps.ai',       badge: 'AI' },
  { labelKey: 'components:boot.steps.ready',    badge: null },
] as const

const STEP_DELAY = 620   // ms between each step
const STEP_OFFSET = 400  // ms before the first step

/* ── Hash rain characters (matrix-style) ───────────────────────────────────── */
const HASH_CHARS = '0123456789abcdefABCDEF░▒▓|/\\<>{}[]$#@%&*+='.split('')
const HASH_TOKENS = ['0x', 'bc1', 'ETH', 'BTC', 'TRX', 'AML', 'OFAC', 'CASE', 'TX', 'XMR', 'MIX', 'BRG']

function makeHashColumn() {
  const len = 12 + Math.floor(Math.random() * 18)
  const lines: string[] = []
  for (let i = 0; i < len; i++) {
    const useToken = Math.random() < 0.15
    if (useToken) {
      lines.push(HASH_TOKENS[Math.floor(Math.random() * HASH_TOKENS.length)])
    } else {
      const charCount = 1 + Math.floor(Math.random() * 4)
      let s = ''
      for (let j = 0; j < charCount; j++) s += HASH_CHARS[Math.floor(Math.random() * HASH_CHARS.length)]
      lines.push(s)
    }
  }
  return lines.join('\n')
}

/* ── Component ─────────────────────────────────────────────────────────────── */
export default function BootScreen({ onComplete, onOpenDocs }: { onComplete: () => void; onOpenDocs?: () => void }) {
  const { t } = useTranslation()
  const [completedSteps, setCompletedSteps] = useState(0)
  const [bootComplete, setBootComplete] = useState(false)
  const [exiting, setExiting] = useState(false)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  // Generate stable hash-rain columns once
  const hashColumns = useMemo(() => {
    const count = 18
    return Array.from({ length: count }, (_, i) => ({
      id: i,
      left: (i / count) * 100 + (Math.random() * 4 - 2),
      text: makeHashColumn(),
      duration: 6 + Math.random() * 8,
      delay: -Math.random() * 10,
      fontSize: 0.7 + Math.random() * 0.3,
    }))
  }, [])

  // Drive the staggered boot sequence
  useEffect(() => {
    BOOT_STEPS.forEach((_, i) => {
      const t = setTimeout(() => {
        setCompletedSteps(i + 1)
        if (i === BOOT_STEPS.length - 1) {
          setBootComplete(true)
        }
      }, STEP_OFFSET + i * STEP_DELAY)
      timers.current.push(t)
    })
    return () => {
      timers.current.forEach(clearTimeout)
    }
  }, [])

  const progress = Math.round((completedSteps / BOOT_STEPS.length) * 100)

  // Which badges are active (one becomes active per step that has a badge)
  const activeBadges = new Set<string>(
    BOOT_STEPS
      .slice(0, completedSteps)
      .map(s => s.badge)
      .filter((b): b is NonNullable<typeof b> => b !== null)
  )

  function handleStart() {
    setExiting(true)
    // Wait for exit animation, then tell App to swap to AuthScreen
    const t = setTimeout(onComplete, 550)
    timers.current.push(t)
  }

  return (
    <div className={`boot-screen${exiting ? ' exiting' : ''}`}>
      {/* Background layers */}
      <div className="boot-grid" />
      <div className="boot-vignette" />
      <div className="boot-hash-rain" aria-hidden="true">
        {hashColumns.map(col => (
          <span
            key={col.id}
            className="boot-hash-col"
            style={{
              left: `${col.left}%`,
              animationDuration: `${col.duration}s`,
              animationDelay: `${col.delay}s`,
              fontSize: `${col.fontSize}rem`,
            }}
          >
            {col.text}
          </span>
        ))}
      </div>
      <div className="boot-scanline" />
      <div className="boot-noise" />

      {/* Corner brackets */}
      <span className="boot-bracket tl" />
      <span className="boot-bracket tr" />
      <span className="boot-bracket bl" />
      <span className="boot-bracket br" />

      {/* Radar panel (top-left, desktop only) */}
      <div className="boot-radar-panel">
        <div className="boot-radar-label"><i /> {t('components:boot.threatRadar')}</div>
        <div className="boot-radar">
          <span className="boot-radar-ring r2" />
          <span className="boot-radar-ring r3" />
          <span className="boot-radar-cross-h" />
          <span className="boot-radar-cross-v" />
          <span className="boot-radar-sweep" />
          <span className="boot-radar-blip b1" />
          <span className="boot-radar-blip b2" />
          <span className="boot-radar-blip b3" />
          <span className="boot-radar-blip b4" />
          <span className="boot-radar-center" />
        </div>
      </div>

      {/* Status / log panel (top-right) */}
      <div className="boot-status-panel">
        <div className="boot-status-head">
          <span>{t('components:boot.systemBootLog')}</span>
          <span>{bootComplete ? t('components:boot.statusReady') : t('components:boot.statusInit')}</span>
        </div>
        <div className="boot-status-log">
          {BOOT_STEPS.map((step, i) => {
            const isDone = i < completedSteps
            const isActive = i === completedSteps && !bootComplete
            if (i > completedSteps) return null
            return (
              <div
                key={step.labelKey}
                className="boot-log-line"
                style={{ animationDelay: `${i * 0.05}s` }}
              >
                <span className="boot-log-prefix">$</span>
                <span className={`boot-log-text${isActive ? ' active' : ''}`}>{t(step.labelKey)}…</span>
                {isDone ? (
                  <span className="boot-log-ok">{t('components:boot.ok')}</span>
                ) : isActive ? (
                  <span className="boot-log-cursor" />
                ) : (
                  <span className="boot-log-pending">{t('components:boot.pending')}</span>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Central logo + orbit */}
      <div className="boot-center">
        <div className="boot-logo-wrap">
          <span className="boot-orbit o3" />
          <span className="boot-orbit o2" />
          <span className="boot-orbit o1" />
          <span className="boot-logo-glow g3" />
          <span className="boot-logo-glow g2" />
          <span className="boot-logo-glow" />
          <img src="/cryptx-icon.svg" alt="CrypTX" className="boot-logo" />
        </div>

        <h1 className="boot-brand">Cryp<b>TX</b></h1>
        <div className="boot-tagline">{t('components:boot.tagline')}</div>

        {/* Coverage badges */}
        <div className="boot-badges">
          {(['CHAINS', 'AML', 'EVIDENCE', 'NET', 'AI'] as const).map(badge => (
            <span key={badge} className={`boot-badge${activeBadges.has(badge) ? ' active' : ''}`}>
              <Check className="boot-check" />
              <Loader2 className="boot-spinner" />
              {badge}
            </span>
          ))}
        </div>

        {/* Progress bar */}
        <div className="boot-progress-wrap">
          <div className="boot-progress-meta">
            <span>{t('components:boot.bootSequence')}</span>
            <span className="boot-progress-pct">{progress}%</span>
          </div>
          <div className="boot-progress-track">
            <div className="boot-progress-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>

        {/* Ready indicator */}
        <div className={`boot-ready-indicator${bootComplete ? ' ready' : ''}`}>
          <i />
          {bootComplete ? t('components:boot.allSystemsNominal') : t('components:boot.initializing')}
        </div>

        {/* Action buttons — START CRYPTX + READ DOCS */}
        <div className="boot-btn-row">
          <button
            type="button"
            className={`boot-start-btn${bootComplete ? ' ready' : ''}`}
            onClick={handleStart}
            disabled={!bootComplete}
          >
            <Power size={18} />
            {t('components:boot.startCrypTX')}
            <ArrowRight size={18} />
          </button>

          <button
            type="button"
            className={`boot-docs-btn${bootComplete ? ' ready' : ''}`}
            onClick={() => onOpenDocs?.()}
          >
            <BookOpen size={18} />
            {t('components:boot.readDocs')}
          </button>
        </div>
      </div>

      {/* Bottom HUD corners */}
      <div className="boot-hud-corner boot-hud-bl">
        {t('components:boot.secureBoot')} <span>v2.4.1</span>
      </div>
      <div className="boot-hud-corner boot-hud-br">
        <Lock size={9} style={{ display: 'inline', verticalAlign: '-1px', marginRight: 4 }} />
        {t('components:boot.encryptedSession')} <span>·</span> <ShieldCheck size={9} style={{ display: 'inline', verticalAlign: '-1px', marginRight: 4 }} /> {t('components:boot.zeroTrust')}
      </div>
    </div>
  )
}
