/**
 * F1: Alert Delivery Channels — webhook / email / Telegram / SSE config panel.
 * Plugs into the Wallet Monitor page.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Send, Trash2, Plus, Loader2, Bell, Webhook, Mail, MessageCircle } from 'lucide-react'
import {
  listAlertDestinations, createAlertDestination, toggleAlertDestination,
  deleteAlertDestination, listAlertDeliveries,
} from '../api/client'
import type { AlertDestination } from '../types'

const KIND_ICON: Record<string, React.ReactNode> = {
  webhook: <Webhook size={13} />,
  email: <Mail size={13} />,
  telegram: <MessageCircle size={13} />,
  sse: <Bell size={13} />,
  inapp: <Bell size={13} />,
}

export default function DeliveryChannels() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [newDest, setNewDest] = useState<{ name: string; kind: 'webhook' | 'email' | 'telegram' | 'sse'; url: string; secret: string; chat_id: string; bot_token: string; to_addr: string; smtp_host: string }>({ name: '', kind: 'webhook', url: '', secret: '', chat_id: '', bot_token: '', to_addr: '', smtp_host: '' })

  const { data, isLoading } = useQuery({
    queryKey: ['alert-destinations'],
    queryFn: listAlertDestinations,
  })
  const { data: delivData } = useQuery({
    queryKey: ['alert-deliveries'],
    queryFn: () => listAlertDeliveries(20),
  })

  const createMut = useMutation({
    mutationFn: () => {
      const config: Record<string, unknown> = {}
      if (newDest.kind === 'webhook') { config.url = newDest.url; config.secret = newDest.secret }
      else if (newDest.kind === 'telegram') { config.chat_id = newDest.chat_id; config.bot_token = newDest.bot_token }
      else if (newDest.kind === 'email') { config.to_addr = newDest.to_addr; config.smtp_host = newDest.smtp_host }
      return createAlertDestination({ name: newDest.name, kind: newDest.kind, config })
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['alert-destinations'] }); setShowForm(false); setNewDest({ name: '', kind: 'webhook', url: '', secret: '', chat_id: '', bot_token: '', to_addr: '', smtp_host: '' }) },
  })
  const delMut = useMutation({ mutationFn: (id: string) => deleteAlertDestination(id), onSuccess: () => qc.invalidateQueries({ queryKey: ['alert-destinations'] }) })
  const togMut = useMutation({ mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => toggleAlertDestination(id, enabled), onSuccess: () => qc.invalidateQueries({ queryKey: ['alert-destinations'] }) })

  const dests = data?.destinations || []
  const deliveries = delivData?.deliveries || []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="card-title">Delivery Channels</h3>
        <button onClick={() => setShowForm(!showForm)} className="btn-primary text-xs">
          <Plus size={12} /> Add Channel
        </button>
      </div>

      {showForm && (
        <div className="card-cyber space-y-2 animate-slide-up">
          <input value={newDest.name} onChange={e => setNewDest({ ...newDest, name: e.target.value })} placeholder="Channel name (e.g. SOC Webhook)" className="input" />
          <select value={newDest.kind} onChange={e => setNewDest({ ...newDest, kind: e.target.value as 'webhook' | 'email' | 'telegram' | 'sse' })} className="input">
            <option value="webhook">Webhook (HTTP POST)</option>
            <option value="telegram">Telegram Bot</option>
            <option value="email">Email (SMTP)</option>
            <option value="sse">Browser SSE only</option>
          </select>
          {newDest.kind === 'webhook' && (
            <>
              <input value={newDest.url} onChange={e => setNewDest({ ...newDest, url: e.target.value })} placeholder="https://your-endpoint.com/alerts" className="input font-mono text-xs" />
              <input value={newDest.secret} onChange={e => setNewDest({ ...newDest, secret: e.target.value })} placeholder="HMAC secret (optional, for signature)" className="input font-mono text-xs" />
            </>
          )}
          {newDest.kind === 'telegram' && (
            <>
              <input value={newDest.bot_token} onChange={e => setNewDest({ ...newDest, bot_token: e.target.value })} placeholder="Bot token (123456:ABC...)" className="input font-mono text-xs" />
              <input value={newDest.chat_id} onChange={e => setNewDest({ ...newDest, chat_id: e.target.value })} placeholder="Chat ID (e.g. -1001234567890)" className="input font-mono text-xs" />
            </>
          )}
          {newDest.kind === 'email' && (
            <>
              <input value={newDest.to_addr} onChange={e => setNewDest({ ...newDest, to_addr: e.target.value })} placeholder="alerts@yourorg.com" className="input" />
              <input value={newDest.smtp_host} onChange={e => setNewDest({ ...newDest, smtp_host: e.target.value })} placeholder="SMTP host (smtp.gmail.com)" className="input" />
            </>
          )}
          <button onClick={() => createMut.mutate()} disabled={!newDest.name.trim() || createMut.isPending} className="btn-primary">
            {createMut.isPending && <Loader2 size={12} className="animate-spin" />} Create Channel
          </button>
        </div>
      )}

      {/* Destinations list */}
      {isLoading ? <Loader2 className="animate-spin" size={20} /> : (
        <div className="space-y-2">
          {dests.map((d: AlertDestination) => (
            <div key={d.id} className="flex items-center gap-3 card-cyber py-2">
              <span style={{ color: d.enabled ? '#34D399' : '#6b7280' }}>{KIND_ICON[d.kind]}</span>
              <div className="flex-1">
                <div className="text-sm font-bold" style={{ color: '#fff2f4' }}>{d.name}</div>
                <div className="text-[10px] text-text-muted uppercase">{d.kind}</div>
              </div>
              <button onClick={() => togMut.mutate({ id: d.id, enabled: !d.enabled })}
                className={`badge ${d.enabled ? 'badge-cyan' : 'badge-muted'}`}>
                {d.enabled ? 'Active' : 'Paused'}
              </button>
              <button onClick={() => delMut.mutate(d.id)} className="text-text-muted hover:text-neon-red">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          {dests.length === 0 && <p className="text-text-muted text-xs">No delivery channels configured. Alerts will only show in-app.</p>}
        </div>
      )}

      {/* Recent deliveries */}
      {deliveries.length > 0 && (
        <div>
          <h4 className="text-xs uppercase tracking-wider text-text-muted mb-2">Recent Deliveries</h4>
          <div className="space-y-1">
            {deliveries.slice(0, 8).map(d => (
              <div key={d.id} className="flex items-center justify-between text-xs py-1 px-2 rounded" style={{ background: 'rgba(255,255,255,0.02)' }}>
                <span className="flex items-center gap-2">
                  <span style={{ color: d.status === 'ok' ? '#34D399' : '#F87171' }}>●</span>
                  {d.destination_name}
                </span>
                <span className="text-text-muted text-[10px]">{d.status} · {new Date(d.created_at).toLocaleTimeString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
