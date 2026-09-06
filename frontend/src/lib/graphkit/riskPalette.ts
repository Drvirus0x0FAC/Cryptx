/**
 * riskPalette — the ONE unified risk visual language for every CrypTX graph.
 *
 * Replaces the three previously-duplicated, divergent risk maps:
 *   • TraceGraph `RISK_GLOW`      (7 buckets, glow flags)
 *   • NexusGraph `riskColor()`    (4 thresholds — and a bug: low-risk returned
 *                                  crimson #ff4052, same as the seed, so clean
 *                                  wallets visually echoed the suspect subject)
 *   • NexusIntelPanel `SEV_COLOR` / `RISK_COLORS`
 *
 * The tier scale is now monotonic and colorblind-aware (green → yellow → amber
 * → orange → red → crimson), with a dedicated `sanctioned` override because an
 * OFAC hit is categorical, not score-based. Glow is reserved for the two tiers
 * an analyst must not miss (sanctioned + critical).
 *
 * Everything here is pure (no React, no theme class reads) so it is trivially
 * testable and reusable from any rendering layer.
 */

export type RiskTier =
  | 'clean'        // 0–24  — no signal
  | 'low'          // 25–49 — mild exposure
  | 'medium'       // 50–69 — notable
  | 'high'         // 70–89 — serious
  | 'critical'     // 90+   — priority
  | 'sanctioned';  // categorical OFAC/sanctions hit

export interface RiskStyle {
  tier: RiskTier
  /** primary stroke / ring color */
  color: string
  /** soft fill for auras / backgrounds (low alpha) */
  soft: string
  /** true for tiers that pulse/glow (sanctioned, critical) */
  glow: boolean
  /** human label */
  label: string
}

const TIER_STYLES: Record<RiskTier, Omit<RiskStyle, 'tier'>> = {
  clean:      { color: '#22c55e', soft: 'rgba(34,197,94,0.14)',  glow: false, label: 'Clean' },
  low:        { color: '#84cc16', soft: 'rgba(132,204,22,0.14)', glow: false, label: 'Low' },
  medium:     { color: '#ffd60a', soft: 'rgba(255,214,10,0.16)', glow: false, label: 'Medium' },
  high:       { color: '#ff9f0a', soft: 'rgba(255,159,10,0.16)', glow: false, label: 'High' },
  critical:   { color: '#ff2d55', soft: 'rgba(255,45,85,0.18)',  glow: true,  label: 'Critical' },
  sanctioned: { color: '#f0356b', soft: 'rgba(240,53,107,0.20)', glow: true,  label: 'Sanctioned' },
}

/** Sort order for legends / tables (lowest risk first). */
export const RISK_TIER_ORDER: RiskTier[] = ['clean', 'low', 'medium', 'high', 'critical', 'sanctioned']

/**
 * Resolve a risk score (0–100) plus optional categorical flags into a tier.
 * `riskLevel` (string from the backend, e.g. 'clean'|'low'|'medium'|'high'|
 * 'critical'|'sanctioned') takes precedence when present, so categorical
 * sanctions hits always map to the sanctioned tier regardless of score.
 */
export function riskTier(
  score: number | null | undefined,
  riskLevel?: string | null,
  sanctioned?: boolean,
): RiskTier {
  if (sanctioned) return 'sanctioned'
  const lvl = (riskLevel || '').toLowerCase().trim()
  if (lvl === 'sanctioned') return 'sanctioned'
  if (lvl && (TIER_STYLES as Record<string, unknown>)[lvl]) return lvl as RiskTier
  const s = typeof score === 'number' && isFinite(score) ? score : 0
  if (s >= 90) return 'critical'
  if (s >= 70) return 'high'
  if (s >= 50) return 'medium'
  if (s >= 25) return 'low'
  return 'clean'
}

/** Full style record for a tier. The single source of truth for ring/aura color. */
export function riskStyle(
  score: number | null | undefined,
  riskLevel?: string | null,
  sanctioned?: boolean,
): RiskStyle {
  const tier = riskTier(score, riskLevel, sanctioned)
  return { tier, ...TIER_STYLES[tier] }
}

/** Style for a known tier directly (for legends). */
export function tierStyle(tier: RiskTier): RiskStyle {
  return { tier, ...TIER_STYLES[tier] }
}

/**
 * Arc geometry for the gauge ring drawn around a node. The arc starts at 12
 * o'clock and sweeps clockwise, its length proportional to risk_score/100.
 * Returns the strokeDasharray + offset for an SVG circle of the given radius.
 *
 * Example: `<circle r={r} stroke={style.color}
 *              strokeDasharray={arc.dash} strokeDashoffset={arc.offset} />`
 */
export function riskArc(score: number | null | undefined, radius: number): { dash: string; offset: number; pct: number } {
  const s = typeof score === 'number' && isFinite(score) ? Math.max(0, Math.min(100, score)) : 0
  const pct = s / 100
  const circ = 2 * Math.PI * radius
  return { dash: `${circ * pct} ${circ}`, offset: 0, pct }
}

/** True when a node's risk demands the pulsing attention aura. */
export function isHighRisk(
  score?: number | null,
  riskLevel?: string | null,
  sanctioned?: boolean,
): boolean {
  const st = riskStyle(score, riskLevel, sanctioned)
  return st.glow
}
