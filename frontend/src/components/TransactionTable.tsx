import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ExternalLink, ArrowDownLeft, ArrowUpRight, Minus, Hash } from 'lucide-react'
import type { Transaction } from '../types'
import { useVirtualRows, midTrunc } from './VirtualRows'

interface Props {
  txs: Transaction[]
  chain?: string
  title?: string
  maxRows?: number
}

/** Above this row count the table switches to windowed (virtualized) rendering:
 *  every row stays reachable by scroll, but only ~40 are ever in the DOM. */
const VIRTUALIZE_AT = 100
const V_ROW_H = 34
const V_VIEWPORT = 480

// Chains with an internal TxDetail page
const INTERNAL_CHAINS = new Set(['ETH', 'MATIC', 'BSC', 'ARB', 'OP', 'BASE', 'BTC', 'TRX'])

const EXPLORER_TX: Record<string, string> = {
  ETH:  'https://etherscan.io/tx/',
  MATIC:'https://polygonscan.com/tx/',
  BSC:  'https://bscscan.com/tx/',
  ARB:  'https://arbiscan.io/tx/',
  OP:   'https://optimistic.etherscan.io/tx/',
  BASE: 'https://basescan.org/tx/',
  TRX:  'https://tronscan.org/#/transaction/',
  BTC:  'https://blockstream.info/tx/',
  SOL:  'https://solscan.io/tx/',
  LTC:  'https://blockchair.com/litecoin/transaction/',
  DOGE: 'https://blockchair.com/dogecoin/transaction/',
}

function txValue(tx: Transaction): string {
  if (tx.value_eth !== undefined && tx.value_eth !== 0)
    return `${tx.value_eth} ETH`
  if (tx.value_trx !== undefined && tx.value_trx !== 0)
    return `${tx.value_trx} TRX`
  if (tx.delta_btc !== undefined && tx.delta_btc !== 0)
    return `${tx.delta_btc > 0 ? '+' : ''}${tx.delta_btc} BTC`
  if (tx.value !== undefined && tx.value !== 0)
    return `${tx.value}${tx.token ? ' ' + tx.token : ''}`
  return '-'
}

function chainKey(chain?: string): string {
  return (chain ?? '').toUpperCase()
}

function txDetailPath(hash: string, chain?: string): string | null {
  const c = chainKey(chain)
  if (!hash || !INTERNAL_CHAINS.has(c)) return null
  return `/tx/${c}/${encodeURIComponent(hash)}`
}

function FullAddressCell({ address }: { address?: string }) {
  if (!address) return <span className="text-text-muted">-</span>
  return (
    <span className="block min-w-[220px] max-w-[520px] break-all font-mono text-[11px] leading-snug text-text-secondary" title={address}>
      {address}
    </span>
  )
}

function TxHashCell({ hash, chain }: { hash: string; chain?: string }) {
  if (!hash) return <span className="text-text-muted">-</span>
  const path = txDetailPath(hash, chain)

  if (path) {
    return (
      <Link
        to={path}
        onClick={e => e.stopPropagation()}
        className="flex min-w-[260px] items-start gap-1 break-all font-mono text-[11px] leading-snug transition-colors hover:underline"
        style={{ color: '#ff5a6e' }}
        title="Open transaction details"
      >
        <Hash size={9} className="mt-0.5 shrink-0" style={{ color: '#ff5a6e' }} />
        <span>{hash}</span>
      </Link>
    )
  }

  const c = chainKey(chain)
  const base = EXPLORER_TX[c]
  if (base) {
    return (
      <a
        href={base + hash}
        target="_blank"
        rel="noopener noreferrer"
        onClick={e => e.stopPropagation()}
        className="flex min-w-[260px] items-start gap-1 break-all font-mono text-[11px] leading-snug hover:underline"
        style={{ color: '#b09aa0' }}
      >
        <span>{hash}</span>
        <ExternalLink size={9} className="mt-0.5 shrink-0" />
      </a>
    )
  }

  return <span className="block min-w-[260px] break-all font-mono text-[11px] leading-snug text-text-secondary">{hash}</span>
}

export default function TransactionTable({ txs, chain, title = 'Transactions', maxRows = 25 }: Props) {
  const { t } = useTranslation()
  if (txs.length > VIRTUALIZE_AT)
    return <VirtualizedTxTable txs={txs} chain={chain} title={title} />
  return <ClassicTxTable txs={txs} chain={chain} title={title} maxRows={maxRows} />
}

/** Windowed table for huge result sets — all rows scrollable, ~40 in the DOM. */
function VirtualizedTxTable({ txs, chain, title }: { txs: Transaction[]; chain?: string; title: string }) {
  const navigate = useNavigate()
  const v = useVirtualRows(txs.length, V_ROW_H, V_VIEWPORT)
  return (
    <div className="card">
      <p className="card-title">
        {title} ({txs.length.toLocaleString()} fetched · virtualized)
      </p>
      <div className="overflow-auto" style={{ maxHeight: V_VIEWPORT }} onScroll={v.onScroll}>
        <table className="data-table w-full text-xs">
          <thead className="sticky top-0 z-10 bg-bg-primary">
            <tr>
              <th>Dir</th>
              <th>Time</th>
              <th>Hash</th>
              <th>From</th>
              <th>To</th>
              <th className="text-right">Value</th>
            </tr>
          </thead>
          <tbody>
            {v.topSpacer}
            {txs.slice(v.start, v.end).map((tx, i) => {
              const hash = tx.hash ?? tx.txid ?? ''
              const path = txDetailPath(hash, chain)
              return (
                <tr
                  key={v.start + i}
                  onClick={() => { if (path) navigate(path) }}
                  className={path ? 'cursor-pointer transition-colors hover:bg-bg-secondary/45' : undefined}
                  style={{ height: V_ROW_H }}
                  title={hash || undefined}
                >
                  <td>
                    {tx.direction === 'IN' ? (
                      <ArrowDownLeft size={12} style={{ color: '#34D399' }} />
                    ) : tx.direction === 'OUT' ? (
                      <ArrowUpRight size={12} style={{ color: '#F87171' }} />
                    ) : (
                      <Minus size={12} className="text-text-muted" />
                    )}
                  </td>
                  <td className="text-text-secondary whitespace-nowrap">{tx.time ? tx.time.slice(0, 19) : '-'}</td>
                  <td className="whitespace-nowrap font-mono text-[11px]" style={{ color: path ? '#ff5a6e' : undefined }}>
                    {midTrunc(hash, 12)}
                  </td>
                  <td className="whitespace-nowrap font-mono text-[11px] text-text-secondary" title={tx.from}>{midTrunc(tx.from, 10)}</td>
                  <td className="whitespace-nowrap font-mono text-[11px] text-text-secondary" title={tx.to}>{midTrunc(tx.to, 10)}</td>
                  <td className="text-right font-mono text-text-primary whitespace-nowrap">
                    {txValue(tx)}
                    {tx.is_error && <span className="ml-1" style={{ color: '#F87171' }}>[err]</span>}
                  </td>
                </tr>
              )
            })}
            {v.bottomSpacer}
          </tbody>
        </table>
      </div>
      <p className="text-text-muted text-xs mt-2">
        All {txs.length.toLocaleString()} rows scrollable — windowed rendering keeps the page fast.
      </p>
    </div>
  )
}

function ClassicTxTable({ txs, chain, title = 'Transactions', maxRows = 25 }: Props) {
  const navigate = useNavigate()
  const rows = txs.slice(0, maxRows)
  if (!rows.length)
    return (
      <div className="card">
        <p className="card-title">{title}</p>
        <p className="text-text-muted text-sm">No transactions available.</p>
      </div>
    )

  return (
    <div className="card">
      <p className="card-title">{title} ({txs.length} fetched)</p>
      <div className="overflow-x-auto">
        <table className="data-table w-full text-xs">
          <thead>
            <tr>
              <th>Dir</th>
              <th>Time</th>
              <th>Hash</th>
              <th>From</th>
              <th>To</th>
              <th className="text-right">Value</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((tx, i) => {
              const hash = tx.hash ?? tx.txid ?? ''
              const path = txDetailPath(hash, chain)
              return (
                <tr
                  key={i}
                  onClick={() => { if (path) navigate(path) }}
                  className={path ? 'cursor-pointer transition-colors hover:bg-bg-secondary/45' : undefined}
                  title={path ? 'Open transaction details' : undefined}
                >
                  <td>
                    {tx.direction === 'IN' ? (
                      <ArrowDownLeft size={12} style={{ color: '#34D399' }} />
                    ) : tx.direction === 'OUT' ? (
                      <ArrowUpRight size={12} style={{ color: '#F87171' }} />
                    ) : (
                      <Minus size={12} className="text-text-muted" />
                    )}
                  </td>
                  <td className="text-text-secondary whitespace-nowrap">
                    {tx.time ? tx.time.slice(0, 19) : '-'}
                  </td>
                  <td>
                    <TxHashCell hash={hash} chain={chain} />
                  </td>
                  <td><FullAddressCell address={tx.from} /></td>
                  <td><FullAddressCell address={tx.to} /></td>
                  <td className="text-right font-mono text-text-primary">
                    {txValue(tx)}
                    {tx.is_error && (
                      <span className="ml-1" style={{ color: '#F87171' }}>[err]</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {txs.length > maxRows && (
        <p className="text-text-muted text-xs mt-2">
          Showing {maxRows} of {txs.length} transactions.
        </p>
      )}
    </div>
  )
}
