import { useTranslation } from 'react-i18next'
import type { ExposureResult } from '../types'

interface Props {
  exposure: ExposureResult
}

export default function ExposureBreakdown({ exposure }: Props) {
  const { t } = useTranslation()
  const pct      = Math.min(100, exposure.direct_pct)
  const cleanPct = 100 - pct

  const color =
    pct >= 60 ? '#F87171' :
    pct >= 30 ? '#F87171' :
    pct >= 10 ? '#FBBF24' :
    pct > 0   ? '#FBBF24' :
                '#34D399'

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-[12px]">
        <span className="text-text-secondary">{t('components:shared.exposure.directExposure')}</span>
        <span className="text-tech font-bold" style={{ color, textShadow: `0 0 8px ${color}55` }}>
          {exposure.direct_pct.toFixed(1)}%
        </span>
      </div>

      {/* Stacked bar */}
      <div className="w-full h-2 rounded-full overflow-hidden flex"
        style={{ background: '#160a0e' }}>
        {pct > 0 && (
          <div
            className="h-full rounded-l-full transition-all duration-700"
            style={{ width: `${pct}%`, background: color, boxShadow: `0 0 6px ${color}88` }}
            title={`${pct.toFixed(1)}% risky`}
          />
        )}
        {cleanPct > 0 && (
          <div
            className="h-full transition-all duration-700"
            style={{ width: `${cleanPct}%`, background: '#34D399' }}
            title={`${cleanPct.toFixed(1)}% clean`}
          />
        )}
      </div>

      {/* Legend */}
      <div className="flex gap-4 text-[11px]">
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full" style={{ background: color }} />
          <span className="text-text-secondary">
            {t('components:shared.exposure.risky')}: {exposure.risky_volume.toFixed(6)} {exposure.unit}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full" style={{ background: '#34D399' }} />
          <span className="text-text-secondary">
            {t('components:shared.exposure.total')}: {exposure.total_volume.toFixed(6)} {exposure.unit}
          </span>
        </div>
      </div>

      {/* Breakdown */}
      {exposure.breakdown.length > 0 && (
        <div className="space-y-1 pt-1">
          {exposure.breakdown.map((b, i) => (
            <div key={i} className="flex justify-between text-[11px]">
              <span className="text-text-primary font-medium">{b.entity}</span>
              <span className="text-text-muted text-tech">
                {b.volume.toFixed(6)} {exposure.unit}
              </span>
            </div>
          ))}
        </div>
      )}

      {exposure.direct_pct === 0 && (
        <p className="text-[11px]" style={{ color: '#34D399' }}>
          {t('components:shared.exposure.noDirectExposure')}
        </p>
      )}
    </div>
  )
}
