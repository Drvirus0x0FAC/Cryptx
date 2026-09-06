/**
 * InvestigationGraphHost — full-screen iframe wrapper for the Nexus Graph.
 * Renders inside the normal app Layout so the sidebar/nav remain visible,
 * but the graph itself is loaded in an isolated iframe pointing at /nexus-embed.
 * This keeps the heavy d3-force simulation in its own document context.
 */
import { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { X, Maximize2, Minimize2, Network, Loader2 } from 'lucide-react'

export default function InvestigationGraphHost() {
  const navigate = useNavigate()
  const { addr } = useParams()
  const [loading, setLoading] = useState(true)
  const [fullscreen, setFullscreen] = useState(false)
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const iframeSrc = addr
    ? `/nexus-embed/${encodeURIComponent(addr)}`
    : '/nexus-embed'

  useEffect(() => {
    const handler = () => setLoading(false)
    const iframe = iframeRef.current
    if (iframe) {
      iframe.addEventListener('load', handler)
      return () => iframe.removeEventListener('load', handler)
    }
  }, [])

  useEffect(() => {
    if (!fullscreen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setFullscreen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fullscreen])

  return (
    <div
      ref={containerRef}
      className="igraph-host"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: 'rgb(var(--bg-deep, 10 12 18))',
        position: fullscreen ? 'fixed' : undefined,
        inset: fullscreen ? 0 : undefined,
        zIndex: fullscreen ? 99999 : undefined,
      }}
    >
      {/* Toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '8px 16px',
          background: 'rgb(var(--bg-card, 18 22 30))',
          borderBottom: '1px solid rgb(var(--bg-border, 40 44 55) / 0.5)',
          flexShrink: 0,
        }}
      >
        <Network size={16} style={{ color: 'rgb(var(--cxv-acc, 56 224 255))' }} />
        <span style={{ fontWeight: 700, fontSize: 14, color: 'rgb(var(--text-primary, 230 234 240))' }}>
          Investigation Graph
        </span>
        {loading && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'rgb(var(--text-muted, 130 136 148))' }}>
            <Loader2 size={12} className="animate-spin" /> Loading graph…
          </span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button
            type="button"
            onClick={() => setFullscreen(f => !f)}
            title={fullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen'}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 30, height: 30, borderRadius: 8, border: 'none', cursor: 'pointer',
              background: 'rgb(var(--bg-border, 40 44 55) / 0.4)',
              color: 'rgb(var(--text-muted, 130 136 148))',
            }}
          >
            {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
          <button
            type="button"
            onClick={() => navigate('/')}
            title="Close"
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 30, height: 30, borderRadius: 8, border: 'none', cursor: 'pointer',
              background: 'rgb(var(--cxv-brand, 255 82 125) / 0.15)',
              color: 'rgb(var(--cxv-brand, 255 82 125))',
            }}
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Iframe */}
      <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        <iframe
          ref={iframeRef}
          src={iframeSrc}
          title="Investigation Graph"
          style={{
            width: '100%',
            height: '100%',
            border: 'none',
            background: 'rgb(var(--bg-deep, 10 12 18))',
          }}
          allow="fullscreen"
        />
      </div>
    </div>
  )
}
