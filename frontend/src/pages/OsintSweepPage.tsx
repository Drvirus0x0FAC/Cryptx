/**
 * OsintSweepPage - live social / forum / darkweb-index scan for any address.
 * Sources: Reddit, GitHub, Ahmia (.onion index), Pastebin dumps, BitcoinTalk.
 * Results cache for 24h and can be filed into the evidence vault.
 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Radar, Loader2, RefreshCw, Archive, ExternalLink, AlertTriangle,
  CheckCircle2, XCircle, KeyRound, Search, Network, ShieldAlert, Globe,
  MessagesSquare, Code2, FileWarning, Skull,
} from 'lucide-react'
import { osintSweep, osintToEvidence, type OsintSweepResult, type RedditType } from '../api/boards'
import { listCases } from '../api/client'
import CinematicStage from '../components/CinematicStage'
import type { Case } from '../types'

const SOURCE_LABELS: Record<string, string> = {
  cryptoscamdb: 'CryptoScamDB', chainabuse: 'Chainabuse', bitcoinwhoswho: "Bitcoin Who's Who",
  ahmia_darkweb: 'Ahmia (darkweb)', reddit: 'Reddit', reddit_deep: 'Reddit (deep)', x_twitter: 'X / Twitter',
  telegram: 'Telegram', bitcointalk: 'BitcoinTalk', github: 'GitHub',
  pastebin_dumps: 'Pastebin', web_mentions: 'Open web',
}

const CATEGORY_META: Record<string, { label: string; color: string; icon: typeof Globe }> = {
  abuse: { label: 'Scam / abuse', color: '#ff2d55', icon: FileWarning },
  darkweb: { label: 'Darkweb', color: '#bf5af2', icon: Skull },
  paste: { label: 'Paste leak', color: '#ff9f0a', icon: FileWarning },
  social: { label: 'Social', color: '#4aa3ff', icon: MessagesSquare },
  forum: { label: 'Forum', color: '#22c578', icon: MessagesSquare },
  code: { label: 'Code', color: '#8e9db5', icon: Code2 },
  web: { label: 'Open web', color: '#8e9db5', icon: Globe },
}

const SIGNAL_TONE: Record<string, { color: string; bg: string; label: string }> = {
  critical: { color: '#ff2d55', bg: 'rgba(255,45,85,0.12)', label: 'CRITICAL' },
  high: { color: '#ff5a30', bg: 'rgba(255,90,48,0.12)', label: 'HIGH' },
  elevated: { color: '#bf5af2', bg: 'rgba(191,90,242,0.12)', label: 'ELEVATED' },
  notable: { color: '#ff9f0a', bg: 'rgba(255,159,10,0.12)', label: 'NOTABLE' },
  informational: { color: '#4aa3ff', bg: 'rgba(74,163,255,0.10)', label: 'INFO' },
  clear: { color: '#22c578', bg: 'rgba(34,197,120,0.10)', label: 'CLEAR' },
}

function sourceTone(source: { ok: boolean; status?: string | null }) {
  if (source.ok && source.status === 'fallback') return 'warning'
  if (source.ok) return 'ok'
  if (['blocked', 'timeout', 'unavailable', 'unconfigured'].includes(source.status || '')) return 'warning'
  return 'error'
}

export default function OsintSweepPage() {
  const { t } = useTranslation()
  const { addr = '' } = useParams()
  const navigate = useNavigate()
  const [input, setInput] = useState(addr)
  const [result, setResult] = useState<OsintSweepResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [caseId, setCaseId] = useState('')
  const [filed, setFiled] = useState('')
  const [filter, setFilter] = useState('')
  const [redditType, setRedditType] = useState<RedditType>('all')

  const { data: cases = [] } = useQuery<Case[]>({ queryKey: ['cases'], queryFn: listCases })

  async function run(address: string, refresh = false, rType: RedditType = redditType) {
    if (!address.trim()) return
    setLoading(true)
    setError('')
    setFiled('')
    try {
      setResult(await osintSweep(address.trim(), refresh, rType))
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || t('tools:osintSweep.errors.failed'))
    }
    setLoading(false)
  }

  useEffect(() => { if (addr) { setInput(addr); run(addr) } // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addr])

  const hits = (result?.hits || []).filter((h) => !filter || h.source === filter)

  return (
    <div className="noscroll-page p-6 max-w-5xl mx-auto space-y-5 page-enter">
      <CinematicStage
        variant="osint"
        icon={Radar}
        collapsed={!!result}
      >
        <div className="flex gap-2 flex-wrap">
          <input className="input font-mono flex-1 min-w-[240px]" placeholder={t('tools:osintSweep.inputPlaceholder')}
            value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/osint/${encodeURIComponent(input.trim())}`) }} />
          <select className="input !w-auto" value={redditType} onChange={(e) => setRedditType(e.target.value as RedditType)}
            title={t('tools:osintSweep.subtitle')}>
            <option value="all">{t('tools:osintSweep.reddit.all')}</option>
            <option value="posts">{t('tools:osintSweep.reddit.posts')}</option>
            <option value="comments">{t('tools:osintSweep.reddit.comments')}</option>
            <option value="off">{t('tools:osintSweep.reddit.off')}</option>
          </select>
          <button className="btn-primary" onClick={() => navigate(`/osint/${encodeURIComponent(input.trim())}`)} disabled={!input.trim() || loading}>
            {loading ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />} {t('tools:osintSweep.sweep')}
          </button>
          {result && (
            <button className="btn-ghost" title={t('tools:osintSweep.subtitle')} onClick={() => run(input, true)} disabled={loading}>
              <RefreshCw size={13} />
            </button>
          )}
        </div>
      </CinematicStage>

      {/* Results — grows & scrolls internally */}
      <div className="noscroll-grow space-y-5">
      {error && <div className="card-cyber !border-red-500/40 text-xs text-red-400 flex items-center gap-2"><AlertTriangle size={13} />{error}</div>}
      {loading && <div className="card-cyber text-xs text-text-muted flex items-center gap-2"><Loader2 size={13} className="animate-spin" /> {t('tools:osintSweep.loading')}</div>}

      {result && !loading && (
        <>
          {/* Signal assessment banner */}
          {result.signals && (() => {
            const tone = SIGNAL_TONE[result.signals.level] || SIGNAL_TONE.informational
            return (
              <div className="rounded-lg p-3 flex items-start gap-3" style={{ background: tone.bg, border: `1px solid ${tone.color}55` }}>
                <ShieldAlert size={18} style={{ color: tone.color }} className="mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold tracking-widest px-1.5 py-0.5 rounded" style={{ background: tone.color, color: '#0a0e18' }}>{tone.label}</span>
                    <span className="text-xs font-semibold" style={{ color: tone.color }}>{result.signals.headline}</span>
                  </div>
                  {result.signals.by_category.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {result.signals.by_category.map((c) => {
                        const m = CATEGORY_META[c.category] || CATEGORY_META.web
                        const Icon = m.icon
                        return (
                          <button key={c.category} onClick={() => setFilter('')} title={`${c.hits} hits`}
                            className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded"
                            style={{ background: `${m.color}1e`, color: m.color, border: `1px solid ${m.color}44` }}>
                            <Icon size={10} /> {m.label} · {c.hits}
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              </div>
            )
          })()}

          {/* Pivots for the swept address */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-widest text-text-muted">{t('tools:osintSweep.pivots.label')}</span>
            <button className="btn-ghost !py-1 !text-xs" onClick={() => navigate(`/nexus/${encodeURIComponent(result.address)}`)} style={{ color: '#4aa3ff' }}>
              <Network size={12} /> {t('tools:osintSweep.pivots.nexus')}
            </button>
            <button className="btn-ghost !py-1 !text-xs" onClick={() => navigate(`/intel/${encodeURIComponent(result.address)}`)}>
              <Search size={12} /> {t('tools:osintSweep.pivots.addressIntel')}
            </button>
          </div>

          {/* Deep Reddit investigation summary */}
          {result.reddit_deep?.enabled && (
            <div className="card-cyber !py-2.5 flex items-center gap-3 flex-wrap" style={{ borderColor: 'rgba(255,69,0,0.35)' }}>
              <div className="flex h-7 w-7 items-center justify-center rounded-lg shrink-0" style={{ background: 'rgba(255,69,0,0.14)' }}>
                <MessagesSquare size={14} style={{ color: '#ff4500' }} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-text-primary">{t('tools:osintSweep.deepReddit.title')}
                  <span className="text-text-muted font-normal"> · reddit_scraper --type {result.reddit_deep.search_type}</span>
                </p>
                <p className="text-[11px] text-text-secondary">
                  <b className="text-text-primary">{result.reddit_deep.posts}</b> {t('tools:osintSweep.deepReddit.postsWord')} · <b className="text-text-primary">{result.reddit_deep.comments}</b> {t('tools:osintSweep.deepReddit.commentsWord')}
                  {result.reddit_deep.status && <span className="text-text-muted"> · {result.reddit_deep.status}</span>}
                </p>
                {result.reddit_deep.warning && <p className="text-[10px] text-amber-400 mt-0.5">{result.reddit_deep.warning}</p>}
              </div>
              <button className="btn-ghost !py-1 !text-xs" onClick={() => setFilter(filter === 'reddit_deep' ? '' : 'reddit_deep')}>
                {filter === 'reddit_deep' ? t('tools:osintSweep.deepReddit.showAll') : t('tools:osintSweep.deepReddit.showReddit')}
              </button>
            </div>
          )}

          {/* Source status strip */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            {Object.entries(result.sources).map(([name, s]) => {
              const tone = sourceTone(s)
              const message = s.warning || s.error || (s.status === 'fallback' ? t('tools:osintSweep.sources.fallback') : '')
              return (
                <button key={name} onClick={() => setFilter(filter === name ? '' : name)}
                  className={`card-cyber !p-2.5 text-left transition-colors ${filter === name ? '!border-neon-cyan/60' : ''}`}>
                  <div className="flex items-center gap-1.5 text-[10px] text-text-muted">
                    {tone === 'ok' && <CheckCircle2 size={11} className="text-emerald-400" />}
                    {tone === 'warning' && <AlertTriangle size={11} className="text-amber-400" />}
                    {tone === 'error' && <XCircle size={11} className="text-red-400" />}
                    {SOURCE_LABELS[name] || name}
                  </div>
                  <div className="text-lg font-bold text-text-primary mt-0.5">{s.hits}</div>
                  {message && (
                    <div
                      className={`text-[9px] truncate ${tone === 'error' ? 'text-red-400' : 'text-amber-300'}`}
                      title={message}
                    >
                      {message}
                    </div>
                  )}
                </button>
              )
            })}
          </div>

          {/* File to evidence */}
          <div className="card-cyber flex items-center gap-2 flex-wrap !py-2.5">
            <span className="text-xs text-text-secondary flex-1">
              {t('tools:osintSweep.evidence.totalHits', { count: result.total_hits, at: result.swept_at?.slice(0, 16).replace('T', ' ') })}
              {result.cached && ` · ${t('tools:osintSweep.evidence.cached')}`}
            </span>
            <select className="input !py-1 !text-xs w-52" value={caseId} onChange={(e) => setCaseId(e.target.value)}>
              <option value="">{t('tools:osintSweep.evidence.selectCase')}</option>
              {cases.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <button className="btn-ghost !py-1" disabled={!caseId}
              onClick={() => osintToEvidence(result.address, caseId).then((r) => setFiled(t('tools:osintSweep.evidence.filedOk', { id: r.evidence_id.slice(0, 8), hash: r.chain_hash.slice(0, 12) }))).catch(() => setFiled(t('tools:osintSweep.evidence.filedFail')))}>
              <Archive size={12} /> {t('tools:osintSweep.evidence.fileBtn')}
            </button>
            {filed && <span className="text-[10px] text-emerald-400">{filed}</span>}
          </div>

          {/* Hits */}
          {hits.length === 0 ? (
            <div className="card-cyber text-center py-8 text-xs text-text-muted">
              {t('tools:osintSweep.hits.empty')}
            </div>
          ) : (
            <div className="space-y-2">
              {hits.map((h, i) => {
                const m = CATEGORY_META[h.category || 'web'] || CATEGORY_META.web
                const Icon = m.icon
                return (
                  <div key={i} className="card-cyber !py-2.5"
                    style={h.high_signal ? { borderLeft: `3px solid ${m.color}`, borderRadius: 0 } : undefined}>
                    <div className="flex items-center gap-2 text-[10px] text-text-muted flex-wrap">
                      <span className="px-1.5 py-0.5 rounded bg-bg-secondary uppercase tracking-wider">{SOURCE_LABELS[h.source] || h.source}</span>
                      <span className="flex items-center gap-1 px-1.5 py-0.5 rounded" style={{ background: `${m.color}1e`, color: m.color }}>
                        <Icon size={9} /> {m.label}
                      </span>
                      {h.post_type && <span className="px-1.5 py-0.5 rounded" style={{ background: 'rgba(255,69,0,0.16)', color: '#ff6a33' }}>{h.post_type}</span>}
                      {h.subreddit && <span>r/{h.subreddit}</span>}
                      {h.author && <span>u/{h.author}</span>}
                      {typeof h.score === 'number' && <span>{h.score} pts</span>}
                      {h.repo && <span>{h.repo}</span>}
                      {h.timestamp && <span>{h.timestamp}</span>}
                      <div className="flex-1" />
                      <a href={h.url} target="_blank" rel="noreferrer noopener" className="flex items-center gap-1 text-neon-cyan hover:underline">
                        {t('tools:osintSweep.hits.open')} <ExternalLink size={10} />
                      </a>
                    </div>
                    <p className="text-xs font-semibold text-text-primary mt-1">{h.title || h.url}</p>
                    {h.snippet && <p className="text-[11px] text-text-secondary mt-0.5 line-clamp-2">{h.snippet}</p>}
                  </div>
                )
              })}
            </div>
          )}

          {/* Unconfigured sources */}
          <div className="card-cyber !py-2.5">
            <p className="text-[10px] uppercase tracking-widest text-text-muted mb-1.5">{t('tools:osintSweep.sources.additional')}</p>
            {result.unconfigured_sources.map((s) => (
              <p key={s.name} className="text-[11px] text-text-secondary flex items-center gap-1.5">
                <KeyRound size={10} className="text-amber-400" /> <b>{s.name}</b> - {s.note} <span className="text-text-muted">({s.requires})</span>
              </p>
            ))}
            <p className="text-[10px] text-text-muted mt-2">{result.disclaimer}</p>
          </div>
        </>
      )}
      </div>
    </div>
  )
}
