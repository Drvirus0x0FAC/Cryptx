/**
 * F11: Chain-of-Custody report — opens the printable HTML report in a new tab.
 * Reusable button. Plugs into Case Detail + Evidence Vault.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ScrollText, Loader2, ShieldCheck } from 'lucide-react'
import { custodyReport, custodyReportHtmlUrl } from '../api/client'

export default function CustodyReportButton({ caseId }: { caseId: string }) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [summary, setSummary] = useState<{ valid: boolean; entries: number } | null>(null)

  async function open() {
    setLoading(true)
    try {
      const r = await custodyReport(caseId)
      setSummary({ valid: r.custody_integrity.chain_valid, entries: r.summary.total_audit_entries + r.summary.total_case_events })
      window.open(custodyReportHtmlUrl(caseId), '_blank')
    } finally { setLoading(false) }
  }

  return (
    <div className="flex items-center gap-3">
      <button onClick={open} disabled={loading || !caseId} className="btn-ghost text-xs flex items-center gap-1.5">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <ScrollText size={12} />}
        Custody Report
      </button>
      {summary && (
        <span className="flex items-center gap-1 text-[10px]">
          <ShieldCheck size={11} style={{ color: summary.valid ? '#34D399' : '#F87171' }} />
          <span style={{ color: summary.valid ? '#34D399' : '#F87171' }}>
            {summary.valid ? 'Chain valid' : 'Chain broken'} · {summary.entries} events
          </span>
        </span>
      )}
    </div>
  )
}
