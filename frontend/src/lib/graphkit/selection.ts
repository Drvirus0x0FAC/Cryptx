/**
 * selection — multi-select helpers shared by the graphs.
 *
 * None of the three graphs supported multi-select before (single selection
 * only). These pure helpers implement the selection-set model + rubber-band
 * marquee hit-testing, so each graph only has to wire pointer events.
 */

/** A point in screen/world coordinates. */
export interface Pt { x: number; y: number }

/** Axis-aligned rectangle (world coords). */
export interface Rect { x: number; y: number; w: number; h: number }

/** Normalise a rectangle so w/h are non-negative (drag up-left → down-right or vice-versa). */
export function normaliseRect(r: Rect): Rect {
  return {
    x: r.w < 0 ? r.x + r.w : r.x,
    y: r.h < 0 ? r.y + r.h : r.y,
    w: Math.abs(r.w),
    h: Math.abs(r.h),
  }
}

/** Point-in-rectangle test. */
export function pointInRect(p: Pt, r: Rect): boolean {
  const n = normaliseRect(r)
  return p.x >= n.x && p.x <= n.x + n.w && p.y >= n.y && p.y <= n.y + n.h
}

/**
 * Toggle membership in a selection set (for shift-click multi-select).
 * Returns a new Set (immutable) — never mutates the input.
 */
export function toggleInSet<T>(set: Set<T>, item: T): Set<T> {
  const next = new Set(set)
  if (next.has(item)) next.delete(item); else next.add(item)
  return next
}

/**
 * Add a list of ids to a selection set.
 */
export function addToSelection<T>(set: Set<T>, items: Iterable<T>): Set<T> {
  const next = new Set(set)
  for (const it of items) next.add(it)
  return next
}

/**
 * Marquee selection: given a rectangle and a list of positioned nodes, return
 * the ids of the nodes whose centre falls inside the (normalised) rectangle.
 */
export function selectInRect<T extends { id: string; x: number; y: number }>(nodes: T[], rect: Rect): string[] {
  const n = normaliseRect(rect)
  const hits: string[] = []
  for (const node of nodes) {
    if (node.x >= n.x && node.x <= n.x + n.w && node.y >= n.y && node.y <= n.y + n.h) {
      hits.push(node.id)
    }
  }
  return hits
}

/**
 * Decide the next selection state from a click event.
 *  - shift-click → toggle the clicked id in the set (multi-select)
 *  - plain click when the id is already in a multi-selection → keep as-is
 *    (the caller will usually clear-on-drag; on mouseup-without-drag it reduces
 *    to just the clicked id)
 *  - plain click → single selection of the id
 */
export function selectionFromClick<T>(current: Set<T>, id: T, shiftKey: boolean): Set<T> {
  if (shiftKey) return toggleInSet(current, id)
  if (current.size > 1 && current.has(id)) return current
  return new Set([id])
}
