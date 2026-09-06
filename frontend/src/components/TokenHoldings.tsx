import type { TokenBalance } from '../types'
import { useTranslation } from 'react-i18next'
import { ExternalLink } from 'lucide-react'

export default function TokenHoldings({ tokens, chain }: { tokens: TokenBalance[]; chain?: string }) {
  const { t } = useTranslation()
  if (!tokens.length) return null

  const explorerBase =
    chain === 'TRX'
      ? 'https://tronscan.org/#/contract/'
      : 'https://etherscan.io/token/'

  return (
    <div className="card">
      <p className="card-title">{t('components:shared.tokenHoldings.title')} ({tokens.length})</p>
      <div className="space-y-2">
        {tokens.map((t, i) => (
          <div
            key={i}
            className="flex items-center justify-between py-2 border-b border-border/50 last:border-0"
          >
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-bg-elevated flex items-center justify-center text-xs font-bold text-accent-cyan">
                {(t.symbol || '?').slice(0, 3)}
              </div>
              <div>
                <p className="text-sm font-semibold text-text-primary">{t.symbol}</p>
                {t.name && <p className="text-xs text-text-muted">{t.name}</p>}
                {t.contract && (
                  <a
                    href={explorerBase + t.contract}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[10px] text-accent-cyan/70 hover:text-accent-cyan flex items-center gap-0.5"
                  >
                    {t.contract.slice(0, 16)}…<ExternalLink size={9} />
                  </a>
                )}
              </div>
            </div>
            <div className="text-right">
              <p className="text-sm font-mono text-text-primary">
                {typeof t.balance === 'number' ? t.balance.toLocaleString(undefined, { maximumFractionDigits: 6 }) : t.balance}
              </p>
              {t.usd_value !== undefined && t.usd_value !== null && (
                <p className="text-xs text-text-secondary">
                  ${t.usd_value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
