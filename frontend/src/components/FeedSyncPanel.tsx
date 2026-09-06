/**
 * F4: Sanctions & Threat-Feed Sync panel.
 * Shows feed freshness, lets you manually sync, and surfaces diff-alerts
 * (newly-designated addresses matching your open cases).
 * Plugs into the Sanctions Screener page.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { RefreshCw, Loader2, AlertTriangle, CheckCircle, Database, Bell } from 'lucide-react'
import { syncFeeds, feedStatus, feedDiffAlerts, reviewFeedDiffAlert } from '../api/client'

export default function FeedSyncPanel() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { data: statusData } = useQuery({ queryKey: ['feed-status'], queryFn: feedStatus })
  const { data: alertsData } = useQuery({ queryKey: ['feed-diff-alerts'], queryFn: () => feedDiffAlerts({ reviewed: false, limit: 20 }) })

  const syncMut = useMutation({
    mutationFn: syncFeeds,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['feed-status'] }); qc.invalidateQueries({ queryKey: ['feed-diff-alerts'] }) },
  })
  const reviewMut = useMutation({
    mutationFn: (id: string) => reviewFeedDiffAlert(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['feed-diff-alerts'] }),
  })

  const feeds = statusData?.feeds || []
  const alerts = alertsData?.alerts || []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="card-title flex items-center gap-2"><Database size={15} /> Sanctions &amp; Threat Feeds</h3>
        <button onClick={() => syncMut.mutate()} disabled={syncMut.isPending} className="btn-primary text-xs">
          {syncMut.isPending ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          Sync Now
        </button>
      </div>

      {/* Feed status */}
      <div className="space-y-2">
        {feeds.map(f => (
          <div key={f.feed_id} className="flex items-center justify-between card-cyber py-2 text-xs">
            <div>
              <div className="font-bold" style={{ color: '#fff2f4' }}>{f.feed_name}</div>
              <div className="text-text-muted text-[10px]">
                {f.record_count} records · {f.new_count} new last sync
              </div>
            </div>
            <div className="flex items-center gap-2">
              {f.last_status === 'ok'
                ? <CheckCircle size={14} style={{ color: '#34D399' }} />
                : <AlertTriangle size={14} style={{ color: '#F87171' }} />}
              <span className="text-text-muted text-[10px]">
                {f.last_synced ? new Date(f.last_synced).toLocaleDateString() : 'never'}
              </span>
            </div>
          </div>
        ))}
        {feeds.length === 0 && <p className="text-text-muted text-xs">No feeds synced yet. Click "Sync Now".</p>}
      </div>

      {/* Diff alerts */}
      {alerts.length > 0 && (
        <div>
          <h4 className="text-xs uppercase tracking-wider text-neon-red flex items-center gap-1 mb-2">
            <Bell size={12} /> {alerts.length} New Designations Match Your Cases
          </h4>
          <div className="space-y-1">
            {alerts.map(a => (
              <div key={a.id} className="flex items-center justify-between text-xs py-1.5 px-2 rounded border border-neon-red/20"
                style={{ background: 'rgba(220,38,38,0.05)' }}>
                <div>
                  <span className="font-mono">{a.address.slice(0, 18)}…</span>
                  <span className="ml-2 text-text-muted">{a.entity}</span>
                </div>
                <button onClick={() => reviewMut.mutate(a.id)} className="btn-ghost text-[10px]">Acknowledge</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
