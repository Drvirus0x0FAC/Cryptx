/**
 * chainGlyphs — professional vector blockchain brand logos for Nexus Graph nodes.
 *
 * Every glyph is hand-authored as pure inline SVG (paths / circles / gradients only —
 * no external images, no icon fonts) inside a normalized 100×100 box centred at
 * (50,50). Marks are drawn white/monochrome so they read correctly on the
 * brand-coloured disc the parent renders behind them; where a brand requires
 * negative-space knock-outs (Base slot, Gnosis owl eyes, Moonbeam crescent,
 * Tether stem slit) the knock-out is carved with `fillRule="evenodd"` so the disc
 * — and its glossy shine overlay — shows through naturally.
 *
 * Usage (integrator): place inside a translated SVG <g> sitting on the node centre,
 * over a disc of radius > r filled with the brand colour:
 *
 *   <circle r={discR} fill={badge.fill} stroke={badge.stroke} />
 *   <ChainGlyph chain={chainKey} r={discR * 0.68} color={badge.fill} />
 *
 * `chain` accepts any raw chain/network string; it is normalised through
 * `glyphKey()` (lowercase + alias resolution). `r` is the radius the glyph art is
 * scaled into (the 100-unit box maps to 2r). `color` should be the brand disc
 * colour — it is exposed as `currentColor` for marks that need it. `opacity`
 * is a legacy optional passthrough.
 *
 * `hasGlyph()` returns true for every non-empty chain key: known chains render
 * their brand mark and unknown chains render a clean generic fallback (hexagon
 * outline with the chain's first letters), so callers never need a text fallback.
 *
 * Supported canonical keys (aliases in parentheses):
 *   eth (ethereum) · btc (bitcoin) · trx (tron) · bnb (bsc, binance)
 *   matic (polygon, pol) · arb (arbitrum) · op (optimism) · base · gno (gnosis)
 *   avax (avalanche) · sol (solana) · xrp (ripple) · ltc (litecoin)
 *   doge (dogecoin) · bch (bitcoin-cash, bitcoincash) · zec (zcash)
 *   ada (cardano) · dot (polkadot) · atom (cosmos) · near · apt (aptos) · sui
 *   ton · algo (algorand) · xlm (stellar) · kas (kaspa) · ftm (fantom)
 *   mnt (mantle) · glmr (moonbeam) · zeta (zep, zetachain) · stx (stacks) · icp
 *   usdt (tether) · xmr (monero)
 * Anything else → generic hexagon fallback with the chain's leading letters.
 */
import type { ReactNode } from 'react'

const W = '#ffffff'

// ── Brand marks (authored in a 100×100 box centred at 50,50) ─────────────────

const GLYPHS: Record<string, ReactNode> = {
  // Ethereum — octahedron with classic left/right facet shading
  eth: (
    <g fill={W}>
      <polygon points="50,10 50,38 74,50" opacity="0.62" />
      <polygon points="50,10 26,50 50,38" opacity="0.95" />
      <polygon points="50,44 74,54 50,66" opacity="0.62" />
      <polygon points="50,44 50,66 26,54" opacity="0.95" />
      <polygon points="50,72 74,58 50,92" opacity="0.5" />
      <polygon points="50,72 50,92 26,58" opacity="0.8" />
    </g>
  ),
  // Bitcoin — tilted ₿ with double crown/base bars
  btc: (
    <g transform="rotate(14 50 50)" fill={W}>
      <path
        fillRule="evenodd"
        d="M34 22 h20 c10 0 17 5 17 13 c0 6 -3.5 10 -8.5 12 c7 1.6 11.5 6.4 11.5 13.5 C74 70 66 76 55 76 H34 Z
           M45 32 v12 h8.5 c5 0 8 -2.4 8 -6 s-3 -6 -8 -6 Z
           M45 54 v12 h10 c5.5 0 8.8 -2.3 8.8 -6 s-3.3 -6 -8.8 -6 Z"
      />
      <rect x="42" y="13" width="6" height="9" />
      <rect x="53" y="13" width="6" height="9" />
      <rect x="42" y="76" width="6" height="9" />
      <rect x="53" y="76" width="6" height="9" />
    </g>
  ),
  // Bitcoin Cash — same ₿, counter-tilted (brand disc is green)
  bch: (
    <g transform="rotate(-14 50 50)" fill={W}>
      <path
        fillRule="evenodd"
        d="M34 22 h20 c10 0 17 5 17 13 c0 6 -3.5 10 -8.5 12 c7 1.6 11.5 6.4 11.5 13.5 C74 70 66 76 55 76 H34 Z
           M45 32 v12 h8.5 c5 0 8 -2.4 8 -6 s-3 -6 -8 -6 Z
           M45 54 v12 h10 c5.5 0 8.8 -2.3 8.8 -6 s-3.3 -6 -8.8 -6 Z"
      />
      <rect x="42" y="13" width="6" height="9" />
      <rect x="53" y="13" width="6" height="9" />
      <rect x="42" y="76" width="6" height="9" />
      <rect x="53" y="76" width="6" height="9" />
    </g>
  ),
  // TRON — angular folded-triangle emblem
  trx: (
    <path
      fill={W}
      fillRule="evenodd"
      d="M20 18 L84 30 L54 86 Z M33 30 L64 36 L50 64 Z"
    />
  ),
  // BNB — five interlocking diamond facets
  bnb: (
    <g fill={W}>
      {[[50, 50], [50, 26.5], [50, 73.5], [26.5, 50], [73.5, 50]].map(([cx, cy], i) => (
        <path key={i} d={`M${cx} ${cy - 10.5} L${cx + 10.5} ${cy} L${cx} ${cy + 10.5} L${cx - 10.5} ${cy} Z`} />
      ))}
    </g>
  ),
  // Polygon — the two interlocking hooked ribbons of the knot mark
  matic: (
    <g fill="none" stroke={W} strokeWidth="10" strokeLinejoin="miter">
      <path d="M67 25 L37 42.5 V57.5" />
      <path d="M33 75 L63 57.5 V42.5" />
    </g>
  ),
  // Arbitrum — nested upward swoosh peaks
  arb: (
    <g fill={W}>
      <path d="M50 12 C62 34 71 56 82 86 L70 86 C61 62 55 44 50 30 C45 44 39 62 30 86 L18 86 C29 56 38 34 50 12 Z" />
      <path d="M50 52 C54 60 57 68 63 86 L55 86 C52 78 50.5 73 50 71 C49.5 73 48 78 45 86 L37 86 C43 68 46 60 50 52 Z" opacity="0.92" />
    </g>
  ),
  // Optimism — geometric OP letterforms drawn as paths (no fonts)
  op: (
    <g fill={W}>
      <path fillRule="evenodd" d="M35 33.5 a16.5 16.5 0 1 0 0.01 0 Z M35 41 a9 9 0 1 1 -0.01 0 Z" />
      <path d="M58.5 33 h8.5 v34 h-8.5 Z" />
      <path fillRule="evenodd" d="M68 32 a10.5 10.5 0 1 0 0.01 0 Z M68 37.7 a4.8 4.8 0 1 1 -0.01 0 Z" />
    </g>
  ),
  // Base — the signature white bar anchored to the left of the brand disc
  base: <rect x="20" y="43" width="38" height="14" rx="2" fill={W} />,
  // Gnosis — geometric owl (head with ring eyes + beak, even-odd knock-outs)
  gno: (
    <g fill={W}>
      <path
        fillRule="evenodd"
        d="M50 19 a30 30 0 1 0 0.01 0 Z
           M39 37 a8 8 0 1 0 0.01 0 Z
           M61 37 a8 8 0 1 0 0.01 0 Z
           M50 53 L43.5 61 L56.5 61 Z"
      />
      <circle cx="39" cy="45" r="2.8" />
      <circle cx="61" cy="45" r="2.8" />
    </g>
  ),
  // Avalanche — mountain peak with detached falling wedge
  avax: (
    <g fill={W}>
      <path d="M44 22 L20 74 h16 c3 0 5 -1.2 6.6 -4 L56 48 c1.6 -3 1.6 -5.6 0 -8.6 L50 28 c-2 -3.8 -4 -3.8 -6 0 Z" />
      <path d="M62 60 L54 74 h26 Z" />
    </g>
  ),
  // Solana — three stripes; top & bottom lean "/", middle leans "\"
  sol: (
    <g fill={W}>
      <path d="M32 24 h42 l-12 13 H20 Z" />
      <path d="M20 43 h42 l12 13 H32 Z" />
      <path d="M32 62 h42 l-12 13 H20 Z" />
    </g>
  ),
  // XRP — twin curved bands forming the hourglass X
  xrp: (
    <g fill="none" stroke={W} strokeWidth="11" strokeLinecap="round">
      <path d="M24 28 c7 12 15.5 18 26 18 c10.5 0 19 -6 26 -18" />
      <path d="M24 72 c7 -12 15.5 -18 26 -18 c10.5 0 19 6 26 18" />
    </g>
  ),
  // Litecoin — italic Ł
  ltc: (
    <path fill={W} d="M44 18 h13 L49 56 l16 -6 v10 l-18 7 l-3 15 H31 l3 -13 l-9 3.4 V62 l12 -4.6 Z" />
  ),
  // Dogecoin — Ð with crossing stroke
  doge: (
    <path
      fill={W}
      fillRule="evenodd"
      d="M36 20 h18 c16 0 26 12 26 30 s-10 30 -26 30 H36 V56 H26 v-11 h10 Z
         M47 31 v14 h10 v11 H47 v14 h6 c9.5 0 15 -7.6 15 -19.5 S62.5 31 53 31 Z"
    />
  ),
  // Zcash — Z struck through by twin horizontal bars
  zec: (
    <g fill={W}>
      <rect x="20" y="42" width="60" height="6" />
      <rect x="20" y="52" width="60" height="6" />
      <path d="M30 27 h40 v9 L45 64 h25 v9 H30 v-9 l25 -28 H30 Z" />
    </g>
  ),
  // Cardano — orbital dot constellation (1 + 6 + 12)
  ada: (
    <g fill={W}>
      <circle cx="50" cy="50" r="7" />
      {Array.from({ length: 6 }).map((_, i) => {
        const a = (i / 6) * Math.PI * 2
        return <circle key={`i${i}`} cx={50 + Math.cos(a) * 21} cy={50 + Math.sin(a) * 21} r="4.2" />
      })}
      {Array.from({ length: 12 }).map((_, i) => {
        const a = (i / 12) * Math.PI * 2 + Math.PI / 12
        return <circle key={`o${i}`} cx={50 + Math.cos(a) * 33.5} cy={50 + Math.sin(a) * 33.5} r="2.3" opacity="0.9" />
      })}
    </g>
  ),
  // Polkadot — six-petal ellipse ring
  dot: (
    <g fill={W}>
      <ellipse cx="50" cy="23" rx="12" ry="8" />
      <ellipse cx="50" cy="77" rx="12" ry="8" />
      <ellipse cx="26.5" cy="36.5" rx="8" ry="12" transform="rotate(-30 26.5 36.5)" />
      <ellipse cx="73.5" cy="36.5" rx="8" ry="12" transform="rotate(30 73.5 36.5)" />
      <ellipse cx="26.5" cy="63.5" rx="8" ry="12" transform="rotate(30 26.5 63.5)" />
      <ellipse cx="73.5" cy="63.5" rx="8" ry="12" transform="rotate(-30 73.5 63.5)" />
    </g>
  ),
  // Cosmos — nucleus with three electron orbits
  atom: (
    <g stroke={W} strokeWidth="3.4" fill="none">
      <circle cx="50" cy="50" r="6.5" fill={W} stroke="none" />
      <ellipse cx="50" cy="50" rx="34" ry="12.5" />
      <ellipse cx="50" cy="50" rx="34" ry="12.5" transform="rotate(60 50 50)" />
      <ellipse cx="50" cy="50" rx="34" ry="12.5" transform="rotate(-60 50 50)" />
    </g>
  ),
  // NEAR — bold geometric N
  near: <path fill={W} d="M25 76 V24 h11 l29 37 V24 h11 v52 H64 L35 39 v37 Z" />,
  // Aptos — stepped sphere built from horizontal bars
  apt: (
    <g fill={W}>
      {[34, 50, 62, 70, 62, 50, 34].map((w, i) => (
        <rect key={i} x={50 - w / 2} y={14.2 + i * 10.6} width={w} height="8" rx="2" />
      ))}
    </g>
  ),
  // Sui — water droplet with inner droplet knock-out
  sui: (
    <path
      fill={W}
      fillRule="evenodd"
      d="M50 14 C64 32 74 45 74 60 a24 24 0 1 1 -48 0 C26 45 36 32 50 14 Z
         M50 32 c-9 12 -13 19 -13 26 a13 13 0 0 0 26 0 c0 -7 -4 -14 -13 -26 Z"
    />
  ),
  // TON — faceted diamond crystal
  ton: (
    <path
      fill={W}
      fillRule="evenodd"
      d="M24 24 h52 c4 0 6.6 4.4 4.4 8 L54 84 c-1.8 3.2 -6.2 3.2 -8 0 L19.6 32 c-2.2 -3.6 0.4 -8 4.4 -8 Z
         M50 72 V33 H30 Z M50 72 V33 h20 Z"
    />
  ),
  // Algorand — bold A with crossbar
  algo: (
    <g fill="none" stroke={W} strokeLinecap="round" strokeLinejoin="round">
      <path d="M28 78 L50 24 L72 78" strokeWidth="9" />
      <path d="M39 59 h22" strokeWidth="8" />
    </g>
  ),
  // Stellar — orbit ring with diagonal slash
  xlm: (
    <g fill="none" stroke={W} strokeWidth="6.5" strokeLinecap="round">
      <path d="M27 68 a28 28 0 1 1 46 -34" />
      <path d="M16 62 L84 30" />
    </g>
  ),
  // Kaspa — angular italic K built from sharp chevrons
  kas: (
    <g fill={W}>
      <path d="M30 78 L36 22 h11 L41 78 Z" />
      <path d="M43 44 L68 22 h13 L54 50 L80 78 H67 L43 56 Z" />
    </g>
  ),
  // Fantom — curved italic f with crossbar
  ftm: (
    <g fill={W}>
      <path d="M64 12 C48 12 36 24 34 40 L26 78 h11 L45 40 C47 30 54 21 66 21 Z" />
      <path d="M25 44 h28 l-2 10 H23 Z" />
    </g>
  ),
  // Mantle — sharp geometric M monogram
  mnt: <path fill={W} d="M24 76 V24 h14 l12 20 12 -20 h14 v52 h-12 V44 L50 66 36 44 v32 Z" />,
  // Moonbeam — eclipse crescent with moon dot
  glmr: (
    <g fill={W}>
      <path fillRule="evenodd" d="M45 26 a26 26 0 1 0 0.01 0 Z M58 20 a21 21 0 1 0 0.01 0 Z" />
      <circle cx="66" cy="62" r="4.5" />
    </g>
  ),
  // ZetaChain — bold chamfered Z
  zeta: <path fill={W} d="M26 24 h48 L40 62 h34 v14 H26 l34 -38 H26 Z" />,
  // Stacks — geometric S with rounded turns
  stx: (
    <path
      fill="none"
      stroke={W}
      strokeWidth="9"
      d="M68 33 H45 a9.5 9.5 0 0 0 0 19 h12 a9.5 9.5 0 0 1 0 19 H34"
    />
  ),
  // Internet Computer — twin-loop infinity
  icp: (
    <g fill="none" stroke={W} strokeWidth="8">
      <circle cx="34.5" cy="50" r="15.5" />
      <circle cx="65.5" cy="50" r="15.5" />
    </g>
  ),
  // Tether — ₮ with split stem over a coin-edge ellipse
  usdt: (
    <g>
      <path
        fill={W}
        fillRule="evenodd"
        d="M26 25 h48 v13 H57 v39 H43 V38 H26 Z M48.8 38 h2.4 v39 h-2.4 Z"
      />
      <ellipse cx="50" cy="83" rx="20" ry="5" fill="none" stroke={W} strokeWidth="4" />
    </g>
  ),
  // Monero — wide M over the coin's bottom arc
  xmr: (
    <g fill="none" stroke={W} strokeWidth="9" strokeLinejoin="round" strokeLinecap="round">
      <path d="M23 64 V35 L50 66 L77 35 V64" />
      <path d="M31 74 a23 23 0 0 0 38 0" />
    </g>
  ),
}

// ── Alias resolution ──────────────────────────────────────────────────────────
// Maps every chain key used by CHAIN_BADGES (NexusGraph.tsx) — plus common
// synonyms — onto the canonical GLYPHS keys above.
const ALIASES: Record<string, string> = {
  ethereum: 'eth', bitcoin: 'btc', tron: 'trx', bsc: 'bnb', binance: 'bnb',
  polygon: 'matic', pol: 'matic', arbitrum: 'arb', optimism: 'op',
  gnosis: 'gno', avalanche: 'avax', solana: 'sol', ripple: 'xrp',
  litecoin: 'ltc', dogecoin: 'doge', zcash: 'zec', cardano: 'ada',
  polkadot: 'dot', cosmos: 'atom', aptos: 'apt', algorand: 'algo',
  stellar: 'xlm', kaspa: 'kas', fantom: 'ftm', mantle: 'mnt',
  moonbeam: 'glmr', zep: 'zeta', zetachain: 'zeta', stacks: 'stx',
  tether: 'usdt', monero: 'xmr', 'bitcoin-cash': 'bch', bitcoincash: 'bch',
  internetcomputer: 'icp', 'internet-computer': 'icp',
}

/** Normalise a raw chain/network string to its canonical glyph key. */
export function glyphKey(chain: string): string {
  const k = (chain || '').toLowerCase().trim()
  return ALIASES[k] || k
}

/**
 * True for every non-empty chain key — known chains render their brand mark,
 * unknown chains render the generic hexagon fallback. Callers can rely on
 * `hasGlyph(x) → <ChainGlyph chain={x} … />` always producing a visual.
 */
export function hasGlyph(chain: string): boolean {
  return glyphKey(chain).length > 0
}

// ── Generic fallback: hexagon outline + leading letters ──────────────────────

function FallbackGlyph({ chain }: { chain: string }): JSX.Element {
  const letters = (chain || '').replace(/[^a-z0-9]/gi, '').slice(0, 4).toUpperCase() || '?'
  const fontSize = letters.length <= 2 ? 34 : letters.length === 3 ? 27 : 21
  return (
    <g>
      <polygon
        points="50,16 79,33 79,67 50,84 21,67 21,33"
        fill="none" stroke={W} strokeWidth="6" strokeLinejoin="round" opacity="0.9"
      />
      <text
        x="50" y={50 + fontSize * 0.35}
        textAnchor="middle"
        fontFamily="Arial, Helvetica, sans-serif"
        fontWeight="800"
        fontSize={fontSize}
        fill={W}
      >
        {letters}
      </text>
    </g>
  )
}

/**
 * Centred chain brand logo for SVG graphs. Place inside a translated <g>:
 *   <ChainGlyph chain="btc" r={14} color="#f7931a" />
 *
 * @param chain  Raw chain key (alias-resolved; unknown keys → hexagon fallback)
 * @param r      Radius the glyph is scaled into (glyph art fits a 2r box)
 * @param color  Brand disc colour, exposed as currentColor for negative-space marks
 * @param opacity Optional legacy passthrough (defaults to 1)
 */
export function ChainGlyph({ chain, r, color = '#0b0f1a', opacity = 1 }: {
  chain: string; r: number; color?: string; opacity?: number
}): JSX.Element {
  const key = glyphKey(chain)
  const glyph = GLYPHS[key] ?? <FallbackGlyph chain={key} />
  const s = (r * 2) / 100
  return (
    <g transform={`translate(${-r},${-r}) scale(${s})`} color={color} opacity={opacity}
      style={{ pointerEvents: 'none' }}>
      {glyph}
    </g>
  )
}

/* ========================================================================== */
/* Brand colours + ready-to-use ChainLogo (disc + white mark)                 */
/* ========================================================================== */

/**
 * Brand fill colours keyed by canonical {@link glyphKey}. Used as the disc
 * colour behind a white {@link ChainGlyph} mark — the classic "coloured circle
 * + brand symbol" logo style. Covers every glyph plus the common ERC-20 tokens
 * shown in the coverage explorer.
 */
export const BRAND_COLORS: Record<string, string> = {
  // L1 / L2 chains
  eth: '#627eea', btc: '#f7931a', bch: '#8dc351', trx: '#eb0029', bnb: '#f3ba2f',
  matic: '#8247e5', arb: '#28a0f0', op: '#ff0420', base: '#0052ff', gno: '#04795b',
  avax: '#e84142', sol: '#14f195', xrp: '#23292f', ltc: '#345d9d', doge: '#c2a633',
  zec: '#ecb244', ada: '#0033ad', dot: '#e6007a', atom: '#2e3148', near: '#000000',
  apt: '#0d0d0d', sui: '#6fbcf0', ton: '#0098ea', algo: '#000000', xlm: '#14161e',
  kas: '#70c7ba', ftm: '#13b5ec', mnt: '#000000', glmr: '#ff2e56', zeta: '#1c1c1c',
  stx: '#5546ff', icp: '#3b00b9', xmr: '#ff6600',
  // Stablecoins & major tokens (glyph falls back to a clean hex mark, brand-coloured)
  usdt: '#26a17b', usdc: '#2775ca', dai: '#f5ac37', busd: '#f0b90b', tusd: '#1a5aff',
  usdp: '#00845d', pyusd: '#0070ba', frax: '#000000',
  uni: '#ff007a', link: '#2a5ada', aave: '#b6509e', comp: '#00d395', mkr: '#1aab9b',
  snx: '#00d1ff', crv: '#40e0d0', ldo: '#00a3ff', grt: '#6f4cff', sushi: '#fa52a0',
  yfi: '#006ae3', ens: '#5298ff', '1inch': '#1b314f', bal: '#1e1e1e', lrc: '#1c60ff',
  ankr: '#2e6df6', celo: '#fbcc5c', fil: '#0090ff', eos: '#000000', tezos: '#2c7df7',
  xtz: '#2c7df7', chz: '#cd0124', enj: '#7866d5', amp: '#d633b0', ren: '#001a33',
  weth: '#627eea', wbtc: '#f09242', steth: '#00a3ff', cbeth: '#0052ff',
}

/**
 * Resolve a chain/token's brand colour via {@link glyphKey}, falling back to
 * `fallback` when unknown.
 */
export function brandColor(chain: string, fallback = '#334155'): string {
  return BRAND_COLORS[glyphKey(chain)] ?? fallback
}

/**
 * Drop-in brand logo: a brand-coloured disc with the white {@link ChainGlyph}
 * mark centred on it (the same visual language as the Nexus Graph nodes and the
 * reference crypto-logo set). Pure inline SVG — no external images, air-gap safe.
 *
 *   <ChainLogo chain="btc" size={36} />
 *   <ChainLogo chain="USDT" size={20} color="#26a17b" />
 *
 * `chain` accepts any chain/token string (normalised through `glyphKey`).
 * `color` overrides the auto-resolved brand colour for the disc.
 */
export function ChainLogo({ chain, size = 34, color, title }: {
  chain: string; size?: number; color?: string; title?: string
}): JSX.Element {
  const fill = color ?? brandColor(chain)
  const r = size / 2
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}
      style={{ display: 'block', flexShrink: 0 }} aria-hidden={title ? undefined : true}>
      {title ? <title>{title}</title> : null}
      <circle cx={r} cy={r} r={r} fill={fill} />
      {/* soft top shine for depth (matches Nexus node discs) */}
      <ellipse cx={r} cy={r * 0.7} rx={r * 0.78} ry={r * 0.5} fill="#ffffff" opacity={0.10} />
      <g transform={`translate(${r},${r})`}>
        <ChainGlyph chain={chain} r={r * 0.6} color={fill} />
      </g>
    </svg>
  )
}
