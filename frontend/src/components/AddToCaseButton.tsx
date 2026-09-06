/**
 * AddToCaseButton — assign or reassign a board to an investigation case.
 * Shows a dropdown with all cases; selecting one links the board to that case.
 * If the board is already assigned, shows the case name with an option to unassign.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FolderPlus, Check, X, ChevronDown, Loader2, Briefcase } from 'lucide-react'
import { listCases } from '../api/client'
import { updateBoard } from '../api/boards'
import type { Case } from '../types'

export default function AddToCaseButton({
  boardId, currentCaseId, compact = false, onLinked,
}: {
  boardId: string
  currentCaseId?: string
  compact?: boolean
  onLinked?: (caseId: string) => void
}) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)

  const { data: cases = [] } = useQuery<Case[]>({ queryKey: ['cases'], queryFn: listCases })

  const linkedCase = cases.find(c => c.id === currentCaseId)

  const linkMut = useMutation({
    mutationFn: (caseId: string) => updateBoard(boardId, { case_id: caseId }),
    onSuccess: (_data, caseId) => {
      qc.invalidateQueries({ queryKey: ['boards'] })
      qc.invalidateQueries({ queryKey: ['board', boardId] })
      setOpen(false)
      onLinked?.(caseId)
    },
  })

  if (compact && linkedCase) {
    // Already linked in compact mode — show a small badge
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold"
        style={{ background: 'rgba(6,182,212,0.1)', border: '1px solid rgba(6,182,212,0.25)', color: '#06b6d4' }}>
        <Briefcase size={10} /> {linkedCase.name}
      </span>
    )
  }

  return (
    <div className="relative">
      {linkedCase ? (
        // Already assigned — show case name + change/unassign
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setOpen(!open)}
            className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-[10px] font-semibold transition-colors"
            style={{ background: 'rgba(6,182,212,0.1)', border: '1px solid rgba(6,182,212,0.25)', color: '#06b6d4' }}
          >
            <Briefcase size={11} /> {linkedCase.name}
            <ChevronDown size={10} className="opacity-60" />
          </button>
        </div>
      ) : (
        <button
          onClick={() => setOpen(!open)}
          className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-[10px] font-semibold transition-colors text-text-muted hover:text-neon-cyan"
          style={{ border: '1px solid rgb(var(--bg-border))' }}
          title="Link this board to a case"
        >
          <FolderPlus size={11} /> Add to case
        </button>
      )}

      {open && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          {/* Dropdown */}
          <div className="absolute right-0 top-full mt-1 z-50 w-64 max-h-80 overflow-y-auto rounded-lg shadow-xl"
            style={{ background: 'rgb(var(--bg-elevated) / 0.98)', border: '1px solid rgb(var(--bg-border))', backdropFilter: 'blur(14px)' }}>
            <div className="p-2 border-b text-[10px] uppercase tracking-widest text-text-muted"
              style={{ borderColor: 'rgb(var(--bg-border))' }}>
              Link to case
            </div>
            {cases.length === 0 ? (
              <div className="p-3 text-xs text-text-muted text-center">
                No cases yet. <a href="/cases" className="text-neon-cyan underline">Create one</a>.
              </div>
            ) : (
              <div className="p-1">
                {cases.map(c => (
                  <button
                    key={c.id}
                    onClick={() => linkMut.mutate(c.id)}
                    disabled={linkMut.isPending}
                    className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded text-xs text-left transition-colors hover:bg-white/5"
                    style={{ color: c.id === currentCaseId ? '#06b6d4' : 'rgb(var(--text-primary))' }}
                  >
                    <span className="min-w-0">
                      <span className="font-semibold truncate block">{c.name}</span>
                      <span className="text-[9px] text-text-muted">{c.address_count ?? 0} addresses</span>
                    </span>
                    {c.id === currentCaseId && <Check size={13} className="shrink-0" />}
                  </button>
                ))}
              </div>
            )}
            {/* Unassign option */}
            {currentCaseId && (
              <div className="p-1 border-t" style={{ borderColor: 'rgb(var(--bg-border))' }}>
                <button
                  onClick={() => linkMut.mutate('')}
                  disabled={linkMut.isPending}
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-left text-text-muted hover:text-red-400 transition-colors"
                >
                  <X size={13} /> Unassign from case
                </button>
              </div>
            )}
            {linkMut.isPending && (
              <div className="p-2 text-center"><Loader2 size={13} className="animate-spin text-neon-cyan inline" /></div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
