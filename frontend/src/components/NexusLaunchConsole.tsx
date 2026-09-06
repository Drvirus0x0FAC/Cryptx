/**
 * NexusLaunchConsole — the cinematic input screen for the Nexus Graph module.
 *
 * Shares the `.nxc` shell and backdrop with NexusProgressCinema so launching an
 * investigation and watching it run read as one continuous sequence: the same
 * centred console, the same grid/scan/mote backdrop, the same typography.
 *
 * Purely presentational — every value and handler is owned by the page.
 */
import { useMemo } from 'react'
import { ChevronDown, Cpu, Loader2, Minus, Network, Plus, Search, Sparkles, Target } from 'lucide-react'

interface Props {
  address: string
  onAddressChange: (v: string) => void
  onSubmit: () => void
  /** Chain inferred from the address format — drives the live badge. */
  detectedChain?: string | null
  chain: string
  onChainChange: (v: string) => void
  hops: number
  onHopsChange: (n: number) => void
  focus: string
  onFocusChange: (v: string) => void
  includeAi: boolean
  onIncludeAiChange: (v: boolean) => void
  busy?: boolean
}

const CHAINS: Array<{ value: string; label: string }> = [
  { value: 'auto',      label: 'Auto · Ethereum + ERC-20 (USDT, USDC…)' },
  { value: 'eth',       label: 'Ethereum · ETH + ERC-20 (USDT)' },
  { value: 'btc',       label: 'Bitcoin · BTC' },
  { value: 'tron',      label: 'Tron · TRX + TRC-20 (USDT)' },
  { value: 'bsc',       label: 'BNB Smart Chain · BNB + BEP-20 (USDT)' },
  { value: 'polygon',   label: 'Polygon · MATIC + ERC-20' },
  { value: 'arbitrum',  label: 'Arbitrum · ETH + ERC-20' },
  { value: 'optimism',  label: 'Optimism · ETH + ERC-20' },
  { value: 'base',      label: 'Base · ETH + ERC-20' },
  { value: 'gnosis',    label: 'Gnosis · xDAI + ERC-20' },
  { value: 'avax',      label: 'Avalanche C-Chain · AVAX + ERC-20' },
  { value: 'solana',    label: 'Solana · SOL + SPL (USDT/USDC)' },
  { value: 'xrp',       label: 'XRP Ledger · XRP + issued tokens' },
  { value: 'litecoin',  label: 'Litecoin · LTC' },
  { value: 'dogecoin',  label: 'Dogecoin · DOGE' },
  { value: 'bch',       label: 'Bitcoin Cash · BCH' },
  { value: 'zcash',     label: 'Zcash · ZEC (transparent t-addr)' },
  { value: 'cardano',   label: 'Cardano · ADA' },
  { value: 'polkadot',  label: 'Polkadot · DOT' },
  { value: 'cosmos',    label: 'Cosmos Hub · ATOM' },
  { value: 'near',      label: 'NEAR · NEAR' },
  { value: 'aptos',     label: 'Aptos · APT' },
  { value: 'sui',       label: 'Sui · SUI' },
  { value: 'ton',       label: 'TON · Toncoin' },
  { value: 'algorand',  label: 'Algorand · ALGO + ASA' },
  { value: 'stellar',   label: 'Stellar · XLM + assets' },
]

const TICKER = [
  'ETHEREUM', 'BITCOIN', 'TRON', 'BNB CHAIN', 'POLYGON', 'ARBITRUM', 'OPTIMISM', 'BASE',
  'GNOSIS', 'AVALANCHE', 'SOLANA', 'XRP LEDGER', 'LITECOIN', 'DOGECOIN', 'BITCOIN CASH',
  'ZCASH', 'CARDANO', 'POLKADOT', 'COSMOS', 'NEAR', 'APTOS', 'SUI', 'TON', 'ALGORAND', 'STELLAR',
]

// Fixed constellation — a seed wallet fanning out into two hop rings.
const NET_NODES = [
  { x: 600, y: 128, r: 7 },
  { x: 470, y: 78, r: 4 }, { x: 512, y: 186, r: 4 }, { x: 700, y: 74, r: 4 },
  { x: 742, y: 176, r: 4 }, { x: 604, y: 44, r: 3.5 }, { x: 596, y: 214, r: 3.5 },
  { x: 356, y: 132, r: 3 }, { x: 404, y: 40, r: 2.5 }, { x: 418, y: 220, r: 2.5 },
  { x: 848, y: 116, r: 3 }, { x: 800, y: 34, r: 2.5 }, { x: 808, y: 216, r: 2.5 },
  { x: 250, y: 72, r: 2 }, { x: 268, y: 196, r: 2 }, { x: 944, y: 66, r: 2 },
  { x: 950, y: 190, r: 2 }, { x: 150, y: 130, r: 1.8 }, { x: 1046, y: 132, r: 1.8 },
]
const NET_EDGES: Array<[number, number]> = [
  [0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [0, 6],
  [1, 7], [1, 8], [2, 9], [2, 7], [3, 10], [3, 11], [4, 12], [4, 10],
  [7, 13], [7, 14], [10, 15], [10, 16], [13, 17], [15, 18], [14, 17], [16, 18],
]

export default function NexusLaunchConsole({
  address, onAddressChange, onSubmit, detectedChain,
  chain, onChainChange, hops, onHopsChange,
  focus, onFocusChange, includeAi, onIncludeAiChange, busy,
}: Props) {
  const ready = address.trim().length > 0 && !busy
  const effectiveChain = chain === 'auto' ? (detectedChain || null) : chain

  const readout = useMemo(() => {
    const where = effectiveChain
      ? effectiveChain.toUpperCase()
      : 'Ethereum + ERC-20 (pending address)'
    return `${hops} hop${hops === 1 ? '' : 's'} · ${where} · AI synthesis ${includeAi ? 'on' : 'off'}`
  }, [hops, effectiveChain, includeAi])

  return (
    <div className="nxc">
      {/* ── Backdrop ─────────────────────────────────────────────────────── */}
      <div className="nxc-bg" aria-hidden>
        <div className="nxc-grid" />
        <div className="nxc-scan" />
        {Array.from({ length: 14 }, (_, i) => (
          <span key={i} className="nxc-particle" style={{
            left: `${(i * 71) % 96}%`, top: `${58 + ((i * 29) % 40)}%`,
            ['--dur' as string]: `${12 + ((i * 5) % 8)}s`,
            ['--delay' as string]: `${-((i * 11) % 13)}s`,
            ['--dx' as string]: `${((i % 5) - 2) * 16}px`,
          }} />
        ))}

        {/* Constellation */}
        <svg viewBox="0 0 1200 260" preserveAspectRatio="xMidYMid meet"
          style={{
            position: 'absolute', left: 0, right: 0, top: -8, height: 250, width: '100%', opacity: 0.7,
            maskImage: 'radial-gradient(ellipse 60% 74% at 50% 26%, #000 18%, transparent 72%)',
            WebkitMaskImage: 'radial-gradient(ellipse 60% 74% at 50% 26%, #000 18%, transparent 72%)',
          }}>
          {NET_EDGES.map(([a, b], i) => (
            <line key={i} className="nxl-net-edge"
              x1={NET_NODES[a].x} y1={NET_NODES[a].y} x2={NET_NODES[b].x} y2={NET_NODES[b].y}
              stroke="rgb(var(--accent-blue) / 0.5)" strokeWidth={1.1}
              style={{ ['--delay' as string]: `${(i % 7) * 0.28}s` }} />
          ))}
          {/* node 0 is the seed: the crest sits on it, so it is an edge anchor only */}
          {NET_NODES.map((n, i) => i === 0 ? null : (
            <circle key={i} className="nxl-net-node" cx={n.x} cy={n.y} r={n.r}
              fill="rgb(var(--accent-blue))"
              style={{ ['--r' as string]: n.r, ['--delay' as string]: `${(i % 9) * 0.32}s` }} />
          ))}
        </svg>
      </div>

      {/* ── Content ──────────────────────────────────────────────────────── */}
      <div className="relative z-10 flex w-full flex-col gap-5 px-6 py-7 lg:px-9 lg:py-9">

        {/* Crest + title */}
        <div className="nxc-rise flex flex-col items-center gap-3 text-center" style={{ ['--delay' as string]: '0s' }}>
          <div className="relative flex items-center justify-center" style={{ width: 78, height: 78 }}>
            <svg width={78} height={78} className="absolute inset-0">
              <circle className="nxl-crest-ring" cx={39} cy={39} r={35} fill="none"
                stroke="rgb(var(--accent-blue) / 0.35)" strokeWidth={1} strokeDasharray="4 10"
                style={{ transformOrigin: '39px 39px' }} />
              <circle className="nxl-crest-ring-r" cx={39} cy={39} r={28} fill="none"
                stroke="rgb(var(--accent-blue) / 0.22)" strokeWidth={1} strokeDasharray="2 7"
                style={{ transformOrigin: '39px 39px' }} />
            </svg>
            <span className="nxc-halo absolute rounded-2xl" style={{
              inset: 12, border: '1px solid rgb(var(--accent-blue) / 0.45)', transformOrigin: '50% 50%',
            }} />
            <div className="relative flex h-[52px] w-[52px] items-center justify-center rounded-2xl"
              style={{
                background: 'linear-gradient(140deg, rgb(var(--accent-blue) / 0.22), rgb(var(--accent-purple) / 0.14))',
                border: '1px solid rgb(var(--accent-blue) / 0.4)',
                boxShadow: '0 0 28px rgb(var(--accent-blue) / 0.28), inset 0 1px 0 rgb(255 255 255 / 0.08)',
              }}>
              <Network size={22} strokeWidth={1.8} style={{ color: 'rgb(var(--text-bright))' }} />
            </div>
          </div>

          <div>
            <p className="m-0 text-[9px] font-bold uppercase tracking-[0.42em]" style={{ color: 'rgb(var(--accent-blue))' }}>
              Blockchain investigation engine
            </p>
            <h1 className="m-0 mt-2 text-[26px] font-extrabold leading-none tracking-tight" style={{ color: 'rgb(var(--text-bright))' }}>
              Nexus Graph
            </h1>
            <p className="m-0 mt-2.5 max-w-[560px] text-[12px] leading-relaxed" style={{ color: 'rgb(var(--text-muted))' }}>
              Enter a wallet to fuse address intelligence, multi-hop fund tracing and behavioural
              correlation into a single investigative graph.
            </p>
          </div>
        </div>

        {/* Primary address field + launch */}
        <div className="nxc-rise flex flex-col gap-2.5 sm:flex-row" style={{ ['--delay' as string]: '0.07s' }}>
          <div className="nxl-field flex min-w-0 flex-1 items-center gap-3 rounded-xl px-4 py-3.5"
            style={{
              background: 'rgb(var(--bg-primary) / 0.72)',
              border: '1px solid rgb(var(--bg-border) / 0.5)',
            }}>
            <Search size={15} className="shrink-0" style={{ color: 'rgb(var(--text-muted))' }} />
            <input
              value={address}
              onChange={e => onAddressChange(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && ready) onSubmit() }}
              spellCheck={false}
              autoComplete="off"
              placeholder="Any address — 0x… (ETH/ERC-20) · bc1…/1… (BTC) · T… (Tron/USDT) · t1… (Zcash)"
              className="font-mono text-[13px]"
              style={{ color: 'rgb(var(--text-bright))' }}
            />
            {detectedChain && chain === 'auto' && (
              <span className="shrink-0 rounded-md px-2 py-1 font-mono text-[9px] font-bold uppercase tracking-wider"
                style={{
                  color: 'rgb(var(--accent-green))',
                  background: 'rgb(var(--accent-green) / 0.12)',
                  border: '1px solid rgb(var(--accent-green) / 0.3)',
                }}>
                {detectedChain} detected
              </span>
            )}
          </div>

          <button
            type="button"
            disabled={!ready}
            onClick={onSubmit}
            className="nxl-launch flex shrink-0 items-center justify-center gap-2.5 rounded-xl px-7 py-3.5 text-[13px] font-extrabold uppercase tracking-[0.14em]"
            style={{
              background: 'linear-gradient(135deg, rgb(var(--accent-blue)), rgb(var(--accent-indigo)))',
              color: 'rgb(var(--bg-primary))',
              border: '1px solid rgb(var(--accent-blue) / 0.7)',
              boxShadow: '0 0 30px rgb(var(--accent-blue) / 0.35), inset 0 1px 0 rgb(255 255 255 / 0.25)',
            }}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Target size={15} />}
            Build Nexus
          </button>
        </div>

        {/* Control deck */}
        <div className="nxc-rise grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)]"
          style={{ ['--delay' as string]: '0.13s' }}>

          {/* Chain / asset */}
          <div className="nxl-field rounded-xl px-4 py-3"
            style={{ background: 'rgb(var(--bg-primary) / 0.62)', border: '1px solid rgb(var(--bg-border) / 0.4)' }}>
            <p className="m-0 mb-2 text-[9px] font-bold uppercase tracking-[0.24em]" style={{ color: 'rgb(var(--text-muted))' }}>
              Chain / asset
            </p>
            <div className="flex items-center gap-2">
              <select value={chain} onChange={e => onChainChange(e.target.value)}
                className="cursor-pointer appearance-none text-[12px] font-semibold"
                style={{ color: 'rgb(var(--text-bright))' }}>
                {CHAINS.map(c => (
                  <option key={c.value} value={c.value} style={{ background: 'rgb(var(--bg-surface))' }}>{c.label}</option>
                ))}
              </select>
              <ChevronDown size={14} className="shrink-0" style={{ color: 'rgb(var(--text-muted))' }} />
            </div>
          </div>

          {/* Hop depth */}
          <div className="rounded-xl px-4 py-3"
            style={{ background: 'rgb(var(--bg-primary) / 0.62)', border: '1px solid rgb(var(--bg-border) / 0.4)' }}>
            <div className="mb-2 flex items-center justify-between">
              <p className="m-0 text-[9px] font-bold uppercase tracking-[0.24em]" style={{ color: 'rgb(var(--text-muted))' }}>
                Trace depth
              </p>
              <span className="font-mono text-[11px] font-bold tabular-nums" style={{ color: 'rgb(var(--accent-blue))' }}>
                {hops} hop{hops === 1 ? '' : 's'}
              </span>
            </div>
            <div className="flex items-center gap-2.5">
              <button type="button" onClick={() => onHopsChange(Math.max(1, hops - 1))}
                className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded-md"
                style={{ background: 'rgb(var(--bg-border) / 0.32)', color: 'rgb(var(--text-secondary))' }}
                aria-label="Decrease hop depth">
                <Minus size={12} />
              </button>
              <div className="flex h-2.5 flex-1 items-stretch gap-1">
                {Array.from({ length: 8 }, (_, i) => (
                  <span key={i} className="nxl-seg" data-on={i < hops} />
                ))}
              </div>
              <button type="button" onClick={() => onHopsChange(Math.min(8, hops + 1))}
                className="flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded-md"
                style={{ background: 'rgb(var(--bg-border) / 0.32)', color: 'rgb(var(--text-secondary))' }}
                aria-label="Increase hop depth">
                <Plus size={12} />
              </button>
            </div>
          </div>

          {/* AI synthesis */}
          <div className="rounded-xl px-4 py-3"
            style={{ background: 'rgb(var(--bg-primary) / 0.62)', border: '1px solid rgb(var(--bg-border) / 0.4)' }}>
            <p className="m-0 mb-2 text-[9px] font-bold uppercase tracking-[0.24em]" style={{ color: 'rgb(var(--text-muted))' }}>
              AI synthesis
            </p>
            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-[12px] font-semibold" style={{ color: 'rgb(var(--text-bright))' }}>
                <Sparkles size={13} style={{ color: includeAi ? 'rgb(var(--accent-blue))' : 'rgb(var(--text-muted))' }} />
                {includeAi ? 'Enabled' : 'Disabled'}
              </span>
              <button type="button" role="switch" aria-checked={includeAi} aria-label="Toggle AI synthesis"
                className="nxl-switch" data-on={includeAi} onClick={() => onIncludeAiChange(!includeAi)} />
            </div>
          </div>
        </div>

        {/* Analyst focus directive */}
        <div className="nxc-rise nxl-field rounded-xl px-4 py-3"
          style={{ background: 'rgb(var(--bg-primary) / 0.62)', border: '1px solid rgb(var(--bg-border) / 0.4)', ['--delay' as string]: '0.19s' }}>
          <p className="m-0 mb-1.5 flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-[0.24em]" style={{ color: 'rgb(var(--text-muted))' }}>
            <Cpu size={10} /> Analyst focus directive <span style={{ opacity: 0.6 }}>· optional</span>
          </p>
          <textarea
            value={focus}
            onChange={e => onFocusChange(e.target.value)}
            rows={2}
            placeholder="e.g. prioritise mixer exposure and bridge hops out of this cluster…"
            className="resize-none text-[12px] leading-relaxed"
            style={{ color: 'rgb(var(--text-bright))' }}
          />
        </div>

        {/* Mission readout */}
        <div className="nxc-rise flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-2.5"
          style={{
            background: 'rgb(var(--accent-blue) / 0.06)',
            border: '1px solid rgb(var(--accent-blue) / 0.22)',
            ['--delay' as string]: '0.25s',
          }}>
          <p className="m-0 font-mono text-[11px]" style={{ color: 'rgb(var(--text-secondary))' }}>
            <span style={{ color: 'rgb(var(--accent-blue))' }}>▸ </span>
            {readout}
            <span className="nxc-caret" style={{ color: 'rgb(var(--accent-blue))' }}> ▌</span>
          </p>
          <p className="m-0 text-[10px]" style={{ color: 'rgb(var(--text-muted))' }}>
            Depth is operator-set — no assumed default. Shielded Zcash/Monero value is private by design and not traceable.
          </p>
        </div>

        {/* Supported-chain ticker */}
        <div className="nxl-marquee nxc-rise" style={{ ['--delay' as string]: '0.3s' }}>
          <div>
            {[...TICKER, ...TICKER].map((c, i) => (
              <span key={i} className="whitespace-nowrap px-4 font-mono text-[9px] tracking-[0.24em]"
                style={{ color: 'rgb(var(--text-muted))', opacity: 0.55 }}>
                {c} <span style={{ color: 'rgb(var(--accent-blue))' }}>·</span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
