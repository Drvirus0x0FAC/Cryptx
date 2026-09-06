import { useTranslation } from 'react-i18next'
import { AlertTriangle, Globe } from 'lucide-react'
import type { MixerHit, ChainHopSwap } from '../types'

function MixerHits({ hits }: { hits: MixerHit[] }) {
  if (!hits.length) return null
  return (
    <div>
      <p className="text-xs font-semibold text-risk-mixer mb-2 uppercase tracking-wider">
        ⚠ Mixer / Obfuscation Interactions ({hits.length})
      </p>
      <div className="space-y-2">
        {hits.map((h, i) => (
          <div key={i} className="rounded border border-risk-mixer/30 bg-risk-mixer/10 p-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-risk-mixer">{h.mixer_name}</span>
              <span className="text-text-muted">{h.mixer_type}</span>
            </div>
            <div className="text-text-muted font-mono mt-1 break-all">
              {h.counterparty}
            </div>
            {h.tx_hash && (
              <div className="text-text-muted font-mono mt-0.5">
                tx: {h.tx_hash.slice(0, 20)}…
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function BridgeSwapHits({ data }: { data: ChainHopSwap }) {
  const all = [...data.bridge_hits, ...data.swap_hits]
  if (!all.length && !data.heuristics.length) return null

  const riskColor = data.risk_level === 'high'
    ? 'text-risk-mixer border-risk-mixer/30 bg-risk-mixer/10'
    : 'text-risk-bridge border-risk-bridge/30 bg-risk-bridge/10'

  return (
    <div>
      <p className={`text-xs font-semibold mb-2 uppercase tracking-wider ${riskColor.split(' ')[0]}`}>
        <Globe size={12} className="inline mr-1" />
        Chain Hopping / Swap Signals - Risk:{' '}
        <span className="font-bold">{data.risk_level.toUpperCase()}</span>
      </p>
      {all.slice(0, 8).map((h, i) => (
        <div
          key={i}
          className={`rounded border ${riskColor} p-2 text-xs mb-2`}
        >
          <div className="flex justify-between">
            <span className="font-semibold">{h.name}</span>
            <span className="text-text-muted">{h.type} · {h.chain}</span>
          </div>
          {(h.value || h.token) && (
            <div className="font-mono text-text-secondary mt-0.5">
              {h.direction} {h.value} {h.token}
            </div>
          )}
        </div>
      ))}
      {data.heuristics.map((heu, i) => (
        <div key={i} className="rounded border border-risk-medium/30 bg-risk-medium/10 p-2 text-xs mb-2">
          <span className="text-risk-medium font-semibold">{heu.type.replace(/_/g, ' ').toUpperCase()}</span>
          <p className="text-text-muted mt-0.5">{heu.evidence}</p>
        </div>
      ))}
    </div>
  )
}

interface Props {
  mixerHits?: MixerHit[]
  chainHopSwap?: ChainHopSwap
}

export default function MixerAlerts({ mixerHits, chainHopSwap }: Props) {
  const { t } = useTranslation()
  const hasMixer = mixerHits && mixerHits.length > 0
  const hasBridge =
    chainHopSwap &&
    (chainHopSwap.bridge_count > 0 ||
      chainHopSwap.swap_count > 0 ||
      chainHopSwap.heuristics.length > 0)

  if (!hasMixer && !hasBridge) return null

  return (
    <div className="card space-y-4">
      <p className="card-title">{t('components:shared.mixer.riskSignals')}</p>
      {hasMixer && <MixerHits hits={mixerHits!} />}
      {hasBridge && <BridgeSwapHits data={chainHopSwap!} />}
    </div>
  )
}
