import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowRight, Building2, CornerDownLeft, Fingerprint, GitBranch, Hash, Network,
  Radar, Search, Shield, ShieldAlert, Tag, Waypoints, Brain, CandlestickChart,
} from 'lucide-react'
import { searchEntities } from '../api/client'
import type { EntityHit } from '../api/client'

export interface PaletteNavItem {
  to: string
  /** i18n key (under the `nav` namespace) resolved at render time. */
  labelKey: string
  icon: LucideIcon
  /** i18n key (under the `nav` namespace) for the parent section. */
  sectionKey: string
}

interface ActionDef {
  id: string
  /** i18n key prefix under the `command` namespace, e.g. "actions.auto". */
  key: string
  icon: LucideIcon
  to: string
}

interface ResolvedAction {
  id: string
  label: string
  hint: string
  icon: LucideIcon
  to: string
}

const EVM_ADDR = /^0x[a-fA-F0-9]{40}$/
const EVM_TX = /^0x[a-fA-F0-9]{64}$/
const RAW_TX = /^[a-fA-F0-9]{64}$/
const BTC_ADDR = /^(bc1[a-zA-Z0-9]{20,60}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$/
const TRON_ADDR = /^T[A-Za-z0-9]{33}$/
const SOL_ADDR = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/
const ENS_NAME = /^[a-z0-9-]+\.eth$/i

/** Build the list of subject actions for a paste-detected query (i18n keys only). */
function subjectActions(q: string): ActionDef[] {
  const enc = encodeURIComponent(q)
  const address: ActionDef[] = [
    { id: 'auto', key: 'command:actions.auto', icon: Radar, to: `/auto/${enc}` },
    { id: 'intel', key: 'command:actions.intel', icon: Shield, to: `/intel/${enc}` },
    { id: 'nexus', key: 'command:actions.nexus', icon: Network, to: `/nexus/${enc}` },
    { id: 'holistic', key: 'command:actions.holistic', icon: Waypoints, to: `/holistic/${enc}` },
    { id: 'forensics', key: 'command:actions.forensics', icon: Brain, to: `/forensics/${enc}` },
    { id: 'trace', key: 'command:actions.trace', icon: GitBranch, to: `/trace/${enc}` },
  ]
  if (EVM_TX.test(q)) {
    return [
      { id: 'txlens', key: 'command:actions.txlens', icon: Hash, to: `/tx-lens/AUTO/${enc}` },
      { id: 'txdetail', key: 'command:actions.txdetail', icon: Hash, to: `/tx/ETH/${enc}` },
      ...address.slice(0, 1),
    ]
  }
  if (RAW_TX.test(q)) {
    return [
      { id: 'txlens', key: 'command:actions.txlens', icon: Hash, to: `/tx-lens/AUTO/${enc}` },
      { id: 'txdetail', key: 'command:actions.txdetailBtc', icon: Hash, to: `/tx/BTC/${enc}` },
    ]
  }
  if (EVM_ADDR.test(q)) {
    return [...address,
      { id: 'perpdex', key: 'command:actions.perpdex', icon: CandlestickChart, to: `/perp-dex/${enc}` }]
  }
  if (BTC_ADDR.test(q) || TRON_ADDR.test(q) || ENS_NAME.test(q)) return address
  if (SOL_ADDR.test(q)) return address
  return []
}

export default function CommandPalette({ navItems }: { navItems: PaletteNavItem[] }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen(o => !o)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (open) {
      setQuery('')
      setCursor(0)
      setTimeout(() => inputRef.current?.focus(), 30)
    }
  }, [open])

  const q = query.trim()
  const subject = useMemo(() => subjectActions(q), [q])
  const navMatches = useMemo(() => {
    if (subject.length > 0) return []
    const needle = q.toLowerCase()
    // Match against the resolved (translated) label so users can type in their
    // own language, e.g. "tabl" finds "Tableau de bord" in French.
    const items = needle
      ? navItems.filter(i => t(i.labelKey).toLowerCase().includes(needle) || t(i.sectionKey).toLowerCase().includes(needle))
      : navItems
    return items.slice(0, 8)
  }, [q, subject.length, navItems, t])

  // Unified entity search (labels + attribution + KYV + sanctions) for text queries
  const [entityHits, setEntityHits] = useState<EntityHit[]>([])
  useEffect(() => {
    if (!open || subject.length > 0 || q.length < 2) { setEntityHits([]); return }
    const to = window.setTimeout(() => {
      searchEntities(q, 8)
        .then(r => setEntityHits(r.hits.slice(0, 8)))
        .catch(() => setEntityHits([]))
    }, 250)
    return () => window.clearTimeout(to)
  }, [q, open, subject.length])

  const entityIcon = (kind: EntityHit['kind']): LucideIcon =>
    kind === 'vasp' ? Building2 : kind === 'sanctions' ? ShieldAlert
    : kind === 'board' ? Network : kind === 'case' ? Radar : Tag

  const entityRoute = (h: EntityHit): string => {
    if (h.kind === 'board' && h.ref) return `/boards/${encodeURIComponent(h.ref)}`
    if (h.kind === 'case' && h.ref) return `/cases/${encodeURIComponent(h.ref)}`
    if (h.address) return `/intel/${encodeURIComponent(h.address)}`
    return h.kind === 'sanctions' ? '/sanctions' : '/attribution'
  }

  // Resolve subject action defs into label/hint using the active language.
  const resolvedSubject: ResolvedAction[] = subject.map(a => ({
    id: a.id,
    label: t(`${a.key}.label`),
    hint: t(`${a.key}.hint`),
    icon: a.icon,
    to: a.to,
  }))

  const rows: { key: string; label: string; hint: string; icon: LucideIcon; to: string }[] = [
    ...resolvedSubject.map(a => ({ key: a.id, label: a.label, hint: a.hint, icon: a.icon, to: a.to })),
    ...navMatches.map(i => ({ key: i.to, label: t(i.labelKey), hint: t(i.sectionKey), icon: i.icon, to: i.to })),
    ...entityHits.map((h, i) => ({
      key: `ent-${i}-${h.address || h.ref}`,
      label: `${h.name || h.address}`,
      hint: `${h.kind} · ${h.category}${h.chain ? ` · ${h.chain}` : ''}`,
      icon: entityIcon(h.kind),
      to: entityRoute(h),
    })),
  ]

  function go(to: string) {
    setOpen(false)
    navigate(to)
  }

  function onInputKey(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor(c => Math.min(c + 1, rows.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor(c => Math.max(c - 1, 0)) }
    else if (e.key === 'Enter' && rows[cursor]) { e.preventDefault(); go(rows[cursor].to) }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[120] flex items-start justify-center bg-black/60 backdrop-blur-sm pt-[14vh] px-4"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-xl rounded-xl border border-bg-border bg-bg-elevated shadow-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-bg-border px-4 py-3">
          <Search size={15} className="text-text-muted shrink-0" />
          <input
            ref={inputRef}
            className="flex-1 bg-transparent text-sm text-text-primary outline-none placeholder:text-text-muted font-mono"
            placeholder={t('command:palette.placeholder')}
            value={query}
            onChange={e => { setQuery(e.target.value); setCursor(0) }}
            onKeyDown={onInputKey}
          />
          <kbd className="text-[9px] text-text-muted border border-bg-border rounded px-1.5 py-0.5">{t('command:palette.hintEsc')}</kbd>
        </div>

        <div className="max-h-[46vh] overflow-y-auto py-2">
          {subject.length > 0 && (
            <p className="px-4 pb-1 text-[10px] uppercase tracking-widest text-text-muted">
              {t('command:palette.investigatePrefix')} <span className="font-mono normal-case text-text-secondary">{q.slice(0, 18)}…</span>
            </p>
          )}
          {rows.length === 0 && (
            <p className="px-4 py-6 text-center text-xs text-text-muted">
              {t('command:palette.empty')}
            </p>
          )}
          {rows.map((row, i) => {
            const Icon = row.icon
            return (
              <button
                key={row.key}
                type="button"
                onClick={() => go(row.to)}
                onMouseEnter={() => setCursor(i)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                  i === cursor ? 'bg-bg-secondary text-text-primary' : 'text-text-secondary'
                }`}
              >
                <Icon size={14} className={i === cursor ? 'text-accent-cyan' : 'text-text-muted'} />
                <span className="flex-1 text-xs font-semibold">{row.label}</span>
                <span className="text-[10px] text-text-muted">{row.hint}</span>
                {i === cursor && <CornerDownLeft size={12} className="text-text-muted" />}
              </button>
            )
          })}
        </div>

        <div className="flex items-center gap-4 border-t border-bg-border px-4 py-2 text-[10px] text-text-muted">
          <span className="flex items-center gap-1"><ArrowRight size={10} className="rotate-90" /> {t('command:palette.footerNavigate')}</span>
          <span className="flex items-center gap-1"><CornerDownLeft size={10} /> {t('command:palette.footerOpen')}</span>
          <span className="flex items-center gap-1"><Fingerprint size={10} /> {t('command:palette.footerAutoDetect')}</span>
        </div>
      </div>
    </div>
  )
}
