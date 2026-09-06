/**
 * CryptoTxMap - interactive animated global cryptocurrency-transaction map.
 * A dotted world-map silhouette with glowing exchange hubs, great-circle arcs
 * carrying flowing transaction pulses + traveling packets, drifting token glyphs
 * and a live ticker. Hovering a hub highlights its routes. Pure SVG + CSS/SMIL.
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

const W = 1000
const H = 500

// Continents approximated as lon/lat ellipses → dotted landmasses.
const CONTINENTS: Array<[number, number, number, number]> = [
  [-100, 46, 34, 20], [-88, 15, 11, 11], [-60, -20, 15, 27], [-42, 72, 12, 8],
  [12, 50, 22, 12], [22, 4, 22, 32], [46, 27, 12, 12], [95, 52, 46, 22],
  [78, 22, 12, 12], [108, 8, 14, 12], [134, -25, 17, 12],
]
function isLand(lon: number, lat: number): boolean {
  for (const [cx, cy, rx, ry] of CONTINENTS) {
    const dx = (lon - cx) / rx
    const dy = (lat - cy) / ry
    if (dx * dx + dy * dy <= 1) return true
  }
  return false
}
function project(lon: number, lat: number): [number, number] {
  return [((lon + 180) / 360) * W, ((90 - lat) / 180) * H]
}

// Major exchange / hub cities (lon, lat).
const CITIES: Array<[number, number]> = [
  [-122, 37.7], [-74, 40.7], [-79, 43.7], [-46, -23], [-0.1, 51.5], [8.5, 47],
  [8.7, 50], [3.4, 6.5], [37, 55], [55, 25], [72, 19], [103, 1.3],
  [114, 22], [127, 37.5], [139, 35.7], [151, -33.9],
]
const LINKS: Array<[number, number]> = [
  [0, 14], [1, 4], [3, 10], [8, 15], [5, 12], [10, 0], [9, 14], [4, 11],
  [6, 13], [2, 7], [1, 9], [11, 15], [12, 4], [7, 3],
]
const GLYPHS: Array<[string, number, number]> = [
  ['₿', 120, 120], ['Ξ', 900, 110], ['◇', 780, 430], ['₮', 190, 420], ['◎', 500, 80], ['⟠', 640, 200],
]

function arcPath(a: [number, number], b: [number, number]): string {
  const mx = (a[0] + b[0]) / 2
  const my = (a[1] + b[1]) / 2
  const dist = Math.hypot(b[0] - a[0], b[1] - a[1])
  const lift = Math.min(180, dist * 0.32)
  return `M${a[0].toFixed(1)} ${a[1].toFixed(1)} Q ${mx.toFixed(1)} ${(my - lift).toFixed(1)} ${b[0].toFixed(1)} ${b[1].toFixed(1)}`
}

export default function CryptoTxMap() {
  const { t } = useTranslation()
  const [hover, setHover] = useState<number | null>(null)

  const land = useMemo(() => {
    const cols = 74, rows = 34
    const pts: Array<[number, number]> = []
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const lon = -180 + ((c + 0.5) / cols) * 360
        const lat = 90 - ((r + 0.5) / rows) * 180
        if (isLand(lon, lat)) pts.push(project(lon, lat))
      }
    }
    return pts
  }, [])

  const nodes = useMemo(() => CITIES.map(([lon, lat]) => project(lon, lat)), [])
  const arcs = useMemo(() => LINKS.map(([a, b]) => ({ a, b, d: arcPath(nodes[a], nodes[b]) })), [nodes])

  return (
    <div className="cxv-map">
      <svg viewBox={`0 0 ${W} ${H}`} className="cxv-map-svg" preserveAspectRatio="xMidYMid meet">
        <defs>
          <radialGradient id="cxvHub" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#ff5a7a" stopOpacity="0.95" />
            <stop offset="100%" stopColor="#ff2d55" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="cxvArcG" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#ff2d55" stopOpacity="0" />
            <stop offset="50%" stopColor="#ff6a86" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#ff2d55" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* dotted world map */}
        <g className="cxv-map-land">
          {land.map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r={1.5} />
          ))}
        </g>

        {/* routes */}
        {arcs.map((arc, i) => {
          const on = hover !== null && (arc.a === hover || arc.b === hover)
          const dur = 3.2 + (i % 6) * 0.6
          return (
            <g key={`arc${i}`} className={on ? 'cxv-route on' : 'cxv-route'}>
              <path id={`cxvR${i}`} d={arc.d} className="cxv-route-base" fill="none" />
              <path d={arc.d} className="cxv-route-flow" fill="none" stroke="url(#cxvArcG)"
                    style={{ animationDuration: `${dur}s`, animationDelay: `${(i * 0.35).toFixed(2)}s` }} />
              <circle r={on ? 3.4 : 2.6} className="cxv-route-packet">
                <animateMotion dur={`${dur}s`} begin={`${(i * 0.4).toFixed(2)}s`} repeatCount="indefinite" rotate="auto">
                  <mpath href={`#cxvR${i}`} />
                </animateMotion>
              </circle>
            </g>
          )
        })}

        {/* hubs */}
        {nodes.map(([x, y], i) => (
          <g key={`n${i}`} className={hover === i ? 'cxv-hub on' : 'cxv-hub'}
             onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <circle cx={x} cy={y} r={11} fill="url(#cxvHub)" className="cxv-hub-glow" />
            <circle cx={x} cy={y} r={2.4} className="cxv-hub-core" />
            <circle cx={x} cy={y} r={2.4} className="cxv-hub-ring" fill="none">
              <animate attributeName="r" values="2.4;16" dur="3s" begin={`${(i % 7) * 0.4}s`} repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.7;0" dur="3s" begin={`${(i % 7) * 0.4}s`} repeatCount="indefinite" />
            </circle>
            {/* generous invisible hit-area for hover */}
            <circle cx={x} cy={y} r={20} fill="transparent" />
          </g>
        ))}

        {/* drifting token glyphs */}
        {GLYPHS.map(([c, x, y], i) => (
          <text key={`g${i}`} x={x} y={y} className="cxv-map-glyph" style={{ animationDelay: `${i * 0.7}s` }}>{c}</text>
        ))}
      </svg>

      {/* live transaction ticker */}
      <div className="cxv-map-feed">
        <span><b>0x71c9…af32</b> → <b>bc1q9f…4e2a</b></span>
        <span>BTC 12.408 · <i>bridge</i></span>
        <span>ETH → BASE · 7 hops</span>
        <span><b>0x3af1…9c02</b> · <i>mixer</i></span>
      </div>
    </div>
  )
}
