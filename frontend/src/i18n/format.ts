/**
 * i18n/format.ts — locale-aware formatting helpers.
 *
 * Thin, memoised wrappers around the Intl APIs that resolve the locale from the
 * active i18next language (config.ts maps each short code to a full BCP-47
 * locale). Use these instead of hard-coded `toLocaleString('en-US', …)` calls
 * so dates, times, numbers and currencies render in the user's language.
 *
 * Two flavours are exported:
 *
 *  1. **Plain functions** (`formatDate`, `formatNumber`, …) — read the
 *     *current* i18next language. Suitable for one-off renders outside React
 *     (utilities, console formatters) or inside components that already
 *     re-render when the language changes.
 *
 *  2. **`useFormat()` hook** — returns the same helpers bound to the active
 *     language, and re-renders the calling component on `languageChanged`.
 *     This is the recommended entry point from React components.
 */

import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from './index'
import { intlLocaleFor, type SupportedLanguage } from './config'

/** Resolve the active BCP-47 locale from i18next's current language. */
export function activeLocale(): string {
  const lng = (i18n.language || 'en') as SupportedLanguage
  return intlLocaleFor(lng)
}

/* ── Shared Intl formatter caches ─────────────────────────────────────────
 * Intl format objects are expensive to construct; cache one per locale so the
 * common case (one active language at a time) is essentially free.
 */
const dateTimeCache = new Map<string, Intl.DateTimeFormat>()
const numberCache = new Map<string, Intl.NumberFormat>()

function getDateTimeFormatter(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  // Options are part of the cache key — different precisions need different formatters.
  const key = `${locale}|${JSON.stringify(options)}`
  let fmt = dateTimeCache.get(key)
  if (!fmt) {
    fmt = new Intl.DateTimeFormat(locale, options)
    dateTimeCache.set(key, fmt)
  }
  return fmt
}

function getNumberFormatter(locale: string, options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = `${locale}|${JSON.stringify(options)}`
  let fmt = numberCache.get(key)
  if (!fmt) {
    fmt = new Intl.NumberFormat(locale, options)
    numberCache.set(key, fmt)
  }
  return fmt
}

function toDate(input: Date | number | string): Date {
  if (input instanceof Date) return input
  if (typeof input === 'number') return new Date(input)
  return new Date(input)
}

/* ── Date / time ────────────────────────────────────────────────────────── */

/** Short date only, e.g. "27/07/2026" (fr) / "7/27/2026" (en-US) / "2026/7/27" (zh). */
export function formatDate(input: Date | number | string, locale = activeLocale()): string {
  return getDateTimeFormatter(locale, { dateStyle: 'medium' }).format(toDate(input))
}

/** Time only, 24h, e.g. "14:05:09". Matches the previous LiveClock behaviour. */
export function formatTime(input: Date | number | string, locale = activeLocale()): string {
  return getDateTimeFormatter(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(toDate(input))
}

/** Short time without seconds, e.g. "14:05". */
export function formatTimeShort(input: Date | number | string, locale = activeLocale()): string {
  return getDateTimeFormatter(locale, { hour: '2-digit', minute: '2-digit', hour12: false }).format(toDate(input))
}

/** Date + time, e.g. "27 Jul 2026, 14:05:09". */
export function formatDateTime(input: Date | number | string, locale = activeLocale()): string {
  return getDateTimeFormatter(locale, { dateStyle: 'medium', timeStyle: 'medium' }).format(toDate(input))
}

/* ── Numbers / currency ─────────────────────────────────────────────────── */

/** Locale-formatted number, e.g. "1 234,56" (fr) / "1,234.56" (en). */
export function formatNumber(value: number, options: Intl.NumberFormatOptions = {}, locale = activeLocale()): string {
  return getNumberFormatter(locale, options).format(value)
}

/** Compact notation for large magnitudes, e.g. "1.2M" / "1,2 M". */
export function formatCompact(value: number, locale = activeLocale()): string {
  return getNumberFormatter(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

/** Percentage, e.g. "42%" / "42 %". Pass a 0–100 value (multiplied internally). */
export function formatPercent(value: number, fractionDigits = 0, locale = activeLocale()): string {
  return getNumberFormatter(locale, { style: 'percent', minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits }).format(value / 100)
}

/** Currency. Defaults to USD; pass any ISO 4217 code. */
export function formatCurrency(value: number, currency = 'USD', locale = activeLocale()): string {
  return getNumberFormatter(locale, { style: 'currency', currency, maximumFractionDigits: value < 1 ? 6 : 2 }).format(value)
}

/** Token/crypto amount with a fixed number of decimals, e.g. "1.5000 ETH". */
export function formatTokenAmount(value: number, symbol: string, fractionDigits = 4, locale = activeLocale()): string {
  const n = getNumberFormatter(locale, { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits }).format(value)
  return `${n} ${symbol}`
}

/* ── React hook ───────────────────────────────────────────────────────────
 * `useTranslation()` subscribes the component to language changes, so reading
 * `i18n.language` afterwards is always fresh and the component re-renders.
 */
export interface FormatFunctions {
  locale: string
  formatDate: (input: Date | number | string) => string
  formatTime: (input: Date | number | string) => string
  formatTimeShort: (input: Date | number | string) => string
  formatDateTime: (input: Date | number | string) => string
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string
  formatCompact: (value: number) => string
  formatPercent: (value: number, fractionDigits?: number) => string
  formatCurrency: (value: number, currency?: string) => string
  formatTokenAmount: (value: number, symbol: string, fractionDigits?: number) => string
}

/**
 * React hook returning all format helpers bound to the *current* language.
 * Re-renders the calling component whenever the language changes.
 *
 * @example
 *   const { formatDateTime, formatCurrency } = useFormat()
 *   <span>{formatDateTime(tx.timestamp)} · {formatCurrency(tx.usd, 'USD')}</span>
 */
export function useFormat(): FormatFunctions {
  const { i18n: inst } = useTranslation()
  const locale = useMemo(() => intlLocaleFor((inst.language || 'en') as SupportedLanguage), [inst.language])

  return useMemo<FormatFunctions>(() => ({
    locale,
    formatDate: (input) => formatDate(input, locale),
    formatTime: (input) => formatTime(input, locale),
    formatTimeShort: (input) => formatTimeShort(input, locale),
    formatDateTime: (input) => formatDateTime(input, locale),
    formatNumber: (value, options) => formatNumber(value, options ?? {}, locale),
    formatCompact: (value) => formatCompact(value, locale),
    formatPercent: (value, fractionDigits) => formatPercent(value, fractionDigits ?? 0, locale),
    formatCurrency: (value, currency) => formatCurrency(value, currency ?? 'USD', locale),
    formatTokenAmount: (value, symbol, fractionDigits) => formatTokenAmount(value, symbol, fractionDigits ?? 4, locale),
    // useCallback not needed: useMemo already stabilises the whole object across
    // renders that don't change the language.
  }), [locale])
}
