/**
 * CoverageModal — in-app sub-screen showing all supported chains + tokens.
 * Triggered by the "N chains supported" badge on the Dashboard.
 */
import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { X, Search, Zap, CheckCircle2, ShieldCheck, Coins, Layers } from 'lucide-react'
import { SUPPORTED_CHAINS, SUPPORTED_TOKENS, type ChainInfo } from '../lib/coverage'
import { ChainLogo, brandColor } from '../lib/chainGlyphs'

const FAMILY_COLORS: Record<string, string> = {
  EVM: '#627eea',
  UTXO: '#f7931a',
  Solana: '#14f195',
  Tron: '#eb0029',
  Cosmos: '#2e3148',
  others: '#64748b',
}

const CATEGORY_LABELS: Record<string, { labelKey: string; color: string }> = {
  native:     { labelKey: 'components:shared.coverage.catNative',   color: '#627eea' },
  stablecoin: { labelKey: 'components:shared.coverage.catStablecoin', color: '#22c55e' },
  wrapped:    { labelKey: 'components:shared.coverage.catWrapped',  color: '#f59e0b' },
  lst:        { labelKey: 'components:shared.coverage.catLst',      color: '#8b5cf6' },
  defi:       { labelKey: 'components:shared.coverage.catDefi',     color: '#06b6d4' },
  meme:       { labelKey: 'components:shared.coverage.catMeme',     color: '#ec4899' },
}

export default function CoverageModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState<'chains' | 'tokens'>('chains')

  const filteredChains = useMemo(() => {
    if (!query.trim()) return SUPPORTED_CHAINS
    const q = query.toLowerCase()
    return SUPPORTED_CHAINS.filter(c =>
      c.name.toLowerCase().includes(q) || c.symbol.toLowerCase().includes(q) || c.id.includes(q)
    )
  }, [query])

  const filteredTokens = useMemo(() => {
    if (!query.trim()) return SUPPORTED_TOKENS
    const q = query.toLowerCase()
    return SUPPORTED_TOKENS.filter(t =>
      t.name.toLowerCase().includes(q) || t.symbol.toLowerCase().includes(q)
    )
  }, [query])

  // Group tokens by category
  const tokensByCategory = useMemo(() => {
    const groups: Record<string, typeof SUPPORTED_TOKENS> = {}
    for (const t of filteredTokens) {
      (groups[t.category] ||= []).push(t)
    }
    return groups
  }, [filteredTokens])

  // Group chains by family
  const chainsByFamily = useMemo(() => {
    const groups: Record<string, ChainInfo[]> = {}
    for (const c of filteredChains) {
      (groups[c.family] ||= []).push(c)
    }
    return groups
  }, [filteredChains])

  if (!open) return null

  const liveTraceCount = SUPPORTED_CHAINS.filter(c => c.liveTrace).length

  return (
    <div
      className="fixed left-0 right-0 bottom-0 top-[var(--topbar-h)] z-[90] flex items-start justify-center p-3 sm:p-4"
      style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-5xl overflow-hidden rounded-2xl flex flex-col"
        style={{
          maxHeight: 'calc(100dvh - var(--topbar-h) - 24px)',
          background: 'rgb(var(--bg-elevated) / 0.98)',
          border: '1px solid rgb(var(--bg-border))',
          boxShadow: '0 24px 70px rgba(0,0,0,0.4)',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between p-4 border-b" style={{ borderColor: 'rgb(var(--bg-border))' }}>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg flex items-center justify-center"
              style={{ background: 'rgba(220,38,38,0.12)', border: '1px solid rgba(220,38,38,0.3)' }}>
              <Zap size={18} style={{ color: '#dc2626' }} />
            </div>
            <div>
              <h2 className="text-sm font-bold tracking-wide uppercase" style={{ color: 'rgb(var(--text-bright))' }}>
                {t('components:shared.coverage.title')}
              </h2>
              <p className="text-xs" style={{ color: 'rgb(var(--text-muted))' }}>
                {SUPPORTED_CHAINS.length} {t('components:shared.coverage.blockchains')} · {SUPPORTED_TOKENS.length} {t('components:shared.coverage.tokens')} · {liveTraceCount} {t('components:shared.coverage.liveTraceable')}
              </p>
            </div>
          </div>
          <button onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
            style={{ background: 'rgb(var(--bg-secondary))', color: 'rgb(var(--text-muted))' }}>
            <X size={16} />
          </button>
        </div>

        {/* Search + tabs */}
        <div className="flex shrink-0 flex-col gap-2 p-3 border-b sm:flex-row sm:items-center" style={{ borderColor: 'rgb(var(--bg-border))' }}>
          <div className="relative min-w-0 flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'rgb(var(--text-muted))' }} />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder={t('components:shared.coverage.searchPh')}
              className="w-full h-9 pl-9 pr-3 rounded-lg text-xs"
              style={{ background: 'rgb(var(--bg-secondary))', border: '1px solid rgb(var(--bg-border))', color: 'rgb(var(--text-primary))' }}
            />
          </div>
          <div className="flex shrink-0 gap-1 p-0.5 rounded-lg" style={{ background: 'rgb(var(--bg-secondary))' }}>
            <button onClick={() => setTab('chains')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${tab === 'chains' ? '' : 'opacity-50'}`}
              style={tab === 'chains' ? { background: 'rgba(220,38,38,0.15)', color: '#dc2626' } : { color: 'rgb(var(--text-muted))' }}>
              <Layers size={12} className="inline mr-1" /> {t('components:shared.coverage.chains')}
            </button>
            <button onClick={() => setTab('tokens')}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${tab === 'tokens' ? '' : 'opacity-50'}`}
              style={tab === 'tokens' ? { background: 'rgba(220,38,38,0.15)', color: '#dc2626' } : { color: 'rgb(var(--text-muted))' }}>
              <Coins size={12} className="inline mr-1" /> {t('components:shared.coverage.tokens')}
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {tab === 'chains' ? (
            <div className="space-y-5">
              {Object.entries(chainsByFamily).map(([family, chains]) => (
                <div key={family}>
                  <h3 className="text-[10px] uppercase tracking-widest font-bold mb-2 flex items-center gap-2"
                    style={{ color: 'rgb(var(--text-muted))' }}>
                    <span className="w-2 h-2 rounded-full" style={{ background: FAMILY_COLORS[family] }} />
                    {family} <span className="opacity-50">({chains.length})</span>
                  </h3>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                    {chains.map(chain => (
                      <div key={chain.id}
                        className="flex items-center gap-2.5 rounded-lg p-2.5 transition-colors hover:bg-white/5"
                        style={{ background: 'rgb(var(--bg-secondary) / 0.5)', border: '1px solid rgb(var(--bg-border) / 0.5)' }}>
                        {/* Chain brand logo (disc + white glyph) */}
                        <ChainLogo chain={chain.id || chain.symbol} size={36}
                          color={brandColor(chain.symbol, chain.color)} title={chain.name} />

                        <div className="min-w-0 flex-1">
                          <p className="text-xs font-bold truncate" style={{ color: 'rgb(var(--text-primary))' }}>{chain.name}</p>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            <span className="text-[9px] font-mono" style={{ color: 'rgb(var(--text-muted))' }}>${chain.symbol}</span>
                            {chain.liveTrace && (
                              <span className="flex items-center gap-0.5 text-[8px] px-1 py-0.5 rounded"
                                style={{ background: 'rgba(34,197,94,0.12)', color: '#22c55e' }}>
                                <CheckCircle2 size={8} /> {t('components:shared.coverage.trace')}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {/* Legend */}
              <div className="flex items-center gap-4 pt-3 border-t text-[10px]" style={{ borderColor: 'rgb(var(--bg-border))', color: 'rgb(var(--text-muted))' }}>
                <span className="flex items-center gap-1"><ShieldCheck size={11} /> {t('components:shared.coverage.liveTraceLegend')}</span>
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              {Object.entries(tokensByCategory).map(([cat, tokens]) => (
                <div key={cat}>
                  <h3 className="text-[10px] uppercase tracking-widest font-bold mb-2 flex items-center gap-2"
                    style={{ color: 'rgb(var(--text-muted))' }}>
                    <span className="w-2 h-2 rounded-full" style={{ background: CATEGORY_LABELS[cat]?.color || '#64748b' }} />
                    {CATEGORY_LABELS[cat] ? t(CATEGORY_LABELS[cat].labelKey) : cat} <span className="opacity-50">({tokens.length})</span>
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {tokens.map(t => {
                      const chain = SUPPORTED_CHAINS.find(c => c.id === t.chain)
                      return (
                        <div key={`${t.symbol}-${t.chain}`}
                          className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5"
                          style={{ background: 'rgb(var(--bg-secondary) / 0.5)', border: '1px solid rgb(var(--bg-border) / 0.5)' }}>
                          <ChainLogo chain={t.symbol} size={18}
                            color={brandColor(t.symbol, chain?.color ?? '#334155')} title={t.name} />
                          <span className="text-xs font-mono font-bold" style={{ color: 'rgb(var(--text-primary))' }}>{t.symbol}</span>
                          <span className="text-[10px] truncate max-w-[120px]" style={{ color: 'rgb(var(--text-muted))' }}>{t.name}</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
