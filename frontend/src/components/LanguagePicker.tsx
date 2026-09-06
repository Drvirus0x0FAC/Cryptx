/**
 * LanguagePicker.tsx — CrypTX language switcher.
 *
 * Renders a compact icon button for the top bar (mirrors the existing
 * Theme / Density toggles: `topbar-icon-btn` + `.nav-tip` tooltip) or a full
 * segmented / list control for the Settings "Workspace" panel.
 *
 * Behaviour:
 *   - On select, calls `i18n.changeLanguage(code)`. The i18n bootstrap
 *     (`src/i18n/index.ts`) listens for `languageChanged` and, in turn, updates
 *     `<html lang>`, persists the choice via `setPrefs({ language })`, and
 *     triggers a re-render of every `useTranslation()` consumer — so the whole
 *     UI flips language instantly with no reload.
 *   - The active language is read from `i18n.language` (single source of truth),
 *     NOT from prefs, so the highlight stays correct even before prefs resolve.
 */

import { useEffect, useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Languages, Check, ChevronDown } from 'lucide-react'
import i18n from '../i18n'
import { SUPPORTED_LANGUAGES, type SupportedLanguage } from '../i18n/config'

type Variant = 'compact' | 'full'

interface LanguagePickerProps {
  /** `compact` = top-bar icon button; `full` = settings-panel block control. */
  variant?: Variant
  /** Optional extra className on the root element. */
  className?: string
}

export default function LanguagePicker({ variant = 'compact', className }: LanguagePickerProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  // Stable id for the tooltip / dropdown aria relationship.
  const listId = useId()

  // Close on outside click / Escape. Matches the dismiss patterns used by
  // CommandPalette and the module island in Layout.tsx.
  useEffect(() => {
    if (!open) return
    function onPointerDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  function select(code: SupportedLanguage) {
    if (code !== i18n.language) {
      // changeLanguage emits `languageChanged` → index.ts handles html lang +
      // prefs persistence + React re-render of all consumers.
      void i18n.changeLanguage(code)
    }
    setOpen(false)
  }

  const activeDef = SUPPORTED_LANGUAGES.find(l => l.code === i18n.language) ?? SUPPORTED_LANGUAGES[0]

  /* ── Compact variant (top bar) ───────────────────────────────────────── */
  if (variant === 'compact') {
    return (
      <div className={`lang-picker lang-picker-compact${className ? ` ${className}` : ''}`} ref={rootRef}>
        <button
          type="button"
          className="topbar-icon-btn lang-picker-btn"
          onClick={() => setOpen(o => !o)}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={listId}
          aria-label={t('layout:topbar.language') || 'Language'}
          title={t('layout:topbar.language') || 'Language'}
        >
          <Languages size={15} strokeWidth={1.75} />
          <span className="lang-picker-code">{activeDef.short}</span>
          <span className="nav-tip">{t('layout:topbar.language')}</span>
        </button>
        {open && (
          <ul id={listId} role="listbox" className="lang-picker-menu">
            {SUPPORTED_LANGUAGES.map(lang => {
              const selected = lang.code === activeDef.code
              return (
                <li key={lang.code} role="option" aria-selected={selected}>
                  <button
                    type="button"
                    className={selected ? 'lang-picker-option active' : 'lang-picker-option'}
                    onClick={() => select(lang.code)}
                  >
                    <span className="lang-picker-option-name">{lang.nativeName}</span>
                    <span className="lang-picker-option-en">{lang.englishName}</span>
                    {selected && <Check size={13} className="lang-picker-option-check" />}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    )
  }

  /* ── Full variant (Settings panel) ───────────────────────────────────── */
  return (
    <div className={`lang-picker lang-picker-full${className ? ` ${className}` : ''}`} ref={rootRef}>
      <button
        type="button"
        className="lang-picker-full-trigger"
        onClick={() => setOpen(o => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
      >
        <Languages size={13} />
        <span className="lang-picker-full-name">{activeDef.nativeName}</span>
        <span className="lang-picker-full-code">{activeDef.short}</span>
        <ChevronDown size={13} className={open ? 'lang-picker-full-chev open' : 'lang-picker-full-chev'} />
      </button>
      {open && (
        <ul id={listId} role="listbox" className="lang-picker-menu lang-picker-menu-full">
          {SUPPORTED_LANGUAGES.map(lang => {
            const selected = lang.code === activeDef.code
            return (
              <li key={lang.code} role="option" aria-selected={selected}>
                <button
                  type="button"
                  className={selected ? 'lang-picker-option active' : 'lang-picker-option'}
                  onClick={() => select(lang.code)}
                >
                  <span className="lang-picker-option-name">{lang.nativeName}</span>
                  <span className="lang-picker-option-en">{lang.englishName}</span>
                  {selected && <Check size={13} className="lang-picker-option-check" />}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
