/**
 * i18n/config.ts — CrypTX supported-language registry and detection.
 *
 * Defines the canonical list of supported UI languages, the mapping from each
 * short language code to its full BCP-47 locale (used for Intl date / time /
 * number / currency formatting), and the initial-language resolution strategy:
 *
 *   saved preference  →  browser language  →  DEFAULT_LANGUAGE (English)
 *
 * Kept dependency-free so it can be imported by both the i18next bootstrap
 * (`./index.ts`) and the React format helpers (`./format.ts`) without cycles.
 */

export type SupportedLanguage = 'en' | 'fr' | 'es' | 'ru' | 'zh'

export interface LanguageDefinition {
  /** Short i18next language code (also the prefs field value). */
  code: SupportedLanguage
  /** Native endonym shown in the picker ("Français", "中文", …). */
  nativeName: string
  /** English exonym, used for aria-labels / tooltips. */
  englishName: string
  /** Short uppercase tag for the compact picker button ("EN", "FR", …). */
  short: string
  /**
   * Full BCP-47 locale used by Intl APIs for date / time / number / currency
   * formatting in this language.
   */
  intlLocale: string
}

/**
 * The five languages CrypTX ships with. English first since it is the fallback.
 */
export const SUPPORTED_LANGUAGES: readonly LanguageDefinition[] = [
  { code: 'en', nativeName: 'English',  englishName: 'English',  short: 'EN', intlLocale: 'en-US' },
  { code: 'fr', nativeName: 'Français', englishName: 'French',   short: 'FR', intlLocale: 'fr-FR' },
  { code: 'es', nativeName: 'Español',  englishName: 'Spanish',  short: 'ES', intlLocale: 'es-ES' },
  { code: 'ru', nativeName: 'Русский',  englishName: 'Russian',  short: 'RU', intlLocale: 'ru-RU' },
  { code: 'zh', nativeName: '中文',      englishName: 'Chinese',  short: 'ZH', intlLocale: 'zh-CN' },
]

/** Language CrypTX falls back to when a key or locale is missing. */
export const DEFAULT_LANGUAGE: SupportedLanguage = 'en'

/** Set of supported codes for O(1) membership checks. */
export const SUPPORTED_CODES: ReadonlySet<SupportedLanguage> = new Set(
  SUPPORTED_LANGUAGES.map(l => l.code),
)

/** Cast / validate an unknown value into a SupportedLanguage (or null). */
export function asSupportedLanguage(value: unknown): SupportedLanguage | null {
  return typeof value === 'string' && (SUPPORTED_CODES as Set<string>).has(value)
    ? (value as SupportedLanguage)
    : null
}

/** Look up the full definition for a supported code (defaults to English). */
export function getLanguageDefinition(code: SupportedLanguage): LanguageDefinition {
  return SUPPORTED_LANGUAGES.find(l => l.code === code) ?? SUPPORTED_LANGUAGES[0]
}

/** Resolve a supported code to its Intl BCP-47 locale (fallback: en-US). */
export function intlLocaleFor(code: SupportedLanguage): string {
  return getLanguageDefinition(code).intlLocale
}

/**
 * Resolve the BCP-47 locale that should drive Intl formatting for an arbitrary
 * browser-reported language string ("fr", "fr-FR", "zh-Hant", "ru-RU", …).
 * Returns the locale of the closest supported language, or `intlLocaleFor(en)`
 * when nothing matches.
 */
export function matchBrowserLocale(browserLang: string | undefined | null): SupportedLanguage {
  if (!browserLang) return DEFAULT_LANGUAGE
  const lower = browserLang.toLowerCase()
  // Exact code match first ("fr", "zh", "ru"…).
  for (const lang of SUPPORTED_LANGUAGES) {
    if (lower === lang.code || lower.startsWith(`${lang.code}-`)) return lang.code
  }
  // Common alternative tags / scripts.
  if (lower.startsWith('zh-') || lower === 'zh') return 'zh'
  if (lower.startsWith('es-') || lower === 'es') return 'es'
  if (lower.startsWith('fr-') || lower === 'fr') return 'fr'
  if (lower.startsWith('ru-') || lower === 'ru') return 'ru'
  return DEFAULT_LANGUAGE
}

/**
 * Decide which language CrypTX should boot in.
 *
 *   1. An explicit override (e.g. ?lang=fr) wins — useful for deep links / demos.
 *   2. A previously saved preference (`cryptx_prefs.language`).
 *   3. The browser's reported language, if it maps to a supported one.
 *   4. DEFAULT_LANGUAGE (English).
 *
 * Safe on SSR: bails to English whenever `window` is undefined.
 */
export function detectInitialLanguage(): SupportedLanguage {
  if (typeof window === 'undefined') return DEFAULT_LANGUAGE

  // 1. URL override (e.g. https://app/?lang=fr).
  try {
    const param = new URLSearchParams(window.location.search).get('lang')
    const fromUrl = asSupportedLanguage(param)
    if (fromUrl) return fromUrl
  } catch {
    /* ignore malformed search string */
  }

  // 2. Saved preference.
  try {
    const raw = window.localStorage.getItem('cryptx_prefs')
    if (raw) {
      const parsed = JSON.parse(raw) as { language?: unknown }
      const saved = asSupportedLanguage(parsed?.language)
      if (saved) return saved
    }
  } catch {
    /* corrupt prefs JSON — fall through */
  }

  // 3. Browser language.
  const nav = (typeof navigator !== 'undefined'
    && (navigator.languages?.[0] || navigator.language)) || null
  return matchBrowserLocale(nav)
}
