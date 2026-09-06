/**
 * i18n/index.ts — CrypTX i18next bootstrap.
 *
 * Imported for its side effect in `src/main.tsx` (before <App /> mounts). It
 * initialises a single i18next instance, registers react-i18next, and wires up
 * the resource bundles for every supported language.
 *
 * Resources are bundled at build time (no network round trip). At CrypTX's
 * scale (~9 namespaces, 5 languages) this is a few KB gzipped per language and
 * keeps language switching instantaneous and offline-friendly.
 *
 * The active language is resolved by `detectInitialLanguage()` (see config.ts):
 *
 *   ?lang=…  →  saved pref  →  browser language  →  English fallback
 *
 * Whenever the language later changes via `i18n.changeLanguage(code)` (called
 * from the LanguagePicker), we also:
 *   - reflect it on <html lang="…"> for a11y / SEO,
 *   - keep the Intl helpers in `./format.ts` in sync (they read i18n.language).
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import {
  DEFAULT_LANGUAGE,
  SUPPORTED_LANGUAGES,
  detectInitialLanguage,
  getLanguageDefinition,
  type SupportedLanguage,
} from './config'

// English resources (source of truth / fallback bundle).
import enCommon from './locales/en/common.json'
import enNav from './locales/en/nav.json'
import enLayout from './locales/en/layout.json'
import enAuth from './locales/en/auth.json'
import enSettings from './locales/en/settings.json'
import enDashboard from './locales/en/dashboard.json'
import enCommand from './locales/en/command.json'
import enComponents from './locales/en/components.json'
import enTools from './locales/en/tools.json'

// French resources.
import frCommon from './locales/fr/common.json'
import frNav from './locales/fr/nav.json'
import frLayout from './locales/fr/layout.json'
import frAuth from './locales/fr/auth.json'
import frSettings from './locales/fr/settings.json'
import frDashboard from './locales/fr/dashboard.json'
import frCommand from './locales/fr/command.json'
import frComponents from './locales/fr/components.json'
import frTools from './locales/fr/tools.json'

// Spanish resources.
import esCommon from './locales/es/common.json'
import esNav from './locales/es/nav.json'
import esLayout from './locales/es/layout.json'
import esAuth from './locales/es/auth.json'
import esSettings from './locales/es/settings.json'
import esDashboard from './locales/es/dashboard.json'
import esCommand from './locales/es/command.json'
import esComponents from './locales/es/components.json'
import esTools from './locales/es/tools.json'

// Russian resources.
import ruCommon from './locales/ru/common.json'
import ruNav from './locales/ru/nav.json'
import ruLayout from './locales/ru/layout.json'
import ruAuth from './locales/ru/auth.json'
import ruSettings from './locales/ru/settings.json'
import ruDashboard from './locales/ru/dashboard.json'
import ruCommand from './locales/ru/command.json'
import ruComponents from './locales/ru/components.json'
import ruTools from './locales/ru/tools.json'

// Chinese resources.
import zhCommon from './locales/zh/common.json'
import zhNav from './locales/zh/nav.json'
import zhLayout from './locales/zh/layout.json'
import zhAuth from './locales/zh/auth.json'
import zhSettings from './locales/zh/settings.json'
import zhDashboard from './locales/zh/dashboard.json'
import zhCommand from './locales/zh/command.json'
import zhComponents from './locales/zh/components.json'
import zhTools from './locales/zh/tools.json'

/**
 * All namespace names. Add new namespaces here and at each language import
 * block above. The default namespace is `common` so the most-used keys (status,
 * actions, units, errors) can be referenced by bare key in hot paths.
 */
export const NAMESPACES = [
  'common', 'nav', 'layout', 'auth', 'settings',
  'dashboard', 'command', 'components', 'tools',
] as const
export type Namespace = (typeof NAMESPACES)[number]
export const DEFAULT_NAMESPACE: Namespace = 'common'

const RESOURCES = {
  en: {
    common: enCommon, nav: enNav, layout: enLayout, auth: enAuth, settings: enSettings,
    dashboard: enDashboard, command: enCommand, components: enComponents, tools: enTools,
  },
  fr: {
    common: frCommon, nav: frNav, layout: frLayout, auth: frAuth, settings: frSettings,
    dashboard: frDashboard, command: frCommand, components: frComponents, tools: frTools,
  },
  es: {
    common: esCommon, nav: esNav, layout: esLayout, auth: esAuth, settings: esSettings,
    dashboard: esDashboard, command: esCommand, components: esComponents, tools: esTools,
  },
  ru: {
    common: ruCommon, nav: ruNav, layout: ruLayout, auth: ruAuth, settings: ruSettings,
    dashboard: ruDashboard, command: ruCommand, components: ruComponents, tools: ruTools,
  },
  zh: {
    common: zhCommon, nav: zhNav, layout: zhLayout, auth: zhAuth, settings: zhSettings,
    dashboard: zhDashboard, command: zhCommand, components: zhComponents, tools: zhTools,
  },
} as const

/** The full i18next resource bundle (typed). Exported for type augmentation. */
export type AppResources = typeof RESOURCES

const initialLanguage = detectInitialLanguage()

void i18n
  .use(initReactI18next)
  .init({
    resources: RESOURCES,
    lng: initialLanguage,
    fallbackLng: DEFAULT_LANGUAGE,
    supportedLngs: SUPPORTED_LANGUAGES.map(l => l.code),
    ns: NAMESPACES as unknown as string[],
    defaultNS: DEFAULT_NAMESPACE,
    // React already escapes interpolated values; double-escaping would render
    // entities like &amp; literally inside JSX text nodes.
    interpolation: { escapeValue: false },
    // A missing key in any non-English bundle gracefully falls back to the
    // English value (fallbackLng), so untranslated keys never render as raw
    // dot-paths to end users.
    returnNull: false,
    react: {
      // Re-render consumers on language change (default true; explicit for clarity).
      bindI18n: 'languageChanged loaded',
      useSuspense: false,
    },
  })

/**
 * Keep <html lang="…"> in sync with the active language so screen readers,
 * search engines, and the browser spell-checker all agree.
 */
function syncHtmlLang(code: SupportedLanguage) {
  if (typeof document === 'undefined') return
  // Use the short code; Intl formatting reads the locale map in config.ts.
  document.documentElement.lang = code
}

// Set the initial attribute, then keep it in sync on every change.
syncHtmlLang(initialLanguage)
i18n.on('languageChanged', (lng) => {
  syncHtmlLang(lng as SupportedLanguage)
  // Also remember the choice in prefs so it survives reloads (matches the
  // pattern used by theme/density in Layout.tsx). Safe no-op if prefs is busy.
  try {
    const def = getLanguageDefinition(lng as SupportedLanguage)
    if (def) {
      // Lazy import to avoid a static cycle (prefs.ts has no i18n dependency,
      // but deferring keeps the boundary clean).
      void import('../lib/prefs').then(({ setPrefs }) => setPrefs({ language: def.code }))
    }
  } catch {
    /* prefs unavailable — ignore */
  }
})

export default i18n
