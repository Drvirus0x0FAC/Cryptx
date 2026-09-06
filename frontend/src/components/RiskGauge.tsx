import { useTranslation } from 'react-i18next'
import type { RiskScoreLevel } from '../types'

interface Props {
  score: number
  level: RiskScoreLevel
  size?: number
  showLabel?: boolean
}

const LEVEL_CONFIG: Record<RiskScoreLevel, { color: string; labelKey: string }> = {
  CLEAN:      { color: '#34D399', labelKey: 'clean'      },
  LOW:        { color: '#34D399', labelKey: 'low'        },
  MEDIUM:     { color: '#FBBF24', labelKey: 'medium'     },
  HIGH:       { color: '#FBBF24', labelKey: 'high'       },
  CRITICAL:   { color: '#F87171', labelKey: 'critical'   },
  SANCTIONED: { color: '#ff5d86', labelKey: 'sanctioned' },
  ERROR:      { color: '#475569', labelKey: 'error'      },
}

export default function RiskGauge({ score, level, size = 160, showLabel = true }: Props) {
  const { t } = useTranslation()
  const cfg       = LEVEL_CONFIG[level] ?? LEVEL_CONFIG.ERROR
  const r         = 54
  const cx        = size / 2
  const cy        = size / 2
  const strokeW   = 9
  const startAngle = -210 * (Math.PI / 180)
  const sweepTotal = 240 * (Math.PI / 180)
  const clamped    = Math.min(100, Math.max(0, score))
  const sweepUsed  = (clamped / 100) * sweepTotal

  function pt(angle: number, rad: number) {
    return { x: cx + rad * Math.cos(angle), y: cy + rad * Math.sin(angle) }
  }

  function arcPath(startA: number, sweepA: number, rad: number) {
    const end = startA + sweepA
    const s = pt(startA, rad)
    const e = pt(end, rad)
    const large = sweepA > Math.PI ? 1 : 0
    return `M ${s.x} ${s.y} A ${rad} ${rad} 0 ${large} 1 ${e.x} ${e.y}`
  }

  const trackPath = arcPath(startAngle, sweepTotal, r)
  const fillPath  = arcPath(startAngle, sweepUsed,  r)

  const ticks = [0, 60, 120, 180, 240].map(
    (d) => startAngle + (d / 240) * sweepTotal
  )

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* Dim bg ring */}
        <circle cx={cx} cy={cy} r={r + strokeW * 0.5} fill="none"
          stroke="rgba(255,64,82,0.04)" strokeWidth={strokeW + 10} />

        {/* Track */}
        <path d={trackPath} stroke="#160a0e" strokeWidth={strokeW} fill="none" strokeLinecap="round" />

        {/* Score fill */}
        {clamped > 0 && (
          <path
            d={fillPath}
            stroke={cfg.color}
            strokeWidth={strokeW}
            fill="none"
            strokeLinecap="round"
            style={{ transition: 'stroke-dasharray 0.6s ease' }}
          />
        )}

        {/* Tick marks */}
        {ticks.map((a, i) => {
          const inner = pt(a, r - strokeW * 0.8)
          const outer = pt(a, r + strokeW * 0.8)
          return <line key={i} x1={inner.x} y1={inner.y} x2={outer.x} y2={outer.y}
                   stroke="#1a3248" strokeWidth={1.5} />
        })}

        {/* Score text */}
        <text x={cx} y={cy - 4} textAnchor="middle" fill={cfg.color}
              fontSize={size * 0.22} fontWeight="700"
              fontFamily="'Roboto', sans-serif">
          {clamped}
        </text>
        <text x={cx} y={cy + 14} textAnchor="middle" fill="#475569"
              fontSize={size * 0.08} fontFamily="'Roboto Mono', monospace">
          / 100
        </text>
      </svg>

      {showLabel && (
        <span
          className="text-[10px] font-bold tracking-[0.2em] uppercase px-3 py-1 rounded-full"
          style={{ color: cfg.color, background: `${cfg.color}14`, border: `1px solid ${cfg.color}40`,
                   textShadow: `0 0 8px ${cfg.color}55`, fontFamily: "'Roboto Mono', monospace" }}
        >
          {t(`components:shared.riskGauge.${cfg.labelKey}`)}
        </span>
      )}
    </div>
  )
}
