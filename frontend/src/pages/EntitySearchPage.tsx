import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertCircle, ChevronRight, Loader2, Search, ShieldAlert, ShieldCheck, Building2, Ban, Tag } from 'lucide-react'
import { api } from '../api/client'

interface EntityCard {
  entity_id: string
  name: string
  type: string
  subtype: string
  category: string
  jurisdiction?: string
  country?: string
  addresses: Array<{ chain: string; address: string; label: string }>
  sources: string[]
  relevance: number
  also_in?: string[]
}

interface VaspDossier {
  entity: { name: string; type: string; jurisdiction: string; country: string }
  known_addresses: Array<{ chain: string; address: string; label: string }>
  address_count: number
  sanctions_screening: { screened: number; sanctioned_hits: number; sanctioned_addresses: unknown[] }
  risk_assessment: { level: string; score: number; basis: string; sanctioned: boolean }
  attribution_references: number
  disclaimer?: string
  generated_at?: string
}

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

const TYPE_ICONS: Record<string, typeof Building2> = {
  vasp: Building2,
  sanctioned_entity: Ban,
  attribution_label: Tag,
  local_label: Tag,
}

function relevanceColor(r: number) {
  if (r >= 0.85) return 'text-neon-green'
  if (r >= 0.6) return 'text-neon-amber'
  return 'text-text-muted'
}

export default function EntitySearchPage() {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<EntityCard[]>([])
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState('')
  const [dossier, setDossier] = useState<VaspDossier | null>(null)
  const [dossierLoading, setDossierLoading] = useState(false)
  const [dossierName, setDossierName] = useState('')

  async function search() {
    if (!query.trim() || query.trim().length < 2) return
    setLoading(true)
    setError('')
    setResults([])
    setDossier(null)
    try {
      const r = await api.get('/entities/search', { params: { q: query.trim(), limit: 20 } })
      setResults(r.data.entities || [])
      setSearched(true)
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setLoading(false)
    }
  }

  async function loadDossier(name: string) {
    setDossierLoading(true)
    setDossierName(name)
    setDossier(null)
    try {
      const r = await api.get(`/entities/vasp/${encodeURIComponent(name)}/dossier`)
      setDossier(r.data)
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setDossierLoading(false)
    }
  }

  return (
    <div className="noscroll-page mx-auto max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-text-primary">
          <Search className="text-neon-cyan" /> {t('entitySearch.title', 'Entity Search')}
        </h1>
        <p className="mt-1 text-sm text-text-muted">
          {t('entitySearch.subtitle', 'Search across VASP directory, sanctions lists, attribution labels, and local labels — one box, all sources.')}
        </p>
      </div>

      {/* Search bar */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search size={18} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && search()}
            placeholder="Search Binance, Lazarus, FixedFloat, Tornado Cash…"
            className="w-full rounded-lg border border-border bg-bg-secondary py-2.5 pl-10 pr-4 text-sm text-text-primary placeholder:text-text-muted focus:border-neon-cyan focus:outline-none"
          />
        </div>
        <button
          onClick={search}
          disabled={!query.trim() || loading}
          className="flex items-center gap-2 rounded-lg bg-neon-cyan px-5 py-2.5 text-sm font-bold text-bg-primary transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
          {t('common.search', 'Search')}
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">
          <AlertCircle size={16} /> {error}
        </div>
      )}

      <div className="noscroll-grow grid gap-6 lg:grid-cols-[1fr_400px] min-h-0">
        {/* Results list */}
        <div className="space-y-2">
          {searched && !loading && results.length === 0 && (
            <p className="py-8 text-center text-sm text-text-muted">No entities found for "{query}"</p>
          )}
          {results.map(entity => {
            const Icon = TYPE_ICONS[entity.type] || Tag
            return (
              <button
                key={entity.entity_id}
                onClick={() => entity.type === 'vasp' && loadDossier(entity.name)}
                className="group flex w-full items-start gap-3 rounded-lg border border-border bg-bg-secondary p-3 text-left transition-colors hover:border-neon-cyan/50"
              >
                <Icon size={20} className={`mt-0.5 shrink-0 ${entity.category === 'sanctioned' ? 'text-neon-red' : entity.category === 'exchange' ? 'text-neon-cyan' : 'text-text-muted'}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="font-bold text-text-primary">{entity.name}</p>
                    <span className={`text-[10px] font-bold ${relevanceColor(entity.relevance)}`}>{Math.round(entity.relevance * 100)}%</span>
                  </div>
                  <p className="text-[11px] uppercase tracking-widest text-text-muted">{entity.subtype} · {entity.category}</p>
                  {entity.jurisdiction && <p className="text-xs text-text-secondary">{entity.jurisdiction}</p>}
                  <div className="mt-1 flex flex-wrap gap-1">
                    {entity.sources.map(s => <span key={s} className="rounded border border-border px-1.5 py-0.5 text-[9px] text-text-muted">{s}</span>)}
                    {entity.addresses.length > 0 && <span className="rounded border border-border px-1.5 py-0.5 text-[9px] text-text-muted">{entity.addresses.length} addr</span>}
                  </div>
                </div>
                {entity.type === 'vasp' && <ChevronRight size={16} className="mt-1 shrink-0 text-text-muted group-hover:text-neon-cyan" />}
              </button>
            )
          })}
        </div>

        {/* VASP Dossier panel */}
        <div className="lg:sticky lg:top-4 lg:self-start">
          {dossierLoading && (
            <div className="flex items-center justify-center rounded-xl border border-border bg-bg-secondary p-8">
              <Loader2 className="animate-spin text-neon-cyan" />
            </div>
          )}
          {dossier && (
            <div className="space-y-3 rounded-xl border border-border bg-bg-secondary p-4">
              <div className="flex items-center gap-2">
                <Building2 className="text-neon-cyan" />
                <h3 className="font-bold text-text-primary">{dossier.entity.name}</h3>
              </div>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between"><span className="text-text-muted">Type</span><span className="text-text-primary">{dossier.entity.type}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Jurisdiction</span><span className="text-text-primary">{dossier.entity.jurisdiction || '—'}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Country</span><span className="text-text-primary">{dossier.entity.country || '—'}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Known addresses</span><span className="text-text-primary">{dossier.address_count}</span></div>
              </div>

              {/* Risk */}
              <div className={`rounded-lg border p-3 ${dossier.risk_assessment.sanctioned ? 'border-neon-red/50 bg-neon-red/10' : 'border-border bg-bg-elevated'}`}>
                <div className="flex items-center gap-2">
                  {dossier.risk_assessment.sanctioned ? <ShieldAlert className="text-neon-red" size={18} /> : <ShieldCheck className="text-neon-green" size={18} />}
                  <span className="font-bold text-text-primary">{dossier.risk_assessment.level}</span>
                  <span className="ml-auto text-lg font-mono font-bold text-text-primary">{dossier.risk_assessment.score}</span>
                </div>
                <p className="mt-1 text-xs text-text-muted">{dossier.risk_assessment.basis}</p>
              </div>

              {/* Sanctions screening */}
              <div className="text-xs">
                <p className="font-bold uppercase tracking-widest text-text-muted">Sanctions Screening</p>
                <p className="text-text-secondary">{dossier.sanctions_screening.screened} addresses screened · {dossier.sanctions_screening.sanctioned_hits} sanctioned</p>
              </div>

              <p className="text-[10px] italic text-text-muted">{dossier.disclaimer}</p>
            </div>
          )}
          {!dossier && !dossierLoading && (
            <div className="rounded-xl border border-dashed border-border bg-bg-secondary/50 p-8 text-center">
              <Building2 className="mx-auto mb-2 text-text-muted" size={32} />
              <p className="text-xs text-text-muted">{t('entitySearch.selectVasp', 'Click a VASP result to view its due-diligence dossier')}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
