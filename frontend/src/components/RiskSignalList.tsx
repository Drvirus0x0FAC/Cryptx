import type { RiskSignal } from '../types'
import { useTranslation } from 'react-i18next'
import { ShieldAlert, ShieldCheck, AlertTriangle, Info } from 'lucide-react'

const SEVERITY_CFG = {
  CRITICAL: { icon: ShieldAlert,   color: '#ff5d86', bg: 'rgba(255,59,107,0.08)',  border: 'rgba(255,59,107,0.25)' },
  HIGH:     { icon: ShieldAlert,   color: '#F87171', bg: 'rgba(255,45,85,0.08)',   border: 'rgba(255,45,85,0.25)'  },
  MEDIUM:   { icon: AlertTriangle, color: '#FBBF24', bg: 'rgba(255,159,10,0.08)',  border: 'rgba(255,159,10,0.25)' },
  LOW:      { icon: AlertTriangle, color: '#FBBF24', bg: 'rgba(255,159,10,0.05)',  border: 'rgba(255,159,10,0.15)' },
  INFO:     { icon: Info,          color: '#ff5a6e', bg: 'rgba(255,64,82,0.05)',   border: 'rgba(255,64,82,0.15)'  },
}

interface Props {
  signals: RiskSignal[]
  compact?: boolean
}

export default function RiskSignalList({ signals, compact = false }: Props) {
  const { t } = useTranslation()
  if (!signals.length) {
    return (
      <div className="flex items-center gap-2 text-sm" style={{ color: '#34D399' }}>
        <ShieldCheck size={15} />
        <span className="text-tech">{t('components:shared.riskSignals.empty')}</span>
      </div>
    )
  }

  const sorted = [...signals].sort((a, b) => b.weight - a.weight)

  return (
    <div className="space-y-1.5">
      {sorted.map((sig, i) => {
        const cfg  = SEVERITY_CFG[sig.severity as keyof typeof SEVERITY_CFG] ?? SEVERITY_CFG.INFO
        const Icon = cfg.icon
        return (
          <div key={i}
            className="flex gap-3 p-2.5 rounded-lg"
            style={{ background: cfg.bg, border: `1px solid ${cfg.border}` }}>
            <Icon size={14} className="mt-0.5 shrink-0" style={{ color: cfg.color }} />
            <div className="min-w-0 flex-1">
              <div className="text-[12px] font-semibold text-tech" style={{ color: cfg.color }}>
                {sig.label}
              </div>
              {!compact && sig.detail && (
                <div className="text-[11px] text-text-secondary mt-0.5 truncate" title={sig.detail}>
                  {sig.detail}
                </div>
              )}
            </div>
            {sig.weight > 0 && (
              <span className="ml-auto text-[10px] text-tech shrink-0 opacity-70" style={{ color: cfg.color }}>
                +{sig.weight}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
