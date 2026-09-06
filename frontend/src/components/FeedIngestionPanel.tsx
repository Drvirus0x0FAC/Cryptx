/**
 * F5: Known-Bad Feed Ingestion panel.
 * Import CSV/JSON of address intelligence → review queue → approve/reject.
 * Plugs into the Attribution Submissions page.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Upload, Loader2, CheckCircle, XCircle, ChevronRight, FileUp } from 'lucide-react'
import { listFeedImports, getFeedImport, reviewFeedImport, importFeedCsv } from '../api/client'
import type { FeedImport, FeedImportRow } from '../types'

const SOURCE_LABELS: Record<string, string> = {
  etherscan_labels: 'Etherscan Labels',
  chainabuse: 'Chainabuse',
  curated_cluster: 'Curated Cluster',
  ofac_sdn: 'OFAC SDN',
  chainalysis_public: 'Chainalysis (public)',
  manual_bulk: 'Manual Bulk',
}

export default function FeedIngestionPanel() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [selectedId, setSelectedId] = useState('')
  const [importing, setImporting] = useState(false)
  const [csvText, setCsvText] = useState('')
  const [source, setSource] = useState('manual_bulk')

  const { data: importsData } = useQuery({ queryKey: ['feed-imports'], queryFn: () => listFeedImports() })
  const { data: detail } = useQuery({
    queryKey: ['feed-import', selectedId],
    queryFn: () => getFeedImport(selectedId, 'pending'),
    enabled: !!selectedId,
  })

  const importMut = useMutation({
    mutationFn: () => importFeedCsv({ source, csv_content: csvText }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['feed-imports'] }); setImporting(false); setCsvText('') },
  })
  const reviewMut = useMutation({
    mutationFn: ({ id, rowIds, action }: { id: string; rowIds: number[]; action: 'approve' | 'reject' }) =>
      reviewFeedImport(id, rowIds, action),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['feed-imports'] }); qc.invalidateQueries({ queryKey: ['feed-import', selectedId] }) },
  })

  const imports = importsData?.imports || []
  const rows: FeedImportRow[] = detail?.rows || []
  const sources = importsData?.sources || ['etherscan_labels','chainabuse','curated_cluster','ofac_sdn','chainalysis_public','manual_bulk']
  const allPendingRowIds = rows.filter((r: FeedImportRow) => r.status === 'pending').map((r: FeedImportRow) => r.id)

  return (
    <div className="space-y-4">
      <h3 className="card-title">Address Intelligence Imports</h3>

      {/* Import form */}
      <div className="card-cyber space-y-2">
        <div className="flex items-center gap-2">
          <FileUp size={14} style={{ color: '#60A5FA' }} />
          <span className="text-xs font-bold" style={{ color: '#fff2f4' }}>New Import</span>
        </div>
        <select value={source} onChange={e => setSource(e.target.value)} className="input">
          {sources.map(s => <option key={s} value={s}>{SOURCE_LABELS[s] || s}</option>)}
        </select>
        <textarea value={csvText} onChange={e => setCsvText(e.target.value)}
          placeholder="CSV: address,chain,label,category,entity&#10;0xabc...,eth,Binance Hot,exchange,Binance&#10;0xdef...,eth,Tornado,scam,..."
          rows={5} className="input resize-none font-mono text-xs" />
        <button onClick={() => { setImporting(true); importMut.mutate() }} disabled={!csvText.trim() || importMut.isPending} className="btn-primary text-xs">
          {importMut.isPending ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
          Queue for Review
        </button>
      </div>

      {/* Import list */}
      <div className="space-y-2">
        {imports.map((imp: FeedImport) => (
          <div key={imp.id} className="card-cyber py-2">
            <button onClick={() => setSelectedId(selectedId === imp.id ? '' : imp.id)}
              className="w-full flex items-center justify-between text-left">
              <div>
                <div className="text-xs font-bold" style={{ color: '#fff2f4' }}>
                  {SOURCE_LABELS[imp.source] || imp.source} {imp.filename && `· ${imp.filename}`}
                </div>
                <div className="text-[10px] text-text-muted">
                  {imp.imported_rows} rows · {imp.approved_rows} approved · {new Date(imp.created_at).toLocaleDateString()}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`badge ${imp.status === 'completed' ? 'badge-cyan' : imp.status === 'review' ? 'badge-muted' : 'badge-muted'}`}>{imp.status}</span>
                <ChevronRight size={14} className={`transition-transform ${selectedId === imp.id ? 'rotate-90' : ''}`} style={{ color: '#6b7280' }} />
              </div>
            </button>

            {/* Review rows */}
            {selectedId === imp.id && (
              <div className="mt-3 pt-3 border-t border-white/10 space-y-1 animate-slide-up">
                {rows.length === 0 ? (
                  <p className="text-text-muted text-xs py-2">No pending rows.</p>
                ) : (
                  <>
                    <div className="flex gap-2 mb-2">
                      <button onClick={() => reviewMut.mutate({ id: imp.id, rowIds: allPendingRowIds, action: 'approve' })}
                        className="btn-primary text-[10px] flex items-center gap-1"><CheckCircle size={11} /> Approve All</button>
                      <button onClick={() => reviewMut.mutate({ id: imp.id, rowIds: allPendingRowIds, action: 'reject' })}
                        className="btn-ghost text-[10px] flex items-center gap-1"><XCircle size={11} /> Reject All</button>
                    </div>
                    {rows.map((r: FeedImportRow) => (
                      <div key={r.id} className="flex items-center justify-between text-xs py-1 px-2 rounded" style={{ background: 'rgba(255,255,255,0.02)' }}>
                        <div className="flex-1 min-w-0">
                          <span className="font-mono text-[10px]">{r.address.slice(0, 20)}…</span>
                          <span className="ml-2 text-text-muted">{r.label || r.category}</span>
                          {r.risk_weight > 50 && <span className="ml-2 text-neon-red text-[10px]">⚠ {r.risk_weight}</span>}
                        </div>
                        <div className="flex gap-1">
                          <button onClick={() => reviewMut.mutate({ id: imp.id, rowIds: [r.id], action: 'approve' })}
                            className="text-green-400 hover:scale-110"><CheckCircle size={13} /></button>
                          <button onClick={() => reviewMut.mutate({ id: imp.id, rowIds: [r.id], action: 'reject' })}
                            className="text-red-400 hover:scale-110"><XCircle size={13} /></button>
                        </div>
                      </div>
                    ))}
                  </>
                )}
              </div>
            )}
          </div>
        ))}
        {imports.length === 0 && <p className="text-text-muted text-xs">No imports yet.</p>}
      </div>
    </div>
  )
}
