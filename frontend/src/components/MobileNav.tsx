import { useState, useEffect } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Activity, Network, BellRing, FolderOpen, Menu, X,
  Shield, Waypoints, Hash, BarChart2, Sparkles, Archive, Cpu, Radar,
  Layers, Database, UserX, Users, ShieldAlert, Fingerprint, Scale, GitMerge,
  Gem, FileText, FilePlus2, LayoutDashboard,
} from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { listMonitorNotifications } from '../api/client'

/**
 * Mobile navigation: a persistent bottom tab bar with the 5 most-used destinations,
 * plus a slide-in drawer (hamburger) for the full module list.
 *
 * Only renders on screens <= 768px (CSS controls visibility). On desktop this is
 * display:none and adds zero overhead. Labels resolve through i18n so the whole
 * nav flips with the active language.
 */
export default function MobileNav() {
  const { t } = useTranslation()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const location = useLocation()
  const { user } = useAuth()

  // Close drawer on navigation
  useEffect(() => { setDrawerOpen(false) }, [location.pathname])

  // Poll unread monitor count (same as Layout, but for the badge)
  useEffect(() => {
    let active = true
    const poll = async () => {
      try {
        const notifs = await listMonitorNotifications({ unread_only: true, limit: 1 })
        if (active && Array.isArray(notifs)) setUnread(notifs.length)
      } catch { /* ignore */ }
    }
    poll()
    const iv = setInterval(poll, 30000)
    return () => { active = false; clearInterval(iv) }
  }, [])

  const primaryTabs = [
    { to: '/', icon: Activity, label: t('components:mobileNav.tabs.home'), exact: true },
    { to: '/nexus', icon: Network, label: t('components:mobileNav.tabs.nexus') },
    { to: '/monitor', icon: BellRing, label: t('components:mobileNav.tabs.alerts'), badge: unread },
    { to: '/cases', icon: FolderOpen, label: t('components:mobileNav.tabs.cases') },
  ]

  // Drawer items reuse the same nav:* keys as the desktop sidebar (Layout.tsx).
  const drawerGroups: Array<{ sectionKey: string; items: Array<{ to: string; icon: typeof Activity; labelKey: string; exact?: boolean }> }> = [
    { sectionKey: 'nav:sections.core', items: [
      { to: '/', icon: Activity, labelKey: 'nav:items.dashboard', exact: true },
      { to: '/boards', icon: LayoutDashboard, labelKey: 'nav:items.boards' },
      { to: '/nexus', icon: Network, labelKey: 'nav:items.nexus' },
      { to: '/trace', icon: Waypoints, labelKey: 'nav:items.trace' },
      { to: '/intel', icon: Shield, labelKey: 'nav:items.intel' },
      { to: '/nft-tron', icon: Gem, labelKey: 'nav:items.nftTron' },
    ]},
    { sectionKey: 'nav:sections.investigation', items: [
      { to: '/auto', icon: Sparkles, labelKey: 'nav:items.auto' },
      { to: '/entity', icon: Users, labelKey: 'nav:items.entity' },
      { to: '/tx-lens', icon: Hash, labelKey: 'nav:items.txLens' },
      { to: '/dex', icon: BarChart2, labelKey: 'nav:items.dex' },
      { to: '/monitor', icon: BellRing, labelKey: 'nav:items.monitor' },
      { to: '/evidence', icon: Archive, labelKey: 'nav:items.evidence' },
    ]},
    { sectionKey: 'nav:sections.intelligence', items: [
      { to: '/ai-agent', icon: Cpu, labelKey: 'nav:items.aiAgent' },
      { to: '/osint', icon: Radar, labelKey: 'nav:items.osint' },
      { to: '/batch', icon: Layers, labelKey: 'nav:items.batch' },
      { to: '/labels', icon: Database, labelKey: 'nav:items.labels' },
      { to: '/victim-reports', icon: UserX, labelKey: 'nav:items.victimReports' },
      { to: '/reports', icon: FileText, labelKey: 'nav:items.reports' },
    ]},
    { sectionKey: 'nav:sections.compliance', items: [
      { to: '/sanctions', icon: ShieldAlert, labelKey: 'nav:items.sanctions' },
      { to: '/attribution', icon: Fingerprint, labelKey: 'nav:items.attribution' },
      { to: '/attribution-submissions', icon: FilePlus2, labelKey: 'nav:items.submissions' },
      { to: '/regulatory', icon: Scale, labelKey: 'nav:items.regulatory' },
      { to: '/demix', icon: GitMerge, labelKey: 'nav:items.demix' },
    ]},
  ]

  return (
    <>
      {/* Backdrop */}
      <div className={`cryptx-mobile-drawer-backdrop ${drawerOpen ? 'open' : ''}`}
           onClick={() => setDrawerOpen(false)} />

      {/* Slide-in drawer with full nav */}
      <nav className={`cryptx-mobile-drawer ${drawerOpen ? 'open' : ''}`} aria-label={t('components:mobileNav.openFullMenu')}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <span style={{ color: '#dc2626', fontWeight: 700, fontSize: 18 }}>CrypTX</span>
          <button onClick={() => setDrawerOpen(false)} aria-label={t('components:mobileNav.close')}
                  style={{ background: 'none', border: 'none', color: '#9ca3af', cursor: 'pointer' }}>
            <X size={22} />
          </button>
        </div>
        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 16 }}>
          {user?.email ?? t('components:mobileNav.investigator')}
        </div>
        {drawerGroups.map(group => (
          <div key={group.sectionKey} style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 10, textTransform: 'uppercase', color: '#6b7280', letterSpacing: 1, marginBottom: 8 }}>
              {t(group.sectionKey)}
            </div>
            {group.items.map(item => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.exact}
                style={({ isActive }) => ({
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '10px 8px', borderRadius: 8, textDecoration: 'none',
                  color: isActive ? '#dc2626' : '#d1d5db',
                  background: isActive ? 'rgba(220,38,38,0.1)' : 'transparent',
                  fontSize: 14,
                })}
              >
                <item.icon size={18} />
                {t(item.labelKey)}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* Bottom tab bar */}
      <nav className="cryptx-mobile-nav" aria-label={t('components:mobileNav.menu')}>
        {primaryTabs.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.exact}
            className={({ isActive }) => `cryptx-mobile-nav-item ${isActive ? 'active' : ''}`}
            style={{ position: 'relative' }}
          >
            <item.icon />
            <span>{item.label}</span>
            {item.badge ? <span className="cryptx-mobile-nav-badge">{item.badge > 99 ? '99+' : item.badge}</span> : null}
          </NavLink>
        ))}
        {/* Hamburger → opens drawer */}
        <button className="cryptx-mobile-nav-item" onClick={() => setDrawerOpen(true)} aria-label={t('components:mobileNav.openFullMenu')}>
          <Menu />
          <span>{t('components:mobileNav.menu')}</span>
        </button>
      </nav>
    </>
  )
}
