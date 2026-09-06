/**
 * TypeGlyph — small monochrome pictograms for entity types, used as corner
 * badges on graph nodes (top-right) and as legend marks.
 *
 * Authored in a 24×24 box (Lucide-compatible) centred at (12,12), drawn with
 * `currentColor` so they inherit the entity-type accent color. These are
 * intentionally simple geometric pictograms (not full Lucide imports) so the
 * graphkit stays dependency-free.
 */
import type { ReactNode } from 'react'
import type { EntityType } from './entityTypes'

export interface TypeGlyphProps {
  type: EntityType
  size?: number
  /** stroke/fill color; defaults to currentColor so a parent <g color="..."> sets it */
  color?: string
  strokeWidth?: number
}

const P: Record<EntityType, ReactNode> = {
  // wallet — rounded pouch
  wallet: (
    <g fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round">
      <path d="M4 8 a2 2 0 0 1 2-2 h11 a2 2 0 0 1 2 2 v9 a2 2 0 0 1 -2 2 h-11 a2 2 0 0 1 -2 -2 z" />
      <path d="M4 9 h13" /><circle cx="16.5" cy="13.5" r="1.2" fill="currentColor" stroke="none" />
    </g>
  ),
  // contract — code brackets
  contract: (
    <g fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round">
      <path d="M9 7 L4 12 L9 17" /><path d="M15 7 L20 12 L15 17" /><path d="M13 5 L11 19" />
    </g>
  ),
  // exchange — building columns
  exchange: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round" strokeLinecap="round">
      <path d="M4 20 L20 20" /><path d="M5 20 L5 10" /><path d="M9.7 20 L9.7 10" /><path d="M14.3 20 L14.3 10" /><path d="M19 20 L19 10" />
      <path d="M3 10 L12 4 L21 10" /><path d="M4 7.5 L4 10 L20 10 L20 7.5" fill="currentColor" stroke="none" opacity="0.55" />
    </g>
  ),
  // mixer — swirl
  mixer: (
    <g fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round">
      <path d="M5 5 C 12 5, 12 12, 19 12 C 12 12, 12 19, 5 19" />
      <path d="M5 5 C 12 5, 12 12, 19 12" opacity="0.5" />
    </g>
  ),
  // bridge — two pillars + span
  bridge: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round" strokeLinecap="round">
      <path d="M3 9 C 8 4, 16 4, 21 9" /><path d="M6 9 L6 20" /><path d="M18 9 L18 20" />
      <path d="M3 9 L21 9" /><path d="M4 20 L8 20" /><path d="M16 20 L20 20" />
    </g>
  ),
  // dex — swap arrows
  dex: (
    <g fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round">
      <path d="M5 9 L17 9" /><path d="M14 6 L17 9 L14 12" />
      <path d="M19 15 L7 15" /><path d="M10 12 L7 15 L10 18" />
    </g>
  ),
  // scam — warning triangle + !
  scam: (
    <g fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round">
      <path d="M12 4 L21 19 L3 19 Z" /><path d="M12 10 L12 14" /><circle cx="12" cy="16.6" r="0.9" fill="currentColor" stroke="none" />
    </g>
  ),
  // sanctioned — shield-with-ban
  sanctioned: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round" strokeLinecap="round">
      <path d="M12 3 L20 6 L20 12 C 20 16, 16 19.5, 12 21 C 8 19.5, 4 16, 4 12 L4 6 Z" />
      <path d="M8 8 L16 16" opacity="0.7" />
    </g>
  ),
  // miner — pickaxe
  miner: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round" strokeLinecap="round">
      <path d="M4 4 C 9 4, 16 6, 20 11" /><path d="M20 4 C 15 4, 8 6, 4 11" />
      <path d="M12 11 L7 20" /><path d="M11 20 L14 20" />
    </g>
  ),
  // entity — person bust
  entity: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round" strokeLinecap="round">
      <circle cx="12" cy="8" r="3.4" /><path d="M5 20 C 5 15, 9 13.5, 12 13.5 C 15 13.5, 19 15, 19 20" />
    </g>
  ),
  // unknown — question dot
  unknown: (
    <g fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round" strokeLinecap="round">
      <circle cx="12" cy="12" r="8.5" /><path d="M9.5 9.5 a2.5 2.5 0 0 1 4.5 1.5 c0 1.8 -2.5 2 -2.5 3.5" /><circle cx="12" cy="16.5" r="0.9" fill="currentColor" stroke="none" />
    </g>
  ),
}

export function TypeGlyph({ type, size = 24, color, strokeWidth }: TypeGlyphProps): ReactNode {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      style={{ color: color || 'currentColor', display: 'block', overflow: 'visible' }}
      stroke={color}
      strokeWidth={strokeWidth}
      aria-hidden="true"
    >
      {P[type] || P.unknown}
    </svg>
  )
}
