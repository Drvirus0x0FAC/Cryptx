import { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertCircle, Bot, ChevronRight, Loader2, Send, Sparkles, Zap } from 'lucide-react'
import { api } from '../api/client'

interface ToolCall {
  step: number
  tool: string
  params: Record<string, unknown>
  result_preview: string
}

interface AgentJob {
  id: string
  prompt: string
  status: string
  step: number
  max_steps: number
  tool_calls: ToolCall[]
  final_answer: string | null
  error: string | null
  started_at: string
  updated_at: string
}

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

const TOOL_ICONS: Record<string, string> = {
  trace_funds: '🔍',
  screen_sanctions: '🚫',
  identify_vasp: '🏦',
  compute_risk: '⚠️',
  draft_sar: '📋',
  open_freeze_request: '❄️',
  search_entities: '🔎',
  get_address_intel: '📡',
}

const EXAMPLE_PROMPTS = [
  'Trace 0x28C6c06298d514Db089934071355E5743bf21D60 and find where the funds cash out',
  'Screen this address for sanctions and compute its risk score: 0x8589427373D6d84E98730d7795D8f6F8731Fda16',
  'Investigate 0x21a31ee1afc51d94c2efccaa2092ad1028285549 — trace, check sanctions, identify the VASP, and draft a SAR',
]

export default function NlAgentPage() {
  const { t } = useTranslation()
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [job, setJob] = useState<AgentJob | null>(null)
  const [error, setError] = useState('')
  const [tools, setTools] = useState<Array<{ name: string; description: string }>>([])
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.get('/nl-agent/tools').then(r => setTools(r.data.tools || [])).catch(() => {})
  }, [])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [job])

  async function run() {
    if (!prompt.trim() || loading) return
    setLoading(true)
    setError('')
    setJob(null)
    try {
      const r = await api.post('/nl-agent/run', { prompt: prompt.trim() })
      setJob(r.data)
    } catch (e) {
      setError(friendlyError(e))
    } finally {
      setLoading(false)
    }
  }

  const isRunning = loading || (job && job.status === 'running')

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-text-primary">
          <Bot className="text-neon-cyan" /> {t('nlAgent.title', 'AI Investigation Agent')}
        </h1>
        <p className="mt-1 text-sm text-text-muted">
          {t('nlAgent.subtitle', 'Describe what you want to investigate in plain language. The agent autonomously traces funds, screens sanctions, drafts reports, and opens freeze requests.')}
        </p>
      </div>

      {/* Prompt input */}
      <div className="rounded-xl border border-border bg-bg-secondary p-4">
        <div className="flex gap-2">
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) run() }}
            placeholder="e.g. Trace 0xabc... and find where the funds cash out, then draft a SAR"
            rows={3}
            className="flex-1 resize-none rounded-lg border border-border bg-bg-primary px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-neon-cyan focus:outline-none"
          />
          <button
            onClick={run}
            disabled={!prompt.trim() || loading}
            className="flex shrink-0 items-center gap-2 rounded-lg bg-neon-cyan px-4 py-2 text-sm font-bold text-bg-primary transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            {t('nlAgent.run', 'Run')}
          </button>
        </div>
        {error && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">
            <AlertCircle size={16} /> {error}
          </div>
        )}
        {/* Example prompts */}
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLE_PROMPTS.map((ex, i) => (
            <button
              key={i}
              onClick={() => setPrompt(ex)}
              className="flex items-center gap-1 rounded-full border border-border bg-bg-elevated px-3 py-1 text-[11px] text-text-muted transition-colors hover:border-neon-cyan/50 hover:text-neon-cyan"
            >
              <Sparkles size={11} /> {ex.slice(0, 50)}…
            </button>
          ))}
        </div>
      </div>

      {/* Available tools */}
      {tools.length > 0 && (
        <div className="rounded-xl border border-border bg-bg-secondary p-4">
          <h3 className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-text-muted">
            <Zap size={14} className="text-neon-amber" /> {t('nlAgent.tools', 'Available Tools')}
          </h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {tools.map(tool => (
              <div key={tool.name} className="rounded-lg border border-border bg-bg-elevated px-2 py-1.5">
                <p className="text-xs font-bold text-text-primary">{TOOL_ICONS[tool.name] || '🔧'} {tool.name}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Job result */}
      {job && (
        <div className="rounded-xl border border-border bg-bg-secondary p-4">
          {/* Status bar */}
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              {isRunning ? (
                <Loader2 size={16} className="animate-spin text-neon-cyan" />
              ) : job.status === 'completed' ? (
                <ChevronRight size={16} className="text-neon-green" />
              ) : (
                <AlertCircle size={16} className="text-neon-red" />
              )}
              <span className="text-sm font-bold text-text-primary capitalize">{job.status}</span>
              <span className="text-xs text-text-muted">· step {job.step}/{job.max_steps}</span>
            </div>
          </div>

          {/* Tool call log */}
          {job.tool_calls.length > 0 && (
            <div ref={logRef} className="mb-4 max-h-64 space-y-2 overflow-y-auto rounded-lg border border-border bg-bg-primary p-3">
              {job.tool_calls.map((tc, i) => (
                <div key={i} className="rounded-lg border border-border bg-bg-elevated p-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm">{TOOL_ICONS[tc.tool] || '🔧'}</span>
                    <span className="font-mono text-xs font-bold text-neon-cyan">{tc.tool}</span>
                    <span className="text-[10px] text-text-muted">step {tc.step}</span>
                  </div>
                  <pre className="mt-1 overflow-x-auto text-[10px] text-text-muted">{tc.result_preview}</pre>
                </div>
              ))}
            </div>
          )}

          {/* Final answer */}
          {job.final_answer && (
            <div className="rounded-lg border border-neon-green/30 bg-neon-green/5 p-4">
              <h4 className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-neon-green">
                <Sparkles size={14} /> {t('nlAgent.result', 'Investigation Result')}
              </h4>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-text-primary">{job.final_answer}</p>
            </div>
          )}

          {job.error && (
            <div className="rounded-lg border border-neon-red/40 bg-neon-red/10 p-3 text-sm text-neon-red">
              {job.error}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
