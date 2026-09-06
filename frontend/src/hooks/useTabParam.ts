import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Tab state persisted in the URL (?tab=...) so analysts can deep-link and
 * share exact views into a case. Falls back to defaultTab when the param is
 * missing or not in the valid set.
 */
export function useTabParam<T extends string>(defaultTab: T, valid: readonly T[]) {
  const [searchParams, setSearchParams] = useSearchParams()
  const raw = searchParams.get('tab')
  const active = (raw && (valid as readonly string[]).includes(raw) ? raw : defaultTab) as T

  const setActive = useCallback(
    (tab: T) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (tab === defaultTab) next.delete('tab')
          else next.set('tab', tab)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams, defaultTab],
  )

  return [active, setActive] as const
}
