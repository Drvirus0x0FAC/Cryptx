/**
 * prefs.ts — CrypTX tool-feature preferences.
 *
 * Client-side, localStorage-backed configuration that controls how the
 * investigation tools behave (request timeout, default trace depth, monitor
 * refresh cadence, risk-alert threshold, animations, etc.). These are read by
 * the relevant modules and by the Settings "Tool Features" panel.
 *
 * Kept separate from the backend API-key settings so it needs no server round
 * trip and never blocks the UI.
 */

import type { SupportedLanguage } from '../i18n/config'

export interface CryptxPrefs {
  /** Axios request timeout, in seconds (applied to api/client.ts). */
  apiTimeoutSec: number
  /** Default Fund Tracer hop depth (1–5). */
  defaultHops: number
  /** Default Fund Tracer traversal mode. */
  traceMode: 'linear' | 'wide'
  /** Default chain used to seed lookups. */
  defaultChain: string
  /** Wallet Monitor auto-refresh cadence in seconds (0 = off). */
  monitorRefreshSec: number
  /** Risk score at/above which a subject is treated as an alert (0–100). */
  riskAlertThreshold: number
  /** Max addresses processed per Batch Screen run. */
  batchSize: number
  /** Default rows shown in result tables. */
  resultRows: number
  /** Enable decorative motion / ambient animations across the app. */
  animations: boolean
  /** Ask for confirmation before destructive actions. */
  confirmDelete: boolean
  /** Show the live Threat Landscape ticker / feed. */
  liveThreatFeed: boolean
  /** Automatically run public enrichment on every address lookup. */
  autoEnrich: boolean
  /** Active UI language (also drives locale-aware Intl formatting). */
  language: SupportedLanguage
}

export const DEFAULT_PREFS: CryptxPrefs = {
  apiTimeoutSec: 120,
  defaultHops: 3,
  traceMode: 'linear',
  defaultChain: 'auto',
  monitorRefreshSec: 30,
  riskAlertThreshold: 70,
  batchSize: 100,
  resultRows: 25,
  animations: true,
  confirmDelete: true,
  liveThreatFeed: true,
  autoEnrich: true,
  language: 'en',
}

const STORAGE_KEY = 'cryptx_prefs'

/** Read all preferences, merged over defaults (safe on SSR / bad data). */
export function getPrefs(): CryptxPrefs {
  if (typeof window === 'undefined') return { ...DEFAULT_PREFS }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_PREFS }
    const parsed = JSON.parse(raw) as Partial<CryptxPrefs>
    return { ...DEFAULT_PREFS, ...parsed }
  } catch {
    return { ...DEFAULT_PREFS }
  }
}

/** Read a single preference. */
export function getPref<K extends keyof CryptxPrefs>(key: K): CryptxPrefs[K] {
  return getPrefs()[key]
}

/** Persist a partial update and return the merged result. */
export function setPrefs(patch: Partial<CryptxPrefs>): CryptxPrefs {
  const next = { ...getPrefs(), ...patch }
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    // Broadcast so live consumers (e.g. axios client, ambient animations) react.
    window.dispatchEvent(new CustomEvent('cryptx-prefs-changed', { detail: next }))
  } catch {
    /* storage unavailable — ignore */
  }
  return next
}

/** Reset everything back to defaults. */
export function resetPrefs(): CryptxPrefs {
  return setPrefs({ ...DEFAULT_PREFS })
}
