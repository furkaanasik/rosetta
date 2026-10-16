import type { PageBlocks } from "../api/types";
import {
  blockAtPdfY,
  elementAtOffset,
  pdfScrollFor,
  syncableBlocks,
  translationScrollFor,
  type ElementBox,
} from "../lib/syncScroll";

const page: PageBlocks = {
  page: 1,
  width: 500,
  height: 700,
  has_text_layer: true,
  blocks: [
    { key: "0-2", order: 2, type: "paragraph", bbox: [72, 200, 432, 300], translatable: true, translated: true },
    { key: "0-0", order: 0, type: "heading", bbox: [72, 60, 432, 90], translatable: true, translated: true },
    { key: "0-1", order: 1, type: "paragraph", bbox: [72, 100, 432, 180], translatable: true, translated: true },
    { key: "0-3", order: 3, type: "furniture", bbox: [72, 650, 432, 660], translatable: false, translated: false },
  ],
};

// Translation pane: same order, different heights (Turkish is longer).
const boxes: ElementBox[] = [
  { key: "0-0", top: 0, height: 40 },
  { key: "0-1", top: 50, height: 120 },
  { key: "0-2", top: 180, height: 150 },
];

describe("sync scroll mapping", () => {
  it("sorts by vertical position and ignores furniture", () => {
    expect(syncableBlocks(page).map((b) => b.key)).toEqual(["0-0", "0-1", "0-2"]);
  });

  it("finds the block at a PDF y, or the next one below", () => {
    expect(blockAtPdfY(page, 70)?.key).toBe("0-0");
    expect(blockAtPdfY(page, 95)?.key).toBe("0-1"); // gap → next block
    expect(blockAtPdfY(page, 250)?.key).toBe("0-2");
    expect(blockAtPdfY(page, 690)?.key).toBe("0-2"); // past the end → last
  });

  it("maps PDF scroll to the matching translation element, proportionally", () => {
    // scale 2: PDF y 140 (middle of 0-1) → 280 px of PDF scroll.
    expect(translationScrollFor(page, 280, 2, boxes)).toBe(50 + 120 * 0.5);
  });

  it("maps translation scroll back to the PDF", () => {
    // halfway through 0-2 (top 180, height 150) → PDF y 250 → 500 px at scale 2
    expect(pdfScrollFor(page, 255, 2, boxes)).toBe(500);
  });

  it("round-trips approximately", () => {
    const t = translationScrollFor(page, 440, 2, boxes);
    expect(t).not.toBeNull();
    expect(pdfScrollFor(page, t ?? 0, 2, boxes)).toBeCloseTo(440, 5);
  });

  it("handles empty input", () => {
    expect(elementAtOffset([], 10)).toBeNull();
    expect(translationScrollFor({ ...page, blocks: [] }, 10, 1, boxes)).toBeNull();
  });
});
