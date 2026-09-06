import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Bug, Loader2, RefreshCw, Fingerprint, Globe, AtSign, Mail, ArrowUpRight, ShieldAlert,
} from 'lucide-react'
import { scamAtlas, scamNetworkDetail, scamNetworkPromote } from '../api/client'
import { useFormat } from '../i18n/format'
import CinematicStage from '../components/CinematicStage'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

const SIG_COLOR: Record<string, string> = { high: '#ff4052', medium: '#ffd60a', info: '#9a858c' }

/**
 * Scam Network Atlas — AI-fraud infrastructure forensics (3.3).
 * Clusters victim reports into named scam networks via shared deposit addresses,
 * domains, emails and handles; surfaces kit-fingerprint and deepfake-KYC signals;
 * promotes networks into the attribution engine as provenance-tracked leads.
 */
export default function ScamNetworkAtlas() {
  const { t } = useTranslation()
  const { formatCurrency, formatNumber } = useFormat()
  const [atlas, setAtlas] = useState<any>(null)
  const [selected, setSelected] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function load(rebuild = false) {
    setBusy(true); setErr('')
    try {
      const a = await scamAtlas(rebuild)
      setAtlas(a)
      if (!selected && a.networks?.length) setSelected(a.networks[0].id)
    } catch (e) { setErr(friendlyError(e)) } finally { setBusy(false) }
  }
  useEffect(() => { load() }, [])

  const nets = atlas?.networks || []
  return (
    <div className="noscroll-page p-6 max-w-7xl mx-auto space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
            <Bug size={22} className="text-neon-cyan" /> {t('tools:scamAtlas.title')}
          </h1>
          <p className="text-sm text-text-muted mt-1">
            {t('tools:scamAtlas.subtitle')}
          </p>
        </div>
        <button className="btn-primary flex items-center gap-2" onClick={() => load(true)} disabled={busy}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} {t('tools:scamAtlas.recluster')}
        </button>
      </div>
      {err && <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>}

      <div className="noscroll-grow">
      <CinematicStage variant="scam" icon={Bug} title={t('tools:scamAtlas.title')} subtitle={t('tools:scamAtlas.subtitle')} collapsed={false}>
      {atlas && (
        <div className="grid gap-3 md:grid-cols-4">
          <div className="card"><p className="text-xs text-text-muted">{t('tools:scamAtlas.stats.victimReports')}</p><p className="text-2xl font-bold text-text-primary">{atlas.report_count}</p></div>
          <div className="card"><p className="text-xs text-text-muted">{t('tools:scamAtlas.stats.scamNetworks')}</p><p className="text-2xl font-bold text-neon-cyan">{atlas.network_count}</p></div>
          <div className="card"><p className="text-xs text-text-muted">{t('tools:scamAtlas.stats.totalDamage')}</p><p className="text-2xl font-bold text-red-400">{formatCurrency(Number(nets.reduce((s: number, n: any) => s + n.total_damage_usd, 0)))}</p></div>
          <div className="card"><p className="text-xs text-text-muted">{t('tools:scamAtlas.stats.syntheticKyc')}</p><p className="text-2xl font-bold text-yellow-300">{nets.filter((n: any) => n.signals.some((s: any) => s.signal === 'synthetic_kyc_pattern')).length}</p></div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <div className="card p-2 space-y-1 max-h-[560px] overflow-y-auto">
          {nets.map((n: any) => (
            <button key={n.id} onClick={() => setSelected(n.id)}
              className={`w-full text-left rounded-lg px-3 py-2 text-sm transition ${
                selected === n.id ? 'bg-neon-cyan/15 text-neon-cyan' : 'text-text-secondary hover:text-text-primary'}`}>
              <span className="font-medium">{n.name}</span>
              <span className="block text-[11px] text-text-muted">
                {t('tools:scamAtlas.list.victimsDamage', { count: n.victim_count, damage: formatNumber(Number(n.total_damage_usd)) })} · {n.scam_types.slice(0, 2).join(', ')}
              </span>
              {n.signals.length > 0 && (
                <span className="mt-1 flex flex-wrap gap-1">
                  {n.signals.slice(0, 3).map((s: any, i: number) => (
                    <span key={i} className="badge text-[9px]" style={{ background: SIG_COLOR[s.severity] + '22', color: SIG_COLOR[s.severity] }}>{s.signal}</span>
                  ))}
                </span>
              )}
            </button>
          ))}
          {nets.length === 0 && !busy && <p className="p-3 text-xs text-text-muted">{t('tools:scamAtlas.list.empty')}</p>}
        </div>
        {selected ? <NetworkDetail nid={selected} /> : <div className="card text-sm text-text-muted">{t('tools:scamAtlas.list.selectPrompt')}</div>}
      </div>
      </CinematicStage>
      </div>
    </div>
  )
}

function NetworkDetail({ nid }: { nid: string }) {
  const { t } = useTranslation()
  const { formatCurrency, formatNumber } = useFormat()
  const [net, setNet] = useState<any>(null)
  const [err, setErr] = useState('')
  const [promoteMsg, setPromoteMsg] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setPromoteMsg(''); scamNetworkDetail(nid).then(setNet).catch(e => setErr(friendlyError(e))) }, [nid])
  if (err) return <div className="card border-red-500/40 text-red-400 text-sm">{err}</div>
  if (!net) return <div className="card text-sm text-text-muted">{t('tools:scamAtlas.detail.loading')}</div>

  async function promote() {
    setBusy(true); setPromoteMsg('')
    try {
      const r = await scamNetworkPromote(nid)
      setPromoteMsg(t('tools:scamAtlas.detail.promoted', { count: r.attributions_added }))
    } catch (e) { setPromoteMsg(friendlyError(e)) } finally { setBusy(false) }
  }

  const dates = net.first_seen
    ? t('tools:scamAtlas.detail.dateRange', { from: net.first_seen.slice(0, 10), to: net.last_seen?.slice(0, 10) })
    : t('tools:scamAtlas.detail.undated')

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="font-semibold text-text-primary">{net.name}</p>
            <p className="text-xs text-text-muted">
              {t('tools:scamAtlas.detail.meta', { count: net.victim_count, damage: formatNumber(Number(net.total_damage_usd)), dates, chains: net.chains.join(', ') })}
            </p>
          </div>
          <button className="btn-primary flex items-center gap-2 text-sm" onClick={promote} disabled={busy}>
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Fingerprint size={14} />} {t('tools:scamAtlas.detail.promote')}
          </button>
        </div>
        {promoteMsg && <p className="text-xs text-green-300">{promoteMsg}</p>}

        {net.signals.length > 0 && (
          <div className="space-y-2">
            {net.signals.map((s: any, i: number) => (
              <div key={i} className="rounded-lg border border-border bg-bg-secondary/40 p-3">
                <p className="flex items-center gap-2 text-sm font-medium" style={{ color: SIG_COLOR[s.severity] }}>
                  <ShieldAlert size={14} /> {s.signal.replace(/_/g, ' ')} <span className="badge text-[10px]">{s.severity}</span>
                </p>
                <p className="text-xs text-text-secondary mt-1">{s.detail}</p>
                <p className="text-[11px] text-text-muted mt-0.5">{t('tools:scamAtlas.detail.basis', { basis: s.basis })}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="card space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">{t('tools:scamAtlas.detail.addresses', { count: net.addresses.length })}</p>
          {net.addresses.map((a: string) => (
            <div key={a} className="flex items-center justify-between gap-2 text-xs">
              <span className="font-mono break-all">{a}</span>
              <Link to={`/intel/${a}`} className="text-neon-cyan hover:underline shrink-0 flex items-center gap-0.5">
                {t('tools:scamAtlas.detail.intel')} <ArrowUpRight size={11} />
              </Link>
            </div>
          ))}
        </div>
        <div className="card space-y-3">
          {net.domains.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-text-muted flex items-center gap-1"><Globe size={12} /> {t('tools:scamAtlas.detail.domains')}</p>
              <p className="text-xs text-text-secondary break-all">{net.domains.join(' · ')}</p>
            </div>
          )}
          {net.emails.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-text-muted flex items-center gap-1"><Mail size={12} /> {t('tools:scamAtlas.detail.emails')}</p>
              <p className="text-xs text-text-secondary break-all">{net.emails.join(' · ')}</p>
            </div>
          )}
          {net.handles.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-text-muted flex items-center gap-1"><AtSign size={12} /> {t('tools:scamAtlas.detail.handles')}</p>
              <p className="text-xs text-text-secondary break-all">{net.handles.map((h: string) => '@' + h).join(' · ')}</p>
            </div>
          )}
          {net.linking_artifacts?.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">{t('tools:scamAtlas.detail.linkingArtifacts')}</p>
              <p className="text-[11px] text-text-muted break-all">{net.linking_artifacts.slice(0, 12).join(' · ')}</p>
            </div>
          )}
        </div>
      </div>

      <div className="card overflow-x-auto">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">{t('tools:scamAtlas.detail.memberReports')}</p>
        <table className="w-full text-sm">
          <thead><tr className="text-text-muted text-left"><th className="p-2">{t('tools:scamAtlas.detail.colType')}</th><th className="p-2">{t('tools:scamAtlas.detail.colScammerAddr')}</th><th className="p-2">{t('tools:scamAtlas.detail.colUsd')}</th><th className="p-2">{t('tools:scamAtlas.detail.colChain')}</th><th className="p-2">{t('tools:scamAtlas.detail.colIncident')}</th><th className="p-2">{t('tools:scamAtlas.detail.colStatus')}</th></tr></thead>
          <tbody>
            {(net.reports || []).map((r: any) => (
              <tr key={r.id} className="border-t border-border text-xs">
                <td className="p-2">{r.scam_type}</td>
                <td className="p-2 font-mono break-all max-w-[220px]">{r.scammer_address}</td>
                <td className="p-2">{formatCurrency(Number(r.amount_usd || 0))}</td>
                <td className="p-2 uppercase">{r.chain}</td>
                <td className="p-2">{(r.incident_date || r.report_date || '').slice(0, 10)}</td>
                <td className="p-2"><span className="badge text-[10px]">{r.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
