import type { RiskCategory } from '../types'

const CATEGORY_CFG: Record<string, { label: string; color: string; bg: string }> = {
  sanctioned: { label: 'SANCTIONED', color: '#f0356b', bg: '#2e1065' },
  mixer:      { label: 'MIXER',      color: '#ef4444', bg: '#2d0505' },
  darknet:    { label: 'DARKNET',    color: '#ff5a6e', bg: '#3b0606' },
  scam:       { label: 'SCAM',       color: '#f97316', bg: '#2d1001' },
  bridge:     { label: 'BRIDGE',     color: '#f59e0b', bg: '#2d1d01' },
  dex:        { label: 'DEX/SWAP',   color: '#e11d2e', bg: '#110a0e' },
  exchange:   { label: 'EXCHANGE',   color: '#22c55e', bg: '#052e16' },
  behavioral: { label: 'BEHAVIOR',   color: '#ff5a6e', bg: 'rgba(56,189,248,0.08)' },
  exposure:   { label: 'EXPOSURE',   color: '#ff5d86', bg: '#1f1033' },
}

interface Props {
  categories: string[]
}

export default function CategoryBadges({ categories }: Props) {
  if (!categories.length) return null

  return (
    <div className="flex flex-wrap gap-2">
      {categories.map((cat) => {
        const cfg = CATEGORY_CFG[cat] ?? { label: cat.toUpperCase(), color: '#94a3b8', bg: '#241a1e' }
        return (
          <span
            key={cat}
            className="text-xs font-bold tracking-wider px-2.5 py-1 rounded border uppercase"
            style={{
              color: cfg.color,
              backgroundColor: cfg.bg,
              borderColor: `${cfg.color}44`,
            }}
          >
            {cfg.label}
          </span>
        )
      })}
    </div>
  )
}
