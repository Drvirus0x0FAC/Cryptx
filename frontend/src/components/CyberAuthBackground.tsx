import { useEffect, useRef } from 'react'

/**
 * Animated cyber/crypto background for the login screen.
 * Single canvas: a drifting blockchain "constellation" (nodes + linking edges)
 * with travelling value-flow pulses, plus a faint falling hex/code rain.
 * Pure red/black to match the CrypTX brand. Pauses when tab hidden.
 */

const HEX = '0123456789abcdefABCDEF₿Ξ⟠✕△◇⬡01'
const RED = '255,64,82'

type Node = { x: number; y: number; vx: number; vy: number; r: number; pulse: number }
type Pulse = { a: number; b: number; t: number; speed: number }

export default function CyberAuthBackground() {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let raf = 0
    let w = 0
    let h = 0
    let nodes: Node[] = []
    let pulses: Pulse[] = []
    let drops: { x: number; y: number; speed: number; ch: string }[] = []
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

    function build() {
      if (!canvas) return
      w = canvas.clientWidth
      h = canvas.clientHeight
      canvas.width = Math.floor(w * dpr)
      canvas.height = Math.floor(h * dpr)
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0)

      const count = Math.max(28, Math.min(72, Math.floor((w * h) / 26000)))
      nodes = Array.from({ length: count }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.22,
        vy: (Math.random() - 0.5) * 0.22,
        r: Math.random() * 1.8 + 1.0,
        pulse: Math.random() * Math.PI * 2,
      }))
      pulses = []
      const dropCount = Math.floor(w / 42)
      drops = Array.from({ length: dropCount }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        speed: Math.random() * 0.9 + 0.4,
        ch: HEX[Math.floor(Math.random() * HEX.length)],
      }))
    }

    build()
    const ro = new ResizeObserver(build)
    ro.observe(canvas)

    const LINK = 150

    function frame() {
      if (!canvas || !ctx) return
      ctx.clearRect(0, 0, w, h)

      // faint hex rain
      ctx.font = '12px "Roboto Mono", monospace'
      for (const d of drops) {
        ctx.fillStyle = `rgba(${RED},0.10)`
        ctx.fillText(d.ch, d.x, d.y)
        d.y += d.speed
        if (d.y > h + 12) {
          d.y = -12
          d.x = Math.random() * w
          d.ch = HEX[Math.floor(Math.random() * HEX.length)]
        }
      }

      // move nodes
      for (const n of nodes) {
        n.x += n.vx
        n.y += n.vy
        if (n.x < 0 || n.x > w) n.vx *= -1
        if (n.y < 0 || n.y > h) n.vy *= -1
        n.pulse += 0.02
      }

      // edges
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i]
          const b = nodes[j]
          const dx = a.x - b.x
          const dy = a.y - b.y
          const dist = Math.hypot(dx, dy)
          if (dist < LINK) {
            const alpha = (1 - dist / LINK) * 0.28
            ctx.strokeStyle = `rgba(${RED},${alpha})`
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.moveTo(a.x, a.y)
            ctx.lineTo(b.x, b.y)
            ctx.stroke()
            // occasionally spawn a travelling pulse along a close edge
            if (!reduce && dist < 110 && Math.random() < 0.0009 && pulses.length < 36) {
              pulses.push({ a: i, b: j, t: 0, speed: Math.random() * 0.02 + 0.01 })
            }
          }
        }
      }

      // travelling value-flow pulses
      for (let k = pulses.length - 1; k >= 0; k--) {
        const p = pulses[k]
        const a = nodes[p.a]
        const b = nodes[p.b]
        if (!a || !b) { pulses.splice(k, 1); continue }
        p.t += p.speed
        if (p.t >= 1) { pulses.splice(k, 1); continue }
        const px = a.x + (b.x - a.x) * p.t
        const py = a.y + (b.y - a.y) * p.t
        ctx.fillStyle = `rgba(255,120,135,${0.9 * (1 - Math.abs(0.5 - p.t) * 1.4)})`
        ctx.beginPath()
        ctx.arc(px, py, 2.2, 0, Math.PI * 2)
        ctx.fill()
      }

      // nodes
      for (const n of nodes) {
        const glow = (Math.sin(n.pulse) + 1) / 2
        ctx.fillStyle = `rgba(${RED},${0.5 + glow * 0.5})`
        ctx.beginPath()
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2)
        ctx.fill()
        ctx.strokeStyle = `rgba(${RED},${0.10 + glow * 0.12})`
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.arc(n.x, n.y, n.r + 4 + glow * 3, 0, Math.PI * 2)
        ctx.stroke()
      }

      raf = requestAnimationFrame(frame)
    }

    function start() { cancelAnimationFrame(raf); raf = requestAnimationFrame(frame) }
    function stop() { cancelAnimationFrame(raf) }
    const onVis = () => (document.hidden ? stop() : start())
    document.addEventListener('visibilitychange', onVis)
    start()

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [])

  return <canvas ref={ref} className="auth-canvas-bg" aria-hidden="true" />
}
