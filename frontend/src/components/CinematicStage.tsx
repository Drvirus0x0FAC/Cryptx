import { useEffect, useRef, useState, type ReactNode, type FormEvent } from 'react'
import type { LucideIcon } from 'lucide-react'

/**
 * CinematicStage — the shared cinematic input console.
 *
 * Every module's input screen renders through this one component, so they all
 * share the same staging as the Nexus run screen: a centred console panel over
 * a grid/scan/mote backdrop, a wallet constellation converging on the crest,
 * and a centred crest + title block above the page's own fields. It collapses
 * into a slim sticky bar once a result exists (driven by `collapsed`) so
 * results get the screen space back.
 *
 * The console chrome is uniform on purpose — module identity comes from the
 * icon, kicker and title each page passes, not from a bespoke colour theme.
 * Styling lives in `src/cinematic-console.css` (layered over
 * `cinematic-stages.css`, which still owns the collapsed bar state).
 *
 * The component is intentionally layout-agnostic about the form internals:
 * the page passes its existing fields as `children` and optionally an
 * `onSubmit` (used when the children are wrapped in a real <form>). All
 * business logic, handlers, state and i18n stay in the page.
 *
 * Variants are styled in `src/cinematic-stages.css`.
 */

/** Deterministic drifting motes — fixed so they never re-randomise on render. */
const MOTES = Array.from({ length: 14 }, (_, i) => ({
  left: `${(i * 71) % 96}%`,
  top: `${58 + ((i * 29) % 40)}%`,
  dur: `${12 + ((i * 5) % 8)}s`,
  delay: `${-((i * 11) % 13)}s`,
  dx: `${((i % 5) - 2) * 16}px`,
}))

/** A seed wallet fanning out into two hop rings, drawn behind the crest. */
const NET_NODES = [
  { x: 600, y: 128, r: 7 },
  { x: 470, y: 78, r: 4 }, { x: 512, y: 186, r: 4 }, { x: 700, y: 74, r: 4 },
  { x: 742, y: 176, r: 4 }, { x: 604, y: 44, r: 3.5 }, { x: 596, y: 214, r: 3.5 },
  { x: 356, y: 132, r: 3 }, { x: 404, y: 40, r: 2.5 }, { x: 418, y: 220, r: 2.5 },
  { x: 848, y: 116, r: 3 }, { x: 800, y: 34, r: 2.5 }, { x: 808, y: 216, r: 2.5 },
  { x: 250, y: 72, r: 2 }, { x: 268, y: 196, r: 2 }, { x: 944, y: 66, r: 2 },
  { x: 950, y: 190, r: 2 }, { x: 150, y: 130, r: 1.8 }, { x: 1046, y: 132, r: 1.8 },
]
const NET_EDGES: Array<[number, number]> = [
  [0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [0, 6],
  [1, 7], [1, 8], [2, 9], [2, 7], [3, 10], [3, 11], [4, 12], [4, 10],
  [7, 13], [7, 14], [10, 15], [10, 16], [13, 17], [15, 18], [14, 17], [16, 18],
]

export type CineVariant =
  | 'intel' | 'trace' | 'dex' | 'nexus' | 'nft' | 'boards' | 'auto'
  | 'entity' | 'txlens' | 'perpdex' | 'monitor' | 'evidence' | 'predictive'
  | 'ai' | 'osint' | 'cases' | 'batch' | 'labels' | 'victim' | 'scam'
  | 'reports' | 'sanctions' | 'attribution' | 'submissions' | 'regulatory'
  | 'demix' | 'comply' | 'contract' | 'laundering' | 'court' | 'recovery' | 'freeze'

type CommonProps = {
  /** Unique visual variant — maps to a `.cine-stage--{variant}` theme. */
  variant: CineVariant
  /** Primary title (usually a page title i18n string). */
  title?: ReactNode
  /** Subtitle / tagline beneath the title. */
  subtitle?: ReactNode
  /** Icon rendered inside the animated crest. */
  icon?: LucideIcon
  /** When true the stage collapses to a slim sticky bar (result is showing). */
  collapsed?: boolean
  /** Optional eyebrow / kicker label above the title. */
  kicker?: ReactNode
  /** Optional right-aligned secondary controls in the hero header. */
  actions?: ReactNode
  /** Extra className to merge onto the outer stage node. */
  className?: string
  /** Inline style passthrough (used by some pages for per-instance accents). */
  style?: React.CSSProperties
}

type FormProps = CommonProps & {
  /** Submit handler — when provided, wraps children in a real <form>. */
  onSubmit?: (e: FormEvent) => void
  children: ReactNode
}

/**
 * The stage renders a fixed FX layer (4 spans) + a content layer. The content
 * layer holds the hero header (crest + title + subtitle) and the form slot.
 * Collapsing toggles `data-state` between `hero` and `bar`; CSS handles the
 * height/opacity transition + sticky positioning.
 */
export default function CinematicStage({
  variant,
  title,
  subtitle,
  icon: Icon,
  collapsed = false,
  kicker,
  actions,
  className,
  style,
  onSubmit,
  children,
}: FormProps) {
  const stageRef = useRef<HTMLDivElement>(null)
  // Tracks whether the collapse transition has completed at least once so we
  // can keep the hero header mounted (just hidden) for the reverse animation.
  const [mounted, setMounted] = useState(true)

  useEffect(() => { setMounted(true) }, [])

  const Tag = onSubmit ? 'form' : 'div'
  // `key` forces a clean re-mount of the FX layer on variant change so the
  // boot animation replays when navigating between modules.
  return (
    <section
      ref={stageRef}
      className={`cine-stage cine-console cine-stage--${variant}${collapsed ? ' cine-stage--bar' : ''}${className ? ' ' + className : ''}`}
      data-state={collapsed ? 'bar' : 'hero'}
      data-variant={variant}
      style={style}
    >
      {/* Console backdrop — shared with the Nexus run screen. */}
      <div className="cine-fx" aria-hidden="true" key={variant}>
        <div className="nxc-grid" />
        <div className="nxc-scan" />
        {MOTES.map((m, i) => (
          <span key={i} className="nxc-particle" style={{
            left: m.left, top: m.top,
            ['--dur' as string]: m.dur, ['--delay' as string]: m.delay, ['--dx' as string]: m.dx,
          }} />
        ))}
        <svg className="cine-net" viewBox="0 0 1200 260" preserveAspectRatio="xMidYMid meet">
          {NET_EDGES.map(([a, b], i) => (
            <line key={i} className="nxl-net-edge"
              x1={NET_NODES[a].x} y1={NET_NODES[a].y} x2={NET_NODES[b].x} y2={NET_NODES[b].y}
              style={{ ['--delay' as string]: `${(i % 7) * 0.28}s` }} />
          ))}
          {/* node 0 is the seed the crest sits on — an edge anchor only */}
          {NET_NODES.map((n, i) => i === 0 ? null : (
            <circle key={i} className="nxl-net-node" cx={n.x} cy={n.y} r={n.r}
              style={{ ['--r' as string]: n.r, ['--delay' as string]: `${(i % 9) * 0.32}s` }} />
          ))}
        </svg>
      </div>

      <Tag
        className="cine-stage__inner"
        onSubmit={onSubmit as never}
      >
        {/* Hero header — hidden (not unmounted) once collapsed. */}
        <header className="cine-hero" aria-hidden={collapsed || undefined}>
          <div className="cine-crest">
            {Icon ? <Icon size={22} strokeWidth={1.75} className="cine-crest__icon" /> : null}
            <span className="cine-crest__pulse" />
            <span className="cine-crest__ring" />
          </div>
          <div className="cine-hero__text">
            {kicker ? <p className="cine-kicker">{kicker}</p> : null}
            {title ? <h1 className="cine-title">{title}</h1> : null}
            {subtitle ? <p className="cine-subtitle">{subtitle}</p> : null}
          </div>
          {actions ? <div className="cine-hero__actions">{actions}</div> : null}
        </header>

        {/* Compact chip shown only in the collapsed bar state. */}
        <div className="cine-chip" aria-hidden={!collapsed || undefined}>
          {Icon ? <Icon size={13} strokeWidth={2} /> : null}
          <span>{title}</span>
        </div>

        {/* Form slot — page provides its inputs/buttons here verbatim. */}
        <div className="cine-form-slot">{mounted ? children : null}</div>
      </Tag>
    </section>
  )
}
