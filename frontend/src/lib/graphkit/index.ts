/**
 * graphkit — the shared graph design system for CrypTX's three investigative
 * graphs (NexusGraph, TraceGraph/FundTracer, BoardCanvas).
 *
 * Barrel re-export so graphs import from one place:
 *   import { GraphNodeKit, GraphMiniMap, classifyEntity, riskStyle, ENTITY_META } from '@/lib/graphkit'
 *
 * See individual module docstrings for detail. Pure (additive) — graphs opt in.
 */
export * from './riskPalette'
export * from './entityTypes'
export * from './nodeShapes'
export * from './TypeGlyph'
export * from './GraphNodeKit'
export * from './GraphMiniMap'
export * from './selection'
