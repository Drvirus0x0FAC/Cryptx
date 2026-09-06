import { useTranslation } from 'react-i18next'
import type { RiskLevel } from '../types'
import clsx from 'clsx'

const CONFIG: Record<RiskLevel, { label: string; cls: string }> = {
  clean:      { label: 'CLEAN',      cls: 'bg-risk-clean/20 text-risk-clean border-risk-clean/30' },
  entity:     { label: 'ENTITY',     cls: 'bg-risk-entity/20 text-risk-entity border-risk-entity/30' },
  bridge_swap:{ label: 'BRIDGE/SWAP',cls: 'bg-risk-bridge/20 text-risk-bridge border-risk-bridge/30' },
  scam:       { label: 'SCAM',       cls: 'bg-risk-scam/20 text-risk-scam border-risk-scam/30' },
  mixer:      { label: 'MIXER',      cls: 'bg-risk-mixer/20 text-risk-mixer border-risk-mixer/30' },
  sanctioned: { label: 'SANCTIONED', cls: 'bg-risk-sanctioned/20 text-risk-sanctioned border-risk-sanctioned/30' },
  error:      { label: 'ERROR',      cls: 'bg-risk-error/20 text-risk-error border-risk-error/30' },
}

interface Props {
  level: RiskLevel | string
  score?: number
  size?: 'sm' | 'md'
}

export default function RiskBadge({ level, score, size = 'md' }: Props) {
  const { t } = useTranslation()
  const cfg = CONFIG[level as RiskLevel] ?? CONFIG.error
  return (
    <span
      className={clsx(
        'badge border font-semibold tracking-wider',
        cfg.cls,
        size === 'sm' ? 'text-[10px] px-1.5 py-0.5' : 'text-xs',
      )}
    >
      {cfg.label}
      {score !== undefined && ` ${score}/100`}
    </span>
  )
}

export function SeverityBadge({ severity }: { severity: string }) {
  const cls = {
    CRITICAL: 'bg-risk-sanctioned/20 text-risk-sanctioned border-risk-sanctioned/30',
    HIGH:     'bg-risk-mixer/20 text-risk-mixer border-risk-mixer/30',
    MEDIUM:   'bg-risk-medium/20 text-risk-medium border-risk-medium/30',
    LOW:      'bg-risk-entity/20 text-risk-entity border-risk-entity/30',
  }[severity.toUpperCase()] ?? 'bg-bg-tertiary text-text-muted border-border'

  return (
    <span className={clsx('badge border text-[10px] tracking-wider', cls)}>
      {severity.toUpperCase()}
    </span>
  )
}
