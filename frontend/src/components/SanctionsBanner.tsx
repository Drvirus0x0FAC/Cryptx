import { useTranslation } from 'react-i18next'
import { AlertTriangle, CheckCircle, ShieldAlert } from 'lucide-react'
import type { SanctionsResult, MixerHit } from '../types'

// Mixers / services that are themselves OFAC-designated. Interacting with these
// carries direct sanctions exposure even if the subject isn't on the SDN list.
const OFAC_SANCTIONED_SERVICES = [
  'tornado cash', 'blender', 'blender.io', 'sinbad', 'sinbad.io',
  'helix', 'bestmixer', 'chipmixer', 'garantex',
]

export default function SanctionsBanner({
  sanctions, mixerHits,
}: { sanctions?: SanctionsResult; mixerHits?: MixerHit[] }) {
  const { t } = useTranslation()
  if (!sanctions) return null

  const srcLabel: Record<string, string> = {
    chainalysis: 'Chainalysis',
    ofac_local: 'OFAC SDN',
  }
  const label = srcLabel[sanctions.source] ?? sanctions.source ?? 'Unknown'

  // ── Directly listed ──────────────────────────────────────────────────────
  if (sanctions.sanctioned) {
    return (
      <div className="rounded-lg border border-risk-sanctioned/50 bg-risk-sanctioned/10 p-4">
        <div className="flex items-center gap-2 mb-2">
          <AlertTriangle className="text-risk-sanctioned" size={18} />
          <span className="text-risk-sanctioned font-bold uppercase tracking-wider text-sm">
            SANCTIONED ADDRESS - {label}
          </span>
        </div>
        <ul className="space-y-1">
          {(sanctions.identifications ?? []).map((id, i) => (
            <li key={i} className="text-xs text-risk-sanctioned/80">
              <span className="font-semibold">{id.name}</span>
              {id.category && <span className="text-text-muted ml-1">({id.category})</span>}
              {id.description && <p className="text-text-muted mt-0.5">{id.description}</p>}
            </li>
          ))}
        </ul>
      </div>
    )
  }

  // ── Not directly listed, but interacts with OFAC-sanctioned services ──────
  const sanctionedServices = Array.from(new Set(
    (mixerHits ?? [])
      .map(h => h.mixer_name)
      .filter((name): name is string => !!name && OFAC_SANCTIONED_SERVICES.some(s => name.toLowerCase().includes(s))),
  ))

  if (sanctionedServices.length > 0) {
    return (
      <div className="rounded-lg border border-neon-amber/50 bg-neon-amber/10 p-4">
        <div className="flex items-center gap-2 mb-1.5">
          <ShieldAlert className="text-neon-amber shrink-0" size={18} />
          <span className="text-neon-amber font-bold uppercase tracking-wider text-sm">
            Indirect OFAC Exposure
          </span>
        </div>
        <p className="text-xs text-neon-amber/90">
          This address is <span className="font-semibold">not itself on the {label} list</span>, but it
          transacts directly with OFAC-designated entities:{' '}
          <span className="font-semibold">{sanctionedServices.join(', ')}</span>.
        </p>
        <p className="text-[11px] text-text-muted mt-1">
          Funds moving through sanctioned mixers carry the same compliance and seizure risk as direct
          designation. Treat as high-risk for AML/sanctions purposes.
        </p>
      </div>
    )
  }

  // ── Clean ────────────────────────────────────────────────────────────────
  return (
    <div className="rounded-lg border border-risk-clean/30 bg-risk-clean/5 p-3 flex items-center gap-2">
      <CheckCircle className="text-risk-clean shrink-0" size={16} />
      <span className="text-risk-clean text-sm">
        Not on sanctions list ({label}) - no sanctioned-entity interactions detected
      </span>
    </div>
  )
}
