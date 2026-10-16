// Pure layout math for the page-sheet reader (docs/ui-redesign.md §3.2–3.3).
import type { BBox } from "../api/types";

/** CSS px per PDF point at zoom 1 (a page shows at its printed size). */
export const PT_TO_PX = 96 / 72;
/** Vertical gap between sheets, CSS px. */
export const SHEET_GAP = 32;
/** Horizontal gap between the two sheets of a split row, CSS px. */
export const SPLIT_GAP = 24;
/** Room under each sheet for the page number, CSS px. */
export const FOOTER_SPACE = 28;
/** Side padding of the reading area, CSS px. */
export const CANVAS_PADDING = 32;

export const MIN_ZOOM = 0.5;
export const MAX_ZOOM = 3;

export interface Size {
  width: number;
  height: number;
}

export interface Insets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export function clampZoom(zoom: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

/** On-screen size (CSS px) of a page of `width`×`height` PDF points. */
export function sheetSize(widthPt: number, heightPt: number, zoom: number): Size {
  const k = zoom * PT_TO_PX;
  return { width: Math.round(widthPt * k), height: Math.round(heightPt * k) };
}

/**
 * Zoom that fits `columns` sheets of `widthPt` side by side into `available` px
 * (reading-area padding and the split gap included).
 */
export function fitZoom(widthPt: number, available: number, columns: 1 | 2 = 1): number {
  const room = available - CANVAS_PADDING * 2 - (columns - 1) * SPLIT_GAP;
  if (widthPt <= 0 || room <= 0) return MIN_ZOOM;
  return clampZoom(room / columns / (widthPt * PT_TO_PX));
}

/** Fallback margins when the content box is unknown: 11 % at the sides, 9 % top/bottom. */
export function defaultInsetsPt(widthPt: number, heightPt: number): Insets {
  const side = widthPt * 0.11;
  const tb = heightPt * 0.09;
  return { top: tb, right: side, bottom: tb, left: side };
}

/**
 * Inner margins of a sheet (PDF points), derived from the page's content box so the reflowed
 * translation sits where the original text sits. Implausible boxes fall back to the defaults.
 */
export function sheetInsetsPt(widthPt: number, heightPt: number, box?: BBox | null): Insets {
  const fallback = defaultInsetsPt(widthPt, heightPt);
  if (!box) return fallback;
  const [x0, y0, x1, y1] = box;
  if (!(x1 > x0 && y1 > y0) || x0 < 0 || y0 < 0 || x1 > widthPt || y1 > heightPt) return fallback;
  const minSide = widthPt * 0.04;
  const minTb = heightPt * 0.04;
  return {
    top: Math.max(minTb, y0),
    left: Math.max(minSide, x0),
    right: Math.max(minSide, widthPt - x1),
    // The bottom margin keeps the original's but never less than the space the page number uses.
    bottom: Math.max(minTb, Math.min(heightPt - y1, heightPt * 0.12)),
  };
}

/** Insets in CSS px at a zoom. */
export function insetsPx(insets: Insets, zoom: number): Insets {
  const k = zoom * PT_TO_PX;
  return {
    top: Math.round(insets.top * k),
    right: Math.round(insets.right * k),
    bottom: Math.round(insets.bottom * k),
    left: Math.round(insets.left * k),
  };
}

/** Estimated height of one virtual row (sheet + its page number + the gap). */
export function rowEstimate(heightPt: number, zoom: number): number {
  return Math.round(heightPt * zoom * PT_TO_PX) + FOOTER_SPACE + SHEET_GAP;
}

export interface RowSpan {
  index: number;
  start: number;
  end: number;
}

/**
 * The page being read: the row that crosses the line one third down the viewport. If the
 * line falls into a gap, the next row below wins (falling back to the last row above).
 */
export function currentRow(rows: readonly RowSpan[], scrollTop: number, viewportHeight: number): number | null {
  if (!rows.length) return null;
  const line = scrollTop + viewportHeight / 3;
  let above: RowSpan | null = null;
  for (const r of rows) {
    if (line >= r.start && line < r.end) return r.index;
    if (r.start > line) return r.index;
    above = r;
  }
  return above?.index ?? null;
}

/** Pages [first, last] (0-based indexes) that must be mounted: visible ± overscan. */
export function windowRange(visible: readonly number[], count: number, overscan = 2): [number, number] | null {
  if (!visible.length || count <= 0) return null;
  const lo = Math.max(0, Math.min(...visible) - overscan);
  const hi = Math.min(count - 1, Math.max(...visible) + overscan);
  return [lo, hi];
}
