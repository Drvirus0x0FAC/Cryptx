/**
 * F10: AI Q&A over case evidence (RAG).
 * A chat box where the investigator asks natural-language questions about a case
 * and gets grounded answers with [evidence:ID] citations.
 * Plugs into Case Detail page.
 */
import { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Send, Loader2, Cpu, Sparkles } from 'lucide-react'
import { askCaseQuestion } from '../api/client'
import type { CaseQaResult } from '../types'

interface Msg { role: 'user' | 'assistant'; text: string; citations?: CaseQaResult['citations']; aiUsed?: boolean }

export default function CaseQaChat({ caseId }: { caseId: string }) {
  const { t } = useTranslation()
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight)
  }, [msgs, loading])

  async function ask() {
    if (!input.trim() || loading) return
    const q = input.trim()
    setMsgs(m => [...m, { role: 'user', text: q }])
    setInput(''); setLoading(true)
    try {
      const r = await askCaseQuestion(caseId, q)
      setMsgs(m => [...m, { role: 'assistant', text: r.answer, citations: r.citations, aiUsed: r.ai_used }])
    } catch (e) {
      setMsgs(m => [...m, { role: 'assistant', text: `Error: ${e instanceof Error ? e.message : 'failed'}`, aiUsed: false }])
    } finally { setLoading(false) }
  }

  const suggestions = ['Where did the funds cash out?', 'Summarize the risk signals', 'Which addresses are sanctioned?', 'What evidence is missing?']

  return (
    <div className="card-cyber flex flex-col" style={{ height: '450px' }}>
      <div className="flex items-center gap-2 pb-2 border-b border-white/10">
        <Sparkles size={15} style={{ color: '#a78bfa' }} />
        <h3 className="card-title">{t('components:shared.caseQa.title')}</h3>
        <span className="text-[10px] text-text-muted ml-auto">{t('components:shared.caseQa.subtitle')}</span>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3 py-3">
        {msgs.length === 0 && (
          <div className="text-center py-8 space-y-3">
            <Cpu size={32} className="mx-auto" style={{ color: '#a78bfa', opacity: 0.5 }} />
            <p className="text-text-muted text-xs">Ask a question about this case. Answers are grounded in the stored evidence.</p>
            <div className="flex flex-wrap gap-2 justify-center">
              {suggestions.map(s => (
                <button key={s} onClick={() => setInput(s)} className="badge badge-muted hover:badge-cyan text-[10px]">{s}</button>
              ))}
            </div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] rounded-lg p-2.5 text-xs ${m.role === 'user' ? 'bg-neon-red/10 border border-neon-red/20' : 'bg-white/5 border border-white/10'}`}>
              <div className="whitespace-pre-wrap" style={{ color: '#fff2f4' }}>{m.text}</div>
              {m.citations && m.citations.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {m.citations.map((c, j) => (
                    <span key={j} className={`text-[9px] px-1.5 py-0.5 rounded ${c.valid ? 'bg-green-500/15 text-green-400' : 'bg-red-500/15 text-red-400 line-through'}`}>
                      evidence:{c.evidence_id.slice(0, 8)}
                    </span>
                  ))}
                </div>
              )}
              {m.role === 'assistant' && m.aiUsed === false && (
                <div className="text-[9px] text-text-muted mt-1 italic">⚠ AI not configured — showing evidence context only</div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-white/5 border border-white/10 rounded-lg p-2.5">
              <Loader2 size={14} className="animate-spin" style={{ color: '#a78bfa' }} />
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="flex gap-2 pt-2 border-t border-white/10">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask() } }}
          placeholder="Ask about this case…"
          className="input flex-1 text-xs"
          disabled={loading}
        />
        <button onClick={ask} disabled={loading || !input.trim()} className="btn-primary">
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
        </button>
      </div>
    </div>
  )
}
