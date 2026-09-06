/**
 * F12: Collaboration presence indicator.
 * Shows who else is viewing/editing a case right now. Sends heartbeats.
 * Plugs into Case Detail page.
 */
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Users, Circle } from 'lucide-react'
import { joinCollabRoom, collabHeartbeat, leaveCollabRoom } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { CollabPresence } from '../types'

export default function CollabPresenceIndicator({ caseId }: { caseId: string }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [presence, setPresence] = useState<CollabPresence[]>([])

  useEffect(() => {
    if (!caseId) return
    const roomId = `case:${caseId}`
    let active = true
    joinCollabRoom(roomId).then(r => { if (active) setPresence(r.presence) }).catch(() => {})
    const beat = setInterval(() => {
      collabHeartbeat(roomId).then(r => { if (active) setPresence(r.presence) }).catch(() => {})
    }, 15000) // heartbeat every 15s
    return () => {
      active = false
      clearInterval(beat)
      leaveCollabRoom(roomId).catch(() => {})
    }
  }, [caseId])

  // Filter out stale (>60s) and self
  const now = Date.now() / 1000
  const others = presence.filter(p => p.user_id !== (user?.id || user?.email) && (now - p.last_seen) < 60)

  if (others.length === 0) return null

  return (
    <div className="flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg"
      style={{ background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.2)' }}>
      <Users size={13} style={{ color: '#34D399' }} />
      <span className="text-text-secondary">
        {others.length} other {others.length === 1 ? 'investigator' : 'investigators'} viewing:
      </span>
      <div className="flex -space-x-1">
        {others.slice(0, 5).map(p => (
          <div key={p.user_id} className="relative w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold border-2"
            style={{ background: '#dc2626', borderColor: 'rgb(var(--bg-primary))', color: 'inherit' }}
            title={`${p.name} · ${p.panel || 'viewing'}`}>
            {(p.name || p.user_id || '?').charAt(0).toUpperCase()}
            <Circle size={6} className="absolute -bottom-0.5 -right-0.5 fill-green-400 text-green-400" style={{ background: 'rgb(var(--bg-primary))', borderRadius: '50%' }} />
          </div>
        ))}
      </div>
    </div>
  )
}
