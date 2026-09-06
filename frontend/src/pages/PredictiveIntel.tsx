import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Activity, AlertOctagon, BrainCircuit, Clock, Crosshair, Database,
  Droplets, GraduationCap, Loader2, Search, ShieldAlert, Skull,
  Sparkles, Target, TrendingUp,
} from 'lucide-react'
import CinematicStage from '../components/CinematicStage'
import {
  getModelStatus, getPredictionHistory, runPredictAll, trainModels,
} from '../api/predictive'
import type {
  ModelStatus, PredictAllResult, Prediction, PredictionHistoryRow, TrainResult,
} from '../api/predictive'

const CHAINS = ['AUTO', 'ETH', 'BTC', 'MATIC', 'BSC', 'ARB', 'OP', 'BASE', 'TRX', 'SOL']

// Type metadata: labels/blurbs resolve via the `tools:predictive.types.*` translations.
const TYPE_META: Record<string, { labelKey: string; blurbKey: string; Icon: typeof Droplets }> = {
  laundering: { labelKey: 'tools:predictive.types.laundering',        blurbKey: 'tools:predictive.types.launderingBlurb', Icon: Droplets },
  rugpull:    { labelKey: 'tools:predictive.types.rugpull',           blurbKey: 'tools:predictive.types.rugpullBlurb',    Icon: Skull },
  trajectory: { labelKey: 'tools:predictive.types.trajectory',        blurbKey: 'tools:predictive.types.trajectoryBlurb', Icon: TrendingUp },
  victim:     { labelKey: 'tools:predictive.types.victim',            blurbKey: 'tools:predictive.types.victimBlurb',     Icon: Crosshair },
}

function levelColor(level: string) {
  switch ((level || '').toUpperCase()) {
    case 'CRITICAL': return 'text-red-400 border-red-500/50'
    case 'HIGH': return 'text-orange-400 border-orange-500/50'
    case 'ELEVATED': return 'text-yellow-400 border-yellow-500/40'
    case 'GUARDED': return 'text-blue-400 border-blue-500/40'
    default: return 'text-emerald-400 border-emerald-500/40'
  }
}

function ProbRing({ p, size = 84 }: { p: number; size?: number }) {
  const r = (size - 10) / 2
  const c = 2 * Math.PI * r
  const color = p >= 0.65 ? '#f87171' : p >= 0.45 ? '#fb923c' : p >= 0.25 ? '#facc15' : '#34d399'
  return (
    <svg width={size} height={size} className="shrink-0">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={7} />
      <circle
        cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={7}
        strokeLinecap="round" strokeDasharray={`${c * p} ${c}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle"
        className="fill-current text-text-primary" fontSize={size / 4.6} fontWeight={700} fontFamily="monospace">
        {Math.round(p * 100)}%
      </text>
    </svg>
  )
}

function PredictionCard({ pred }: { pred: Prediction }) {
  const { t } = useTranslation()
  const [showEvidence, setShowEvidence] = useState(true)
  const meta = TYPE_META[pred.type] || TYPE_META.trajectory
  const { Icon } = meta
  return (
    <div className={`bg-bg-primary border rounded-lg p-4 ${levelColor(pred.level).split(' ')[1]}`}>
      <div className="flex items-start gap-4">
        <ProbRing p={pred.probability} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Icon size={16} className={levelColor(pred.level).split(' ')[0]} />
            <h3 className="text-sm font-bold text-text-primary">{t(meta.labelKey)}</h3>
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${levelColor(pred.level)}`}>
              {pred.level}
            </span>
          </div>
          <p className="text-[11px] text-text-muted mt-0.5">{t(meta.blurbKey)}</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[11px]">
            <span className="text-text-secondary flex items-center gap-1">
              <Clock size={11} /> {pred.horizon}
            </span>
            <span className="text-text-muted">{t('tools:predictive.card.confidence', { pct: Math.round(pred.confidence * 100) })}</span>
            {pred.trend && <span className="text-text-muted">{t('tools:predictive.card.trend', { trend: pred.trend })}</span>}
          </div>
          {pred.horizons && (
            <div className="flex gap-3 mt-1.5 text-[11px] font-mono">
              {Object.entries(pred.horizons).map(([h, v]) => (
                <span key={h} className="text-text-secondary">{h}: <b>{Math.round(v * 100)}%</b></span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 mt-3">
        {(['precursor_patterns', 'anomaly', 'ml_model'] as const).map((k) => (
          <div key={k} className="bg-bg-secondary rounded px-2 py-1.5">
            <p className="text-[9px] uppercase tracking-wider text-text-muted">
              {k === 'precursor_patterns' ? t('tools:predictive.card.layerPrecursors') : k === 'anomaly' ? t('tools:predictive.card.layerAnomaly') : t('tools:predictive.card.layerMl')}
            </p>
            <p className="text-xs font-mono font-bold text-text-primary">
              {pred.layer_scores[k] === null ? 'n/a' : `${Math.round((pred.layer_scores[k] as number) * 100)}%`}
            </p>
          </div>
        ))}
      </div>

      {pred.evidence.length > 0 && (
        <div className="mt-3">
          <button onClick={() => setShowEvidence(!showEvidence)}
            className="text-[10px] uppercase tracking-widest text-text-muted hover:text-text-primary">
            {t('tools:predictive.card.evidence', { count: pred.evidence.length })} {showEvidence ? '▾' : '▸'}
          </button>
          {showEvidence && (
            <ul className="mt-1.5 space-y-1.5">
              {pred.evidence.map((e, i) => (
                <li key={i} className="flex items-start gap-2 text-[11px]">
                  <span className={`shrink-0 mt-0.5 w-1.5 h-1.5 rounded-full ${
                    e.severity === 'critical' ? 'bg-red-400' : e.severity === 'high' ? 'bg-orange-400'
                      : e.severity === 'medium' ? 'bg-yellow-400' : 'bg-blue-400'}`} />
                  <span className="text-text-secondary leading-snug">{e.finding}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {pred.recommended_actions.length > 0 && (
        <div className="mt-3 border-t border-border pt-2">
          <p className="text-[10px] uppercase tracking-widest text-text-muted mb-1">{t('tools:predictive.card.recommendedActions')}</p>
          <ul className="space-y-1">
            {pred.recommended_actions.map((a, i) => (
              <li key={i} className="text-[11px] text-accent flex items-start gap-1.5">
                <Sparkles size={11} className="mt-0.5 shrink-0" />
                <span>{a}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function PredictiveIntel() {
  const { t } = useTranslation()
  const { addr } = useParams()
  const navigate = useNavigate()
  const [address, setAddress] = useState(addr || '')
  const [chain, setChain] = useState('AUTO')
  const [loading, setLoading] = useState(false)
  const [training, setTraining] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<PredictAllResult | null>(null)
  const [status, setStatus] = useState<ModelStatus | null>(null)
  const [trainMsg, setTrainMsg] = useState('')
  const [history, setHistory] = useState<PredictionHistoryRow[]>([])

  useEffect(() => {
    getModelStatus().then(setStatus).catch(() => undefined)
    getPredictionHistory('', 12).then(setHistory).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (addr && addr !== address) setAddress(addr)
    if (addr) void analyze(addr)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addr])

  async function analyze(a?: string) {
    const subject = (a ?? address).trim()
    if (!subject) return
    setLoading(true)
    setError('')
    try {
      const r = await runPredictAll(subject, chain === 'AUTO' ? '' : chain)
      setResult(r)
      getPredictionHistory('', 12).then(setHistory).catch(() => undefined)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('tools:predictive.errors.prediction'))
    } finally {
      setLoading(false)
    }
  }

  async function handleTrain() {
    setTraining(true)
    setTrainMsg('')
    try {
      const r: TrainResult = await trainModels()
      setTrainMsg(r.trained
        ? t('tools:predictive.model.trainedMsg', { samples: r.samples, positives: r.positives, accuracy: Math.round((r.accuracy || 0) * 100), engine: r.engine })
        : t('tools:predictive.model.notTrainedMsg', { reason: r.reason }))
      getModelStatus().then(setStatus).catch(() => undefined)
    } catch (e) {
      setTrainMsg(e instanceof Error ? e.message : t('tools:predictive.errors.training'))
    } finally {
      setTraining(false)
    }
  }

  const model = status?.models?.[0]

  return (
    <div className="noscroll-page p-4 md:p-6 space-y-4 max-w-6xl mx-auto">
      {/* search */}
      <CinematicStage
        variant="predictive"
        icon={BrainCircuit}
        collapsed={!!result}
      >
        <div className="flex flex-col sm:flex-row gap-2">
          <div className="flex-1 relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void analyze()}
              placeholder={t('tools:predictive.inputPlaceholder')}
              className="w-full bg-bg-secondary border border-border rounded-lg pl-9 pr-3 py-2.5 text-sm text-text-primary font-mono focus:outline-none focus:border-accent"
            />
          </div>
          <select value={chain} onChange={(e) => setChain(e.target.value)}
            className="bg-bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-text-primary">
            {CHAINS.map((c) => <option key={c}>{c}</option>)}
          </select>
          <button onClick={() => void analyze()} disabled={loading || !address.trim()}
            className="bg-accent text-black font-bold text-sm px-5 py-2 rounded-lg disabled:opacity-40 flex items-center gap-2">
            {loading ? <Loader2 size={15} className="animate-spin" /> : <Target size={15} />}
            {t('tools:predictive.predict')}
          </button>
        </div>
      </CinematicStage>

      {/* Results — grows & scrolls internally */}
      <div className="noscroll-grow space-y-4">
      {error && (
        <div className="bg-red-500/10 border border-red-500/40 rounded-lg px-3 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {/* model status strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <div className="bg-bg-secondary border border-border rounded-lg px-3 py-2">
          <p className="text-[9px] uppercase tracking-widest text-text-muted flex items-center gap-1"><GraduationCap size={10} /> {t('tools:predictive.model.mlModel')}</p>
          <p className="text-xs font-bold text-text-primary">
            {model ? `${model.engine} · acc ${Math.round(model.accuracy * 100)}%` : t('tools:predictive.model.notTrained')}
          </p>
          <p className="text-[10px] text-text-muted">{model ? t('tools:predictive.model.samples', { count: model.samples, positives: model.positives }) : t('tools:predictive.model.heuristicMode')}</p>
        </div>
        <div className="bg-bg-secondary border border-border rounded-lg px-3 py-2">
          <p className="text-[9px] uppercase tracking-widest text-text-muted flex items-center gap-1"><Database size={10} /> {t('tools:predictive.model.featureStore')}</p>
          <p className="text-xs font-bold text-text-primary">{t('tools:predictive.model.profiles', { count: status?.feature_vectors ?? 0 })}</p>
          <p className="text-[10px] text-text-muted">{t('tools:predictive.model.baselineStats', { count: status?.baseline_features ?? 0 })}</p>
        </div>
        <div className="bg-bg-secondary border border-border rounded-lg px-3 py-2">
          <p className="text-[9px] uppercase tracking-widest text-text-muted flex items-center gap-1"><Activity size={10} /> {t('tools:predictive.model.predictions')}</p>
          <p className="text-xs font-bold text-text-primary">{t('tools:predictive.model.logged', { count: status?.recent_predictions ?? 0 })}</p>
          <p className="text-[10px] text-text-muted">{t('tools:predictive.model.fullAudit')}</p>
        </div>
        <button onClick={() => void handleTrain()} disabled={training}
          className="bg-bg-secondary border border-border hover:border-accent rounded-lg px-3 py-2 text-left transition-colors">
          <p className="text-[9px] uppercase tracking-widest text-text-muted">{t('tools:predictive.model.retrain')}</p>
          <p className="text-xs font-bold text-accent flex items-center gap-1.5">
            {training ? <Loader2 size={11} className="animate-spin" /> : <GraduationCap size={11} />}
            {training ? t('tools:predictive.model.training') : t('tools:predictive.model.trainMl')}
          </p>
          <p className="text-[10px] text-text-muted">{t('tools:predictive.model.trainHint')}</p>
        </button>
      </div>
      {trainMsg && <p className="text-[11px] text-text-secondary">{trainMsg}</p>}

      {/* composite verdict */}
      {result && (
        <>
          <div className={`border rounded-lg p-4 flex flex-col sm:flex-row sm:items-center gap-4 bg-bg-primary ${levelColor(result.composite_level).split(' ')[1]}`}>
            <ProbRing p={result.composite_threat} size={100} />
            <div className="flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <ShieldAlert size={18} className={levelColor(result.composite_level).split(' ')[0]} />
                <h2 className="text-base font-bold text-text-primary">
                  {t('tools:predictive.verdict.titlePrefix')}{' '}
                  <span className={levelColor(result.composite_level).split(' ')[0]}>{result.composite_level}</span>
                </h2>
              </div>
              <p className="text-xs text-text-secondary mt-1">
                {t('tools:predictive.verdict.primaryVector')} <b className="text-text-primary">{TYPE_META[result.primary_threat]?.labelKey ? t(TYPE_META[result.primary_threat].labelKey) : result.primary_threat}</b>
                {' '}· {t('tools:predictive.verdict.expectedWindow')} <b className="text-text-primary">{result.primary_horizon}</b>
              </p>
              <p className="text-[11px] text-text-muted mt-1.5 leading-relaxed">{result.methodology}</p>
              <div className="flex gap-2 mt-2">
                <button onClick={() => navigate(`/monitor`)} className="text-[11px] text-accent hover:underline">{t('tools:predictive.verdict.addToMonitor')}</button>
                <button onClick={() => navigate(`/trace/${result.address}`)} className="text-[11px] text-accent hover:underline">{t('tools:predictive.verdict.traceFunds')}</button>
                <button onClick={() => navigate(`/intel/${result.address}`)} className="text-[11px] text-accent hover:underline">{t('tools:predictive.verdict.fullIntel')}</button>
              </div>
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-3">
            {Object.values(result.predictions).map((p) => <PredictionCard key={p.type} pred={p} />)}
          </div>
        </>
      )}

      {/* recent predictions */}
      {!result && history.length > 0 && (
        <div className="bg-bg-primary border border-border rounded-lg">
          <div className="px-3 py-2 border-b border-border flex items-center gap-2">
            <AlertOctagon size={13} className="text-text-muted" />
            <h3 className="text-[10px] font-bold uppercase tracking-widest text-text-muted">{t('tools:predictive.history.title')}</h3>
          </div>
          <div className="divide-y divide-border">
            {history.map((h, i) => (
              <button key={i} onClick={() => { setAddress(h.address); void analyze(h.address) }}
                className="w-full flex items-center gap-3 px-3 py-2 hover:bg-bg-secondary/50 text-left">
                <span className={`text-[10px] font-bold w-16 shrink-0 ${levelColor(h.level).split(' ')[0]}`}>{h.level}</span>
                <span className="text-xs font-mono text-text-primary truncate flex-1">{h.address}</span>
                <span className="text-[10px] text-text-muted w-20 shrink-0">{h.ptype}</span>
                <span className="text-xs font-mono text-text-secondary w-10 text-right shrink-0">{Math.round(h.probability * 100)}%</span>
              </button>
            ))}
          </div>
        </div>
      )}
      </div>
    </div>
  )
}
