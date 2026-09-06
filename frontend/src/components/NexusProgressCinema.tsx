/**
 * NexusProgressCinema — the cinematic run screen for a Nexus investigation.
 *
 * Replaces the old three-line "phase 1 / phase 2 / phase 3" checklist with a
 * centred mission-control sequence: a segmented hero dial, a master transport
 * bar, per-phase instrument cards, a live time-distribution pie and a rolling
 * telemetry feed fed by the real pipeline events.
 *
 * Honesty note: every number rendered here is derived from real run state.
 * Intra-phase motion (the arc creeping forward while a request is in flight)
 * is an explicitly-capped time estimate — it never reaches 100 % until the
 * pipeline actually reports the phase as finished, and it is labelled as an
 * estimate wherever it is surfaced as a figure.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity, AlertTriangle, Ban, Check, GitBranch, Loader2, Network, Radar, Search, Terminal,
} from 'lucide-react'

export type CinemaPhaseState = 'idle' | 'running' | 'ok' | 'skipped' | 'error'
export type CinemaPhaseId = 'intel' | 'trace' | 'nexus'

export interface CinemaLogEntry {
  id: number
  t: number
  phase: 'intel' | 'trace' | 'nexus' | 'run'
  level: 'info' | 'ok' | 'warn' | 'error'
  text: string
}

interface Props {
  phases: Record<string, CinemaPhaseState>
  phaseMsg: Record<string, string>
  log: CinemaLogEntry[]
  running: boolean
  error?: string | null
  startedAt: number | null
  finishedAt: number | null
  target: string
  chain: string
  hops: number
  includeAi: boolean
  /** Present once the nexus build lands — drives the completion read-out. */
  summary?: {
    nodes: number
    edges: number
    links: number
    clusters: number
    highRisk: number
    threatLevel?: string
    threatScore?: number
  } | null
  onOpenGraph?: () => void
}

// Phase catalogue: weight = share of the master bar, tau = the time constant
// used to ease the in-flight arc forward while we wait on the network.
const PHASES: Array<{
  id: CinemaPhaseId
  label: string
  short: string
  code: string
  desc: string
  icon: typeof Search
  weight: number
}> = [
  { id: 'intel', label: 'Address Intelligence', short: 'Intel', code: 'P1', desc: 'Identity · labels · risk scoring', icon: Search, weight: 0.18 },
  { id: 'trace', label: 'Transaction Trace', short: 'Trace', code: 'P2', desc: 'Multi-hop cross-chain fund flow', icon: GitBranch, weight: 0.37 },
  { id: 'nexus', label: 'Nexus Correlation', short: 'Nexus', code: 'P3', desc: 'Graph fusion · behavioural links', icon: Network, weight: 0.45 },
]

const TONE: Record<CinemaPhaseState, { rgb: string; word: string }> = {
  idle:    { rgb: 'var(--text-muted)',   word: 'STANDBY' },
  running: { rgb: 'var(--accent-blue)',  word: 'ENGAGED' },
  ok:      { rgb: 'var(--accent-green)', word: 'COMPLETE' },
  skipped: { rgb: 'var(--accent-amber)', word: 'SKIPPED' },
  error:   { rgb: 'var(--accent-red)',   word: 'FAILED' },
}

/** Monochrome ramp for the time-split pie — reads cleanly on both shells. */
const PIE_SHADE = [0.78, 0.46, 0.24]

const LEVEL_RGB: Record<CinemaLogEntry['level'], string> = {
  info:  'var(--accent-blue)',
  ok:    'var(--accent-green)',
  warn:  'var(--accent-amber)',
  error: 'var(--accent-red)',
}

function fmtClock(ms: number) {
  if (!Number.isFinite(ms) || ms < 0) ms = 0
  const total = Math.floor(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function fmtOffset(ms: number) {
  const s = ms / 1000
  return `+${s < 100 ? s.toFixed(1) : Math.round(s)}s`
}

/** Number that eases toward its target so completion figures count up. */
function Odometer({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const [shown, setShown] = useState(value)
  const raf = useRef<number | undefined>(undefined)
  const from = useRef(value)
  const start = useRef(0)

  useEffect(() => {
    from.current = shown
    start.current = performance.now()
    const dur = 780
    const tick = (now: number) => {
      const p = Math.min(1, (now - start.current) / dur)
      const eased = 1 - Math.pow(1 - p, 3)
      setShown(from.current + (value - from.current) * eased)
      if (p < 1) raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => { if (raf.current) cancelAnimationFrame(raf.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  return <>{shown.toFixed(decimals)}</>
}

/** Deterministic drifting motes so the backdrop never re-randomises on render. */
const MOTES = Array.from({ length: 16 }, (_, i) => ({
  left: `${(i * 61) % 97}%`,
  top: `${55 + ((i * 37) % 45)}%`,
  dur: `${11 + ((i * 7) % 9)}s`,
  delay: `${-((i * 13) % 14)}s`,
  dx: `${((i % 5) - 2) * 18}px`,
}))

export default function NexusProgressCinema({
  phases, phaseMsg, log, running, error, startedAt, finishedAt,
  target, chain, hops, includeAi, summary, onOpenGraph,
}: Props) {
  const [now, setNow] = useState(() => Date.now())
  const feedRef = useRef<HTMLDivElement | null>(null)

  // Heartbeat — only while the run is live.
  useEffect(() => {
    if (!running) { setNow(Date.now()); return }
    const h = window.setInterval(() => setNow(Date.now()), 120)
    return () => window.clearInterval(h)
  }, [running])

  // Per-phase clocks, captured from real state transitions.
  const clocks = useRef<Record<string, { start?: number; end?: number }>>({})
  useEffect(() => {
    if (startedAt === null) clocks.current = {}
  }, [startedAt])
  useEffect(() => {
    for (const { id } of PHASES) {
      const st = phases[id]
      const c = (clocks.current[id] ||= {})
      if (st === 'running' && c.start === undefined) { c.start = Date.now(); c.end = undefined }
      if (st !== 'running' && st !== 'idle' && c.start !== undefined && c.end === undefined) c.end = Date.now()
    }
  }, [phases])

  const elapsed = startedAt === null ? 0 : (finishedAt ?? now) - startedAt
  const isDone = !running && !error && !!summary
  const isError = !!error

  // Expected wall-clock per phase — used only for the in-flight easing and the
  // "est. remaining" read-out, never to declare a phase finished.
  const expected = useMemo(() => ({
    intel: 14_000,
    trace: chain === 'eth' || chain === 'auto' ? 70_000 : 40_000,
    nexus: includeAi ? 140_000 : 45_000,
  }), [chain, includeAi])

  const phaseProgress = useMemo(() => {
    const out: Record<string, number> = {}
    for (const { id } of PHASES) {
      const st = phases[id]
      if (st === 'ok' || st === 'skipped' || st === 'error') { out[id] = 1; continue }
      if (st !== 'running') { out[id] = 0; continue }
      const c = clocks.current[id]
      const inFlight = c?.start ? now - c.start : 0
      // Asymptotic ease, hard-capped below 100 % until the pipeline confirms.
      out[id] = Math.min(0.93, 1 - Math.exp(-inFlight / (expected[id as CinemaPhaseId] * 0.55)))
    }
    return out
  }, [phases, now, expected])

  // A phase that FAILED contributes nothing to the master figure — the run did
  // not get that work. A phase that was legitimately skipped does count, since
  // the pipeline resolved it and moved on.
  const overall = useMemo(() => {
    if (isDone) return 1
    return PHASES.reduce((acc, p) => acc + p.weight * (phases[p.id] === 'error' ? 0 : (phaseProgress[p.id] ?? 0)), 0)
  }, [phaseProgress, phases, isDone])

  const remaining = useMemo(() => {
    if (isDone || isError) return 0
    const total = PHASES.reduce((acc, p) => acc + expected[p.id] * (1 - (phaseProgress[p.id] ?? 0)), 0)
    return total
  }, [expected, phaseProgress, isDone, isError])

  // Real time-distribution across phases → the pie.
  const slices = useMemo(() => {
    const rows = PHASES.map(p => {
      const c = clocks.current[p.id]
      const ms = c?.start ? (c.end ?? now) - c.start : 0
      return { id: p.id, label: p.label, code: p.code, ms: Math.max(0, ms) }
    })
    const total = rows.reduce((a, r) => a + r.ms, 0)
    return { rows, total }
  }, [now, phases])

  // Autoscroll the telemetry feed to the newest line.
  useEffect(() => {
    const el = feedRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [log.length])

  const doneCount = PHASES.filter(p => phases[p.id] === 'ok').length
  const activePhase = PHASES.find(p => phases[p.id] === 'running')
  const accent = isError ? 'var(--accent-red)' : isDone ? 'var(--accent-green)' : 'var(--accent-blue)'

  // ── Hero dial geometry ──────────────────────────────────────────────────
  const SIZE = 248
  const C = SIZE / 2
  const R = 96
  const CIRC = 2 * Math.PI * R
  const GAP = CIRC * 0.02
  let cursor = 0
  const arcs = PHASES.map(p => {
    const seg = CIRC * p.weight
    const start = cursor
    cursor += seg
    const st = phases[p.id]
    return {
      id: p.id,
      offset: -start,
      len: Math.max(0, seg - GAP),
      fill: Math.max(0, seg - GAP) * (phaseProgress[p.id] ?? 0),
      rgb: st === 'error' ? 'var(--accent-red)' : st === 'skipped' ? 'var(--accent-amber)' : st === 'ok' ? 'var(--accent-green)' : 'var(--accent-blue)',
    }
  })

  return (
    <div className={`nxc ${isDone ? 'nxc--done nxc-flash' : ''} ${isError ? 'nxc--error' : ''}`}>
      {/* ── Backdrop ─────────────────────────────────────────────────────── */}
      <div className="nxc-bg" aria-hidden>
        <div className="nxc-grid" />
        {running && <div className="nxc-scan" />}
        {running && MOTES.map((m, i) => (
          <span key={i} className="nxc-particle" style={{
            left: m.left, top: m.top,
            ['--dur' as string]: m.dur, ['--delay' as string]: m.delay, ['--dx' as string]: m.dx,
          }} />
        ))}
        {isDone && <div className="nxc-sweep" />}
      </div>

      {/* ── Content ──────────────────────────────────────────────────────── */}
      <div className="relative z-10 flex w-full flex-col gap-5 px-6 py-6 lg:px-8 lg:py-7">

        {/* Title row */}
        <div className="nxc-rise flex flex-wrap items-center justify-between gap-3" style={{ ['--delay' as string]: '0s' }}>
          <div className="flex items-center gap-3">
            <Radar size={16} style={{ color: `rgb(${accent})` }} className={running ? 'animate-spin' : ''} />
            <div>
              <p className="m-0 text-[11px] font-bold uppercase tracking-[0.32em]" style={{ color: `rgb(${accent})` }}>
                {isError ? 'Investigation aborted' : isDone ? 'Investigation complete' : 'Nexus synthesis in progress'}
              </p>
              <p className="m-0 mt-1 font-mono text-[11px] break-all" style={{ color: 'rgb(var(--text-secondary))' }}>
                {target || '—'}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {[
              { k: 'chain', v: (chain === 'auto' ? 'AUTO' : chain.toUpperCase()) },
              { k: 'depth', v: `${hops} hop${hops === 1 ? '' : 's'}` },
              { k: 'ai', v: includeAi ? 'synthesis on' : 'synthesis off' },
            ].map(b => (
              <span key={b.k} className="rounded-md px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider"
                style={{ color: 'rgb(var(--text-secondary))', background: 'rgb(var(--bg-border) / 0.22)', border: '1px solid rgb(var(--bg-border) / 0.4)' }}>
                {b.v}
              </span>
            ))}
            {isDone && onOpenGraph && (
              <button type="button" onClick={onOpenGraph}
                className="flex cursor-pointer items-center gap-2 rounded-lg px-4 py-2 text-xs font-bold text-white"
                style={{
                  background: 'linear-gradient(135deg, rgb(var(--accent-blue)), rgb(var(--accent-purple)))',
                  border: '1px solid rgb(var(--accent-blue) / 0.5)',
                  boxShadow: '0 0 20px rgb(var(--accent-blue) / 0.3)',
                }}>
                <GitBranch size={13} /> Open Graph
              </button>
            )}
          </div>
        </div>

        {/* Hero row: dial + instrumentation */}
        <div className="nxc-rise grid grid-cols-1 items-center gap-7 lg:grid-cols-[248px_minmax(0,1fr)]" style={{ ['--delay' as string]: '0.06s' }}>

          {/* Segmented hero dial */}
          <div className="relative mx-auto" style={{ width: SIZE, height: SIZE }}>
            <svg width={SIZE} height={SIZE} style={{ overflow: 'visible' }}>
              {/* rotating tick ring */}
              <g className="nxc-ticks" style={{ transformOrigin: `${C}px ${C}px` }}>
                {Array.from({ length: 72 }, (_, i) => {
                  const a = (i / 72) * Math.PI * 2
                  const r1 = R + 22
                  const r2 = R + (i % 6 === 0 ? 30 : 26)
                  return (
                    <line key={i}
                      x1={C + Math.cos(a) * r1} y1={C + Math.sin(a) * r1}
                      x2={C + Math.cos(a) * r2} y2={C + Math.sin(a) * r2}
                      stroke={`rgb(${accent} / ${i % 6 === 0 ? 0.5 : 0.2})`} strokeWidth={i % 6 === 0 ? 1.6 : 1} />
                  )
                })}
              </g>

              {/* halo pulse */}
              {running && <circle className="nxc-halo" cx={C} cy={C} r={R + 14} fill="none" stroke={`rgb(${accent} / 0.35)`} strokeWidth={1.5} style={{ transformOrigin: `${C}px ${C}px` }} />}

              <g transform={`rotate(-90 ${C} ${C})`}>
                {/* segment tracks */}
                {arcs.map(a => (
                  <circle key={`t-${a.id}`} cx={C} cy={C} r={R} fill="none"
                    stroke="rgb(var(--bg-border) / 0.35)" strokeWidth={14} strokeLinecap="round"
                    strokeDasharray={`${a.len} ${CIRC - a.len}`} strokeDashoffset={a.offset} />
                ))}
                {/* segment fills — a zero-length dash would still paint a dot
                    under strokeLinecap="round", so empty segments are skipped */}
                {arcs.filter(a => a.fill > 0.6).map(a => (
                  <circle key={`f-${a.id}`} cx={C} cy={C} r={R} fill="none"
                    stroke={`rgb(${a.rgb})`} strokeWidth={14} strokeLinecap="round"
                    strokeDasharray={`${a.fill} ${CIRC - a.fill}`} strokeDashoffset={a.offset}
                    style={{
                      transition: 'stroke-dasharray 0.55s cubic-bezier(0.4,0,0.2,1), stroke 0.4s ease',
                      filter: `drop-shadow(0 0 7px rgb(${a.rgb} / 0.55))`,
                    }} />
                ))}
              </g>

              {/* counter-rotating inner reticle */}
              <g className="nxc-orbit-r" style={{ transformOrigin: `${C}px ${C}px` }}>
                <circle cx={C} cy={C} r={R - 26} fill="none" stroke={`rgb(${accent} / 0.18)`} strokeWidth={1} strokeDasharray="3 9" />
              </g>
            </svg>

            <div className="absolute inset-0 flex flex-col items-center justify-center">
              {isError ? (
                <AlertTriangle size={30} style={{ color: 'rgb(var(--accent-red))' }} />
              ) : (
                <>
                  <p className="m-0 font-mono text-[40px] font-extrabold leading-none tabular-nums"
                    style={{ color: 'rgb(var(--text-bright))', letterSpacing: '-0.03em' }}>
                    <Odometer value={Math.round(overall * 100)} />
                    <span className="text-[18px] font-bold" style={{ color: `rgb(${accent})` }}>%</span>
                  </p>
                  <p className="m-0 mt-1.5 text-[9px] font-bold uppercase tracking-[0.28em]" style={{ color: 'rgb(var(--text-muted))' }}>
                    {isDone ? 'synthesised' : 'estimated'}
                  </p>
                  <p className="m-0 mt-2.5 max-w-[150px] truncate text-center font-mono text-[10px] uppercase tracking-[0.14em]"
                    style={{ color: `rgb(${accent} / 0.9)` }}>
                    {isDone ? 'all phases clear' : activePhase ? `${activePhase.code} · ${activePhase.short}` : 'standing by'}
                  </p>
                </>
              )}
            </div>
          </div>

          {/* Right column */}
          <div className="flex flex-col gap-4">

            {/* Master transport bar */}
            <div>
              <div className="mb-2 flex items-end justify-between">
                <span className="text-[10px] font-bold uppercase tracking-[0.24em]" style={{ color: 'rgb(var(--text-muted))' }}>
                  Master pipeline
                </span>
                <span className="font-mono text-[10px] tabular-nums" style={{ color: 'rgb(var(--text-muted))' }}>
                  {isDone ? 'finished' : isError ? 'halted' : remaining > 1500 ? `est. ${fmtClock(remaining)} remaining` : 'any moment now'}
                </span>
              </div>
              <div className="relative h-2 overflow-hidden rounded-full" style={{ background: 'rgb(var(--bg-border) / 0.28)' }}>
                <div className="absolute inset-y-0 left-0 rounded-full"
                  style={{
                    width: `${Math.max(2, overall * 100)}%`,
                    background: `linear-gradient(90deg, rgb(${accent} / 0.7), rgb(${accent}))`,
                    boxShadow: `0 0 14px rgb(${accent} / 0.55)`,
                    transition: 'width 0.55s cubic-bezier(0.4,0,0.2,1)',
                  }} />
                {running && <div className="nxc-shimmer" />}
              </div>
            </div>

            {/* Instrument tiles + pie */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_150px]">
              <div className="grid grid-cols-2 gap-2.5 xl:grid-cols-4">
                {[
                  { label: 'Elapsed', value: fmtClock(elapsed), mono: true },
                  { label: 'Phases', value: `${doneCount}/3` },
                  { label: 'Events', value: String(log.length) },
                  summary
                    ? { label: 'Nodes', value: String(summary.nodes) }
                    : { label: 'Hops', value: String(hops) },
                ].map(tile => (
                  <div key={tile.label} className="rounded-lg px-3 py-2.5"
                    style={{ background: 'rgb(var(--bg-primary) / 0.55)', border: '1px solid rgb(var(--bg-border) / 0.35)' }}>
                    <p className={`m-0 text-[17px] font-extrabold leading-none tabular-nums ${tile.mono ? 'font-mono' : ''}`}
                      style={{ color: 'rgb(var(--text-bright))' }}>{tile.value}</p>
                    <p className="m-0 mt-1.5 text-[9px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'rgb(var(--text-muted))' }}>{tile.label}</p>
                  </div>
                ))}
              </div>

              {/* Time-distribution pie — real per-phase wall clock */}
              <div className="rounded-lg px-3 py-2.5"
                style={{ background: 'rgb(var(--bg-primary) / 0.55)', border: '1px solid rgb(var(--bg-border) / 0.35)' }}>
                <p className="m-0 mb-1.5 text-[9px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'rgb(var(--text-muted))' }}>
                  Time split
                </p>
                <div className="flex items-center gap-3">
                  <svg width={54} height={54} viewBox="0 0 54 54" className="shrink-0">
                    <g transform="rotate(-90 27 27)">
                      <circle cx={27} cy={27} r={19} fill="none" stroke="rgb(var(--bg-border) / 0.35)" strokeWidth={9} />
                      {(() => {
                        const CC = 2 * Math.PI * 19
                        let off = 0
                        return slices.rows.map((r, i) => {
                          const frac = slices.total > 0 ? r.ms / slices.total : 0
                          const len = frac * CC
                          const node = (
                            <circle key={r.id} cx={27} cy={27} r={19} fill="none"
                              stroke={`rgb(var(--text-bright) / ${PIE_SHADE[i]})`} strokeWidth={9}
                              strokeDasharray={`${Math.max(0, len - 1)} ${CC}`} strokeDashoffset={-off}
                              style={{ transition: 'stroke-dasharray 0.5s ease, stroke-dashoffset 0.5s ease' }} />
                          )
                          off += len
                          return node
                        })
                      })()}
                    </g>
                  </svg>
                  <div className="flex min-w-0 flex-col gap-1">
                    {slices.rows.map((r, i) => (
                      <div key={r.id} className="flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: `rgb(var(--text-bright) / ${PIE_SHADE[i]})` }} />
                        <span className="font-mono text-[9px] tabular-nums" style={{ color: 'rgb(var(--text-secondary))' }}>
                          {r.code} {slices.total > 0 ? `${(r.ms / 1000).toFixed(1)}s` : '—'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Phase instrument cards */}
        <div className="nxc-rise grid grid-cols-1 gap-3 md:grid-cols-3" style={{ ['--delay' as string]: '0.12s' }}>
          {PHASES.map(({ id, label, code, desc, icon: Icon }) => {
            const st = phases[id] ?? 'idle'
            const tone = TONE[st]
            const pct = (phaseProgress[id] ?? 0) * 100
            const msg = phaseMsg[id]
            const c = clocks.current[id]
            const took = c?.start ? ((c.end ?? now) - c.start) / 1000 : 0
            return (
              <div key={id} className="relative overflow-hidden rounded-xl p-3.5"
                style={{
                  background: st === 'idle' ? 'rgb(var(--bg-primary) / 0.4)' : `rgb(${tone.rgb} / 0.05)`,
                  border: `1px solid rgb(${st === 'idle' ? 'var(--bg-border) / 0.35' : `${tone.rgb} / 0.35`})`,
                }}>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                      style={{ background: `rgb(${tone.rgb} / 0.12)` }}>
                      {st === 'ok' ? <Check size={15} style={{ color: `rgb(${tone.rgb})` }} />
                        : st === 'running' ? <Loader2 size={15} className="animate-spin" style={{ color: `rgb(${tone.rgb})` }} />
                        : st === 'error' ? <AlertTriangle size={15} style={{ color: `rgb(${tone.rgb})` }} />
                        : st === 'skipped' ? <Ban size={15} style={{ color: `rgb(${tone.rgb})` }} />
                        : <Icon size={15} style={{ color: 'rgb(var(--text-muted))', opacity: 0.55 }} />}
                    </div>
                    <div className="min-w-0">
                      <p className="m-0 text-[12px] font-bold" style={{ color: 'rgb(var(--text-bright))' }}>{label}</p>
                      <p className="m-0 mt-0.5 text-[10px]" style={{ color: 'rgb(var(--text-muted))' }}>{desc}</p>
                    </div>
                  </div>
                  <span className="shrink-0 rounded px-1.5 py-0.5 font-mono text-[8px] font-bold tracking-[0.14em]"
                    style={{ color: `rgb(${tone.rgb})`, background: `rgb(${tone.rgb} / 0.12)` }}>
                    {tone.word}
                  </span>
                </div>

                <div className="relative mt-3 h-1.5 overflow-hidden rounded-full" style={{ background: 'rgb(var(--bg-border) / 0.3)' }}>
                  <div className="absolute inset-y-0 left-0 rounded-full"
                    style={{
                      width: `${pct}%`,
                      background: `rgb(${tone.rgb})`,
                      boxShadow: `0 0 10px rgb(${tone.rgb} / 0.6)`,
                      transition: 'width 0.55s cubic-bezier(0.4,0,0.2,1)',
                    }} />
                  {st === 'running' && <div className="nxc-shimmer" />}
                </div>

                <div className="mt-2 flex items-center justify-between gap-2">
                  <span className="font-mono text-[9px] tracking-wider" style={{ color: 'rgb(var(--text-muted))' }}>{code}</span>
                  <span className="font-mono text-[9px] tabular-nums" style={{ color: 'rgb(var(--text-muted))' }}>
                    {took > 0 ? `${took.toFixed(1)}s` : '—'}
                  </span>
                </div>

                {msg && (
                  <p className="m-0 mt-2 line-clamp-3 text-[10px] leading-relaxed" style={{ color: 'rgb(var(--text-secondary))' }}>
                    {msg}
                  </p>
                )}
              </div>
            )
          })}
        </div>

        {/* Telemetry feed */}
        <div className="nxc-rise overflow-hidden rounded-xl" style={{
          border: '1px solid rgb(var(--bg-border) / 0.35)',
          background: 'rgb(var(--bg-primary) / 0.62)',
          ['--delay' as string]: '0.18s',
        }}>
          <div className="flex items-center justify-between px-3.5 py-2"
            style={{ borderBottom: '1px solid rgb(var(--bg-border) / 0.3)' }}>
            <span className="flex items-center gap-2 text-[9px] font-bold uppercase tracking-[0.24em]" style={{ color: 'rgb(var(--text-muted))' }}>
              <Terminal size={11} /> Live telemetry
            </span>
            <div className="flex items-center gap-2">
              {running && (
                <div className="nxc-eq flex h-3 items-end gap-[2px]">
                  {[0, 1, 2, 3, 4].map(i => <span key={i} style={{ ['--delay' as string]: `${i * 0.13}s` }} />)}
                </div>
              )}
              <span className="font-mono text-[9px] tabular-nums" style={{ color: 'rgb(var(--text-muted))' }}>
                {log.length} event{log.length === 1 ? '' : 's'}
              </span>
            </div>
          </div>
          <div ref={feedRef} className="max-h-[168px] min-h-[92px] overflow-y-auto px-3.5 py-2.5">
            {log.length === 0 ? (
              <p className="m-0 font-mono text-[10px]" style={{ color: 'rgb(var(--text-muted))' }}>awaiting first event…</p>
            ) : log.map(e => (
              <div key={e.id} className="nxc-log-line flex items-baseline gap-2 py-[3px] font-mono text-[10px] leading-relaxed">
                <span className="shrink-0 tabular-nums" style={{ color: 'rgb(var(--text-dim))' }}>
                  {startedAt ? fmtOffset(e.t - startedAt) : ''}
                </span>
                <span className="shrink-0 rounded px-1 text-[8px] uppercase tracking-wider"
                  style={{ color: `rgb(${LEVEL_RGB[e.level]})`, background: `rgb(${LEVEL_RGB[e.level]} / 0.12)` }}>
                  {e.phase}
                </span>
                <span className="min-w-0 break-words" style={{ color: e.level === 'info' ? 'rgb(var(--text-secondary))' : `rgb(${LEVEL_RGB[e.level]})` }}>
                  {e.text}
                </span>
              </div>
            ))}
            {running && (
              <div className="flex items-center gap-2 py-[3px] font-mono text-[10px]" style={{ color: 'rgb(var(--text-muted))' }}>
                <span className="nxc-caret">▌</span>
              </div>
            )}
          </div>
        </div>

        {/* Completion / failure read-out */}
        {isDone && summary && (
          <div className="nxc-rise grid grid-cols-2 gap-3 rounded-xl px-4 py-3 md:grid-cols-5"
            style={{
              border: '1px solid rgb(var(--accent-green) / 0.3)',
              background: 'rgb(var(--accent-green) / 0.05)',
              ['--delay' as string]: '0.24s',
            }}>
            {[
              { label: 'Nodes', value: summary.nodes },
              { label: 'Edges', value: summary.edges },
              { label: 'Links', value: summary.links },
              { label: 'Clusters', value: summary.clusters },
              { label: 'High risk', value: summary.highRisk },
            ].map(s => (
              <div key={s.label} className="text-center">
                <p className="m-0 text-[20px] font-extrabold leading-none tabular-nums" style={{ color: 'rgb(var(--accent-green))' }}>
                  <Odometer value={s.value} />
                </p>
                <p className="m-0 mt-1 text-[9px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'rgb(var(--text-muted))' }}>{s.label}</p>
              </div>
            ))}
          </div>
        )}

        {isError && (
          <div className="flex items-start gap-2.5 rounded-xl px-4 py-3"
            style={{ border: '1px solid rgb(var(--accent-red) / 0.35)', background: 'rgb(var(--accent-red) / 0.06)' }}>
            <AlertTriangle size={14} className="mt-0.5 shrink-0" style={{ color: 'rgb(var(--accent-red))' }} />
            <p className="m-0 text-xs" style={{ color: 'rgb(var(--accent-red))' }}>{error}</p>
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * The slim strip the cinema collapses into once the completion beat has played,
 * so a finished run keeps its headline numbers without eating the results view.
 */
export function NexusProgressStrip({
  summary, elapsedMs, threatLevel, threatScore, onOpenGraph, onExpand,
}: {
  summary: { nodes: number; edges: number; links: number; clusters: number; highRisk: number }
  elapsedMs: number
  threatLevel?: string
  threatScore?: number
  onOpenGraph?: () => void
  onExpand?: () => void
}) {
  return (
    <div className="nxc-strip flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl px-4 py-3"
      style={{
        border: '1px solid rgb(var(--accent-green) / 0.28)',
        background: 'linear-gradient(90deg, rgb(var(--accent-green) / 0.07), transparent 62%), rgb(var(--bg-card) / 0.8)',
      }}>
      <span className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.2em]" style={{ color: 'rgb(var(--accent-green))' }}>
        <Check size={13} /> Complete
      </span>
      <span className="font-mono text-[11px] tabular-nums" style={{ color: 'rgb(var(--text-muted))' }}>{fmtClock(elapsedMs)}</span>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {[
          { label: 'nodes', value: summary.nodes },
          { label: 'edges', value: summary.edges },
          { label: 'links', value: summary.links },
          { label: 'clusters', value: summary.clusters },
          { label: 'high risk', value: summary.highRisk },
        ].map(s => (
          <span key={s.label} className="font-mono text-[11px] tabular-nums" style={{ color: 'rgb(var(--text-secondary))' }}>
            <strong style={{ color: 'rgb(var(--text-bright))' }}>{s.value}</strong> {s.label}
          </span>
        ))}
        {threatLevel && (
          <span className="rounded px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider"
            style={{ color: 'rgb(var(--accent-amber))', background: 'rgb(var(--accent-amber) / 0.12)' }}>
            {threatLevel}{typeof threatScore === 'number' ? ` ${threatScore}/100` : ''}
          </span>
        )}
      </div>
      <div className="ml-auto flex items-center gap-2">
        {onExpand && (
          <button type="button" onClick={onExpand}
            className="flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-semibold"
            style={{ color: 'rgb(var(--text-secondary))', border: '1px solid rgb(var(--bg-border) / 0.45)', background: 'transparent' }}>
            <Activity size={12} /> Run report
          </button>
        )}
        {onOpenGraph && (
          <button type="button" onClick={onOpenGraph}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-4 py-2 text-xs font-bold text-white"
            style={{
              background: 'linear-gradient(135deg, rgb(var(--accent-blue)), rgb(var(--accent-purple)))',
              border: '1px solid rgb(var(--accent-blue) / 0.5)',
              boxShadow: '0 0 20px rgb(var(--accent-blue) / 0.3)',
            }}>
            <GitBranch size={13} /> Open Graph
          </button>
        )}
      </div>
    </div>
  )
}

export { fmtClock as formatRunClock }
