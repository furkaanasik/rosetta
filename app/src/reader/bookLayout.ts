// DOM side of book pagination: measure a hidden full-length render of a page's HTML, plan sheets
// (paginate.ts) and build one HTML fragment per sheet. Paragraphs break between lines (via DOM
// ranges, so sentence spans/data attributes survive the cut); lists break between items; code,
// figures and tables are never broken.
import { planSheets, type MeasuredItem, type MeasuredUnit, type SheetPlan } from "./paginate";

interface Boundary {
  node: Node;
  offset: number;
}

export interface LineUnit extends MeasuredUnit {
  /** Where the line starts (paragraphs) — the cut point for a break before it. */
  start: Boundary | null;
}

export interface Entry {
  el: HTMLElement;
  item: MeasuredItem;
  kind: "para" | "list" | "atomic";
  lines?: LineUnit[];
}

const PARA = new Set(["P", "H1", "H2", "H3", "H4", "H5", "H6", "FIGCAPTION"]);
const HEADING = /^H[1-6]$/;

/** The engine wraps a page in <main class="page">; fall back to the container itself. */
function flowRoot(container: HTMLElement): HTMLElement {
  return container.querySelector<HTMLElement>(":scope > main") ?? container;
}

function textNodes(el: HTMLElement): Text[] {
  const out: Text[] = [];
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
    // Learn-mode glosses (<rt>) sit above the line; they never start a line of their own.
    acceptNode: (n) =>
      n.parentElement?.closest("rt") || !(n as Text).data.trim() ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  for (let n = walker.nextNode(); n; n = walker.nextNode()) out.push(n as Text);
  return out;
}

function charTop(node: Text, offset: number, range: Range): number {
  range.setStart(node, offset);
  range.setEnd(node, Math.min(node.length, offset + 1));
  const r = range.getClientRects()[0] ?? range.getBoundingClientRect();
  return r.top;
}

/** Line boxes of a block-level text element, with the DOM position each line starts at. */
export function measureLines(el: HTMLElement, originTop: number): LineUnit[] {
  const range = document.createRange();
  const starts: { top: number; start: Boundary | null }[] = [];
  const box = el.getBoundingClientRect();
  let lastTop = -Infinity;
  for (const node of textNodes(el)) {
    range.selectNodeContents(node);
    const rects = Array.from(range.getClientRects()).filter((r) => r.width > 0 && r.height > 0);
    if (!rects.length) continue;
    for (let i = 0; i < rects.length; i++) {
      const top = rects[i]!.top;
      if (top <= lastTop + 1) continue;
      let start: Boundary;
      if (i === 0) {
        start = { node, offset: 0 };
      } else {
        // First character whose box is on this line (binary search over the node's text).
        let lo = 0;
        let hi = node.length - 1;
        while (lo < hi) {
          const mid = (lo + hi) >> 1;
          if (charTop(node, mid, range) >= top - 1) hi = mid;
          else lo = mid + 1;
        }
        start = { node, offset: lo };
      }
      starts.push({ top, start: starts.length === 0 ? null : start });
      lastTop = top;
    }
  }
  range.detach?.();
  if (!starts.length) return [];
  return starts.map((s, i) => ({
    top: s.top - originTop,
    bottom: (i + 1 < starts.length ? starts[i + 1]!.top : box.bottom) - originTop,
    start: s.start,
  }));
}

/** Measures the top-level blocks of a hidden, full-length render. */
export function measureFlow(container: HTMLElement): Entry[] {
  const root = flowRoot(container);
  const origin = root.getBoundingClientRect().top;
  const entries: Entry[] = [];
  for (const el of Array.from(root.children) as HTMLElement[]) {
    const r = el.getBoundingClientRect();
    if (r.height === 0 && r.width === 0) continue;
    const item: MeasuredItem = { top: r.top - origin, bottom: r.bottom - origin };
    if (HEADING.test(el.tagName)) item.keepWithNext = true;
    if (PARA.has(el.tagName) && !HEADING.test(el.tagName)) {
      const lines = measureLines(el, origin);
      if (lines.length > 1) {
        item.units = lines;
        entries.push({ el, item, kind: "para", lines });
        continue;
      }
    } else if (el.tagName === "UL" || el.tagName === "OL") {
      const lis = Array.from(el.children).filter((c) => c.tagName === "LI") as HTMLElement[];
      if (lis.length > 1) {
        item.units = lis.map((li) => {
          const b = li.getBoundingClientRect();
          return { top: b.top - origin, bottom: b.bottom - origin };
        });
        entries.push({ el, item, kind: "list" });
        continue;
      }
    }
    entries.push({ el, item, kind: "atomic" });
  }
  return entries;
}

function sliceParagraph(entry: Entry, from: number, to: number | undefined): HTMLElement {
  const { el, lines = [] } = entry;
  const range = document.createRange();
  const startB = from > 0 ? lines[from]?.start : null;
  const endB = to !== undefined && to < lines.length ? lines[to]?.start : null;
  if (startB) range.setStart(startB.node, startB.offset);
  else range.setStart(el, 0);
  if (endB) range.setEnd(endB.node, endB.offset);
  else range.setEnd(el, el.childNodes.length);
  const out = el.cloneNode(false) as HTMLElement;
  out.append(range.cloneContents());
  if (from > 0) out.classList.add("rs-cont");
  if (endB) out.classList.add("rs-cut");
  return out;
}

function sliceList(entry: Entry, from: number, to: number | undefined): HTMLElement {
  const { el } = entry;
  const out = el.cloneNode(false) as HTMLElement;
  const lis = Array.from(el.children).filter((c) => c.tagName === "LI");
  lis.slice(from, to).forEach((li) => out.append(li.cloneNode(true)));
  if (el.tagName === "OL" && from > 0) {
    const start = Number(el.getAttribute("start") ?? "1") || 1;
    out.setAttribute("start", String(start + from));
  }
  return out;
}

/** One HTML string per sheet, keeping the engine's <main> wrapper attributes. */
export function buildSheets(container: HTMLElement, entries: Entry[], plans: SheetPlan[]): string[] {
  const root = flowRoot(container);
  const shell = root === container ? null : (root.cloneNode(false) as HTMLElement);
  return plans.map((plan) => {
    const host = (shell?.cloneNode(false) as HTMLElement | undefined) ?? document.createElement("div");
    for (const s of plan) {
      const entry = entries[s.index];
      if (!entry) continue;
      const whole = s.from === undefined && s.to === undefined;
      if (whole || entry.kind === "atomic") host.append(entry.el.cloneNode(true));
      else if (entry.kind === "para") host.append(sliceParagraph(entry, s.from ?? 0, s.to));
      else host.append(sliceList(entry, s.from ?? 0, s.to));
    }
    return shell ? host.outerHTML : host.innerHTML;
  });
}

/** Measure → plan → fragments. `capacity` is the sheet's text area height (CSS px). */
export function paginateRendered(container: HTMLElement, capacity: number): string[] {
  const entries = measureFlow(container);
  if (!entries.length) return [container.innerHTML];
  const plans = planSheets(
    entries.map((e) => e.item),
    capacity,
  );
  return buildSheets(container, entries, plans);
}
