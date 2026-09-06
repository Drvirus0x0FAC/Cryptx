import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import {
  FolderOpen, Plus, Trash2, AlertCircle, Loader2,
  Archive, CheckCircle, ArrowRight,
} from 'lucide-react'
import { listCases, createCase, deleteCase } from '../api/client'
import type { Case } from '../types'
import CinematicStage from '../components/CinematicStage'

function riskColor(score: number | null | undefined): string {
  if (score == null || score < 0) return '#475569'
  if (score >= 80) return '#F87171'
  if (score >= 60) return '#FBBF24'
  if (score >= 40) return '#FBBF24'
  if (score >= 20) return '#FBBF24'
  return '#34D399'
}

export default function CaseManager() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [newName, setNewName]     = useState('')
  const [newDesc, setNewDesc]     = useState('')
  const [creating, setCreating]   = useState(false)
  const [filterStatus, setFilter] = useState<string>('all')

  const { data: cases = [], isLoading, error } = useQuery<Case[]>({
    queryKey: ['cases'],
    queryFn: listCases,
  })

  const createMut = useMutation({
    mutationFn: () => createCase(newName.trim(), newDesc.trim()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases'] })
      setNewName('')
      setNewDesc('')
      setCreating(false)
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteCase(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cases'] }),
  })

  const filtered = filterStatus === 'all'
    ? cases
    : cases.filter((c) => c.status === filterStatus)

  return (
    <div className="noscroll-page p-6 max-w-5xl mx-auto space-y-6 page-enter">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center"
            style={{ background: 'rgba(255,45,85,0.12)', border: '1px solid rgba(255,45,85,0.3)' }}>
            <FolderOpen size={16} style={{ color: '#F87171' }} />
          </div>
          <div>
            <h1 className="text-display text-sm font-bold tracking-widest uppercase" style={{ color: 'inherit' }}>
              {t('tools:caseManager.title')}
            </h1>
            <p className="text-text-secondary text-xs mt-0.5">
              {t('tools:caseManager.subtitle')}
            </p>
          </div>
        </div>
        <button onClick={() => setCreating(true)} className="btn-primary">
          <Plus size={14} />
          {t('tools:caseManager.newCase')}
        </button>
      </div>

      {/* Create form */}
      {creating && (
        <CinematicStage variant="cases" icon={FolderOpen} kicker="INTAKE" title={t('tools:caseManager.create.title')} collapsed={false}>
        <div className="space-y-3 animate-slide-up">
          <h3 className="card-title">{t('tools:caseManager.create.title')}</h3>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t('tools:caseManager.create.namePlaceholder')}
            className="input"
          />
          <textarea
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            placeholder={t('tools:caseManager.create.descPlaceholder')}
            rows={3}
            className="input resize-none"
          />
          <div className="flex gap-3">
            <button
              onClick={() => createMut.mutate()}
              disabled={!newName.trim() || createMut.isPending}
              className="btn-primary"
            >
              {createMut.isPending && <Loader2 size={13} className="animate-spin" />}
              {t('tools:caseManager.create.submit')}
            </button>
            <button
              onClick={() => { setCreating(false); setNewName(''); setNewDesc('') }}
              className="btn-ghost"
            >
              {t('tools:caseManager.create.cancel')}
            </button>
          </div>
          {createMut.isError && (
            <p className="text-neon-red text-xs">{t('tools:caseManager.create.failed')}</p>
          )}
        </div>
        </CinematicStage>
      )}

      {/* Cases list — grows & scrolls internally */}
      <div className="noscroll-grow space-y-6">
      {/* Filter */}
      <div className="flex items-center gap-2">
        {(['all', 'active', 'closed', 'archived'] as const).map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={s === filterStatus ? 'badge badge-cyan' : 'badge badge-muted opacity-60 hover:opacity-100'}
          >
            {t(`tools:caseManager.filter.${s}`)}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-text-muted text-tech">
          {t('tools:caseManager.count', { count: filtered.length })}
        </span>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="animate-spin" size={28} style={{ color: '#ff5a6e' }} />
        </div>
      ) : error ? (
        <div className="flex items-center gap-2 text-neon-red text-sm">
          <AlertCircle size={15} />
          {t('tools:caseManager.loadFailed')}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20 text-text-muted">
          <FolderOpen size={44} className="mx-auto mb-4 opacity-20" />
          <p className="text-sm">{t('tools:caseManager.empty')}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((c, i) => {
            const isActive = c.status === 'active'
            const StatusIcon = isActive ? CheckCircle : Archive
            const score = c.max_risk_score ?? -1
            return (
              <div
                key={c.id}
                className="group card hover:border-neon-cyan/20 transition-all duration-150 animate-data-in"
                style={{ animationDelay: `${i * 40}ms` }}
              >
                <div className="flex items-start gap-4">
                  <StatusIcon size={16} className="mt-0.5 shrink-0"
                    style={{ color: isActive ? '#34D399' : '#475569' }} />

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 flex-wrap">
                      <Link
                        to={`/cases/${c.id}`}
                        className="text-sm font-semibold text-text-bright hover:text-neon-cyan transition-colors"
                      >
                        {c.name}
                      </Link>
                      <span className="text-tech text-[10px] px-1.5 py-0.5 rounded"
                        style={{
                          color: isActive ? '#34D399' : '#475569',
                          background: isActive ? 'rgba(0,255,136,0.08)' : 'rgba(10,34,64,0.5)',
                          border: `1px solid ${isActive ? 'rgba(0,255,136,0.2)' : '#160a0e'}`,
                        }}>
                        {t(`tools:caseManager.filter.${c.status as 'active' | 'closed' | 'archived'}`)}
                      </span>
                    </div>
                    {c.description && (
                      <p className="text-text-secondary text-xs mt-1 truncate">{c.description}</p>
                    )}
                    <div className="flex items-center gap-4 mt-1.5 text-[11px] text-text-muted text-tech">
                      <span>{t('tools:caseManager.card.addrCount', { count: c.address_count ?? 0 })}</span>
                      <span>{t('tools:caseManager.card.updated', { date: new Date(c.updated_at).toLocaleDateString() })}</span>
                      {score >= 0 && (
                        <span className="font-bold" style={{ color: riskColor(score) }}>
                          {t('tools:caseManager.card.maxRisk', { score })}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <Link
                      to={`/cases/${c.id}`}
                      className="flex items-center gap-1 text-[11px] text-neon-cyan hover:text-text-bright transition-colors"
                    >
                      {t('tools:caseManager.card.open')} <ArrowRight size={11} />
                    </Link>
                    <button
                      onClick={() => confirm(t('tools:caseManager.card.deleteConfirm', { name: c.name })) && deleteMut.mutate(c.id)}
                      className="p-1 text-text-muted hover:text-neon-red transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
      </div>
    </div>
  )
}
