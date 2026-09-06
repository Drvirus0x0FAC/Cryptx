/**
 * BoardSharedView - public, read-only rendering of a shared investigation board.
 * Reached via tokenized URL (/board-share/:token) WITHOUT a CrypTX account.
 * Private links prompt for the password; snapshots display their SHA-256 seal.
 */
import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Loader2, Lock, ShieldCheck, Eye } from 'lucide-react'
import { sharedMeta, accessShared, type SharedBoardPayload, type BoardEdge, type BoardNode } from '../api/boards'

const short = (a: string) => (a.length > 14 ? `${a.slice(0, 8)}…${a.slice(-4)}` : a)
const CHAIN_COLORS: Record<string, string> = {
  btc: '#f7931a', eth: '#627eea', tron: '#ff2d55', sol: '#9945ff', polygon: '#8247e5',
  arbitrum: '#28a0f0', optimism: '#ff0420', base: '#0052ff', bsc: '#f0b90b',
}
const chainColor = (c: string) => CHAIN_COLORS[(c || '').toLowerCase()] || '#8e9db5'

// compact crimewall entity + lead metadata for read-only rendering
const ENTITY_GLYPHS: Record<string, { g: string; color: string; label: string }> = {
  person: { g: 'P', color: '#ff9f0a', label: 'Person' },
  org: { g: 'O', color: '#64d2ff', label: 'Organization' },
  exchange: { g: 'X', color: '#00d47e', label: 'Exchange' },
  wallet: { g: 'W', color: '#0a84ff', label: 'Wallet' },
  ip: { g: 'IP', color: '#bf5af2', label: 'IP address' },
  email: { g: '@', color: '#ffd60a', label: 'Email' },
  phone: { g: 'T', color: '#34d399', label: 'Phone' },
  social: { g: 'S', color: '#ff375f', label: 'Social' },
  evidence: { g: 'E', color: '#8e9db5', label: 'Evidence' },
  event: { g: 'EV', color: '#ac8e68', label: 'Event' },
}
const LEAD_COLORS: Record<string, { color: string; label: string }> = {
  suspect: { color: '#ff9f0a', label: 'SUSPECT' },
  confirmed: { color: '#ff2d55', label: 'CONFIRMED' },
  cleared: { color: '#30d158', label: 'CLEARED' },
  poi: { color: '#bf5af2', label: 'PERSON OF INTEREST' },
}
const REL_LABEL: Record<string, string> = {
  controls: 'controls', same_owner: 'same owner', kyc_match: 'KYC match',
  communicates: 'communicates', funds: 'funds', associates: 'associates',
  employs: 'employs', registered_to: 'registered to', ip_overlap: 'IP overlap',
  device_match: 'device match', custom: 'custom',
}

export default function BoardSharedView() {
  const { t } = useTranslation()
  const { token = '' } = useParams()
  const [needsPassword, setNeedsPassword] = useState(false)
  const [password, setPassword] = useState('')
  const [payload, setPayload] = useState<SharedBoardPayload | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState({ x: 60, y: 40, z: 1 })
  const [drag, setDrag] = useState<{ sx: number; sy: number; ox: number; oy: number } | null>(null)

  useEffect(() => {
    sharedMeta(token)
      .then((m) => {
        if (m.revoked) { setError(t('tools:boardShared.errors.revoked')); setLoading(false); return }
        if (m.expired) { setError(t('tools:boardShared.errors.expired')); setLoading(false); return }
        if (m.needs_password) { setNeedsPassword(true); setLoading(false) } else { unlock('') }
      })
      .catch(() => { setError(t('tools:boardShared.errors.notFound')); setLoading(false) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  function unlock(pw: string) {
    setLoading(true)
    setError('')
    accessShared(token, pw)
      .then((p) => { setPayload(p); setNeedsPassword(false) })
      .catch((e) => setError(e?.response?.data?.detail || t('tools:boardShared.errors.denied')))
      .finally(() => setLoading(false))
  }

  const st = payload?.state
  const nodeById = useMemo(() => new Map((st?.nodes || []).map((n) => [n.id, n])), [st])

  const { nodes, edges } = useMemo(() => {
    if (!st) return { nodes: [] as BoardNode[], edges: [] as BoardEdge[] }
    const hidden = new Map<string, string>()
    for (const c of st.clusters || []) if (c.collapsed) for (const m of c.members) hidden.set(m, c.id)
    const ns = (st.nodes || []).filter((n) => !hidden.has(n.id))
    const es: BoardEdge[] = []
    const seen = new Set<string>()
    for (const e of st.edges || []) {
      const s = hidden.get(e.source) || e.source
      const t = hidden.get(e.target) || e.target
      if (s === t) continue
      const k = `${s}|${t}|${e.txHash}|${e.asset}`
      if (seen.has(k)) continue
      seen.add(k)
      es.push({ ...e, source: s, target: t })
    }
    return { nodes: ns, edges: es }
  }, [st])

  const fiat = st?.preferences?.fiat ?? true

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center bg-[#05070d] text-text-muted text-xs gap-2"><Loader2 size={14} className="animate-spin" /> {t('tools:boardShared.opening')}</div>
  }

  if (needsPassword && !payload) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#05070d] px-4">
        <div className="w-full max-w-sm rounded-xl border border-bg-border bg-bg-elevated p-6 space-y-4">
          <div className="flex items-center gap-2 text-text-primary text-sm font-bold"><Lock size={15} /> {t('tools:boardShared.password.title')}</div>
          <p className="text-xs text-text-secondary">{t('tools:boardShared.password.hint')}</p>
          <input className="input" type="password" placeholder={t('tools:boardShared.password.placeholder')} value={password}
            onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') unlock(password) }} autoFocus />
          {error && <p className="text-xs text-red-400">{error}</p>}
          <button className="btn-primary w-full" onClick={() => unlock(password)} disabled={!password}>{t('tools:boardShared.password.unlock')}</button>
        </div>
      </div>
    )
  }

  if (error || !payload || !st) {
    return <div className="min-h-screen flex items-center justify-center bg-[#05070d] text-red-400 text-sm">{error || t('tools:boardShared.errors.unable')}</div>
  }

  return (
    <div className="min-h-screen flex flex-col bg-[#05070d]">
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-bg-border bg-bg-elevated/70 flex-wrap">
        <Eye size={14} className="text-neon-cyan" />
        <span className="text-sm font-bold text-text-primary">{payload.name}</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-bg-secondary text-text-muted uppercase tracking-wider">
          {payload.live
            ? t('tools:boardShared.header.readonlyLive')
            : t('tools:boardShared.header.readonlySnapshot', { date: String(payload.frozen_at || '').slice(0, 16).replace('T', ' ') })}
        </span>
        {payload.state_hash && (
          <span className="flex items-center gap-1 text-[9px] text-emerald-400 font-mono" title={t('tools:boardShared.header.sealTitle')}>
            <ShieldCheck size={11} /> {payload.state_hash.slice(0, 16)}…
          </span>
        )}
        <div className="flex-1" />
        <span className="text-[10px] text-text-muted">{t('tools:boardShared.header.stats', { nodes: nodes.length, edges: edges.length })}</span>
      </div>
      {payload.description && <p className="px-4 py-1.5 text-xs text-text-secondary border-b border-bg-border/50">{payload.description}</p>}

      <svg className="flex-1 select-none" style={{ cursor: drag ? 'grabbing' : 'grab' }}
        onMouseDown={(e) => setDrag({ sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y })}
        onMouseMove={(e) => { if (drag) setView((v) => ({ ...v, x: drag.ox + e.clientX - drag.sx, y: drag.oy + e.clientY - drag.sy })) }}
        onMouseUp={() => setDrag(null)} onMouseLeave={() => setDrag(null)}
        onWheel={(e) => setView((v) => ({ ...v, z: Math.max(0.15, Math.min(3.5, v.z * (e.deltaY < 0 ? 1.1 : 0.9))) }))}>
        <defs>
          <marker id="shared-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 1 L 9 5 L 0 9 z" fill="#5b6b83" />
          </marker>
        </defs>
        <g transform={`translate(${view.x},${view.y}) scale(${view.z})`}>
          {/* investigation zones */}
          {(st.zones || []).map((z) => (
            <g key={z.id}>
              <rect x={z.x} y={z.y} width={z.w} height={z.h} rx={10}
                fill={`${z.color}12`} stroke={`${z.color}66`} strokeWidth={1.2} strokeDasharray="8 5" />
              <rect x={z.x} y={z.y - 22} width={Math.min(z.w, Math.max(90, z.name.length * 8 + 26))} height={20} rx={5}
                fill={`${z.color}33`} stroke={`${z.color}88`} strokeWidth={1} />
              <text x={z.x + 10} y={z.y - 8} fontSize={11} fontWeight={700} fill={z.color}>{z.name}</text>
            </g>
          ))}
          {edges.map((e) => {
            const s = nodeById.get(e.source); const t = nodeById.get(e.target)
            if (!s || !t) return null
            const mx = (s.x + t.x) / 2; const my = (s.y + t.y) / 2
            if (e.kind === 'relationship') {
              const relColor = e.color || '#ff453a'
              const relText = e.label || `${REL_LABEL[e.relationship || 'associates'] || 'linked'}${e.confidence != null ? ` · ${e.confidence}%` : ''}`
              return (
                <g key={e.id}>
                  <path d={`M ${s.x} ${s.y} Q ${mx} ${my + 26} ${t.x} ${t.y}`} fill="none"
                    stroke={relColor} strokeWidth={1.8} opacity={0.4 + 0.6 * ((e.confidence ?? 60) / 100)} />
                  <g transform={`translate(${mx},${my + 14})`}>
                    <rect x={-46} y={-9} width={92} height={16} rx={8} fill="#1c0d10" stroke={relColor} strokeWidth={0.8} opacity={0.95} />
                    <text x={0} y={3} textAnchor="middle" fontSize={8.5} fill={relColor === '#ff453a' ? '#ff8a80' : relColor}>{relText.slice(0, 20)}</text>
                  </g>
                </g>
              )
            }
            const label = fiat && e.valueUsd != null
              ? `$${e.valueUsd.toLocaleString(undefined, { maximumFractionDigits: e.valueUsd >= 1000 ? 0 : 2 })}`
              : `${e.value.toLocaleString(undefined, { maximumFractionDigits: 4 })} ${e.asset}`
            return (
              <g key={e.id}>
                <line x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke={e.crossChain ? '#bf5af2' : '#33415c'}
                  strokeWidth={1.4} strokeDasharray={e.crossChain ? '6 4' : undefined} markerEnd="url(#shared-arrow)" />
                <text x={mx} y={my - 7} textAnchor="middle" fontSize={10} fill="#8e9db5">{e.label || label}</text>
                {e.crossChain && (
                  <g transform={`translate(${mx},${my + 8})`}>
                    <rect x={-26} y={-8} width={52} height={16} rx={8} fill="#1c1030" stroke="#bf5af2" strokeWidth={1} />
                    <text x={0} y={3.5} textAnchor="middle" fontSize={8.5} fill="#d8b4fe">⛓ {(s.chain || '?').toUpperCase()}→{(t.chain || '?').toUpperCase()}</text>
                  </g>
                )}
              </g>
            )
          })}
          {nodes.map((n) => (
            <g key={n.id} transform={`translate(${n.x},${n.y})`}>
              {n.kind === 'note' ? (
                <>
                  <rect x={-70} y={-34} width={140} height={68} rx={6} fill="rgba(255,214,10,0.09)" stroke="#8a7a1e" />
                  <text x={0} y={-18} textAnchor="middle" fontSize={10} fontWeight={700} fill="#ffd60a">{n.label}</text>
                  {(n.note || '').split('\n').slice(0, 3).map((line, i) => (
                    <text key={i} x={0} y={-2 + i * 13} textAnchor="middle" fontSize={9} fill="#c9c39a">{line.slice(0, 30)}</text>
                  ))}
                </>
              ) : n.kind === 'tx' ? (
                <>
                  <rect x={-34} y={-22} width={68} height={44} rx={5} fill="rgba(255,214,10,0.08)" stroke="#b8a11d" strokeWidth={1.4} />
                  <text x={0} y={2} textAnchor="middle" fontSize={9} fontWeight={700} fill="#ffd60a">TX</text>
                  <text x={0} y={14} textAnchor="middle" fontSize={7} fill="#8e9db5">{short(n.ref)}</text>
                </>
              ) : ENTITY_GLYPHS[n.kind] ? (
                (() => {
                  const em = ENTITY_GLYPHS[n.kind]
                  const lead = n.lead && n.lead !== 'none' ? LEAD_COLORS[n.lead] : null
                  return (
                    <>
                      {lead && <rect x={-58} y={-27} width={116} height={54} rx={11} fill="none" stroke={lead.color} strokeWidth={1.4} strokeDasharray="4 3" opacity={0.9} />}
                      <rect x={-52} y={-21} width={104} height={42} rx={8} fill="rgba(10,14,24,0.94)" stroke={n.color || em.color} strokeWidth={1.6} />
                      <circle cx={-34} cy={0} r={12} fill={`${em.color}22`} stroke={em.color} strokeWidth={1} />
                      <text x={-34} y={3.5} textAnchor="middle" fontSize={9} fontWeight={800} fill={em.color}>{em.g}</text>
                      <text x={-16} y={-3} fontSize={9} fontWeight={700} fill="#e8eefc">{n.label.slice(0, 13)}</text>
                      <text x={-16} y={9} fontSize={7.5} fill="#8e9db5">{(n.ref || em.label).slice(0, 16)}</text>
                      {lead && <text x={0} y={38} textAnchor="middle" fontSize={8} fontWeight={700} fill={lead.color}>● {lead.label}</text>}
                      {n.priority && <circle cx={-52} cy={-27} r={7} fill="#ff2d55" />}
                    </>
                  )
                })()
              ) : n.kind === 'cluster' ? (
                <>
                  <rect x={-46} y={-28} width={92} height={56} rx={10} fill="rgba(191,90,242,0.10)" stroke={n.color} strokeWidth={1.6} />
                  <text x={0} y={-2} textAnchor="middle" fontSize={10} fontWeight={700} fill="#e9d5ff">{n.label.slice(0, 14)}</text>
                  <text x={0} y={11} textAnchor="middle" fontSize={8} fill="#b9a3d9">{n.caption}</text>
                </>
              ) : (
                <>
                  {n.lead && n.lead !== 'none' && LEAD_COLORS[n.lead] && (
                    <circle r={26} fill="none" stroke={LEAD_COLORS[n.lead].color} strokeWidth={1.4} strokeDasharray="4 3" opacity={0.9} />
                  )}
                  <circle r={22} fill="rgba(10,14,24,0.9)" stroke={n.color || chainColor(n.chain)} strokeWidth={1.6} />
                  <text x={0} y={1} textAnchor="middle" fontSize={7.5} fill="#d7e3f4">{short(n.ref).slice(0, 12)}</text>
                  <text x={0} y={36} textAnchor="middle" fontSize={9} fontWeight={600} fill="#aebdd4">{(n.caption || n.label).slice(0, 22)}</text>
                  <g transform="translate(18,-18)">
                    <circle r={7.5} fill={chainColor(n.chain)} opacity={0.9} />
                    <text y={2.6} textAnchor="middle" fontSize={5.6} fontWeight={800} fill="#0a0e18">{(n.chain || '?').slice(0, 3).toUpperCase()}</text>
                  </g>
                </>
              )}
            </g>
          ))}
        </g>
      </svg>
    </div>
  )
}
