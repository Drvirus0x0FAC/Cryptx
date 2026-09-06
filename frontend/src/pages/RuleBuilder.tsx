import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertCircle, Beaker, Loader2, Plus, ShieldAlert, Trash2, Zap } from 'lucide-react'
import { api } from '../api/client'

interface Template {
  id: string
  name: string
  description: string
  conditions: Array<{ field: string; op: string; value: unknown }>
  operator: string
}

interface CompositeRule {
  id: string
  name: string
  conditions: Array<{ field: string; op: string; value: unknown }>
  operator: string
  enabled: boolean
  template_id?: string
}

function friendlyError(e: unknown) {
  const err = e as { response?: { data?: { detail?: string } }; message?: string }
  return err.response?.data?.detail || err.message || String(e)
}

export default function RuleBuilder() {
  const { t } = useTranslation()
  const [templates, setTemplates] = useState<Template[]>([])
  const [rules, setRules] = useState<CompositeRule[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [dryRunResult, setDryRunResult] = useState<{ matched: number; total_tested: number } | null>(null)

  useEffect(() => {
    refresh()
  }, [])

  async function refresh() {
    setLoading(true)
    try {
      const [tRes, rRes] = await Promise.all([
        api.get('/rules/templates'),
        api.get('/rules/composite'),
      ])
      setTemplates(tRes.data.templates || [])
      setRules(rRes.data.rules || [])
    } catch (e) { setError(friendlyError(e)) }
    finally { setLoading(false) }
  }

  async function createFromTemplate(tmpl: Template) {
    try {
      await api.post('/rules/from-template', { template_id: tmpl.id, name: tmpl.name })
      refresh()
    } catch (e) { setError(friendlyError(e)) }
  }

  async function toggleRule(rule: CompositeRule) {
    try {
      await api.patch(`/rules/composite/${rule.id}`, { enabled: !rule.enabled })
      refresh()
    } catch (e) { setError(friendlyError(e)) }
  }

  async function deleteRule(id: string) {
    try {
      await api.delete(`/rules/composite/${id}`)
      refresh()
    } catch (e) { setError(friendlyError(e)) }
  }

  async function dryRun(rule: CompositeRule) {
    setDryRunResult(null)
    try {
      const r = await api.post('/rules/dry-run', {
        conditions: rule.conditions,
        operator: rule.operator,
        transactions: [], // would need a wallet's tx history in production
      })
      setDryRunResult(r.data)
    } catch (e) { setError(friendlyError(e)) }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-text-primary">
          <ShieldAlert className="text-neon-amber" /> {t('rules.title', 'Alert Rules')}
        </h1>
        <p className="mt-1 text-sm text-text-muted">
          {t('rules.subtitle', 'Create composite monitoring rules with one-click templates. Rules fire when watched wallets match your criteria.')}
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-neon-red/40 bg-neon-red/10 px-3 py-2 text-sm text-neon-red">
          <AlertCircle size={16} /> {error}
          <button onClick={() => setError('')} className="ml-auto text-neon-red/60 hover:text-neon-red">✕</button>
        </div>
      )}

      {/* Templates */}
      <div className="rounded-xl border border-border bg-bg-secondary p-4">
        <h3 className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-text-muted">
          <Zap size={14} className="text-neon-amber" /> {t('rules.templates', 'Templates — one-click create')}
        </h3>
        <div className="grid gap-2 sm:grid-cols-2">
          {templates.map(tmpl => (
            <button
              key={tmpl.id}
              onClick={() => createFromTemplate(tmpl)}
              className="group flex items-start gap-2 rounded-lg border border-border bg-bg-elevated p-3 text-left transition-colors hover:border-neon-amber/50"
            >
              <Plus size={16} className="mt-0.5 shrink-0 text-text-muted group-hover:text-neon-amber" />
              <div className="min-w-0">
                <p className="text-sm font-bold text-text-primary">{tmpl.name}</p>
                <p className="text-xs text-text-muted">{tmpl.description}</p>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Active rules */}
      <div className="rounded-xl border border-border bg-bg-secondary p-4">
        <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-text-muted">
          {t('rules.active', 'Active Rules')} ({rules.length})
        </h3>
        {loading && <Loader2 className="animate-spin text-neon-cyan" />}
        {rules.length === 0 && !loading && (
          <p className="py-4 text-center text-sm text-text-muted">{t('rules.empty', 'No rules yet — create one from a template above.')}</p>
        )}
        <div className="space-y-2">
          {rules.map(rule => (
            <div key={rule.id} className="rounded-lg border border-border bg-bg-elevated p-3">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => toggleRule(rule)}
                  className={`h-4 w-7 rounded-full transition-colors ${rule.enabled ? 'bg-neon-green' : 'bg-text-muted/30'}`}
                >
                  <span className={`block h-3 w-3 rounded-full bg-white transition-transform ${rule.enabled ? 'translate-x-3.5' : 'translate-x-0.5'}`} />
                </button>
                <p className="flex-1 text-sm font-bold text-text-primary">{rule.name}</p>
                {rule.template_id && <span className="rounded bg-neon-amber/15 px-1.5 py-0.5 text-[9px] font-bold text-neon-amber">template</span>}
                <button onClick={() => dryRun(rule)} className="text-text-muted hover:text-neon-cyan" title="Dry run">
                  <Beaker size={14} />
                </button>
                <button onClick={() => deleteRule(rule.id)} className="text-text-muted hover:text-neon-red" title="Delete">
                  <Trash2 size={14} />
                </button>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {rule.conditions.map((c, i) => (
                  <span key={i} className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-text-secondary">
                    {c.field} {c.op} {String(c.value)}
                  </span>
                ))}
                <span className="rounded border border-border px-1.5 py-0.5 text-[10px] font-bold text-text-muted">{rule.operator}</span>
              </div>
            </div>
          ))}
        </div>
        {dryRunResult && (
          <div className="mt-3 rounded-lg border border-neon-cyan/30 bg-neon-cyan/5 p-2 text-xs text-text-secondary">
            Dry run: {dryRunResult.matched}/{dryRunResult.total_tested} transactions would match.
          </div>
        )}
      </div>
    </div>
  )
}
