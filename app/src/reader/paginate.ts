// Book-page pagination of a reflowed (translated) page: fixed-size sheets, overflow continues on
// "devam" sheets of the same size. Fonts are never shrunk (rule 4); figures/code are never split.
//
// The planner is pure: it works on positions measured from a hidden, full-length render of the
// page (offsetTop/height in CSS px, one origin), so it is unit-testable without a layout engine.

export interface MeasuredUnit {
  /** Top and bottom of the unit (a sentence, a list item, a line). */
  top: number;
  bottom: number;
}

export interface MeasuredItem {
  /** Top/bottom of the top-level block, margins excluded. */
  top: number;
  bottom: number;
  /** Headings: never the last thing on a sheet. */
  keepWithNext?: boolean;
  /** Paragraphs and lists can break between these units; atomic blocks (code, figures) have none. */
  units?: MeasuredUnit[];
}

/** A slice of one item placed on a sheet: units [from, to) (whole item when undefined). */
export interface Slice {
  index: number;
  from?: number;
  to?: number;
}

export type SheetPlan = Slice[];

/**
 * Greedy fill: every sheet holds content whose span (first top → last bottom) fits `capacity`.
 * A paragraph/list that doesn't fit is split between units; at least one unit always moves on so
 * the plan always terminates. An atomic block taller than a whole sheet gets a sheet of its own
 * (that sheet grows instead of shrinking or clipping it).
 */
export function planSheets(items: readonly MeasuredItem[], capacity: number): SheetPlan[] {
  if (!items.length || capacity <= 0) return [items.map((_, index) => ({ index }))];
  const sheets: SheetPlan[] = [];
  let sheet: SheetPlan = [];
  let origin: number | null = null; // top of the first thing on the current sheet

  const newSheet = () => {
    if (sheet.length) sheets.push(sheet);
    sheet = [];
    origin = null;
  };

  for (let i = 0; i < items.length; i++) {
    const it = items[i]!;
    let from = 0;
    const units = it.units && it.units.length > 1 ? it.units : null;

    for (;;) {
      const start = units ? units[from]!.top : it.top;
      const base = origin ?? start;
      const fitsWhole = it.bottom - base <= capacity;
      if (fitsWhole) {
        sheet.push(from > 0 ? { index: i, from } : { index: i });
        if (origin === null) origin = start;
        break;
      }
      if (units) {
        // How many more units fit on this sheet?
        let to = from;
        while (to < units.length && units[to]!.bottom - base <= capacity) to++;
        // Widow: never leave a paragraph's last line alone at the top of the next sheet.
        if (to === units.length - 1 && to - from > 1) to--;
        // Orphan: don't start a paragraph with a single line at the bottom of a sheet.
        if (from === 0 && to === 1 && units.length > 2 && sheet.length > 0) to = 0;
        if (to > from) {
          if (to >= units.length) {
            // Every unit fits; only trailing padding overflows: keep the item whole here.
            sheet.push(from > 0 ? { index: i, from } : { index: i });
            if (origin === null) origin = start;
            break;
          }
          sheet.push({ index: i, from, to });
          from = to;
          newSheet();
          continue;
        }
      }
      if (sheet.length === 0) {
        // Nothing else on this sheet and it still doesn't fit: an over-tall atomic block (or a
        // single over-tall unit). It gets the sheet to itself.
        if (units) {
          sheet.push({ index: i, from, to: from + 1 });
          from += 1;
          newSheet();
          if (from >= units.length) break;
          continue;
        }
        sheet.push({ index: i });
        newSheet();
        break;
      }
      // Doesn't fit here: a heading left at the bottom moves along with it.
      const carried: Slice[] = [];
      while (sheet.length > 1) {
        const last = sheet[sheet.length - 1]!;
        if (last.from === undefined && last.to === undefined && items[last.index]?.keepWithNext) {
          carried.unshift(sheet.pop()!);
        } else break;
      }
      newSheet();
      if (carried.length) {
        sheet.push(...carried);
        origin = items[carried[0]!.index]!.top;
      }
    }
  }
  newSheet();
  return sheets.length ? sheets : [[]];
}

/** "25", "25 · devam", "25 · devam 2". */
export function folioLabel(page: number, part: number): string {
  if (part === 0) return String(page);
  return part === 1 ? `${page} · devam` : `${page} · devam ${part}`;
}

/** Recto/verso: even pages mirror the side margins like a printed spread. */
export function mirrorInsets<T extends { left: number; right: number }>(insets: T, page: number): T {
  return page % 2 === 0 ? { ...insets, left: insets.right, right: insets.left } : insets;
}

/** The chapter a page belongs to: the last top-level TOC entry at or before it. */
export function chapterFor<T extends { page: number; level: number }>(toc: readonly T[], page: number): T | null {
  if (!toc.length) return null;
  const top = Math.min(...toc.map((e) => e.level));
  let hit: T | null = null;
  for (const e of toc) if (e.level === top && e.page <= page && (!hit || e.page >= hit.page)) hit = e;
  return hit;
}
