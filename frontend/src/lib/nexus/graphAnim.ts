/**
 * graphAnim.ts — Animation toolkit for the Nexus Graph investigation canvas.
 *
 * Pure TypeScript + React hooks. No runtime dependencies (react only, already
 * a project dependency). Strict-TS safe, SSR/test safe (all DOM access is
 * guarded), and every animation respects the `prefers-reduced-motion` media
 * query by snapping instantly to the end state.
 *
 * ────────────────────────────────────────────────────────────────────────────
 * INTEGRATION GUIDE (for the agent wiring this into pages/NexusGraph.tsx)
 * ────────────────────────────────────────────────────────────────────────────
 *
 * 1) CAMERA — replace the instant `setViewDirect(...)` jumps.
 *
 *    NexusGraph.tsx today:
 *      - line 1083-1088  view state + `setViewDirect(v)` (instant)
 *      - line 1261       `setViewDirect({ x: 0, y: 0, z: 0.85 })` on new graph
 *      - line 1379-1395  `fitView()` computes pan/zoom then jumps instantly
 *      - line 1933       "Reset view" button jumps instantly
 *
 *    Wire it once inside the NexusGraph component:
 *
 *      ```ts
 *      import { useTweenView, fitViewTransform, HOME_VIEW, CAMERA_MS } from '../lib/nexus/graphAnim'
 *
 *      const animateViewTo = useTweenView(
 *        () => viewRef.current,      // getter — always the live camera
 *        (v) => setViewDirect(v),    // setter — writes ref + state each frame
 *      )
 *      // cancel on unmount is automatic; a new call supersedes the old one.
 *      ```
 *
 *    Then `fitView()` (lines 1379-1395) becomes:
 *
 *      ```ts
 *      function fitView() {
 *        const nodes = nodesRef.current.filter(n => !hidden.has(n.id) && (!subgraph || subgraph.ids.has(n.id)))
 *        const target = fitViewTransform(nodes, svgSize.w, svgSize.h, layout === 'flow' ? 180 : 100)
 *        if (target) animateViewTo(target)            // smooth, 450ms (CAMERA_MS)
 *      }
 *      ```
 *
 *    Reset-view button (line 1933): `animateViewTo(HOME_VIEW)`.
 *    Zoom-to-node (inspector "center" actions): build a View centred on the
 *    node — `{ x: W/2 - n.x * z, y: H/2 - n.y * z, z }` — and `animateViewTo(it)`.
 *
 *    NOTE: the exported `View` here is structurally identical to the local
 *    `type View = { x: number; y: number; z: number }` at NexusGraph.tsx:45,
 *    so the two are assignment-compatible in both directions.
 *
 * 2) LAYOUT SWITCHES — replace the hard fx/fy snap (lines 1291-1316).
 *
 *    Today switching force→flow→radial writes `n.fx/n.fy` instantly and the
 *    graph teleports. Instead, tween every node from its CURRENT position:
 *
 *      ```ts
 *      import { usePositionAnimator, LAYOUT_MS, easeInOutCubic } from '../lib/nexus/graphAnim'
 *
 *      const posAnim = usePositionAnimator({
 *        onFrame: (positions) => {
 *          const nodes = nodesRef.current
 *          for (const n of nodes) {
 *            const p = positions.get(n.id)
 *            if (p) { n.fx = p.x; n.fy = p.y; n.x = p.x; n.y = p.y }
 *          }
 *          setRenderTick(t => t + 1)      // re-render SVG each frame
 *        },
 *        onComplete: () => { simRef.current?.alpha(0.15).restart() },
 *      })
 *
 *      // inside the [layout] effect, non-force branch:
 *      const pos = layout === 'community' ? communityLayout(nodes, graph.seed, W, H)
 *                : layout === 'flow'      ? flowLayout(nodes, graph.edges, graph.seed, W, H)
 *                :                          radialLayout(nodes, graph.seed, W, H)
 *      posAnim.animateTo(pos, LAYOUT_MS, easeInOutCubic, { order: bfsOrderFromSeed })
 *      ```
 *
 *    - `order` is optional: an array of node ids in cascade order (e.g. BFS
 *      rank from the seed for flow layout). Nodes get a per-rank start delay
 *      capped at STAGGER_MAX_MS (120ms) for a polished ripple. Omit it to use
 *      distance-based stagger instead (nearby nodes lead, far nodes chase).
 *    - During the animation keep the d3 sim parked (alpha ~0) or at low alpha;
 *      writing fx/fy every frame pins nodes to the tween path either way.
 *    - Call `posAnim.setPosition(id, {x,y})` from the drag handler — it
 *      rewrites any in-flight tween for that node so drags never fight it.
 *    - After a force-mode tick, call `posAnim.setPositions(nodes)` so the
 *      animator's snapshot tracks the live simulation.
 *
 * 3) SUBGRAPH ISOLATE — ISOLATE_MS (400ms) is the reference duration for the
 *    subgraph open/close emphasis (opacity/scale fades on non-member nodes).
 *    Drive scalar fades with `tween({ from: 0, to: 1, duration: ISOLATE_MS, ... })`.
 *
 * ────────────────────────────────────────────────────────────────────────────
 */

import { useCallback, useEffect, useRef, useState } from 'react'

/* ========================================================================== */
/* Public types                                                                */
/* ========================================================================== */

/** 2-D point / node position. */
export interface XY {
  x: number
  y: number
}

/**
 * Pan/zoom camera: `x`,`y` are the SVG translate offsets (screen px) and `z`
 * the zoom scale. Structurally identical to `View` at NexusGraph.tsx:45.
 */
export interface View {
  x: number
  y: number
  z: number
}

/** Easing curve: maps linear progress t∈[0,1] → eased progress. */
export type EaseFn = (t: number) => number

/** Cancels a running animation. Safe to call multiple times. */
export type CancelFn = () => void

/* ========================================================================== */
/* Pro timing constants (ms)                                                   */
/* ========================================================================== */

/** Layout switches (force→flow→radial/community). */
export const LAYOUT_MS = 550
/** Camera moves: fitView, zoom-to-node, reset view. */
export const CAMERA_MS = 450
/** Subgraph isolate / emphasis transitions. */
export const ISOLATE_MS = 400
/** Cap on per-node cascade delay inside PositionAnimator. */
export const STAGGER_MAX_MS = 120

/**
 * The default camera used across NexusGraph.tsx (`{ x: 0, y: 0, z: 0.85 }` —
 * lines 1139, 1261, 1933). Use with `animateViewTo(HOME_VIEW)` for reset.
 */
export const HOME_VIEW: View = { x: 0, y: 0, z: 0.85 }

/* ========================================================================== */
/* Easing functions                                                            */
/* ========================================================================== */

/** Linear — no easing. */
export const linear: EaseFn = (t) => t

/**
 * Smooth symmetric acceleration/deceleration. The workhorse for layout
 * switches and camera moves — feels deliberate, never twitchy.
 */
export const easeInOutCubic: EaseFn = (t) =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2

/**
 * Fast start, long gentle settle. Best for camera zoom-ins and fitView where
 * you want to "arrive" softly at the target frame.
 */
export const easeOutExpo: EaseFn = (t) =>
  t >= 1 ? 1 : 1 - Math.pow(2, -10 * t)

/**
 * Slight overshoot then settle (c1 = 1.70158). Use sparingly for playful
 * micro-emphasis — e.g. a node "pop" when added to a subgraph. Not
 * recommended for whole-graph layout moves.
 */
export const easeOutBack: EaseFn = (t) => {
  const c1 = 1.70158
  const c3 = c1 + 1
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2)
}

/* ========================================================================== */
/* Environment helpers (SSR / test safe)                                       */
/* ========================================================================== */

const now = (): number =>
  typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now()

function raf(cb: (time: number) => void): number {
  if (typeof requestAnimationFrame === 'function') return requestAnimationFrame(cb)
  // Fallback for non-DOM environments (tests, SSR): ~60fps timer.
  return setTimeout(() => cb(now()), 16) as unknown as number
}

function caf(id: number): void {
  if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(id)
  else clearTimeout(id)
}

/**
 * True when the user asked the OS for reduced motion. Every animation entry
 * point in this module checks it (unless `respectReducedMotion: false`) and
 * snaps instantly to the end state — no motion, but callbacks still fire in
 * the same order, so integrators don't need branching logic.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * React hook variant of {@link prefersReducedMotion} that re-renders when the
 * OS setting changes. Use for non-animated fallbacks (e.g. disabling CSS
 * transitions on the SVG container too):
 *
 *   const reduced = useReducedMotion()
 *   <svg style={{ transition: reduced ? 'none' : undefined }} .../>
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(prefersReducedMotion)
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = () => setReduced(mq.matches)
    onChange()
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return reduced
}

/* ========================================================================== */
/* (b) tween — rAF-based scalar tween                                          */
/* ========================================================================== */

export interface TweenOptions {
  /** Start value. */
  from: number
  /** End value. */
  to: number
  /** Duration in ms. `<= 0` jumps instantly to `to`. */
  duration: number
  /** Easing curve. Defaults to {@link easeInOutCubic}. */
  ease?: EaseFn
  /** Start delay in ms. Defaults to 0. */
  delay?: number
  /**
   * Called every animation frame with `(value, linearProgress)`.
   * Guaranteed to fire at least once with the final value `(to, 1)`.
   */
  onUpdate: (value: number, progress: number) => void
  /** Called once after the final onUpdate. Not called if cancelled. */
  onComplete?: () => void
  /**
   * When false, ignore `prefers-reduced-motion`. Defaults to true (respect
   * it). Leave this on unless the motion is essential to comprehension.
   */
  respectReducedMotion?: boolean
}

/**
 * Animate a single number with requestAnimationFrame.
 *
 * Returns a cancel function; cancelling stops further callbacks (`onComplete`
 * will not fire). If the user prefers reduced motion, or `duration <= 0`, the
 * tween completes synchronously (single onUpdate + onComplete) and the
 * returned cancel is a no-op.
 *
 * @example Subgraph isolate fade (ISOLATE_MS):
 *   const cancel = tween({
 *     from: 1, to: 0.15, duration: ISOLATE_MS, ease: easeInOutCubic,
 *     onUpdate: (v) => setDimOpacity(v),
 *   })
 *   // later / on unmount: cancel()
 */
export function tween(opts: TweenOptions): CancelFn {
  const {
    from,
    to,
    duration,
    ease = easeInOutCubic,
    delay = 0,
    onUpdate,
    onComplete,
  } = opts
  const respectRM = opts.respectReducedMotion !== false

  // Instant paths: reduced motion or zero/negative duration.
  if ((respectRM && prefersReducedMotion()) || duration <= 0) {
    onUpdate(to, 1)
    onComplete?.()
    return () => {}
  }

  let rafId: number | null = null
  let cancelled = false
  const start = now() + Math.max(0, delay)

  const frame = (time: number) => {
    if (cancelled) return
    const elapsed = time - start
    if (elapsed < 0) {
      rafId = raf(frame)
      return
    }
    const t = Math.min(1, elapsed / duration)
    onUpdate(from + (to - from) * ease(t), t)
    if (t < 1) {
      rafId = raf(frame)
    } else {
      rafId = null
      onComplete?.()
    }
  }
  rafId = raf(frame)

  return () => {
    cancelled = true
    if (rafId !== null) {
      caf(rafId)
      rafId = null
    }
  }
}

/* ========================================================================== */
/* (c) tweenView — camera pan/zoom tween                                       */
/* ========================================================================== */

export interface TweenViewOptions {
  /** Duration in ms. Defaults to {@link CAMERA_MS} (450). */
  duration?: number
  /** Easing curve. Defaults to {@link easeInOutCubic}. */
  ease?: EaseFn
  /** Called once after the final frame. Not called if cancelled. */
  onComplete?: () => void
  /** When false, ignore `prefers-reduced-motion`. Defaults to true. */
  respectReducedMotion?: boolean
}

/**
 * Animate the pan/zoom camera between two Views.
 *
 * `x`/`y` interpolate linearly; `z` interpolates in log space so zooming
 * feels constant-speed (matching how d3-zoom / map UIs feel — linear zoom
 * interpolation appears to rush at high zoom and crawl at low zoom).
 *
 * The camera getter/setter wiring lives with the caller; inside NexusGraph
 * prefer the {@link useTweenView} hook which binds `viewRef`/`setViewDirect`,
 * auto-supersedes overlapping moves, and cancels on unmount.
 *
 * @example Manual use:
 *   const cancel = tweenView(viewRef.current, target, { duration: CAMERA_MS },
 *     (v) => setViewDirect(v))
 */
export function tweenView(
  from: View,
  to: View,
  opts: TweenViewOptions,
  onUpdate: (v: View) => void,
): CancelFn {
  const { duration = CAMERA_MS, ease = easeInOutCubic, onComplete } = opts
  const lz0 = Math.log(Math.max(from.z, 1e-6))
  const lz1 = Math.log(Math.max(to.z, 1e-6))

  return tween({
    from: 0,
    to: 1,
    duration,
    ease,
    respectReducedMotion: opts.respectReducedMotion,
    onUpdate: (p) => {
      onUpdate({
        x: from.x + (to.x - from.x) * p,
        y: from.y + (to.y - from.y) * p,
        z: Math.exp(lz0 + (lz1 - lz0) * p),
      })
    },
    onComplete,
  })
}

/**
 * React hook binding {@link tweenView} to a live camera getter/setter pair.
 *
 * - The returned `animateViewTo(to, opts?)` always starts from the CURRENT
 *   view (via `getView()`), so interrupting a move mid-flight is seamless.
 * - Starting a new move cancels the previous one (supersede semantics).
 * - The active tween is cancelled automatically on unmount.
 *
 * @example Inside NexusGraph (replaces instant setViewDirect jumps at
 * lines 1261/1379-1395/1933):
 *   const animateViewTo = useTweenView(() => viewRef.current, setViewDirect)
 *   // fitView:  const t = fitViewTransform(visible, w, h, pad); if (t) animateViewTo(t)
 *   // reset:     animateViewTo(HOME_VIEW)
 *   // zoom-to-node: animateViewTo({ x: W/2 - n.x*z, y: H/2 - n.y*z, z }, { duration: CAMERA_MS })
 */
export function useTweenView(
  getView: () => View,
  setView: (v: View) => void,
): (to: View, opts?: TweenViewOptions) => CancelFn {
  const ioRef = useRef({ getView, setView })
  useEffect(() => {
    ioRef.current = { getView, setView }
  })
  const cancelRef = useRef<CancelFn | null>(null)

  useEffect(
    () => () => {
      cancelRef.current?.()
      cancelRef.current = null
    },
    [],
  )

  return useCallback((to: View, opts: TweenViewOptions = {}): CancelFn => {
    cancelRef.current?.() // supersede any in-flight camera move
    const cancel = tweenView(
      ioRef.current.getView(),
      to,
      opts,
      (v) => ioRef.current.setView(v),
    )
    cancelRef.current = cancel
    return cancel
  }, [])
}

/* ========================================================================== */
/* (d) PositionAnimator — many-node position tweens                            */
/* ========================================================================== */

export interface PositionAnimatorOptions {
  /**
   * Called every animation frame with the live position map. THE SAME Map
   * instance is mutated and reused across frames (allocation-free hot path) —
   * read it synchronously (e.g. write positions into sim nodes and bump a
   * render tick) and never retain it.
   */
  onFrame: (positions: ReadonlyMap<string, XY>) => void
  /** Called once when an animateTo run fully completes. Not called on cancel. */
  onComplete?: () => void
  /** When false, ignore `prefers-reduced-motion`. Defaults to true. */
  respectReducedMotion?: boolean
}

export interface AnimateToOptions {
  /**
   * Max per-node start-delay spread in ms. Defaults to {@link STAGGER_MAX_MS}
   * (120). `0` disables stagger — every node starts on the same frame.
   */
  stagger?: number
  /**
   * Explicit cascade order: node ids listed earliest start first; ids missing
   * from the list start last. Ideal: BFS rank from the seed for flow layouts,
   * so the graph visibly ripples outward from the subject. When omitted,
   * stagger delay is derived from travel distance (nearby nodes lead).
   */
  order?: readonly string[]
  /** When false, ignore `prefers-reduced-motion` for this run. */
  respectReducedMotion?: boolean
}

interface NodeTween {
  fromX: number
  fromY: number
  toX: number
  toY: number
  delay: number
}

/**
 * Tweens MANY node positions at once on a single rAF loop.
 *
 * Designed for smooth Nexus Graph layout switches (force→flow→radial —
 * replacing the hard fx/fy snap at NexusGraph.tsx:1291-1316):
 *
 * - `animateTo(targets)` starts each node FROM ITS CURRENT position (even
 *   mid-flight from a previous run) so layout changes never teleport.
 * - A new `animateTo` supersedes the running one — no callback overlap.
 * - Stagger: optional per-node start delays (≤ {@link STAGGER_MAX_MS}) create
 *   a cascade; order by explicit rank (`order`) or by distance.
 * - `setPosition(s)` keeps the animator in sync with external truth: call it
 *   from drag handlers (per node) and after force-sim ticks (all nodes).
 * - Reduced motion → everything jumps instantly to targets, callbacks intact.
 *
 * Prefer the {@link usePositionAnimator} hook in React components — it owns
 * creation, keeps callbacks fresh, and destroys on unmount.
 */
export class PositionAnimator {
  private readonly cb: PositionAnimatorOptions
  private readonly live = new Map<string, XY>()
  private tweens = new Map<string, NodeTween>()
  private rafId: number | null = null
  private startTime = 0
  private duration: number = LAYOUT_MS
  private ease: EaseFn = easeInOutCubic
  private running = false
  private destroyed = false

  constructor(cb: PositionAnimatorOptions) {
    this.cb = cb
  }

  /** True while an animateTo run is in flight. */
  get animating(): boolean {
    return this.running
  }

  /**
   * Live position snapshot (mutated in place each frame — do not retain).
   * Includes every node ever set/animated, also ones not in the latest
   * animateTo targets (they simply hold their last position).
   */
  get positions(): ReadonlyMap<string, XY> {
    return this.live
  }

  /**
   * Bulk-sync positions WITHOUT animation (e.g. after every force-sim tick,
   * or to seed initial placement before the first animateTo). Any in-flight
   * tween for a synced node is rewritten so the node sticks at `p`.
   */
  setPositions(positions: Iterable<readonly [string, XY]>): void {
    for (const [id, p] of positions) this.writePosition(id, p)
  }

  /**
   * Set one node's position instantly — call from the node-drag handler so an
   * in-flight layout animation never fights the user's cursor.
   */
  setPosition(id: string, p: XY): void {
    this.writePosition(id, p)
  }

  /**
   * Animate all `targets` from their current positions over `duration` ms.
   * Supersedes any running animation. Returns a cancel function (equivalent
   * to calling {@link cancel}); the animator keeps the mid-flight positions.
   *
   * @param targets  id → destination (e.g. the Map returned by flowLayout /
   *                 radialLayout / communityLayout in NexusGraph.tsx).
   * @param duration ms per node (excluding stagger delay). Default LAYOUT_MS.
   * @param ease     easing curve. Default easeInOutCubic.
   * @param opts     stagger / order / reduced-motion overrides.
   */
  animateTo(
    targets: ReadonlyMap<string, XY>,
    duration: number = LAYOUT_MS,
    ease: EaseFn = easeInOutCubic,
    opts: AnimateToOptions = {},
  ): CancelFn {
    if (this.destroyed) return () => {}
    this.stopLoop()

    const respectRM =
      opts.respectReducedMotion ?? this.cb.respectReducedMotion ?? true
    const instant = (respectRM && prefersReducedMotion()) || duration <= 0

    // Build per-node tweens from CURRENT positions (mid-flight safe).
    const tweens = new Map<string, NodeTween>()
    for (const [id, target] of targets) {
      const cur = this.live.get(id)
      const fromX = cur ? cur.x : target.x // unknown nodes start at target
      const fromY = cur ? cur.y : target.y
      tweens.set(id, { fromX, fromY, toX: target.x, toY: target.y, delay: 0 })
      if (!cur) this.live.set(id, { x: target.x, y: target.y })
    }
    this.tweens = tweens

    if (instant) {
      for (const [id, tw] of tweens) {
        const cur = this.live.get(id)
        if (cur) {
          cur.x = tw.toX
          cur.y = tw.toY
        }
      }
      this.running = false
      this.cb.onFrame(this.live)
      this.cb.onComplete?.()
      return () => {}
    }

    this.applyStagger(tweens, opts)
    this.duration = duration
    this.ease = ease
    this.running = true
    this.startTime = now()
    this.rafId = raf(this.frame)

    return () => this.cancel()
  }

  /** Stop the current animation, keeping mid-flight positions. */
  cancel(): void {
    this.stopLoop()
  }

  /** Stop everything and release state. Call on unmount (the hook does). */
  destroy(): void {
    this.stopLoop()
    this.destroyed = true
    this.tweens.clear()
    this.live.clear()
  }

  /* ---------------------------------------------------------------------- */

  private writePosition(id: string, p: XY): void {
    const cur = this.live.get(id)
    if (cur) {
      cur.x = p.x
      cur.y = p.y
    } else {
      this.live.set(id, { x: p.x, y: p.y })
    }
    const tw = this.tweens.get(id)
    if (tw) {
      tw.fromX = p.x
      tw.fromY = p.y
      tw.toX = p.x
      tw.toY = p.y
      tw.delay = 0
    }
  }

  private applyStagger(
    tweens: Map<string, NodeTween>,
    opts: AnimateToOptions,
  ): void {
    const stagger =
      opts.stagger === undefined ? STAGGER_MAX_MS : Math.max(0, opts.stagger)
    if (stagger === 0 || tweens.size === 0) return

    if (opts.order && opts.order.length > 0) {
      // Explicit rank cascade: earliest ids lead, unlisted ids trail last.
      const rank = new Map<string, number>()
      opts.order.forEach((id, i) => rank.set(id, i))
      const denom = Math.max(opts.order.length - 1, 1)
      for (const [id, tw] of tweens) {
        const r = rank.get(id) ?? opts.order.length
        tw.delay = Math.min(stagger, (r / denom) * stagger)
      }
    } else {
      // Distance cascade: nodes with the shortest trip lead, far nodes chase.
      // Normalized by (d - dMin)/(dMax - dMin) so the leading node ALWAYS
      // starts at delay 0 — a single animated node moves immediately instead
      // of absorbing the full stagger delay.
      let dMin = Infinity
      let dMax = 0
      const dist = new Map<string, number>()
      for (const [id, tw] of tweens) {
        const d = Math.hypot(tw.toX - tw.fromX, tw.toY - tw.fromY)
        dist.set(id, d)
        if (d < dMin) dMin = d
        if (d > dMax) dMax = d
      }
      const spread = dMax - dMin
      if (spread <= 0) return
      for (const [id, tw] of tweens) {
        tw.delay = (((dist.get(id) ?? 0) - dMin) / spread) * stagger
      }
    }
  }

  private stopLoop(): void {
    if (this.rafId !== null) {
      caf(this.rafId)
      this.rafId = null
    }
    this.running = false
  }

  private readonly frame = (time: number): void => {
    if (this.destroyed) return
    const elapsed = time - this.startTime
    let allDone = true
    for (const [id, tw] of this.tweens) {
      const t = Math.min(1, Math.max(0, (elapsed - tw.delay) / this.duration))
      if (t < 1) allDone = false
      const e = this.ease(t)
      const cur = this.live.get(id)
      if (cur) {
        cur.x = tw.fromX + (tw.toX - tw.fromX) * e
        cur.y = tw.fromY + (tw.toY - tw.fromY) * e
      }
    }
    this.cb.onFrame(this.live)
    if (allDone) {
      this.running = false
      this.rafId = null
      this.cb.onComplete?.()
    } else {
      this.rafId = raf(this.frame)
    }
  }
}

/**
 * React hook owning a {@link PositionAnimator} for the component's lifetime.
 *
 * - The animator instance is stable across renders (safe in deps arrays).
 * - `onFrame`/`onComplete` may be inline closures — the hook always invokes
 *   the LATEST render's callbacks.
 * - Destroyed automatically on unmount (no orphaned rAF loops).
 *
 * @example NexusGraph layout-switch effect (replaces the fx/fy snap at
 * NexusGraph.tsx:1301-1313):
 *   const posAnim = usePositionAnimator({
 *     onFrame: (positions) => {
 *       for (const n of nodesRef.current) {
 *         const p = positions.get(n.id)
 *         if (p) { n.fx = p.x; n.fy = p.y; n.x = p.x; n.y = p.y }
 *       }
 *       setRenderTick(t => t + 1)
 *     },
 *   })
 *
 *   useEffect(() => {
 *     if (layout === 'force') { posAnim.cancel(); /* release fx/fy *\/ }
 *     else posAnim.animateTo(computeLayout(...), LAYOUT_MS, easeInOutCubic)
 *   }, [layout])
 */
export function usePositionAnimator(
  opts: PositionAnimatorOptions,
): PositionAnimator {
  const cbRef = useRef(opts)
  useEffect(() => {
    cbRef.current = opts
  })

  const animRef = useRef<PositionAnimator | null>(null)
  if (animRef.current === null) {
    animRef.current = new PositionAnimator({
      onFrame: (p) => cbRef.current.onFrame(p),
      onComplete: () => cbRef.current.onComplete?.(),
      respectReducedMotion: opts.respectReducedMotion,
    })
  }

  useEffect(
    () => () => {
      animRef.current?.destroy()
      animRef.current = null
    },
    [],
  )

  return animRef.current
}

/* ========================================================================== */
/* (e) fitViewTransform — pure pan/zoom framing helper                         */
/* ========================================================================== */

/**
 * Compute the pan/zoom {@link View} that frames `nodes` inside a W×H viewport
 * with `padding` px of breathing room, centred, capped at `maxZoom`.
 *
 * This is the extracted, pure form of the math inlined in NexusGraph.tsx's
 * `fitView()` (lines 1379-1395) — same formula, same defaults (pad 100 /
 * maxZoom 3; the existing flow-layout pad of 180 is the caller's choice).
 *
 * Degenerate cases are safe: single-node / coincident-node spans are clamped
 * to 1px, viewports smaller than 2×padding still produce a valid (very
 * zoomed-out) view instead of a negative scale.
 *
 * @returns the framing View, or `null` when there is nothing to frame
 *          (empty node list or non-positive viewport) — callers should bail
 *          out exactly like the current `if (!nodes.length) return`.
 *
 * @example
 *   const target = fitViewTransform(visibleNodes, svgSize.w, svgSize.h,
 *     layout === 'flow' ? 180 : 100)
 *   if (target) animateViewTo(target)          // smooth fitView
 *   // …or setViewDirect(target) for an instant jump on first graph load.
 */
export function fitViewTransform(
  nodes: readonly XY[],
  width: number,
  height: number,
  padding = 100,
  maxZoom = 3,
): View | null {
  if (nodes.length === 0 || width <= 0 || height <= 0) return null

  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  for (const n of nodes) {
    if (n.x < minX) minX = n.x
    if (n.x > maxX) maxX = n.x
    if (n.y < minY) minY = n.y
    if (n.y > maxY) maxY = n.y
  }

  const pad = Math.max(0, padding)
  const spanX = Math.max(maxX - minX, 1)
  const spanY = Math.max(maxY - minY, 1)
  const innerW = Math.max(width - pad * 2, 1)
  const innerH = Math.max(height - pad * 2, 1)
  const z = Math.min(innerW / spanX, innerH / spanY, maxZoom)

  return {
    x: pad - minX * z + (innerW - spanX * z) / 2,
    y: pad - minY * z + (innerH - spanY * z) / 2,
    z,
  }
}
