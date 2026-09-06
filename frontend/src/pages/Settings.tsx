import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Settings as SettingsIcon, Save, Eye, EyeOff, CheckCircle, Loader2, Cpu, AlertTriangle,
  X, KeyRound, SlidersHorizontal, Monitor, ExternalLink,
} from 'lucide-react'
import { aiStatus, getSettings, saveSettings, testAiProvider } from '../api/client'
import type { AiStatus, ApiSettings } from '../types'
import { getPrefs, setPrefs, type CryptxPrefs } from '../lib/prefs'
import LanguagePicker from '../components/LanguagePicker'
import '../styles/settings-cockpit.css'

type FieldConfig = {
  key: keyof ApiSettings
  label: string
  hint: string
  url?: string
  placeholder?: string
  group?: string
}

type AiProviderConfig = {
  id: string
  label: string
  kind: string
  keyField: keyof ApiSettings
  modelField: keyof ApiSettings
  baseField?: keyof ApiSettings
  defaultModel: string
  defaultBaseUrl?: string
  hint: string
  url?: string
}

const AI_PROVIDERS: AiProviderConfig[] = [
  { id: 'deepseek', label: 'DeepSeek', kind: 'OpenAI-compatible', keyField: 'DEEPSEEK_API_KEY', modelField: 'DEEPSEEK_MODEL', baseField: 'DEEPSEEK_BASE_URL', defaultModel: 'deepseek-v4-pro', defaultBaseUrl: 'https://api.deepseek.com', hint: 'Strong default for investigation briefs, hypotheses, and structured JSON synthesis.', url: 'https://api-docs.deepseek.com/' },
  { id: 'claude', label: 'Claude', kind: 'Anthropic Messages', keyField: 'CLAUDE_API_KEY', modelField: 'CLAUDE_MODEL', baseField: 'CLAUDE_BASE_URL', defaultModel: 'claude-sonnet-4-5', defaultBaseUrl: 'https://api.anthropic.com', hint: 'Native Claude connector for careful narrative reporting and evidence-grounded reasoning.', url: 'https://docs.anthropic.com/en/api/messages' },
  { id: 'gemini', label: 'Gemini', kind: 'Gemini generateContent', keyField: 'GEMINI_API_KEY', modelField: 'GEMINI_MODEL', baseField: 'GEMINI_BASE_URL', defaultModel: 'gemini-2.5-pro', defaultBaseUrl: 'https://generativelanguage.googleapis.com/v1beta', hint: 'Google Gemini connector for long-context analysis and report generation.', url: 'https://ai.google.dev/api/generate-content' },
  { id: 'openai', label: 'OpenAI', kind: 'OpenAI-compatible', keyField: 'OPENAI_API_KEY', modelField: 'OPENAI_MODEL', baseField: 'OPENAI_BASE_URL', defaultModel: 'gpt-4o-mini', defaultBaseUrl: 'https://api.openai.com/v1', hint: 'OpenAI chat-completions compatible connector for general AI investigation features.', url: 'https://developers.openai.com/api/reference/' },
  { id: 'codex', label: 'Codex / OpenAI', kind: 'OpenAI-compatible', keyField: 'CODEX_API_KEY', modelField: 'CODEX_MODEL', baseField: 'CODEX_BASE_URL', defaultModel: 'gpt-4o-mini', defaultBaseUrl: 'https://api.openai.com/v1', hint: 'Use an OpenAI-compatible API key and model for Codex-style workflows inside CrypTX.', url: 'https://developers.openai.com/api/reference/' },
  { id: 'qwen', label: 'Qwen', kind: 'OpenAI-compatible', keyField: 'QWEN_API_KEY', modelField: 'QWEN_MODEL', baseField: 'QWEN_BASE_URL', defaultModel: 'qwen-plus', defaultBaseUrl: 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1', hint: 'Alibaba Cloud Model Studio / DashScope connector using OpenAI-compatible chat completions.', url: 'https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope' },
  { id: 'kimi', label: 'Kimi', kind: 'OpenAI-compatible', keyField: 'KIMI_API_KEY', modelField: 'KIMI_MODEL', baseField: 'KIMI_BASE_URL', defaultModel: 'kimi-k2', defaultBaseUrl: 'https://api.moonshot.ai/v1', hint: 'Moonshot Kimi connector using the OpenAI-compatible API surface.', url: 'https://platform.kimi.ai/docs/api/overview' },
  { id: 'mistral', label: 'Mistral', kind: 'OpenAI-compatible', keyField: 'MISTRAL_API_KEY', modelField: 'MISTRAL_MODEL', baseField: 'MISTRAL_BASE_URL', defaultModel: 'mistral-large-latest', defaultBaseUrl: 'https://api.mistral.ai/v1', hint: 'Mistral connector for teams that prefer an OpenAI-compatible European provider.', url: 'https://docs.mistral.ai/' },
  { id: 'antigravity', label: 'Antigravity', kind: 'OpenAI-compatible custom', keyField: 'ANTIGRAVITY_API_KEY', modelField: 'ANTIGRAVITY_MODEL', baseField: 'ANTIGRAVITY_BASE_URL', defaultModel: '', hint: 'Custom connector for an Antigravity runtime or gateway that exposes chat completions.' },
  { id: 'manus', label: 'Manus', kind: 'OpenAI-compatible custom', keyField: 'MANUS_API_KEY', modelField: 'MANUS_MODEL', baseField: 'MANUS_BASE_URL', defaultModel: '', hint: 'Custom connector for a Manus runtime or gateway that exposes chat completions.' },
  { id: 'mimi', label: 'Mimi', kind: 'OpenAI-compatible custom', keyField: 'MIMI_API_KEY', modelField: 'MIMI_MODEL', baseField: 'MIMI_BASE_URL', defaultModel: '', hint: 'Custom connector for a Mimi runtime or gateway that exposes chat completions.' },
  { id: 'custom', label: 'Custom LLM', kind: 'OpenAI-compatible custom', keyField: 'CUSTOM_LLM_API_KEY', modelField: 'CUSTOM_LLM_MODEL', baseField: 'CUSTOM_LLM_BASE_URL', defaultModel: '', hint: 'Bring any OpenAI-compatible gateway by setting its API key, base URL, and model.' },
]

const DATA_FIELDS: FieldConfig[] = [
  { key: 'ETHERSCAN_API_KEY', label: 'Etherscan', hint: 'Required for ETH/Polygon/BSC/Arbitrum/OP/Base lookups with higher rate limits.', url: 'https://etherscan.io/apis', group: 'Chain data' },
  { key: 'BLOCKCYPHER_TOKEN', label: 'BlockCypher', hint: 'Improves Bitcoin lookups: richer TX detail, confidence scores, higher rate limits.', url: 'https://www.blockcypher.com', group: 'Chain data' },
  { key: 'ETHPLORER_API_KEY', label: 'Ethplorer', hint: 'ETH fallback when no Etherscan key is set. Defaults to free public key.', url: 'https://ethplorer.io', group: 'Chain data' },
  { key: 'THEGRAPH_API_KEY', label: 'TheGraph', hint: 'Required for DEX analysis via Uniswap/PancakeSwap subgraphs at higher limits.', url: 'https://thegraph.com', group: 'Chain data' },
  { key: 'UD_API_KEY', label: 'Unstoppable Domains', hint: 'Resolves .crypto / .x / .nft / .wallet / .bitcoin domains to addresses.', url: 'https://www.unstoppabledomains.com', group: 'Chain data' },
  { key: 'ARKHAM_API_KEY', label: 'Arkham Intelligence', hint: 'Entity attribution — identifies wallets belonging to exchanges, funds, DEXes.', url: 'https://intel.arkm.com', group: 'Attribution & risk' },
  { key: 'CHAINALYSIS_API_KEY', label: 'Chainalysis', hint: 'Overrides OFAC local list for sanctions screening with real-time data.', url: 'https://www.chainalysis.com', group: 'Attribution & risk' },
  { key: 'SCAMSEARCH_API_KEY', label: 'ScamSearch', hint: 'Community scam reports for addresses, usernames, and phone numbers.', url: 'https://scamsearch.io', group: 'Attribution & risk' },
  { key: 'BITCOINABUSE_API_TOKEN', label: 'BitcoinAbuse', hint: 'Enables BTC abuse report checks from BitcoinAbuse public reports.', url: 'https://www.bitcoinabuse.com/api-docs', group: 'Attribution & risk' },
  { key: 'DUNE_API_KEY', label: 'Dune', hint: 'Enables optional curated label enrichment through a configured Dune query.', url: 'https://dune.com/settings/api', group: 'Attribution & risk' },
  { key: 'DUNE_LABELS_QUERY_ID', label: 'Dune Labels Query ID', hint: 'Optional query ID for an address-label query that accepts an address parameter.', url: 'https://docs.dune.com/api-reference/overview/introduction', group: 'Attribution & risk' },
  { key: 'PASTEBIN_API_KEY', label: 'Pastebin API', hint: 'Enables the official Pastebin API connector for OSINT Sweep.', url: 'https://pastebin.com/doc_api', group: 'OSINT' },
  { key: 'PASTEBIN_USER_KEY', label: 'Pastebin User Key', hint: 'Required to list and inspect your own Pastebin pastes through the official API.', url: 'https://pastebin.com/doc_api', group: 'OSINT' },
]

// Group keys map into the `settings:keys.groups.*` translations.
const KEY_GROUPS = ['chainData', 'attributionRisk', 'osint'] as const

function isSecretName(name: string) {
  return name.includes('KEY') || name.includes('TOKEN')
}

/* ── Status helpers ──────────────────────────────────────────────────────── */
type KeyStatus = 'set' | 'pending' | 'unset'

/* ── Key editor modal ────────────────────────────────────────────────────── */
function KeyEditorModal({
  field, currentValue, onApply, onClose,
}: {
  field: FieldConfig
  currentValue: string
  onApply: (key: keyof ApiSettings, val: string) => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const secret = isSecretName(String(field.key))
  const isSet = secret ? currentValue === 'SET' : Boolean(currentValue)
  const [val, setVal] = useState(secret ? '' : currentValue === 'SET' ? '' : currentValue)
  const [show, setShow] = useState(!secret)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal(
    <div className="cxmodal-back" onClick={onClose}>
      <div className="cxmodal" onClick={e => e.stopPropagation()}>
        <div className="cxmodal-head">
          <span className="ic"><KeyRound size={18} /></span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3>{field.label}</h3>
            <div className="env">{String(field.key)}{isSet ? ` · ${t('settings:editor.configured')}` : ''}</div>
          </div>
          <button className="x" onClick={onClose}><X size={16} /></button>
        </div>
        <p className="cxmodal-hint">{field.hint}</p>
        <div className="cxmodal-inputwrap">
          <input
            className="cxinput"
            style={{ paddingRight: secret ? 34 : 10 }}
            type={secret && !show ? 'password' : 'text'}
            autoFocus
            placeholder={isSet ? t('settings:editor.placeholderReplace') : field.placeholder || t('settings:editor.placeholderGeneric', { label: field.label })}
            value={val}
            onChange={e => setVal(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && val.trim()) { onApply(field.key, val.trim()); onClose() } }}
          />
          {secret && (
            <button className="eye" onClick={() => setShow(s => !s)} type="button">
              {show ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          )}
        </div>
        {field.url && (
          <a className="cxmodal-link" href={field.url} target="_blank" rel="noopener noreferrer">
            {t('settings:editor.getKey')} <ExternalLink size={11} style={{ display: 'inline', verticalAlign: '-1px' }} />
          </a>
        )}
        <div className="cxmodal-actions">
          <button
            className="cxmodal-apply"
            disabled={!val.trim()}
            onClick={() => { onApply(field.key, val.trim()); onClose() }}
          >
            {t('settings:editor.apply')}
          </button>
          <button className="cxmodal-clear" onClick={onClose}>{t('settings:editor.cancel')}</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/* ── Small controls ──────────────────────────────────────────────────────── */
function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return <button type="button" className={`cxtoggle${on ? ' on' : ''}`} onClick={() => onChange(!on)} aria-pressed={on} />
}
function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { v: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="cxseg">
      {options.map(o => (
        <button key={o.v} className={value === o.v ? 'active' : ''} onClick={() => onChange(o.v)}>{o.label}</button>
      ))}
    </div>
  )
}
function Stepper({ value, min, max, step = 1, onChange, suffix }: { value: number; min: number; max: number; step?: number; onChange: (v: number) => void; suffix?: string }) {
  const clamp = (v: number) => Math.max(min, Math.min(max, v))
  return (
    <div className="cxstep">
      <button onClick={() => onChange(clamp(value - step))}>−</button>
      <span className="cxstep-val">{value}{suffix}</span>
      <button onClick={() => onChange(clamp(value + step))}>+</button>
    </div>
  )
}

export default function Settings() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { data: current } = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const { data: aiRuntime, refetch: refetchAiRuntime } = useQuery({ queryKey: ['ai-status'], queryFn: aiStatus })

  const [edits, setEdits] = useState<Partial<ApiSettings>>({})
  const [saved, setSaved] = useState(false)
  const [aiTest, setAiTest] = useState<AiStatus | null>(null)
  const [editField, setEditField] = useState<FieldConfig | null>(null)

  // Tool-feature + workspace preferences
  const [prefs, setPrefsState] = useState<CryptxPrefs>(() => getPrefs())
  const [theme, setTheme] = useState<'dark' | 'light'>(() => (localStorage.getItem('theme') as 'dark' | 'light') || 'dark')
  const [density, setDensity] = useState<'comfortable' | 'compact'>(() => (localStorage.getItem('density') as 'comfortable' | 'compact') || 'comfortable')

  useEffect(() => { if (current) setEdits({}) }, [current])
  useEffect(() => { document.documentElement.classList.toggle('light', theme === 'light'); localStorage.setItem('theme', theme) }, [theme])
  useEffect(() => { document.documentElement.setAttribute('data-density', density); localStorage.setItem('density', density) }, [density])

  const mutation = useMutation({
    mutationFn: saveSettings,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['ai-status'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })
  const aiTestMutation = useMutation({
    mutationFn: testAiProvider,
    onSuccess: data => { setAiTest(data); refetchAiRuntime() },
  })

  function handleChange(key: keyof ApiSettings, val: string) { setEdits(prev => ({ ...prev, [key]: val })) }
  function handleSave() { mutation.mutate(edits) }
  function updatePref(patch: Partial<CryptxPrefs>) { setPrefsState(setPrefs(patch)) }

  const merged: ApiSettings = { ...(current ?? {}), ...edits } as ApiSettings
  const selectedProviderId = (merged.AI_PROVIDER || aiRuntime?.provider || 'deepseek').toLowerCase()
  const selectedProvider = AI_PROVIDERS.find(p => p.id === selectedProviderId) || AI_PROVIDERS[0]
  const hasPendingProviderChange = Boolean(edits.AI_PROVIDER && edits.AI_PROVIDER !== aiRuntime?.provider)
  const changedKeys = Object.keys(edits).filter(k => edits[k as keyof ApiSettings])

  const fieldValue = (key: keyof ApiSettings) => {
    const value = edits[key] ?? merged[key]
    return typeof value === 'string' ? value : ''
  }
  function keyStatus(field: FieldConfig): KeyStatus {
    if (edits[field.key]) return 'pending'
    const v = fieldValue(field.key)
    const secret = isSecretName(String(field.key))
    if (secret ? v === 'SET' : Boolean(v)) return 'set'
    return 'unset'
  }

  const configuredCount = DATA_FIELDS.filter(f => keyStatus(f) === 'set').length

  // AI provider inline fields
  const aiKeyStatus: KeyStatus = edits[selectedProvider.keyField]
    ? 'pending'
    : fieldValue(selectedProvider.keyField) === 'SET' ? 'set' : 'unset'

  return (
    <div className="cxset">
      {/* Header */}
      <div className="cxset-head">
        <span className="cxset-head-icon"><SettingsIcon size={22} /></span>
        <div>
          <h1>{t('settings:title')}</h1>
          <p>{t('settings:subtitle')}</p>
        </div>
        <div className="cxset-head-right">
          {current?._meta?.written_env_paths?.length ? (
            <span className="cxset-envchip" title={current._meta.written_env_paths.join('  |  ')}>
              ◈ {t('settings:head.syncEnv', { count: current._meta.written_env_paths.length })}
            </span>
          ) : null}
          {saved && <span className="cxset-saved"><CheckCircle size={14} /> {t('settings:head.saved')}</span>}
          {mutation.isError && <span className="cxset-saveerr">{t('settings:head.saveFailed')}</span>}
          <button className="cxset-save" onClick={handleSave} disabled={mutation.isPending || changedKeys.length === 0}>
            {mutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {mutation.isPending
              ? t('settings:head.saving')
              : changedKeys.length
                ? t('settings:head.saveButtonCount', { count: changedKeys.length })
                : t('settings:head.saveButton')}
          </button>
        </div>
      </div>

      {/* Grid */}
      <div className="cxset-grid">
        {/* ── API KEYS ── */}
        <section className="cxpanel cxset-area-keys">
          <div className="cxpanel-title">
            <span className="cxc">◈</span> {t('settings:panels.dataSourceKeys')}
            <small>{t('settings:keys.configuredCount', { count: configuredCount, total: DATA_FIELDS.length })}</small>
          </div>
          <div className="cxpanel-body scrollable">
            <div className="cxkeys-groups">
              {KEY_GROUPS.map(group => {
                // Legacy DATA_FIELDS.group values are English strings; map to the key.
                const legacyLabel = group === 'chainData' ? 'Chain data' : group === 'attributionRisk' ? 'Attribution & risk' : 'OSINT'
                return (
                  <div key={group}>
                    <div className="cxkeys-subhead">{t(`settings:keys.groups.${group}`)}</div>
                    <div className="cxkeys">
                      {DATA_FIELDS.filter(f => f.group === legacyLabel).map(f => {
                        const s = keyStatus(f)
                        const statusKey = s === 'set' ? 'settings:status.configured' : s === 'pending' ? 'settings:status.pending' : 'settings:status.notSet'
                        return (
                          <div key={String(f.key)} className="cxkey" onClick={() => setEditField(f)} title={f.hint}>
                            <span className={`cxkey-dot ${s}`} />
                            <div className="cxkey-main">
                              <div className="cxkey-label">{f.label}</div>
                              <div className="cxkey-env">{String(f.key)}</div>
                            </div>
                            <span className={`cxkey-status ${s}`}>{t(statusKey)}</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </section>

        {/* ── AI RUNTIME ── */}
        <section className="cxpanel cxset-area-ai">
          <div className="cxpanel-title"><span className="cxc">◈</span> {t('settings:panels.aiRuntime')}</div>
          <div className="cxpanel-body">
            <div className="cxai-status">
              {t('settings:ai.provider')} <b>{aiRuntime?.provider_name || aiRuntime?.provider || t('settings:ai.providerNone')}</b> · {t('settings:ai.model')} <b>{aiRuntime?.model || t('settings:ai.modelNone')}</b><br />
              {t('settings:ai.apiKey')} {aiRuntime?.configured ? <span className="ok">{t('settings:ai.keyConfigured')}</span> : <span className="off">{t('settings:ai.keyNotConfigured')}</span>}
              {hasPendingProviderChange && <> · <span className="off">{t('settings:ai.saveToActivate', { label: selectedProvider.label })}</span></>}
            </div>

            <div className="cxai-field">
              <label>{t('settings:ai.provider')}</label>
              <select className="cxselect w-full" value={selectedProvider.id} onChange={e => handleChange('AI_PROVIDER', e.target.value)}>
                {AI_PROVIDERS.map(p => <option key={p.id} value={p.id}>{p.label} — {p.kind}</option>)}
              </select>
            </div>

            <div className="cxai-field">
              <label>{t('settings:ai.apiKey')} {aiKeyStatus === 'set' && <span style={{ color: 'rgb(var(--cx-green))' }}>· {t('settings:ai.apiKeySet')}</span>}{aiKeyStatus === 'pending' && <span style={{ color: 'rgb(var(--cx-amber))' }}>· {t('settings:ai.apiKeyPending')}</span>}</label>
              <input
                className="cxinput" type="password"
                placeholder={fieldValue(selectedProvider.keyField) === 'SET' ? t('settings:ai.apiKeyConfiguredPlaceholder') : t('settings:ai.apiKeyPlaceholder', { label: selectedProvider.label })}
                value={typeof edits[selectedProvider.keyField] === 'string' ? (edits[selectedProvider.keyField] as string) : ''}
                onChange={e => handleChange(selectedProvider.keyField, e.target.value)}
              />
            </div>

            <div className="cxai-field">
              <label>{t('settings:ai.model')}</label>
              <input
                className="cxinput"
                placeholder={selectedProvider.defaultModel || t('settings:ai.modelPlaceholder')}
                value={fieldValue(selectedProvider.modelField) === 'SET' ? '' : fieldValue(selectedProvider.modelField)}
                onChange={e => handleChange(selectedProvider.modelField, e.target.value)}
              />
            </div>

            {selectedProvider.baseField && (
              <div className="cxai-field">
                <label>{t('settings:ai.baseUrl')}</label>
                <input
                  className="cxinput"
                  placeholder={selectedProvider.defaultBaseUrl || t('settings:ai.baseUrlPlaceholder')}
                  value={fieldValue(selectedProvider.baseField) === 'SET' ? '' : fieldValue(selectedProvider.baseField)}
                  onChange={e => handleChange(selectedProvider.baseField as keyof ApiSettings, e.target.value)}
                />
              </div>
            )}

            <button
              className="cxtest"
              onClick={() => aiTestMutation.mutate()}
              disabled={aiTestMutation.isPending || !aiRuntime?.configured || hasPendingProviderChange}
            >
              {aiTestMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Cpu size={13} />}
              {t('settings:ai.testProvider')}
            </button>
            {aiTest && <div style={{ marginTop: 8, fontSize: 10.5, color: 'rgb(var(--cx-green))' }}>{t('settings:ai.liveLabel')}: {aiTest.provider_name || aiTest.provider} / {aiTest.model || aiRuntime?.model}</div>}
            {aiTestMutation.isError && <div style={{ marginTop: 8, fontSize: 10.5, color: 'rgb(var(--cx-red))', display: 'flex', gap: 6 }}><AlertTriangle size={12} /> {t('settings:ai.testFailed')}</div>}
          </div>
        </section>

        {/* ── TOOL FEATURES ── */}
        <section className="cxpanel cxset-area-tools">
          <div className="cxpanel-title"><span className="cxc"><SlidersHorizontal size={11} /></span> {t('settings:panels.toolFeatures')}</div>
          <div className="cxpanel-body">
            <div className="cxrow">
              <div><div className="cxrow-label">{t('settings:rows.apiTimeout.label')}</div><div className="cxrow-sub">{t('settings:rows.apiTimeout.sub')}</div></div>
              <div className="cxrange">
                <input type="range" min={30} max={600} step={10} value={prefs.apiTimeoutSec} onChange={e => updatePref({ apiTimeoutSec: Number(e.target.value) })} />
                <span className="cxrange-val">{prefs.apiTimeoutSec}s</span>
              </div>
            </div>
            <div className="cxrow">
              <div><div className="cxrow-label">{t('settings:rows.defaultHops.label')}</div><div className="cxrow-sub">{t('settings:rows.defaultHops.sub')}</div></div>
              <Stepper value={prefs.defaultHops} min={1} max={5} onChange={v => updatePref({ defaultHops: v })} />
            </div>
            <div className="cxrow">
              <div><div className="cxrow-label">{t('settings:rows.traceMode.label')}</div></div>
              <Segmented value={prefs.traceMode} options={[{ v: 'linear', label: t('settings:segmented.linear') }, { v: 'wide', label: t('settings:segmented.wide') }]} onChange={v => updatePref({ traceMode: v })} />
            </div>
            <div className="cxrow">
              <div><div className="cxrow-label">{t('settings:rows.monitorRefresh.label')}</div><div className="cxrow-sub">{t('settings:rows.monitorRefresh.sub')}</div></div>
              <select className="cxselect" value={String(prefs.monitorRefreshSec)} onChange={e => updatePref({ monitorRefreshSec: Number(e.target.value) })}>
                <option value="0">{t('settings:status.off')}</option><option value="15">15s</option><option value="30">30s</option><option value="60">60s</option>
              </select>
            </div>
            <div className="cxrow">
              <div><div className="cxrow-label">{t('settings:rows.riskThreshold.label')}</div><div className="cxrow-sub">{t('settings:rows.riskThreshold.sub')}</div></div>
              <div className="cxrange">
                <input type="range" min={0} max={100} step={5} value={prefs.riskAlertThreshold} onChange={e => updatePref({ riskAlertThreshold: Number(e.target.value) })} />
                <span className="cxrange-val">{prefs.riskAlertThreshold}</span>
              </div>
            </div>
            <div className="cxrow">
              <div><div className="cxrow-label">{t('settings:rows.batchSize.label')}</div><div className="cxrow-sub">{t('settings:rows.batchSize.sub')}</div></div>
              <Stepper value={prefs.batchSize} min={25} max={500} step={25} onChange={v => updatePref({ batchSize: v })} />
            </div>
            <div className="cxrow">
              <div><div className="cxrow-label">{t('settings:rows.autoEnrich.label')}</div><div className="cxrow-sub">{t('settings:rows.autoEnrich.sub')}</div></div>
              <Toggle on={prefs.autoEnrich} onChange={v => updatePref({ autoEnrich: v })} />
            </div>
            <div className="cxrow">
              <div><div className="cxrow-label">{t('settings:rows.confirmDelete.label')}</div></div>
              <Toggle on={prefs.confirmDelete} onChange={v => updatePref({ confirmDelete: v })} />
            </div>
          </div>
        </section>

        {/* ── WORKSPACE ── */}
        <section className="cxpanel cxset-area-work">
          <div className="cxpanel-title"><span className="cxc"><Monitor size={11} /></span> {t('settings:panels.workspace')}</div>
          <div className="cxpanel-body">
            <div className="cxrow">
              <div className="cxrow-label">{t('settings:rows.theme')}</div>
              <Segmented value={theme} options={[{ v: 'dark', label: t('settings:segmented.dark') }, { v: 'light', label: t('settings:segmented.light') }]} onChange={setTheme} />
            </div>
            <div className="cxrow">
              <div className="cxrow-label">{t('settings:rows.density')}</div>
              <Segmented value={density} options={[{ v: 'comfortable', label: t('settings:segmented.comfortable') }, { v: 'compact', label: t('settings:segmented.compact') }]} onChange={setDensity} />
            </div>
            <div className="cxrow">
              <div className="cxrow-label">{t('settings:rows.language')}</div>
              <LanguagePicker variant="full" />
            </div>
            <div className="cxrow">
              <div className="cxrow-label">{t('settings:rows.defaultChain')}</div>
              <select className="cxselect" value={prefs.defaultChain} onChange={e => updatePref({ defaultChain: e.target.value })}>
                {['auto', 'btc', 'eth', 'bsc', 'polygon', 'arbitrum', 'optimism', 'base', 'tron', 'solana'].map(c => <option key={c} value={c}>{t(`settings:chains.${c}`)}</option>)}
              </select>
            </div>
            <div className="cxrow">
              <div className="cxrow-label">Result rows</div>
              <select className="cxselect" value={String(prefs.resultRows)} onChange={e => updatePref({ resultRows: Number(e.target.value) })}>
                {[10, 25, 50, 100].map(n => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
            <div className="cxrow">
              <div><div className="cxrow-label">{t('settings:rows.liveThreatFeed.label')}</div><div className="cxrow-sub">{t('settings:rows.liveThreatFeed.sub')}</div></div>
              <Toggle on={prefs.liveThreatFeed} onChange={v => updatePref({ liveThreatFeed: v })} />
            </div>
            <div className="cxrow">
              <div><div className="cxrow-label">{t('settings:rows.animations.label')}</div></div>
              <Toggle on={prefs.animations} onChange={v => updatePref({ animations: v })} />
            </div>
          </div>
        </section>
      </div>

      {editField && (
        <KeyEditorModal
          field={editField}
          currentValue={fieldValue(editField.key)}
          onApply={handleChange}
          onClose={() => setEditField(null)}
        />
      )}
    </div>
  )
}
