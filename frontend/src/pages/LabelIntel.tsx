import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Building2, Database, Plus, Search, ShieldAlert, Trash2, Upload, Loader2 } from 'lucide-react'
import { createLabel, deleteLabel, importLabels, listLabels, importOfacLabels, getVaspDossier } from '../api/client'
import type { VaspDossier } from '../api/client'
import CinematicStage from '../components/CinematicStage'
import type { LocalLabel } from '../types'

function scoreColor(score: number) {
  if (score >= 70) return '#F87171'
  if (score >= 35) return '#FBBF24'
  if (score > 0) return '#ff5a6e'
  return '#b0929a'
}

export default function LabelIntel() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [query, setQuery] = useState('')
  const [form, setForm] = useState({
    address: '',
    chain: '',
    label: '',
    category: '',
    risk_weight: 0,
    confidence: 1,
    source: 'investigator',
    notes: '',
  })
  const [csvText, setCsvText] = useState('')

  const { data: labels = [], isFetching } = useQuery<LocalLabel[]>({
    queryKey: ['labels', query],
    queryFn: () => listLabels(query),
  })

  const createMut = useMutation({
    mutationFn: () => createLabel(form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['labels'] })
      setForm((p) => ({ ...p, address: '', label: '', notes: '' }))
    },
  })

  const importMut = useMutation({
    mutationFn: () => importLabels(csvText),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['labels'] })
      setCsvText('')
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteLabel(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['labels'] }),
  })

  // Attribution growth loop + VASP dossier
  const ofacMut = useMutation({ mutationFn: importOfacLabels })
  const [vaspQuery, setVaspQuery] = useState('')
  const [dossier, setDossier] = useState<VaspDossier | null>(null)
  const dossierMut = useMutation({
    mutationFn: () => getVaspDossier(vaspQuery.trim()),
    onSuccess: (d) => setDossier(d),
  })

  function downloadDossier() {
    if (!dossier) return
    const blob = new Blob([dossier.markdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `vasp-dossier-${dossier.vasp_name.replace(/\s+/g, '-')}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="noscroll-page p-6 max-w-6xl mx-auto space-y-5">
      <CinematicStage
        variant="labels"
        icon={Database}
        collapsed={false}
      >
        <div>
          <p className="card-title">{t('tools:labelIntel.addLabel.title')}</p>
          <div className="grid grid-cols-1 md:grid-cols-[1fr_90px_160px_150px_110px_110px] gap-3">
            <input className="input" placeholder={t('tools:labelIntel.addLabel.addressPh')} value={form.address}
              onChange={(e) => setForm({ ...form, address: e.target.value })} />
            <input className="input" placeholder={t('tools:labelIntel.addLabel.chainPh')} value={form.chain}
              onChange={(e) => setForm({ ...form, chain: e.target.value.toUpperCase() })} />
            <input className="input" placeholder={t('tools:labelIntel.addLabel.labelPh')} value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })} />
            <input className="input" placeholder={t('tools:labelIntel.addLabel.categoryPh')} value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })} />
            <input className="input" type="number" min={0} max={100} placeholder={t('tools:labelIntel.addLabel.riskPh')}
              value={form.risk_weight}
              onChange={(e) => setForm({ ...form, risk_weight: Number(e.target.value) })} />
            <input className="input" type="number" min={0} max={1} step={0.05} placeholder={t('tools:labelIntel.addLabel.confPh')}
              value={form.confidence}
              onChange={(e) => setForm({ ...form, confidence: Number(e.target.value) })} />
          </div>
          <div className="flex gap-3 mt-3">
            <input className="input flex-1" placeholder={t('tools:labelIntel.addLabel.notesPh')} value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            <button className="btn-primary" disabled={!form.address.trim() || !form.label.trim() || createMut.isPending}
              onClick={() => createMut.mutate()}>
              {createMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              {t('tools:labelIntel.addLabel.addBtn')}
            </button>
          </div>
        </div>
      </CinematicStage>

      {/* Labels management — grows & scrolls internally */}
      <div className="noscroll-grow space-y-5">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="card">
          <p className="card-title">{t('tools:labelIntel.csv.title')}</p>
          <textarea
            className="input min-h-[96px] resize-y"
            placeholder={t('tools:labelIntel.csv.placeholder')}
            value={csvText}
            onChange={(e) => setCsvText(e.target.value)}
          />
          <button className="btn-secondary mt-3" disabled={!csvText.trim() || importMut.isPending}
            onClick={() => importMut.mutate()}>
            {importMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
            {t('tools:labelIntel.csv.importBtn')}
          </button>
        </div>

        {/* ── Label growth loop: bulk open-source imports ── */}
        <div className="card">
          <p className="card-title flex items-center gap-2"><ShieldAlert size={13} /> {t('tools:labelIntel.attributionImports.title')}</p>
          <p className="text-xs text-text-secondary">
            {t('tools:labelIntel.attributionImports.hint')}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button className="btn-primary text-xs" disabled={ofacMut.isPending} onClick={() => ofacMut.mutate()}>
              {ofacMut.isPending ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
              {t('tools:labelIntel.attributionImports.ofacBtn')}
            </button>
            {ofacMut.data && (
              <span className="text-xs text-neon-green">
                {t('tools:labelIntel.attributionImports.ofacResult', { imported: ofacMut.data.imported, skipped: ofacMut.data.skipped_duplicates, rows: ofacMut.data.rows_in_file })}
              </span>
            )}
            {ofacMut.isError && <span className="text-xs text-risk-mixer">{t('tools:labelIntel.attributionImports.ofacFailed')}</span>}
          </div>
          <p className="mt-3 text-[11px] text-text-muted">
            {t('tools:labelIntel.attributionImports.duneHint')}
          </p>
        </div>
      </div>

      {/* ── VASP due-diligence dossier ── */}
      <div className="card">
        <p className="card-title flex items-center gap-2"><Building2 size={13} /> {t('tools:labelIntel.vasp.title')}</p>
        <div className="flex gap-2">
          <input className="input flex-1" placeholder={t('tools:labelIntel.vasp.placeholder')}
            value={vaspQuery} onChange={(e) => setVaspQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') dossierMut.mutate() }} />
          <button className="btn-secondary" disabled={!vaspQuery.trim() || dossierMut.isPending}
            onClick={() => dossierMut.mutate()}>
            {dossierMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
            {t('tools:labelIntel.vasp.buildBtn')}
          </button>
          {dossier && (
            <button className="btn-ghost text-xs" onClick={downloadDossier}>{t('tools:labelIntel.vasp.downloadMd')}</button>
          )}
        </div>
        {dossierMut.isError && (
          <p className="mt-2 text-xs text-risk-mixer">
            {(dossierMut.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t('tools:labelIntel.vasp.failed')}
          </p>
        )}
        {dossier && (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm font-bold text-text-primary">{dossier.vasp_name}</span>
              <span className="badge badge-muted">{dossier.vasp_type}</span>
              <span className="text-xs text-text-muted">
                {dossier.country || t('tools:labelIntel.vasp.countryUnknown')} · {dossier.jurisdiction || t('tools:labelIntel.vasp.jurisdictionUnknown')}
              </span>
              <span className="text-xs font-bold" style={{
                color: dossier.risk_level === 'CRITICAL' ? '#ff5d86' : dossier.risk_level === 'HIGH' ? '#F87171'
                  : dossier.risk_level === 'MEDIUM' ? '#FBBF24' : '#34D399',
              }}>
                {t('tools:labelIntel.vasp.risk', { level: dossier.risk_level })}
              </span>
            </div>
            <ul className="space-y-1">
              {dossier.risk_reasons.map((r, i) => <li key={i} className="text-xs text-text-secondary">▸ {r}</li>)}
            </ul>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="bg-bg-secondary border border-border rounded-lg px-3 py-2">
                <p className="text-[10px] text-text-muted uppercase tracking-widest">{t('tools:labelIntel.vasp.statAddresses')}</p>
                <p className="text-lg font-bold font-mono text-text-primary">{dossier.address_count}</p>
              </div>
              <div className="bg-bg-secondary border border-border rounded-lg px-3 py-2">
                <p className="text-[10px] text-text-muted uppercase tracking-widest">{t('tools:labelIntel.vasp.statChains')}</p>
                <p className="text-lg font-bold font-mono text-text-primary">{dossier.chains.length || '-'}</p>
              </div>
              <div className="bg-bg-secondary border border-border rounded-lg px-3 py-2">
                <p className="text-[10px] text-text-muted uppercase tracking-widest">{t('tools:labelIntel.vasp.statSanctions')}</p>
                <p className="text-lg font-bold font-mono" style={{ color: dossier.sanctions_exposure.length ? '#ff5d86' : undefined }}>
                  {dossier.sanctions_exposure.length}</p>
              </div>
              <div className="bg-bg-secondary border border-border rounded-lg px-3 py-2">
                <p className="text-[10px] text-text-muted uppercase tracking-widest">{t('tools:labelIntel.vasp.statHighRisk')}</p>
                <p className="text-lg font-bold font-mono" style={{ color: dossier.high_risk_attributions.length ? '#F87171' : undefined }}>
                  {dossier.high_risk_attributions.length}</p>
              </div>
            </div>
            <p className="text-[11px] italic text-text-muted">{dossier.disclaimer}</p>
          </div>
        )}
      </div>

      <div className="card">
        <div className="flex items-center justify-between gap-3 mb-3">
          <p className="card-title mb-0">{t('tools:labelIntel.labelsTable.title', { count: labels.length })}</p>
          <div className="relative w-72">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input className="input pl-8 py-1.5 text-xs" placeholder={t('tools:labelIntel.labelsTable.searchPh')}
              value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
        </div>
        {isFetching ? (
          <div className="flex justify-center py-8"><Loader2 className="animate-spin text-accent-cyan" /></div>
        ) : labels.length === 0 ? (
          <p className="text-xs text-text-muted">{t('tools:labelIntel.labelsTable.empty')}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t('tools:labelIntel.labelsTable.colAddress')}</th><th>{t('tools:labelIntel.labelsTable.colChain')}</th><th>{t('tools:labelIntel.labelsTable.colLabel')}</th><th>{t('tools:labelIntel.labelsTable.colCategory')}</th><th>{t('tools:labelIntel.labelsTable.colRisk')}</th><th>{t('tools:labelIntel.labelsTable.colSource')}</th><th></th>
                </tr>
              </thead>
              <tbody>
                {labels.map((l) => (
                  <tr key={l.id}>
                    <td className="font-mono max-w-[260px] truncate">{l.address}</td>
                    <td>{l.chain || '-'}</td>
                    <td className="text-text-primary font-semibold">{l.label}</td>
                    <td>{l.category || '-'}</td>
                    <td style={{ color: scoreColor(l.risk_weight) }}>{l.risk_weight}</td>
                    <td>{l.source}</td>
                    <td>
                      <button className="text-text-muted hover:text-neon-red"
                        onClick={() => deleteMut.mutate(l.id)}>
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      </div>
    </div>
  )
}
