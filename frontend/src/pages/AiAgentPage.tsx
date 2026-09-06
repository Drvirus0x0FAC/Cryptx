import { useEffect, useRef, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Bot, Loader2, Send, FolderOpen, ArrowLeft, ShieldCheck, ShieldAlert,
  Sparkles, FileText, Search, TrendingUp, AlertTriangle, Target, Zap,
  Quote, User, ChevronRight,
} from 'lucide-react'
import {
  agentStatus, agentListCases, agentBriefing, agentChat, agentAction,
  type AgentCaseBrief, type AgentBriefing, type AgentChatResult,
} from '../api/client'

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}
function riskColor(r?: number | null) {
  const v = r ?? 0
  if (v >= 80) return '#ff4052'
  if (v >= 60) return '#ff7a18'
  if (v >= 40) return '#ffd60a'
  return '#34D399'
}
const ACTION_ICONS: Record<string, typeof FileText> = {
  find_cashout: TrendingUp,
  generate_subpoena_targets: FileText,
  find_missing_evidence: Search,
  summarize_for_prosecutor: ShieldCheck,
  list_weak_assumptions: AlertTriangle,
  create_pivots: Zap,
}

interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  citations?: { evidence_id: string; valid: boolean }[]
  followups?: string[]
  action?: string
  structured?: any
}

export default function AiAgentPage() {
  const { t } = useTranslation()
  const [cases, setCases] = useState<AgentCaseBrief[]>([])
  const [loadingCases, setLoadingCases] = useState(true)
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(null)
  const [caseId, setCaseId] = useState<string>('')
  const [briefing, setBriefing] = useState<AgentBriefing | null>(null)
  const [loadingBrief, setLoadingBrief] = useState(false)
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    agentListCases().then(d => setCases(d.cases || [])).catch(e => setError(friendlyError(e))).finally(() => setLoadingCases(false))
    agentStatus().then(s => setAiConfigured(s.configured)).catch(() => setAiConfigured(false))
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, busy])

  const assign = useCallback(async (id: string) => {
    setCaseId(id); setLoadingBrief(true); setError(''); setMessages([]); setBriefing(null)
    try {
      const b = await agentBriefing(id)
      setBriefing(b)
      setMessages([{ role: 'assistant', content: b.welcome }])
    } catch (e) { setError(friendlyError(e)) } finally { setLoadingBrief(false) }
  }, [])

  function unassign() {
    setCaseId(''); setBriefing(null); setMessages([]); setInput(''); setError('')
  }

  const send = useCallback(async (text: string) => {
    const q = text.trim()
    if (!q || busy || !caseId) return
    setInput(''); setError('')
    const history = [...messages, { role: 'user' as const, content: q }]
    setMessages(history)
    setBusy(true)
    try {
      const res: AgentChatResult = await agentChat(caseId, history.map(m => ({ role: m.role, content: m.content })))
      setMessages(m => [...m, {
        role: 'assistant', content: res.answer, citations: res.citations, followups: res.followups,
      }])
    } catch (e) {
      setMessages(m => [...m, { role: 'assistant', content: `⚠️ ${friendlyError(e)}` }])
    } finally { setBusy(false) }
  }, [busy, caseId, messages])

  const runAction = useCallback(async (queryType: string, label: string) => {
    if (busy || !caseId) return
    setBusy(true); setError('')
    setMessages(m => [...m, { role: 'user', content: t('tools:aiAgent.runAction', { label }) }])
    try {
      const res = await agentAction(caseId, queryType)
      setMessages(m => [...m, {
        role: 'assistant',
        content: res.has_error ? (res.raw_content || t('tools:aiAgent.unparseable')) : '',
        action: res.query_label || label,
        structured: res.has_error ? null : res.result,
      }])
    } catch (e) {
      setMessages(m => [...m, { role: 'assistant', content: `⚠️ ${friendlyError(e)}` }])
    } finally { setBusy(false) }
  }, [busy, caseId])

  // ── Case picker ──
  if (!caseId) {
    return (
      <div className="p-6 max-w-6xl mx-auto space-y-5">
        <div>
          <h1 className="text-2xl font-bold text-text-primary flex items-center gap-2">
            <Bot size={22} className="text-neon-cyan" /> {t('tools:aiAgent.title')}
          </h1>
          <p className="text-sm text-text-muted mt-1">
            {t('tools:aiAgent.subtitle')}
          </p>
        </div>
        <AiStatusPill configured={aiConfigured} t={t} />
        {error && <div className="card border-red-500/40 text-red-400 text-sm">{error}</div>}
        {loadingCases ? (
          <div className="card flex items-center gap-2 text-text-muted"><Loader2 size={16} className="animate-spin" /> {t('tools:aiAgent.loadingCases')}</div>
        ) : cases.length === 0 ? (
          <div className="card text-text-muted text-sm flex items-center gap-2">
            <FolderOpen size={16} /> {t('tools:aiAgent.noCases')}
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {cases.map(c => (
              <button key={c.id} onClick={() => assign(c.id)}
                className="card text-left hover:border-neon-cyan/60 transition group">
                <div className="flex items-start justify-between gap-2">
                  <span className="font-semibold text-text-primary group-hover:text-neon-cyan">{c.name}</span>
                  {c.status && <span className="badge text-[10px] shrink-0">{c.status}</span>}
                </div>
                {c.description && <p className="text-xs text-text-muted mt-1 line-clamp-2">{c.description}</p>}
                <div className="flex flex-wrap gap-2 mt-3 text-xs text-text-muted">
                  <span>{t('tools:aiAgent.caseMeta', { addr: c.address_count, evidence: c.evidence_count, notes: c.note_count })}</span>
                  {c.max_risk > 0 && <span className="ml-auto font-semibold" style={{ color: riskColor(c.max_risk) }}>risk {c.max_risk}</span>}
                </div>
                <div className="mt-3 flex items-center gap-1 text-xs font-medium text-neon-cyan opacity-0 group-hover:opacity-100 transition">
                  <Sparkles size={12} /> {t('tools:aiAgent.assignToAi')} <ChevronRight size={12} />
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }

  // ── Investigator workspace ──
  return (
    <div className="noscroll-page p-4 md:p-6 max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={unassign} className="btn-secondary flex items-center gap-1.5 text-sm">
          <ArrowLeft size={14} /> {t('tools:aiAgent.changeCase')}
        </button>
        <div className="flex items-center gap-2">
          <Bot size={18} className="text-neon-cyan" />
          <span className="font-semibold text-text-primary">{briefing?.case.name || t('tools:aiAgent.case')}</span>
          {briefing?.case.status && <span className="badge text-[10px]">{briefing.case.status}</span>}
        </div>
        <div className="ml-auto"><AiStatusPill configured={aiConfigured} t={t} compact /></div>
      </div>

      {loadingBrief && <div className="card flex items-center gap-2 text-text-muted"><Loader2 size={16} className="animate-spin" /> {t('tools:aiAgent.assigning')}</div>}

      {briefing && (
        <div className="noscroll-grow grid gap-4 lg:grid-cols-[1fr_320px] min-h-0">
          {/* Chat column */}
          <div className="card flex flex-col min-h-0 p-0 overflow-hidden">
            <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.map((m, i) => <Bubble key={i} msg={m} onFollowup={send} />)}
              {busy && (
                <div className="flex items-center gap-2 text-text-muted text-sm">
                  <Loader2 size={14} className="animate-spin" /> {t('tools:aiAgent.thinking')}
                </div>
              )}
            </div>
            <div className="cinematic-ai"><div className="cine-fx" aria-hidden="true"><span className="fx-a" /><span className="fx-b" /><span className="fx-c" /><span className="fx-d" /></div>
            <div className="border-t border-border p-3">
              <div className="flex items-end gap-2">
                <textarea
                  className="input flex-1 h-11 max-h-40 resize-none text-sm"
                  placeholder={t('tools:aiAgent.chatPlaceholder')}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
                />
                <button className="btn-primary h-11 px-4 flex items-center gap-1.5" onClick={() => send(input)} disabled={busy || !input.trim()}>
                  {busy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                </button>
              </div>
            </div>
            </div>
          </div>

          {/* Sidebar */}
          <div className="space-y-4">
            <div className="card">
              <p className="card-title mb-2">{t('tools:aiAgent.sidebar.context')}</p>
              <div className="grid grid-cols-3 gap-2 text-center">
                <Stat label={t('tools:aiAgent.sidebar.addresses')} value={briefing.stats.addresses} />
                <Stat label={t('tools:aiAgent.sidebar.evidence')} value={briefing.stats.evidence} />
                <Stat label={t('tools:aiAgent.sidebar.notes')} value={briefing.stats.notes} />
              </div>
              {briefing.addresses.length > 0 && (
                <div className="mt-3 space-y-1 max-h-40 overflow-y-auto">
                  {briefing.addresses.slice(0, 8).map(a => (
                    <div key={a.address} className="flex items-center justify-between gap-2 text-xs">
                      <span className="font-mono text-text-muted truncate">{a.address.slice(0, 10)}…{a.address.slice(-4)}</span>
                      {a.risk_score != null && <span className="shrink-0 font-semibold" style={{ color: riskColor(a.risk_score) }}>{a.risk_score}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="card">
              <p className="card-title mb-2 flex items-center gap-1.5"><Zap size={13} /> {t('tools:aiAgent.sidebar.quickActions')}</p>
              <div className="space-y-1.5">
                {briefing.actions.map(a => {
                  const Icon = ACTION_ICONS[a.id] || Target
                  return (
                    <button key={a.id} onClick={() => runAction(a.id, a.label)} disabled={busy}
                      className="w-full text-left rounded-lg border border-border p-2 hover:border-neon-cyan/60 transition flex items-start gap-2 disabled:opacity-50">
                      <Icon size={14} className="text-neon-cyan mt-0.5 shrink-0" />
                      <div><span className="text-sm font-medium text-text-primary">{a.label}</span>
                        <p className="text-[11px] text-text-muted">{a.description}</p></div>
                    </button>
                  )
                })}
              </div>
            </div>

            <div className="card">
              <p className="card-title mb-2 flex items-center gap-1.5"><Sparkles size={13} /> {t('tools:aiAgent.sidebar.suggestedPrompts')}</p>
              <div className="space-y-1.5">
                {briefing.suggested_prompts.map((p, i) => (
                  <button key={i} onClick={() => send(p)} disabled={busy}
                    className="w-full text-left text-xs text-text-secondary rounded-lg border border-border p-2 hover:border-neon-cyan/60 hover:text-text-primary transition disabled:opacity-50">
                    {p}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Bubble({ msg, onFollowup }: { msg: ChatMsg; onFollowup: (t: string) => void }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex gap-2 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`shrink-0 h-7 w-7 rounded-full flex items-center justify-center ${isUser ? 'bg-bg-secondary' : 'bg-neon-cyan/15'}`}>
        {isUser ? <User size={14} className="text-text-muted" /> : <Bot size={14} className="text-neon-cyan" />}
      </div>
      <div className={`max-w-[85%] ${isUser ? 'text-right' : ''}`}>
        <div className={`rounded-xl px-3 py-2 text-sm whitespace-pre-wrap ${isUser ? 'bg-neon-cyan/10 text-text-primary' : 'bg-bg-secondary/50 text-text-secondary'}`}>
          {msg.action && <div className="text-xs font-semibold text-neon-cyan mb-1">{msg.action}</div>}
          {msg.content}
          {msg.structured && <StructuredResult data={msg.structured} />}
        </div>
        {!!(msg.citations && msg.citations.length) && (
          <div className="flex flex-wrap gap-1 mt-1">
            {msg.citations.map((c, i) => (
              <span key={i} className={`badge text-[10px] flex items-center gap-1 ${c.valid ? '' : 'opacity-60'}`}>
                <Quote size={9} /> {c.evidence_id.slice(0, 8)}{c.valid ? '' : ' ?'}
              </span>
            ))}
          </div>
        )}
        {!!(msg.followups && msg.followups.length) && (
          <div className="flex flex-wrap gap-1 mt-2">
            {msg.followups.map((f, i) => (
              <button key={i} onClick={() => onFollowup(f)}
                className="text-[11px] rounded-full border border-border px-2 py-0.5 text-text-muted hover:text-neon-cyan hover:border-neon-cyan/60 transition">
                {f}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function StructuredResult({ data }: { data: any }) {
  if (data == null) return null
  if (typeof data !== 'object') return <div className="mt-2 text-sm">{String(data)}</div>
  return (
    <div className="mt-2 space-y-2">
      {Object.entries(data).map(([k, v]) => (
        <div key={k}>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">{k.replace(/_/g, ' ')}</div>
          <ValueBlock value={v} />
        </div>
      ))}
    </div>
  )
}

function ValueBlock({ value }: { value: any }) {
  if (value == null || value === '') return <span className="text-text-muted text-xs">—</span>
  if (Array.isArray(value)) {
    return (
      <ul className="list-disc pl-4 space-y-0.5">
        {value.slice(0, 20).map((item, i) => (
          <li key={i} className="text-xs text-text-secondary">
            {typeof item === 'object' ? <ObjInline obj={item} /> : String(item)}
          </li>
        ))}
      </ul>
    )
  }
  if (typeof value === 'object') return <ObjInline obj={value} />
  return <div className="text-sm text-text-primary">{String(value)}</div>
}

function ObjInline({ obj }: { obj: any }) {
  return (
    <span className="text-xs text-text-secondary">
      {Object.entries(obj).slice(0, 8).map(([k, v]) => (
        <span key={k} className="mr-2"><span className="text-text-muted">{k}:</span> {typeof v === 'object' ? JSON.stringify(v).slice(0, 60) : String(v)}</span>
      ))}
    </span>
  )
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-border py-2">
      <div className="text-lg font-bold text-text-primary">{value}</div>
      <div className="text-[10px] text-text-muted uppercase tracking-wide">{label}</div>
    </div>
  )
}

function AiStatusPill({ configured, compact, t }: { configured: boolean | null; compact?: boolean; t: (k: string) => string }) {
  if (configured === null) return null
  return (
    <div className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ${
      configured ? 'bg-green-500/10 text-green-400' : 'bg-amber-500/10 text-amber-400'}`}>
      {configured ? <ShieldCheck size={12} /> : <ShieldAlert size={12} />}
      {configured ? t('tools:aiAgent.status.connected') : (compact ? t('tools:aiAgent.status.notConfigured') : t('tools:aiAgent.status.notConfiguredHint'))}
    </div>
  )
}
