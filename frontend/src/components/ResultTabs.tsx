import type { LucideIcon } from 'lucide-react'

export interface ResultTabDef<T extends string = string> {
  id: T
  label: string
  icon?: LucideIcon
  /** Optional badge count - tells analysts which tabs are worth opening. */
  count?: number
}

/**
 * Standard sticky result-tab strip used by every investigation result screen.
 * Pair with useTabParam() so the active tab is persisted in the URL.
 */
export default function ResultTabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: ResultTabDef<T>[]
  active: T
  onChange: (tab: T) => void
}) {
  return (
    <div className="result-tabs">
      {tabs.map(({ id, label, icon: Icon, count }) => (
        <button
          key={id}
          type="button"
          className={active === id ? 'active' : ''}
          onClick={() => onChange(id)}
        >
          {Icon && <Icon size={14} />}
          {label}
          {count != null && count > 0 && <span className="tab-count">{count > 99 ? '99+' : count}</span>}
        </button>
      ))}
    </div>
  )
}
