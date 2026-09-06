import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  LayoutDashboard, Plus, Trash2, Loader2, Folder, FolderPlus, Pencil,
  Copy, MessageSquare, Share2, ChevronRight, Network, Search, ArrowUpDown, BoxSelect,
  Briefcase,
} from 'lucide-react'
import {
  listFolders, createFolder, renameFolder, deleteFolder,
  listBoards, createBoard, deleteBoard, duplicateBoard,
  type BoardFolder, type BoardMeta, type BoardPreview,
} from '../api/boards'
import { listCases } from '../api/client'
import type { Case } from '../types'
import AddToCaseButton from '../components/AddToCaseButton'
import CinematicStage from '../components/CinematicStage'

type SortKey = 'updated' | 'created' | 'name' | 'nodes'

/** Mini wire-frame render of the board graph for the card thumbnail. */
function PreviewThumb({ p }: { p?: BoardPreview | null }) {
  const W = 260; const H = 84
  const view = useMemo(() => {
    if (!p || !p.nodes.length) return null
    const xs = p.nodes.map((n) => n.x); const ys = p.nodes.map((n) => n.y)
    const minX = Math.min(...xs) - 40; const maxX = Math.max(...xs) + 40
    const minY = Math.min(...ys) - 40; const maxY = Math.max(...ys) + 40
    const s = Math.min(W / Math.max(1, maxX - minX), H / Math.max(1, maxY - minY))
    const ox = (W - s * (maxX - minX)) / 2
    const oy = (H - s * (maxY - minY)) / 2
    return {
      pts: p.nodes.map((n) => ({ x: ox + (n.x - minX) * s, y: oy + (n.y - minY) * s, c: n.c, k: n.k })),
    }
  }, [p])

  if (!view) {
    return (
      <div className="h-[84px] rounded-md flex items-center justify-center"
        style={{ background: 'rgba(5,7,13,0.7)', border: '1px solid rgba(51,65,92,0.35)' }}>
        <Network size={16} className="text-text-muted opacity-50" />
      </div>
    )
  }
  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
      className="rounded-md" style={{ background: 'rgba(5,7,13,0.7)', border: '1px solid rgba(51,65,92,0.35)' }}>
      {(p?.edges || []).map(([a, b], i) => {
        const pa = view.pts[a]; const pb = view.pts[b]
        if (!pa || !pb) return null
        return <line key={i} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="#33415c" strokeWidth={0.7} opacity={0.8} />
      })}
      {view.pts.map((pt, i) => (
        <circle key={i} cx={pt.x} cy={pt.y} r={pt.k === 'address' ? 2.4 : 3} fill={pt.c || '#8e9db5'} opacity={0.95} />
      ))}
    </svg>
  )
}

export default function Boards() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [activeFolder, setActiveFolder] = useState('')
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newCase, setNewCase] = useState('')
  const [newFolderName, setNewFolderName] = useState('')
  const [addingFolder, setAddingFolder] = useState(false)
  const [renamingId, setRenamingId] = useState('')
  const [renameValue, setRenameValue] = useState('')
  const [query, setQuery] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('updated')

  const { data: folders = [] } = useQuery<BoardFolder[]>({ queryKey: ['board-folders'], queryFn: () => listFolders() })
  const { data: boards = [], isLoading } = useQuery<BoardMeta[]>({
    queryKey: ['boards', activeFolder],
    queryFn: () => listBoards(activeFolder),
  })
  const { data: cases = [] } = useQuery<Case[]>({ queryKey: ['cases'], queryFn: listCases })

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    let out = boards
    if (q) out = out.filter((b) => b.name.toLowerCase().includes(q) || (b.description || '').toLowerCase().includes(q))
    const cmp: Record<SortKey, (a: BoardMeta, b: BoardMeta) => number> = {
      updated: (a, b) => String(b.updated_at).localeCompare(String(a.updated_at)),
      created: (a, b) => String(b.created_at).localeCompare(String(a.created_at)),
      name: (a, b) => a.name.localeCompare(b.name),
      nodes: (a, b) => (b.node_count ?? 0) - (a.node_count ?? 0),
    }
    return [...out].sort(cmp[sortKey])
  }, [boards, query, sortKey])

  // Group boards: assigned-to-cases (grouped by case name) vs unassigned
  const { byCase, unassigned } = useMemo(() => {
    const byCase: { caseId: string; caseName: string; boards: BoardMeta[] }[] = []
    const unassigned: BoardMeta[] = []
    for (const b of shown) {
      if (b.case_id) {
        const c = cases.find(c => c.id === b.case_id)
        const caseName = c?.name || 'Linked Case'
        let group = byCase.find(g => g.caseId === b.case_id)
        if (!group) { group = { caseId: b.case_id, caseName, boards: [] }; byCase.push(group) }
        group.boards.push(b)
      } else {
        unassigned.push(b)
      }
    }
    return { byCase, unassigned }
  }, [shown, cases])

  const totals = useMemo(() => ({
    boards: boards.length,
    nodes: boards.reduce((a, b) => a + (b.node_count ?? 0), 0),
    edges: boards.reduce((a, b) => a + (b.edge_count ?? 0), 0),
    openComments: boards.reduce((a, b) => a + (b.open_comments ?? 0), 0),
  }), [boards])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['boards'] })
    qc.invalidateQueries({ queryKey: ['board-folders'] })
  }

  const createBoardMut = useMutation({
    mutationFn: () => createBoard(newName.trim(), { description: newDesc.trim(), folder_id: activeFolder, case_id: newCase }),
    onSuccess: (b) => { invalidate(); setCreating(false); setNewName(''); setNewDesc(''); navigate(`/boards/${b.id}`) },
  })
  const deleteBoardMut = useMutation({ mutationFn: deleteBoard, onSuccess: invalidate })
  const duplicateMut = useMutation({ mutationFn: duplicateBoard, onSuccess: invalidate })
  const createFolderMut = useMutation({
    mutationFn: () => createFolder(newFolderName.trim()),
    onSuccess: () => { invalidate(); setAddingFolder(false); setNewFolderName('') },
  })
  const renameFolderMut = useMutation({
    mutationFn: () => renameFolder(renamingId, renameValue.trim()),
    onSuccess: () => { invalidate(); setRenamingId('') },
  })
  const deleteFolderMut = useMutation({ mutationFn: deleteFolder, onSuccess: () => { invalidate(); setActiveFolder('') } })

  return (
    <div className="noscroll-page p-6 max-w-6xl mx-auto space-y-6 page-enter">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center"
            style={{ background: 'rgba(10,132,255,0.12)', border: '1px solid rgba(10,132,255,0.3)' }}>
            <LayoutDashboard size={16} style={{ color: '#60A5FA' }} />
          </div>
          <div>
            <h1 className="text-display text-sm font-bold tracking-widest uppercase" style={{ color: '#eef4ff' }}>
              {t('tools:boards.title')}
            </h1>
            <p className="text-text-secondary text-xs mt-0.5">
              {t('tools:boards.subtitle')}
            </p>
          </div>
        </div>
        <button onClick={() => setCreating(true)} className="btn-primary">
          <Plus size={14} /> {t('tools:boards.newBoard')}
        </button>
      </div>

      {/* Stats strip */}
      <CinematicStage variant="boards" icon={LayoutDashboard} title={t('tools:boards.title')} subtitle={t('tools:boards.subtitle')} collapsed={false}>
      <div className="flex items-center gap-5 text-[11px] text-text-secondary">
        <span><b className="text-text-primary">{totals.boards}</b> {t('tools:boards.stats.boards')}</span>
        <span><b className="text-text-primary">{totals.nodes}</b> {t('tools:boards.stats.pins')}</span>
        <span><b className="text-text-primary">{totals.edges}</b> {t('tools:boards.stats.connections')}</span>
        {totals.openComments > 0 && (
          <span className="flex items-center gap-1 text-amber-400"><MessageSquare size={11} /><b>{totals.openComments}</b> {t('tools:boards.stats.openNotes')}</span>
        )}
        <div className="flex-1" />
        <div className="flex items-center gap-1 rounded-lg border border-bg-border bg-bg-elevated/60 px-2 py-1">
          <Search size={12} className="text-text-muted" />
          <input className="bg-transparent outline-none text-xs text-text-primary w-44"
            placeholder={t('tools:boards.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-bg-border bg-bg-elevated/60 px-2 py-1">
          <ArrowUpDown size={12} className="text-text-muted" />
          <select className="bg-transparent outline-none text-xs text-text-secondary"
            value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
            <option value="updated">{t('tools:boards.sort.updated')}</option>
            <option value="created">{t('tools:boards.sort.created')}</option>
            <option value="name">{t('tools:boards.sort.name')}</option>
            <option value="nodes">{t('tools:boards.sort.nodes')}</option>
          </select>
        </div>
      </div>
      </CinematicStage>

      <div className="noscroll-grow space-y-6">
      {creating && (
        <div className="card-cyber border-neon-cyan/30 space-y-3 animate-slide-up">
          <h3 className="card-title">{t('tools:boards.create.title')}</h3>
          <input value={newName} onChange={(e) => setNewName(e.target.value)} className="input"
            placeholder={t('tools:boards.create.namePh')} autoFocus />
          <textarea value={newDesc} onChange={(e) => setNewDesc(e.target.value)} className="input resize-none" rows={2}
            placeholder={t('tools:boards.create.descPh')} />
          <select value={newCase} onChange={(e) => setNewCase(e.target.value)} className="input">
            <option value="">{t('tools:boards.create.noCase')}</option>
            {cases.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <div className="flex gap-3">
            <button onClick={() => createBoardMut.mutate()} disabled={!newName.trim() || createBoardMut.isPending} className="btn-primary">
              {createBoardMut.isPending && <Loader2 size={13} className="animate-spin" />} {t('tools:boards.create.submit')}
            </button>
            <button onClick={() => setCreating(false)} className="btn-ghost">{t('tools:boards.create.cancel')}</button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[240px_1fr] gap-6">
        {/* Folders rail */}
        <div className="space-y-1">
          <div className="flex items-center justify-between px-1 pb-1">
            <span className="text-[10px] uppercase tracking-widest text-text-muted">{t('tools:boards.folders.label')}</span>
            <button onClick={() => setAddingFolder(true)} className="text-text-muted hover:text-text-primary" title={t('tools:boards.folders.newFolder')}>
              <FolderPlus size={13} />
            </button>
          </div>
          <button onClick={() => setActiveFolder('')}
            className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs text-left transition-colors ${activeFolder === '' ? 'bg-bg-secondary text-text-primary' : 'text-text-secondary hover:text-text-primary'}`}>
            <LayoutDashboard size={13} /> {t('tools:boards.folders.allBoards')}
          </button>
          {folders.map((f) => (
            <div key={f.id} className={`group w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs transition-colors ${activeFolder === f.id ? 'bg-bg-secondary text-text-primary' : 'text-text-secondary hover:text-text-primary'}`}>
              {renamingId === f.id ? (
                <input value={renameValue} onChange={(e) => setRenameValue(e.target.value)} className="input py-0.5 text-xs flex-1"
                  onKeyDown={(e) => { if (e.key === 'Enter') renameFolderMut.mutate(); if (e.key === 'Escape') setRenamingId('') }} autoFocus />
              ) : (
                <>
                  <button onClick={() => setActiveFolder(f.id)} className="flex items-center gap-2 flex-1 text-left min-w-0">
                    <Folder size={13} className="shrink-0" />
                    <span className="truncate">{f.name}</span>
                    <span className="text-text-muted">({f.board_count ?? 0})</span>
                  </button>
                  <button onClick={() => { setRenamingId(f.id); setRenameValue(f.name) }}
                    className="opacity-0 group-hover:opacity-100 text-text-muted hover:text-text-primary" title={t('tools:boards.folders.rename')}><Pencil size={11} /></button>
                  <button onClick={() => deleteFolderMut.mutate(f.id)}
                    className="opacity-0 group-hover:opacity-100 text-text-muted hover:text-red-400" title={t('tools:boards.folders.deleteFolder')}><Trash2 size={11} /></button>
                </>
              )}
            </div>
          ))}
          {addingFolder && (
            <div className="px-1 pt-1">
              <input value={newFolderName} onChange={(e) => setNewFolderName(e.target.value)} className="input py-1 text-xs"
                placeholder={t('tools:boards.folders.namePh')}
                onKeyDown={(e) => { if (e.key === 'Enter' && newFolderName.trim()) createFolderMut.mutate(); if (e.key === 'Escape') setAddingFolder(false) }} autoFocus />
            </div>
          )}
        </div>

        {/* Boards — grouped by case assignment */}
        <div>
          {isLoading ? (
            <div className="flex items-center gap-2 text-text-muted text-xs p-6"><Loader2 size={14} className="animate-spin" /> {t('tools:boards.loading')}</div>
          ) : shown.length === 0 ? (
            <div className="card-cyber text-center py-10">
              <Network size={22} className="mx-auto text-text-muted mb-2" />
              <p className="text-text-secondary text-xs">
                {query ? t('tools:boards.empty.noMatch', { query }) : (activeFolder ? t('tools:boards.empty.noBoardsFolder') : t('tools:boards.empty.noBoards'))}
              </p>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Assigned to cases */}
              {byCase.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <Briefcase size={13} style={{ color: '#06b6d4' }} />
                    <span className="text-[11px] uppercase tracking-widest font-bold text-text-muted">
                      {t('tools:boards.groups.assigned', { count: byCase.reduce((a, g) => a + g.boards.length, 0) })}
                    </span>
                  </div>
                  <div className="space-y-4">
                    {byCase.map(group => (
                      <div key={group.caseId}>
                        <button onClick={() => navigate(`/cases/${group.caseId}`)}
                          className="flex items-center gap-1.5 mb-2 text-xs font-semibold hover:underline"
                          style={{ color: '#06b6d4' }}>
                          <Briefcase size={11} />
                          {group.caseName}
                          <span className="text-text-muted font-normal">{t('tools:boards.groups.boardsCount', { count: group.boards.length })}</span>
                          <ChevronRight size={11} className="opacity-50" />
                        </button>
                        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                          {group.boards.map(b => <BoardCard key={b.id} b={b} />)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Unassigned */}
              {unassigned.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <LayoutDashboard size={13} className="text-text-muted" />
                    <span className="text-[11px] uppercase tracking-widest font-bold text-text-muted">
                      {t('tools:boards.groups.unassigned', { count: unassigned.length })}
                    </span>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                    {unassigned.map(b => <BoardCard key={b.id} b={b} />)}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      </div>
    </div>
  )

  // ── Board card (extracted so it can be reused in grouped sections) ──
  function BoardCard({ b }: { b: BoardMeta }) {
    return (
      <div className="card-cyber group cursor-pointer hover:border-neon-cyan/40 transition-colors"
        onClick={() => navigate(`/boards/${b.id}`)}>
        <PreviewThumb p={b.preview} />
        <div className="flex items-start justify-between gap-2 mt-2.5">
          <h3 className="text-xs font-bold text-text-primary truncate">{b.name}</h3>
          <ChevronRight size={13} className="text-text-muted shrink-0 group-hover:text-neon-cyan" />
        </div>
        {b.description && <p className="text-[11px] text-text-secondary mt-1 line-clamp-2">{b.description}</p>}
        <div className="flex items-center gap-3 mt-3 text-[10px] text-text-muted">
          <span>{t('tools:boards.card.pins', { count: b.node_count ?? 0 })}</span>
          <span>{t('tools:boards.card.links', { count: b.edge_count ?? 0 })}</span>
          {(b.zone_count ?? 0) > 0 && <span className="flex items-center gap-1"><BoxSelect size={10} />{b.zone_count}</span>}
          <span>v{b.version}</span>
          {(b.open_comments ?? 0) > 0 && <span className="flex items-center gap-1 text-amber-400"><MessageSquare size={10} />{b.open_comments}</span>}
          {(b.active_shares ?? 0) > 0 && <span className="flex items-center gap-1 text-neon-cyan"><Share2 size={10} />{b.active_shares}</span>}
        </div>
        <div className="flex items-center justify-between gap-2 mt-3 pt-2 border-t border-bg-border">
          {/* Add to case button */}
          <div onClick={(e) => e.stopPropagation()}>
            <AddToCaseButton boardId={b.id} currentCaseId={b.case_id} compact />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-text-muted">{t('tools:boards.card.updated', { date: String(b.updated_at || '').slice(0, 16).replace('T', ' ') })}</span>
            <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
              <button onClick={(e) => { e.stopPropagation(); duplicateMut.mutate(b.id) }}
                className="text-text-muted hover:text-text-primary" title={t('tools:boards.card.duplicate')}><Copy size={12} /></button>
              <button onClick={(e) => { e.stopPropagation(); if (window.confirm(t('tools:boards.card.deleteConfirm', { name: b.name }))) deleteBoardMut.mutate(b.id) }}
                className="text-text-muted hover:text-red-400" title={t('tools:boards.card.delete')}><Trash2 size={12} /></button>
            </div>
          </div>
        </div>
      </div>
    )
  }
}
