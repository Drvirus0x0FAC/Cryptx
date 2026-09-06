/**
 * F3/F13: Export buttons — PDF / DOCX / FinCEN XML / STIX / MISP.
 * Reusable component. Props determine which formats are offered.
 * Plugs into Report Studio (after a report is generated).
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileText, FileType, Code2, Share2, Loader2, Download, CheckCircle } from 'lucide-react'
import { exportPdf, exportDocx, exportFinCenXml, exportStix, exportMisp, exportCapabilities } from '../api/client'
import { useQuery } from '@tanstack/react-query'

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

export default function ExportButtons({
  htmlContent, caseId, reportData, addresses, title = 'CrypTX_Report',
}: {
  htmlContent?: string
  caseId?: string
  reportData?: Record<string, unknown>
  addresses?: unknown[]
  title?: string
}) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState('')
  const [done, setDone] = useState('')
  const { data: caps } = useQuery({ queryKey: ['export-caps'], queryFn: exportCapabilities })

  async function doExport(kind: string) {
    setBusy(kind); setDone('')
    try {
      if (kind === 'pdf' && htmlContent) {
        const blob = await exportPdf({ html_content: htmlContent, title, case_id: caseId })
        downloadBlob(blob, `${title}.pdf`)
      } else if (kind === 'docx') {
        const blob = await exportDocx({ case_id: caseId, report_data: reportData, title })
        downloadBlob(blob, `${title}.docx`)
      } else if (kind === 'fincen') {
        const { blob } = await exportFinCenXml({ form_type: 'SAR', case_id: caseId, subject: { address: '' }, narrative: String(reportData?.narrative || '') })
        downloadBlob(blob, `fincen_${caseId || 'report'}.xml`)
      } else if (kind === 'stix') {
        const bundle = await exportStix({ case_id: caseId || '', addresses })
        downloadBlob(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' }), `${title}.stix.json`)
      } else if (kind === 'misp') {
        const event = await exportMisp({ case_id: caseId || '', addresses })
        downloadBlob(new Blob([JSON.stringify(event, null, 2)], { type: 'application/json' }), `${title}.misp.json`)
      }
      setDone(kind)
      setTimeout(() => setDone(''), 2500)
    } catch (e) {
      console.error(e)
      alert(`Export failed: ${e instanceof Error ? e.message : 'unknown error'}`)
    } finally {
      setBusy('')
    }
  }

  const safe = (k: string) => caps?.[k as keyof typeof caps] !== 'unavailable' && caps?.[k as keyof typeof caps] !== false
  const Btn = ({ kind, icon, label, color }: { kind: string; icon: React.ReactNode; label: string; color: string }) => (
    <button
      onClick={() => doExport(kind)}
      disabled={!!busy || (caps && !safe(kind))}
      className="btn-ghost text-xs flex items-center gap-1.5 disabled:opacity-30"
      style={{ borderColor: color }}
    >
      {busy === kind ? <Loader2 size={12} className="animate-spin" /> : done === kind ? <CheckCircle size={12} style={{ color: '#34D399' }} /> : icon}
      {label}
    </button>
  )

  return (
    <div className="flex flex-wrap gap-2">
      <Btn kind="pdf" icon={<FileText size={12} />} label="PDF" color="#dc2626" />
      <Btn kind="docx" icon={<FileType size={12} />} label="DOCX" color="#2563eb" />
      <Btn kind="fincen" icon={<Code2 size={12} />} label="FinCEN XML" color="#7c3aed" />
      <Btn kind="stix" icon={<Share2 size={12} />} label="STIX 2.1" color="#0891b2" />
      <Btn kind="misp" icon={<Download size={12} />} label="MISP" color="#16a34a" />
      {caps && (caps.pdf === 'unavailable' || caps.docx === 'unavailable') && (
        <span className="text-[10px] text-text-muted self-center">
          {caps.pdf === 'unavailable' && 'PDF: install weasyprint · '}
          {caps.docx === 'unavailable' && 'DOCX: install python-docx'}
        </span>
      )}
    </div>
  )
}
