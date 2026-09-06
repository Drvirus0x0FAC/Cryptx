import { useState, useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Activity, Archive, BarChart2, BellRing, Bell,
  Cpu, Database, Fingerprint, FolderOpen, Gem, GitBranch, GitMerge, Hash, Layers, Network,
  Scale, Search, Settings, Shield, ShieldAlert, UserX, Users, Waypoints, Moon, Sun, Wifi, WifiOff,
  LogOut, UserRound, Sparkles, ChevronDown, AlignJustify, List, LayoutDashboard, Radar, FilePlus2,
  Newspaper, FileText, FileCode2, Droplets, Snowflake, Gavel,
  Landmark, Radio, Bug, CandlestickChart, BrainCircuit, CheckCheck, MessageSquare, UserPlus,
} from 'lucide-react'
import { healthCheck, listMonitorNotifications, listNotifications, getUnreadNotificationCount, markNotificationRead, markAllNotificationsRead, type UserNotification } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import CommandPalette from './CommandPalette'
import LanguagePicker from './LanguagePicker'
import HelpOverlay from './HelpOverlay'
import FloatingHelpButton from './FloatingHelpButton'
import { useFormat } from '../i18n/format'

/* ── Navigation ──────────────────────────────────────────────────────────────
 * Labels are stored as i18n keys (under the `nav` namespace) and resolved to
 * the active language at render time via `t()`. This keeps the static nav
 * structure stable while letting the whole UI flip languages instantly.
 */
type NavItem = { to: string; icon: typeof Activity; key: string; exact?: boolean; badge?: boolean }

const NAV_GROUPS: Array<{ sectionKey: string; items: NavItem[] }> = [
  {
    sectionKey: 'nav:sections.core',
    items: [
      { to: '/',         icon: Activity,   key: 'nav:items.dashboard',      exact: true },
      { to: '/boards',   icon: LayoutDashboard, key: 'nav:items.boards' },
      { to: '/nexus',    icon: Network,    key: 'nav:items.nexus' },
      { to: '/trace',    icon: Waypoints,  key: 'nav:items.trace' },
      { to: '/intel',    icon: Shield,     key: 'nav:items.intel' },
      { to: '/nft-tron', icon: Gem,        key: 'nav:items.nftTron' },
    ],
  },
  {
    sectionKey: 'nav:sections.investigation',
    items: [
      { to: '/auto',     icon: Sparkles,   key: 'nav:items.auto' },
      { to: '/entity',   icon: Users,      key: 'nav:items.entity' },
      { to: '/tx-lens',  icon: Hash,       key: 'nav:items.txLens' },
      { to: '/dex',      icon: BarChart2,  key: 'nav:items.dex' },
      { to: '/perp-dex', icon: CandlestickChart, key: 'nav:items.perpDex' },
      { to: '/monitor',  icon: BellRing,   key: 'nav:items.monitor',   badge: true },
      { to: '/evidence', icon: Archive,    key: 'nav:items.evidence' },
    ],
  },
  {
    sectionKey: 'nav:sections.intelligence',
    items: [
      { to: '/predictive',     icon: BrainCircuit, key: 'nav:items.predictive' },
      { to: '/ai-agent',       icon: Cpu,        key: 'nav:items.aiAgent' },
      { to: '/osint',          icon: Radar,      key: 'nav:items.osint' },
      { to: '/cases',          icon: FolderOpen, key: 'nav:items.cases' },
      { to: '/batch',          icon: Layers,     key: 'nav:items.batch' },
      { to: '/labels',         icon: Database,   key: 'nav:items.labels' },
      { to: '/victim-reports', icon: UserX,      key: 'nav:items.victimReports' },
      { to: '/scam-atlas',     icon: Bug,        key: 'nav:items.scamAtlas' },
      { to: '/reports',        icon: FileText,   key: 'nav:items.reports' },
    ],
  },
  {
    sectionKey: 'nav:sections.compliance',
    items: [
      { to: '/sanctions',   icon: ShieldAlert,  key: 'nav:items.sanctions' },
      { to: '/attribution', icon: Fingerprint,  key: 'nav:items.attribution' },
      { to: '/attribution-submissions', icon: FilePlus2, key: 'nav:items.submissions' },
      { to: '/regulatory',  icon: Scale,        key: 'nav:items.regulatory' },
      { to: '/demix',       icon: GitMerge,     key: 'nav:items.demix' },
      { to: '/comply',      icon: Landmark,     key: 'nav:items.comply' },
    ],
  },
  {
    sectionKey: 'nav:sections.advanced',
    items: [
      { to: '/contract-forensics', icon: FileCode2, key: 'nav:items.contractForensics' },
      { to: '/laundering',         icon: Droplets,  key: 'nav:items.laundering' },
      { to: '/court-readiness',    icon: Gavel,     key: 'nav:items.courtReadiness' },
      { to: '/recovery',           icon: Snowflake, key: 'nav:items.recovery' },
      { to: '/freeze-desk',        icon: Radio,     key: 'nav:items.freezeDesk' },
    ],
  },
]

const ALL_ITEMS = NAV_GROUPS.flatMap(g => g.items)

/* ── Isolated live clock (P9 fix) ─────────────────────────────────────────────
 * Extracted so the per-second tick only re-renders THIS component, not the entire
 * Layout top bar (which was causing a full nav re-render every second).
 *
 * Time formatting follows the active language locale (fr-FR → "14:05:09",
 * en-US → "14:05:09", zh-CN → "14:05:09") via the format helper. The locale is
 * pulled from useFormat() so a language switch re-binds the clock instantly.
 */
function LiveClock() {
  const { formatTime } = useFormat()
  const [time, setTime] = useState('')
  useEffect(() => {
    const tick = () => setTime(formatTime(new Date()))
    tick()
    const iv = setInterval(tick, 1000)
    return () => clearInterval(iv)
  }, [formatTime])
  return <>{time}</>
}

/* ── Component ─────────────────────────────────────────────────────────────── */
export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const [theme, setTheme] = useState<'dark' | 'light'>(() =>
    (typeof window !== 'undefined' ? localStorage.getItem('theme') as 'dark' | 'light' : null) ?? 'dark'
  )
  const [density, setDensity] = useState<'comfortable' | 'compact'>(() =>
    (typeof window !== 'undefined' ? localStorage.getItem('density') as 'comfortable' | 'compact' : null) ?? 'comfortable'
  )
  const [apiOk, setApiOk]       = useState<boolean | null>(null)
  const [search, setSearch]     = useState('')
  const [unread, setUnread]     = useState(0)
  const [islandOpen, setIslandOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const islandCloseTimer = useRef<ReturnType<typeof window.setTimeout> | null>(null)
  const { user, signOut } = useAuth()

  /* ── Notification bell state ── */
  const [notifOpen, setNotifOpen]   = useState(false)
  const [notifList, setNotifList]   = useState<UserNotification[]>([])
  const [notifCount, setNotifCount] = useState(0)
  const notifRef = useRef<HTMLDivElement>(null)

  const navigate   = useNavigate()
  const location   = useLocation()

  /* ── Theme ── */
  useEffect(() => {
    document.documentElement.classList.toggle('light', theme === 'light')
    localStorage.setItem('theme', theme)
  }, [theme])

  /* ── Table density (comfortable / compact) ── */
  useEffect(() => {
    document.documentElement.setAttribute('data-density', density)
    localStorage.setItem('density', density)
  }, [density])

  useEffect(() => {
    if (islandCloseTimer.current) window.clearTimeout(islandCloseTimer.current)
    setIslandOpen(false)
  }, [location.pathname])

  useEffect(() => () => {
    if (islandCloseTimer.current) window.clearTimeout(islandCloseTimer.current)
  }, [])

  /* ── Health ── */
  useEffect(() => {
    healthCheck().then(setApiOk)
    const iv = setInterval(() => healthCheck().then(setApiOk), 30_000)
    return () => clearInterval(iv)
  }, [])

  /* ── Monitor badge ── */
  useEffect(() => {
    const load = () =>
      listMonitorNotifications({ unread_only: true, limit: 100 })
        .then(n => setUnread(n.length)).catch(() => undefined)
    load()
    const iv = setInterval(load, 15_000)
    return () => clearInterval(iv)
  }, [])

  /* ── Notification polling ── */
  useEffect(() => {
    const poll = () => {
      getUnreadNotificationCount().then(setNotifCount).catch(() => undefined)
    }
    poll()
    const iv = setInterval(poll, 10_000)
    return () => clearInterval(iv)
  }, [])

  /* ── Close notification dropdown on outside click ── */
  useEffect(() => {
    if (!notifOpen) return
    function handleClick(e: MouseEvent) {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setNotifOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [notifOpen])

  async function openNotifPanel() {
    setNotifOpen(o => !o)
    if (!notifOpen) {
      try {
        const list = await listNotifications({ limit: 50 })
        setNotifList(list)
      } catch { /* ignore */ }
    }
  }

  async function handleNotifClick(n: UserNotification) {
    if (!n.is_read) {
      await markNotificationRead(n.id).catch(() => undefined)
      setNotifList(prev => prev.map(x => x.id === n.id ? { ...x, is_read: 1 } : x))
      setNotifCount(c => Math.max(0, c - 1))
    }
    setNotifOpen(false)
    if (n.case_id && n.task_id) {
      navigate(`/cases/${n.case_id}/tasks`)
    } else if (n.case_id) {
      navigate(`/cases/${n.case_id}`)
    }
  }

  async function handleMarkAllRead() {
    await markAllNotificationsRead().catch(() => undefined)
    setNotifList(prev => prev.map(x => ({ ...x, is_read: 1 })))
    setNotifCount(0)
  }

  /* ── Clock moved to isolated <LiveClock /> component (P9 perf fix) ── */

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    const q = search.trim()
    if (!q) return
    navigate(`/intel?address=${encodeURIComponent(q)}`)
    setSearch('')
  }

  function openIsland() {
    if (islandCloseTimer.current) window.clearTimeout(islandCloseTimer.current)
    setIslandOpen(true)
  }

  function scheduleIslandClose() {
    if (islandCloseTimer.current) window.clearTimeout(islandCloseTimer.current)
    islandCloseTimer.current = window.setTimeout(() => setIslandOpen(false), 1200)
  }

  const active = ALL_ITEMS.find(item =>
    item.exact ? location.pathname === item.to : location.pathname.startsWith(item.to)
  )

  const statusColor = apiOk === null
    ? 'rgb(var(--text-muted))'
    : apiOk ? 'rgb(var(--accent-green))' : 'rgb(var(--accent-red))'

  const quickItems = ALL_ITEMS.filter(item =>
    ['/', '/nexus', '/intel', '/tx-lens', '/monitor', '/ai-agent'].includes(item.to)
  )

  return (
    <div className="app-shell">
      <header className="app-topbar command-topbar">
        <div className="topbar-logo">
          <img
            src="/cryptx-logo-full.png"
            alt="CrypTX"
            height={46}
            style={{ display: 'block', width: 'auto', height: 46, objectFit: 'contain', flexShrink: 0, filter: 'drop-shadow(0 0 8px rgba(255,255,255,0.14))' }}
          />
          <div className="topbar-logo-text">
            <span style={{ fontFamily: "'Roboto',sans-serif", fontWeight: 700, fontSize: '1.2rem', color: 'rgb(var(--text-bright))', lineHeight: 1, whiteSpace: 'nowrap' }}>
              Cryp<span style={{ color: 'rgb(var(--accent-red))' }}>TX</span>
            </span>
            <span style={{ fontFamily: "'Roboto', sans-serif", fontWeight: 100, fontSize: '0.55rem', color: 'rgb(var(--text-muted))', letterSpacing: '0.1em', textTransform: 'uppercase', lineHeight: 1, whiteSpace: 'nowrap', marginTop: '5px' }}>
              {t('common:brand.tagline')}
            </span>
          </div>
        </div>

        <div
          className={islandOpen ? 'module-island-wrap open' : 'module-island-wrap'}
          onMouseEnter={openIsland}
          onMouseLeave={scheduleIslandClose}
        >
          <div className="module-island">
            <span className="module-island-pulse" />
            <button
              type="button"
              className="module-island-trigger"
              onClick={() => setIslandOpen(o => !o)}
              aria-expanded={islandOpen}
            >
              {active ? <active.icon size={16} /> : <Sparkles size={16} />}
              <span className="module-island-title">{active ? t(active.key) : t('nav:quick.workspace')}</span>
            </button>
            <div className="module-island-quick">
              {quickItems.slice(0, 5).map(({ to, icon: Icon, key, exact, badge }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={exact}
                  className={({ isActive }) => isActive ? 'module-island-icon active' : 'module-island-icon'}
                  title={t(key)}
                >
                  <Icon size={13} />
                  {badge && unread > 0 && <i />}
                </NavLink>
              ))}
            </div>
            <button type="button" className="module-island-more" onClick={() => setIslandOpen(o => !o)} aria-label={t('nav:quick.openPalette')}>
              <ChevronDown size={14} className="module-island-chevron" />
            </button>
          </div>

          <div className="module-palette">
            <div className="module-palette-head">
              <span><Sparkles size={14} /> {t('layout:island.missionModules')}</span>
              <small>{t('layout:island.toolsCount', { count: ALL_ITEMS.length })}</small>
            </div>
            <div className="module-palette-grid">
              {NAV_GROUPS.map((group) => (
                <section key={group.sectionKey}>
                  <p>{t(group.sectionKey)}</p>
                  {group.items.map(({ to, icon: Icon, key, exact, badge }) => (
                    <NavLink
                      key={to}
                      to={to}
                      end={exact}
                      className={({ isActive }) => isActive ? 'palette-link active' : 'palette-link'}
                    >
                      <span><Icon size={15} /></span>
                      <b>{t(key)}</b>
                      {badge && unread > 0 && <i>{unread}</i>}
                    </NavLink>
                  ))}
                </section>
              ))}
            </div>
          </div>
        </div>

        <form onSubmit={handleSearch} className="topbar-search">
          <Search size={14} strokeWidth={2} style={{ color: 'rgb(var(--text-muted))', flexShrink: 0 }} />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder={t('layout:topbar.searchPlaceholder')}
          />
          <kbd>{search ? t('layout:topbar.searchKbdEnter') : t('layout:topbar.searchKbdHint')}</kbd>
        </form>

        <div className="topbar-right">
          <NavLink
            to="/threat-landscape"
            className={({ isActive }) => isActive ? 'topbar-threat active' : 'topbar-threat'}
            title={t('layout:topbar.threatLandscapeTitle')}
          >
            <Newspaper size={14} strokeWidth={2} />
            <span className="topbar-threat-label">{t('layout:topbar.threatLandscape')}</span>
            <i className="topbar-threat-live" />
          </NavLink>
          {active && (
            <div className="topbar-chip" style={{ borderColor: 'rgb(var(--accent-blue) / 0.3)', color: 'rgb(var(--accent-blue))' }}>
              <active.icon size={10} strokeWidth={2} />
              <span style={{ fontFamily: 'inherit' }}>{t(active.key)}</span>
            </div>
          )}
          <div className="topbar-chip">
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: statusColor, display: 'inline-block', flexShrink: 0 }} />
            {apiOk === null ? t('common:status.sync') : apiOk ? t('common:status.online') : t('common:status.offline')}
            {apiOk ? <Wifi size={10} strokeWidth={2} style={{ opacity: 0.5 }} /> : <WifiOff size={10} strokeWidth={2} style={{ opacity: 0.5 }} />}
          </div>
          <div className="topbar-chip" style={{ fontFamily: "'Roboto Mono',monospace" }}>
            <LiveClock />
          </div>

          {/* ── Notification Bell ── */}
          <div ref={notifRef} style={{ position: 'relative' }}>
            <button
              className="topbar-icon-btn"
              onClick={openNotifPanel}
              title={t('layout:notifications.tooltip')}
              style={{ position: 'relative' }}
            >
              <Bell size={15} strokeWidth={1.75} />
              {notifCount > 0 && (
                <span style={{
                  position: 'absolute', top: -4, right: -6,
                  background: 'rgb(var(--accent-red, 255 82 82))',
                  color: '#fff', fontSize: 9, fontWeight: 700,
                  minWidth: 16, height: 16, borderRadius: 8,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  padding: '0 4px', lineHeight: 1,
                  boxShadow: '0 0 6px rgb(var(--accent-red, 255 82 82) / 0.5)',
                }}>
                  {notifCount > 99 ? '99+' : notifCount}
                </span>
              )}
              <span className="nav-tip">{t('layout:notifications.tooltip')}</span>
            </button>

            {notifOpen && (
              <div style={{
                position: 'absolute', top: 'calc(100% + 8px)', right: 0,
                width: 360, maxHeight: 480,
                background: 'rgb(var(--bg-card, 18 22 30))',
                border: '1px solid rgb(var(--bg-border, 40 44 55) / 0.6)',
                borderRadius: 12, boxShadow: '0 16px 48px rgb(0 0 0 / 0.5)',
                display: 'flex', flexDirection: 'column',
                zIndex: 9999, overflow: 'hidden',
              }}>
                {/* Header */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '12px 16px', borderBottom: '1px solid rgb(var(--bg-border, 40 44 55) / 0.4)',
                }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'rgb(var(--text-primary))' }}>
                    {t('layout:notifications.title')}
                    {notifCount > 0 && (
                      <span style={{
                        marginLeft: 6, fontSize: 10, padding: '1px 6px', borderRadius: 6,
                        background: 'rgb(var(--accent-red, 255 82 82) / 0.15)',
                        color: 'rgb(var(--accent-red, 255 82 82))',
                      }}>{t('layout:notifications.newBadge', { count: notifCount })}</span>
                    )}
                  </span>
                  {notifList.some(n => !n.is_read) && (
                    <button
                      onClick={handleMarkAllRead}
                      style={{
                        background: 'none', border: 'none', cursor: 'pointer',
                        fontSize: 11, color: 'rgb(var(--accent-blue, 56 224 255))',
                        display: 'flex', alignItems: 'center', gap: 4,
                      }}
                    >
                      <CheckCheck size={12} /> {t('layout:notifications.markAllRead')}
                    </button>
                  )}
                </div>

                {/* List */}
                <div style={{ flex: 1, overflowY: 'auto', maxHeight: 400 }}>
                  {notifList.length === 0 ? (
                    <div style={{
                      padding: 32, textAlign: 'center',
                      color: 'rgb(var(--text-muted))', fontSize: 12,
                    }}>
                      <Bell size={24} style={{ opacity: 0.3, marginBottom: 8 }} />
                      <p>{t('layout:notifications.empty')}</p>
                    </div>
                  ) : (
                    notifList.map(n => {
                      const Icon = n.type === 'task_reply' ? MessageSquare
                        : n.type === 'task_assigned' ? UserPlus
                        : Bell
                      return (
                        <button
                          key={n.id}
                          onClick={() => handleNotifClick(n)}
                          style={{
                            display: 'flex', gap: 10, width: '100%', padding: '10px 16px',
                            background: n.is_read ? 'transparent' : 'rgb(var(--accent-blue, 56 224 255) / 0.04)',
                            border: 'none', borderBottom: '1px solid rgb(var(--bg-border, 40 44 55) / 0.2)',
                            cursor: 'pointer', textAlign: 'left', transition: 'background 0.15s',
                          }}
                          onMouseEnter={e => (e.currentTarget.style.background = 'rgb(255 255 255 / 0.04)')}
                          onMouseLeave={e => (e.currentTarget.style.background = n.is_read ? 'transparent' : 'rgb(var(--accent-blue, 56 224 255) / 0.04)')}
                        >
                          <div style={{
                            width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                            background: n.type === 'task_reply' ? 'rgb(var(--accent-blue, 56 224 255) / 0.12)'
                              : n.type === 'task_assigned' ? 'rgb(245 158 11 / 0.12)' : 'rgb(var(--bg-border, 40 44 55) / 0.3)',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                          }}>
                            <Icon size={14} style={{
                              color: n.type === 'task_reply' ? 'rgb(var(--accent-blue, 56 224 255))'
                                : n.type === 'task_assigned' ? '#F59E0B' : 'rgb(var(--text-muted))',
                            }} />
                          </div>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{
                              fontSize: 12, fontWeight: n.is_read ? 500 : 700,
                              color: 'rgb(var(--text-primary))',
                              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                            }}>
                              {!n.is_read && <span style={{
                                display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
                                background: 'rgb(var(--accent-blue, 56 224 255))', marginRight: 6,
                                verticalAlign: 'middle',
                              }} />}
                              {n.title}
                            </div>
                            {n.message && (
                              <div style={{
                                fontSize: 11, color: 'rgb(var(--text-muted))',
                                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                marginTop: 2,
                              }}>
                                {n.message}
                              </div>
                            )}
                            <div style={{ fontSize: 10, color: 'rgb(var(--text-muted))', marginTop: 3, opacity: 0.7 }}>
                              {new Date(n.created_at).toLocaleString()}
                            </div>
                          </div>
                        </button>
                      )
                    })
                  )}
                </div>
              </div>
            )}
          </div>

          <button className="topbar-icon-btn" onClick={() => setDensity(d => d === 'compact' ? 'comfortable' : 'compact')}>
            {density === 'compact' ? <List size={15} strokeWidth={1.75} /> : <AlignJustify size={15} strokeWidth={1.75} />}
            <span className="nav-tip">{density === 'compact' ? t('layout:topbar.densityComfortable') : t('layout:topbar.densityCompact')}</span>
          </button>
          <button className="topbar-icon-btn" onClick={() => setTheme(prev => prev === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? <Sun size={15} strokeWidth={1.75} /> : <Moon size={15} strokeWidth={1.75} />}
            <span className="nav-tip">{theme === 'dark' ? t('layout:topbar.themeLight') : t('layout:topbar.themeDark')}</span>
          </button>
          <LanguagePicker variant="compact" />
          <NavLink to="/settings" className="topbar-icon-btn" title={t('layout:topbar.settings')}>
            <Settings size={15} strokeWidth={1.75} />
            <span className="nav-tip">{t('layout:topbar.settings')}</span>
          </NavLink>
          {user?.registration_type === 'team_leader' && (
            <NavLink to="/team" className="topbar-icon-btn" title={t('nav:items.team')}>
              <Users size={15} strokeWidth={1.75} />
              <span className="nav-tip">{t('nav:items.team')}</span>
            </NavLink>
          )}
          <NavLink
            to="/profile"
            className={({ isActive }) => isActive ? 'topbar-chip' : 'topbar-chip'}
            style={({ isActive }) => ({
              borderColor: isActive ? 'rgb(var(--accent-blue) / 0.35)' : 'rgb(var(--bg-border) / 0.6)',
              color: isActive ? 'rgb(var(--accent-blue))' : 'rgb(var(--text-secondary))',
              textDecoration: 'none',
              maxWidth: 190,
            })}
            title={user?.email || t('layout:topbar.userProfile')}
          >
            <UserRound size={11} strokeWidth={2} />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {user?.name || user?.email || t('layout:topbar.profile')}
            </span>
          </NavLink>
          <button className="topbar-icon-btn" onClick={() => void signOut()} title={t('layout:topbar.logoutTitle')}>
            <LogOut size={15} strokeWidth={1.75} />
            <span className="nav-tip">{t('layout:topbar.logout')}</span>
          </button>
        </div>
      </header>

      {/* Content */}
      <main className="app-content app-content-bg page-enter" key={location.pathname}>
        <div className="cyber-ambient" aria-hidden="true">
          <span className="cyber-orbit orbit-a" />
          <span className="cyber-orbit orbit-b" />
          <span className="cyber-orbit orbit-c" />
          <span className="cyber-flow flow-a" />
          <span className="cyber-flow flow-b" />
          <span className="cyber-flow flow-c" />
          <span className="cyber-packet packet-a" />
          <span className="cyber-packet packet-b" />
          <span className="cyber-packet packet-c" />
          <span className="cyber-scan" />
          <div className="cyber-hash-console">
            <span>0x71c9...af32</span>
            <span>bc1q9f...4e2a</span>
            <span>{t('layout:ambient.txBridgeHop')}</span>
            <span>{t('layout:ambient.mixerExposure')}</span>
            <span>{t('layout:ambient.ofacClear')}</span>
          </div>
          <div className="cyber-crypto-stack">
            <div className="crypto-card btc"><b>BTC</b><span>{t('layout:ambient.btcClusterRisk')} 77</span></div>
            <div className="crypto-card eth"><b>ETH</b><span>{t('layout:ambient.ethBridgePath')}</span></div>
            <div className="crypto-card xmr"><b>XMR</b><span>{t('layout:ambient.xmrMixerWatch')}</span></div>
          </div>
          <div className="cyber-candle-panel">
            {Array.from({ length: 16 }).map((_, i) => <span key={i} />)}
          </div>
          <div className="cyber-case-panel">
            <div><b>{t('layout:ambient.amlTrace')}</b><span>{t('layout:ambient.amlCaseScore', { score: 91 })}</span></div>
            <div><b>{t('layout:ambient.chainSwap')}</b><span>{t('layout:ambient.chainSwapPath')}</span></div>
            <div><b>{t('layout:ambient.walletLink')}</b><span>{t('layout:ambient.hopsCount', { count: 7 })}</span></div>
          </div>
          <div className="cyber-radar-panel">
            <span className="radar-ring ring-1" />
            <span className="radar-ring ring-2" />
            <span className="radar-ring ring-3" />
            <span className="radar-sweep" />
            <b>TX</b>
          </div>
          <div className="cyber-hex-chain">
            <span /><span /><span /><span /><span />
          </div>
          <div className="cyber-symbol-cloud">
            <span className="symbol-btc">BTC</span>
            <span className="symbol-eth">ETH</span>
            <span className="symbol-aml">AML</span>
            <span className="symbol-key">0x</span>
            <span className="symbol-case">CASE</span>
          </div>
          <div className="cyber-ticker">
            <span>{t('layout:ambient.ticker.txTrace')}</span><span>{t('layout:ambient.ticker.amlScreen')}</span><span>{t('layout:ambient.ticker.chainSwap')}</span><span>{t('layout:ambient.ticker.mixerWatch')}</span><span>{t('layout:ambient.ticker.riskNode')}</span><span>{t('layout:ambient.ticker.caseVault')}</span>
            <span>{t('layout:ambient.ticker.txTrace')}</span><span>{t('layout:ambient.ticker.amlScreen')}</span><span>{t('layout:ambient.ticker.chainSwap')}</span><span>{t('layout:ambient.ticker.mixerWatch')}</span><span>{t('layout:ambient.ticker.riskNode')}</span><span>{t('layout:ambient.ticker.caseVault')}</span>
          </div>
        </div>
        {children}
      </main>

      {/* Ctrl+K command palette - address/tx paste-and-go + module search.
          Passes i18n keys so CommandPalette can resolve labels at render time. */}
      <CommandPalette
        navItems={NAV_GROUPS.flatMap(g => g.items.map(i => ({ to: i.to, labelKey: i.key, icon: i.icon, sectionKey: g.sectionKey })))}
      />

      {/* Cinematic "How to use?" help overlay */}
      <FloatingHelpButton onClick={() => setHelpOpen(true)} />
      <HelpOverlay isOpen={helpOpen} onClose={() => setHelpOpen(false)} pathname={location.pathname} />
    </div>
  )
}
