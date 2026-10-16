import type { BlockInfo, PageBlocks } from "../api/types";

/** Blocks that take part in scroll sync (furniture is never rendered in the translation). */
export function syncableBlocks(page: PageBlocks): BlockInfo[] {
  return page.blocks
    .filter((b) => b.type !== "furniture")
    .slice()
    .sort((a, b) => a.bbox[1] - b.bbox[1] || a.order - b.order);
}

/**
 * The block at a vertical position on the PDF page (PDF points from the top).
 * Returns the block containing y, else the next block below y, else the last block.
 */
export function blockAtPdfY(page: PageBlocks, y: number): BlockInfo | null {
  const blocks = syncableBlocks(page);
  if (!blocks.length) return null;
  for (const b of blocks) {
    if (y <= b.bbox[3]) return b;
  }
  return blocks[blocks.length - 1] ?? null;
}

/** Fraction (0..1) of the way through a block at PDF y. */
export function fractionInBlock(block: BlockInfo, y: number): number {
  const [, y0, , y1] = block.bbox;
  const h = y1 - y0;
  if (h <= 0) return 0;
  return Math.min(1, Math.max(0, (y - y0) / h));
}

/** PDF y (points) for a block plus a fraction of its height. */
export function pdfYForBlock(block: BlockInfo, fraction = 0): number {
  const [, y0, , y1] = block.bbox;
  return y0 + (y1 - y0) * fraction;
}

export interface ElementBox {
  key: string;
  top: number; // offsetTop within the scroll container
  height: number;
}

/** The HTML element (by data-block key) at a scroll offset in the translation pane. */
export function elementAtOffset(boxes: ElementBox[], offset: number): ElementBox | null {
  if (!boxes.length) return null;
  const sorted = boxes.slice().sort((a, b) => a.top - b.top);
  for (const box of sorted) {
    if (offset < box.top + box.height) return box;
  }
  return sorted[sorted.length - 1] ?? null;
}

/**
 * PDF pane → translation pane: given the PDF scroll position (CSS px of the rendered page,
 * `scale` px per PDF point), return the translation pane scrollTop that shows the same block.
 */
export function translationScrollFor(
  page: PageBlocks,
  pdfScrollPx: number,
  scale: number,
  boxes: ElementBox[],
): number | null {
  const y = pdfScrollPx / scale;
  const block = blockAtPdfY(page, y);
  if (!block) return null;
  const box = boxes.find((b) => b.key === block.key);
  if (!box) return null;
  return box.top + box.height * fractionInBlock(block, y);
}

/** Translation pane → PDF pane: inverse of translationScrollFor. */
export function pdfScrollFor(
  page: PageBlocks,
  translationScroll: number,
  scale: number,
  boxes: ElementBox[],
): number | null {
  const box = elementAtOffset(boxes, translationScroll);
  if (!box) return null;
  const block = page.blocks.find((b) => b.key === box.key);
  if (!block) return null;
  const fraction = box.height > 0 ? (translationScroll - box.top) / box.height : 0;
  return pdfYForBlock(block, Math.min(1, Math.max(0, fraction))) * scale;
}

/**
 * The block under a click on the original page (PDF points). A block containing the point wins
 * (the smallest one if they nest); otherwise the vertically nearest block within 24 pt.
 */
export function blockAtPoint(page: PageBlocks, x: number, y: number): BlockInfo | null {
  const blocks = syncableBlocks(page);
  const hits = blocks.filter((b) => x >= b.bbox[0] && x <= b.bbox[2] && y >= b.bbox[1] && y <= b.bbox[3]);
  if (hits.length) {
    const area = (b: BlockInfo) => (b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1]);
    return hits.reduce((a, b) => (area(b) < area(a) ? b : a));
  }
  let best: BlockInfo | null = null;
  let bestD = 24;
  for (const b of blocks) {
    const d = y < b.bbox[1] ? b.bbox[1] - y : y > b.bbox[3] ? y - b.bbox[3] : 0;
    if (d <= bestD) {
      best = b;
      bestD = d;
    }
  }
  return best;
}
