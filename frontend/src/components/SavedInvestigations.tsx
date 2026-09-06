/**
 * F2: Saved Investigations — list, save current, reopen, delete.
 * Lets investigators persist a graph and reopen it later without re-fetching.
 * Plugs into Nexus Graph (as a side panel).
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, FolderOpen, Trash2, Loader2, Network, Plus, X } from 'lucide-react'
import { listInvestigations, saveInvestigation, deleteInvestigation } from '../api/client'
import type { SavedInvestigation } from '../types'

export default function SavedInvestigations({
  subject, chain, graph, onOpen,
}: {
  subject?: string
  chain?: string
  graph?: Record<string, unknown>
  onOpen?: (inv: SavedInvestigation) => void
}) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [saving, setSaving] = useState(false)
  const [name, setName] = useState('')

  const { data, isLoading } = useQuery({ queryKey: ['investigations'], queryFn: () => listInvestigations() })
  const delMut = useMutation({
    mutationFn: (id: string) => deleteInvestigation(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['investigations'] }),
  })
  const saveMut = useMutation({
    mutationFn: () => saveInvestigation({ subject: subject || '', chain, graph: graph || {}, name: name || `Investigation ${subject?.slice(0, 10)}` }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['investigations'] }); setSaving(false); setName('') },
  })

  const invs = data?.investigations || []

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <FolderOpen size={15} style={{ color: '#60A5FA' }} />
        <h3 className="card-title">{t('components:shared.savedInv.title')}</h3>
      </div>

      {/* Save current */}
      {subject && graph && (
        <div className="card-cyber space-y-2">
          {saving ? (
            <>
              <input value={name} onChange={e => setName(e.target.value)} placeholder="Investigation name (optional)" className="input text-xs" />
              <div className="flex gap-2">
                <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending} className="btn-primary text-xs">
                  {saveMut.isPending ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Save
                </button>
                <button onClick={() => setSaving(false)} className="btn-ghost text-xs">Cancel</button>
              </div>
            </>
          ) : (
            <button onClick={() => setSaving(true)} className="btn-primary text-xs w-full">
              <Save size={12} /> Save Current Graph
            </button>
          )}
        </div>
      )}

      {/* List */}
      {isLoading ? <Loader2 className="animate-spin" size={18} /> : (
        <div className="space-y-2 max-h-[400px] overflow-y-auto">
          {invs.map(inv => (
            <div key={inv.id} className="card-cyber py-2 group">
              <div className="flex items-center justify-between">
                <button onClick={() => onOpen?.(inv)} className="flex-1 text-left min-w-0">
                  <div className="text-xs font-bold truncate" style={{ color: '#fff2f4' }}>{inv.name}</div>
                  <div className="text-[10px] text-text-muted flex items-center gap-2">
                    <span className="font-mono">{inv.subject.slice(0, 14)}…</span>
                    <Network size={9} />
                    <span>{inv.node_count} nodes · {inv.edge_count} edges</span>
                  </div>
                  <div className="text-[9px] text-text-muted">{new Date(inv.updated_at).toLocaleString()}</div>
                </button>
                <button onClick={() => delMut.mutate(inv.id)} className="opacity-0 group-hover:opacity-100 text-text-muted hover:text-neon-red transition-opacity">
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}
          {invs.length === 0 && (
            <div className="text-center py-6">
              <Plus size={24} className="mx-auto mb-2" style={{ color: '#6b7280', opacity: 0.5 }} />
              <p className="text-text-muted text-xs">No saved investigations yet.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
