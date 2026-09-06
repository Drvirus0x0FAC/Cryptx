import { useEffect, useRef } from 'react'

const CHARS = '01ABCDEF0123456789アイウエオカキクケコ∑∆≡∇◈⬡'

export default function MatrixBg({ opacity = 0.18 }: { opacity?: number }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let raf: number
    let cols: number[] = []

    function resize() {
      if (!canvas) return
      canvas.width  = canvas.offsetWidth
      canvas.height = canvas.offsetHeight
      const numCols = Math.floor(canvas.width / 18)
      cols = Array.from({ length: numCols }, () => Math.floor(Math.random() * canvas.height / 18))
    }

    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(canvas)

    function draw() {
      if (!canvas || !ctx) return
      ctx.fillStyle = `rgba(1,10,19,0.05)`
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      ctx.font = '13px "Roboto Mono", monospace'

      cols.forEach((y, i) => {
        const char  = CHARS[Math.floor(Math.random() * CHARS.length)]
        const x     = i * 18

        // Bright head
        ctx.fillStyle = `rgba(255,64,82,${opacity * 1.8})`
        ctx.fillText(char, x, y * 18)

        // Trail
        ctx.fillStyle = `rgba(255,64,82,${opacity * 0.5})`
        ctx.fillText(CHARS[Math.floor(Math.random() * CHARS.length)], x, (y - 1) * 18)

        if (y * 18 > canvas.height && Math.random() > 0.975) {
          cols[i] = 0
        } else {
          cols[i]++
        }
      })

      raf = requestAnimationFrame(draw)
    }

    raf = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [opacity])

  return (
    <canvas
      ref={ref}
      className="absolute inset-0 w-full h-full pointer-events-none"
      style={{ opacity }}
    />
  )
}
