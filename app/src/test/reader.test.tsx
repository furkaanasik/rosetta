import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { MockEngineApi } from "../api/mock";
import type { PageBlocks } from "../api/types";
import { blockAtPoint } from "../lib/syncScroll";
import { useConfirmed } from "../lib/useConfirmed";
import {
  currentRow,
  fitZoom,
  insetsPx,
  rowEstimate,
  sheetInsetsPt,
  sheetSize,
  windowRange,
  MAX_ZOOM,
  MIN_ZOOM,
} from "../reader/geometry";
import { PageHtmlCache } from "../reader/htmlCache";
import { PageSheet } from "../reader/PageSheet";
import { ReaderCanvas, useProgressSaver } from "../reader/ReaderCanvas";

// jsdom has no layout: give elements a viewport-like size so the virtual list renders rows.
const sized: [string, PropertyDescriptor | undefined][] = [];
beforeAll(() => {
  for (const [prop, value] of [
    ["offsetWidth", 1024],
    ["offsetHeight", 800],
    ["clientWidth", 1024],
    ["clientHeight", 800],
  ] as const) {
    sized.push([prop, Object.getOwnPropertyDescriptor(HTMLElement.prototype, prop)]);
    Object.defineProperty(HTMLElement.prototype, prop, { configurable: true, get: () => value });
  }
});
afterAll(() => {
  for (const [prop, desc] of sized) if (desc) Object.defineProperty(HTMLElement.prototype, prop, desc);
});

describe("sheet sizing", () => {
  it("shows a page at its printed size at zoom 1 (1 pt = 96/72 px)", () => {
    expect(sheetSize(504, 661.5, 1)).toEqual({ width: 672, height: 882 });
    expect(sheetSize(612, 792, 1.5)).toEqual({ width: 1224, height: 1584 });
  });

  it("fits one or two sheets into the reading area", () => {
    // 1280 px wide area, 32 px padding each side → 1216 px for one 672-px-at-zoom-1 sheet.
    expect(fitZoom(504, 1280, 1)).toBeCloseTo(1216 / 672, 5);
    // Split: two sheets + 24 px gap.
    expect(fitZoom(504, 1280, 2)).toBeCloseTo((1216 - 24) / 2 / 672, 5);
    expect(fitZoom(504, 10, 1)).toBe(MIN_ZOOM);
    expect(fitZoom(100, 100_000, 1)).toBe(MAX_ZOOM);
  });

  it("derives sheet margins from the content box, with sane fallbacks", () => {
    expect(sheetInsetsPt(504, 661.5, [72, 60, 432, 600])).toEqual({ top: 60, left: 72, right: 72, bottom: 61.5 });
    // Unknown box → 11 % sides, 9 % top/bottom.
    const d = sheetInsetsPt(500, 1000, null);
    expect(d.left).toBeCloseTo(55);
    expect(d.top).toBeCloseTo(90);
    // A box outside the page is ignored.
    expect(sheetInsetsPt(500, 1000, [10, 10, 900, 20])).toEqual(d);
    // Content flush to the edge still keeps a minimum margin.
    expect(sheetInsetsPt(500, 1000, [0, 0, 500, 1000]).left).toBeCloseTo(20);
    expect(insetsPx({ top: 72, right: 72, bottom: 72, left: 72 }, 1)).toEqual({ top: 96, right: 96, bottom: 96, left: 96 });
  });

  it("row estimate = sheet + page number + gap", () => {
    expect(rowEstimate(661.5, 1)).toBe(882 + 28 + 32);
  });

  it("PageSheet: width equals the original, flow sheets grow (min-height), never shrink text", () => {
    const { container } = render(
      <PageSheet page={7} widthPt={504} heightPt={661.5} zoom={1} layout="flow" insets={{ top: 72, right: 72, bottom: 72, left: 72 }}>
        <p>metin</p>
      </PageSheet>,
    );
    const sheet = container.querySelector<HTMLElement>(".rs-sheet")!;
    expect(sheet.style.width).toBe("672px");
    expect(sheet.style.minHeight).toBe("882px");
    expect(sheet.style.height).toBe("");
    expect(sheet.style.getPropertyValue("--scale")).toBe("1");
    expect(sheet.style.paddingTop).toBe("96px");
    expect(sheet.style.paddingLeft).toBe("96px");
    expect(screen.getByText("7")).toHaveClass("rs-folio");
  });

  it("PageSheet fixed layout keeps the exact page proportions", () => {
    const { container } = render(
      <PageSheet page={1} widthPt={612} heightPt={792} zoom={0.5} layout="fixed">
        <span />
      </PageSheet>,
    );
    const sheet = container.querySelector<HTMLElement>(".rs-sheet")!;
    expect(sheet.style.width).toBe("408px");
    expect(sheet.style.height).toBe("528px");
  });
});

describe("virtualization window", () => {
  it("mounts the visible pages ± 2, clamped to the book", () => {
    expect(windowRange([5, 6], 100)).toEqual([3, 8]);
    expect(windowRange([0], 100)).toEqual([0, 2]);
    expect(windowRange([98, 99], 100)).toEqual([96, 99]);
    expect(windowRange([], 100)).toBeNull();
    expect(windowRange([0], 0)).toBeNull();
  });

  it("current page = the row crossing the line one third down the viewport", () => {
    const rows = [
      { index: 0, start: 0, end: 900 },
      { index: 1, start: 900, end: 1800 },
      { index: 2, start: 1800, end: 2700 },
    ];
    expect(currentRow(rows, 0, 900)).toBe(0); // line at 300
    expect(currentRow(rows, 700, 900)).toBe(1); // line at 1000
    expect(currentRow(rows, 1600, 900)).toBe(2); // line at 1900
    expect(currentRow(rows, 9000, 900)).toBe(2); // past the end → last row
    expect(currentRow([], 0, 900)).toBeNull();
  });

  it("keeps a bounded number of sheets in the DOM for a long book", async () => {
    const api = new MockEngineApi({ pageCount: 200 });
    await api.openBook("/kitap.pdf");
    render(
      <div style={{ height: 800 }}>
        <ReaderCanvas api={api} bookId={1} doc={null} pageCount={200} mode="original" zoom={1} page={1} revision={0} onPageChange={() => undefined} />
      </div>,
    );
    await waitFor(() => expect(document.querySelectorAll(".rs-sheet").length).toBeGreaterThan(0));
    const mounted = document.querySelectorAll(".rs-sheet").length;
    expect(mounted).toBeLessThanOrEqual(7);
    expect(document.querySelector('[data-page="1"]')).not.toBeNull();
  });
});

describe("split sync mapping", () => {
  const page: PageBlocks = {
    page: 1,
    width: 504,
    height: 661.5,
    has_text_layer: true,
    blocks: [
      { key: "0-0", order: 0, type: "heading", bbox: [72, 72, 432, 100], translatable: true, translated: true },
      { key: "0-1", order: 1, type: "paragraph", bbox: [72, 110, 432, 200], translatable: true, translated: true },
      { key: "0-2", order: 2, type: "furniture", bbox: [72, 620, 432, 640], translatable: false, translated: false },
      { key: "0-3", order: 3, type: "image", bbox: [100, 120, 200, 160], translatable: false, translated: false },
    ],
  };

  it("finds the block under a click (smallest when nested), ignoring furniture", () => {
    expect(blockAtPoint(page, 100, 80)?.key).toBe("0-0");
    expect(blockAtPoint(page, 150, 140)?.key).toBe("0-3"); // image nested inside the paragraph
    expect(blockAtPoint(page, 400, 150)?.key).toBe("0-1");
    expect(blockAtPoint(page, 100, 630)).toBeNull(); // furniture never pairs
  });

  it("falls back to the nearest block within 24 pt, else nothing", () => {
    expect(blockAtPoint(page, 100, 210)?.key).toBe("0-1");
    expect(blockAtPoint(page, 100, 400)).toBeNull();
  });
});

describe("page HTML cache", () => {
  it("reuses a page until the revision changes", async () => {
    const api = new MockEngineApi();
    await api.openBook("/k.pdf");
    let calls = 0;
    const orig = api.pageHtml.bind(api);
    api.pageHtml = (...a) => {
      calls += 1;
      return orig(...a);
    };
    const cache = new PageHtmlCache();
    await cache.get(api, 1, 2, "tr", 0);
    await cache.get(api, 1, 2, "tr", 0);
    expect(calls).toBe(1);
    await cache.get(api, 1, 2, "tr", 1);
    expect(calls).toBe(2);
  });
});

/** The app's wiring in miniature: untranslated card → estimate → (dialog) → confirm. */
function Harness({ api }: { api: MockEngineApi }) {
  const c = useConfirmed(() => undefined);
  const [rev, setRev] = useState(0);
  return (
    <div style={{ height: 800 }}>
      <ReaderCanvas
        api={api}
        bookId={1}
        doc={null}
        pageCount={3}
        mode="translation"
        zoom={1}
        page={1}
        revision={rev}
        onPageChange={() => undefined}
        onTranslatePage={(p) =>
          void c.request(
            () => api.estimateTranslate(1, { pages: [p] }),
            (t) => api.translate(1, t),
            () => setRev((r) => r + 1),
          )
        }
      />
      {c.pending && (
        <div role="dialog" aria-label="Maliyet onayı">
          <button type="button" onClick={c.cancel}>
            İptal
          </button>
          <button type="button" onClick={() => void c.confirm()}>
            Onayla
          </button>
        </div>
      )}
    </div>
  );
}

describe("untranslated sheet", () => {
  it("shows the card inside the sheet; the button only opens the cost dialog (no AI call)", async () => {
    const user = userEvent.setup();
    const api = new MockEngineApi({ pageCount: 3 });
    await api.openBook("/k.pdf");
    render(<Harness api={api} />);

    const buttons = await screen.findAllByRole("button", { name: "Bu sayfayı çevir" });
    expect(screen.getAllByText("Bu sayfa henüz çevrilmedi").length).toBeGreaterThan(0);
    // The card lives inside a paper sheet.
    expect(buttons[0]!.closest(".rs-sheet")).not.toBeNull();

    await user.click(buttons[0]!);
    expect(await screen.findByRole("dialog", { name: "Maliyet onayı" })).toBeInTheDocument();
    expect(api.aiCalls).toBe(0);

    await user.click(screen.getByRole("button", { name: "İptal" }));
    expect(api.aiCalls).toBe(0);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("translates only after Onayla, then the sheet shows the Turkish text", async () => {
    const user = userEvent.setup();
    const api = new MockEngineApi({ pageCount: 3 });
    await api.openBook("/k.pdf");
    render(<Harness api={api} />);

    const buttons = await screen.findAllByRole("button", { name: "Bu sayfayı çevir" });
    await user.click(buttons[0]!);
    await user.click(await screen.findByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(api.aiCalls).toBe(1));
    expect(await screen.findAllByText(/Replikasyon/)).not.toHaveLength(0);
  });
});

describe("learn and tr sheets: images and chapter labels", () => {
  const LEARN_HTML =
    '<main class="page" data-page="94"><h1 data-block="93-9" class="b-heading ff-sans">' +
    '<span class="h-label">CHAPTER 3</span> <span data-s="0"><span class="w" data-w="Data" data-l="data">Data</span> ' +
    '<ruby><span class="w" data-w="Models" data-l="model">Models</span><rt>modeller</rt></ruby></span></h1>' +
    '<figure class="fig fig-image"><img data-block="93-0" class="b-image ff-serif" src="assets/p094_b0_1d99d146.png" alt="image"></figure></main>';

  for (const mode of ["learn", "translation"] as const) {
    it(`${mode}: engine crops load through the bearer-token blob hook`, async () => {
      const api = new MockEngineApi({ pageCount: 1 });
      await api.openBook("/k.pdf");
      const fetched: string[] = [];
      api.pageHtml = async (_b, page, m) => ({
        page,
        mode: m,
        html: LEARN_HTML,
        translated_blocks: 1,
        translatable_blocks: 1,
        content_box: [72, 72, 432, 600],
      });
      api.assetBlob = async (_b, name) => {
        fetched.push(name);
        return new Blob(["x"], { type: "image/png" });
      };
      const urls: string[] = [];
      const create = URL.createObjectURL;
      URL.createObjectURL = () => {
        urls.push("blob:test");
        return "blob:test";
      };
      try {
        render(<ReaderCanvas api={api} bookId={1} doc={null} pageCount={1} mode={mode} zoom={1} page={1} revision={0} onPageChange={() => undefined} />);
        await waitFor(() => expect(fetched).toEqual(["p094_b0_1d99d146.png"]));
        const img = document.querySelector<HTMLImageElement>(".rs-html img")!;
        await waitFor(() => expect(img.getAttribute("src")).toBe("blob:test"));
        // The relative engine URL never reaches the DOM.
        expect(document.querySelector('img[src^="assets/"]')).toBeNull();
        // The engine's own chapter label is kept once (not split again).
        expect(document.querySelectorAll(".rs-html h1 .h-label")).toHaveLength(1);
        expect(document.querySelector(".rs-html h1 .h-label")?.textContent).toBe("CHAPTER 3");
        if (mode === "learn") expect(document.querySelector(".rs-html.mode-learn ruby rt")?.textContent).toBe("modeller");
      } finally {
        URL.createObjectURL = create;
      }
    });
  }
});

describe("reading position", () => {
  it("saves the last page at most once per delay, and flushes on unmount", async () => {
    const api = new MockEngineApi({ pageCount: 5 });
    await api.openBook("/k.pdf");
    const saved: number[] = [];
    const orig = api.saveProgress.bind(api);
    api.saveProgress = (b, p) => {
      saved.push(p);
      return orig(b, p);
    };
    const { result, unmount } = renderHook(() => useProgressSaver(api, 1, 20));
    act(() => {
      result.current(2);
      result.current(3);
      result.current(4);
    });
    expect(saved).toEqual([]);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(saved).toEqual([4]);
    act(() => result.current(5));
    unmount();
    expect(saved).toEqual([4, 5]);
    expect(api.lastPage).toBe(5);
  });

  it("external navigation is not echoed back as a page change", async () => {
    const api = new MockEngineApi({ pageCount: 5 });
    await api.openBook("/k.pdf");
    const seen: number[] = [];
    const props = { api, bookId: 1, doc: null, pageCount: 5, mode: "original" as const, zoom: 1, revision: 0, onPageChange: (p: number) => seen.push(p), progressDelayMs: 10 };
    const { rerender } = render(<ReaderCanvas {...props} page={1} />);
    rerender(<ReaderCanvas {...props} page={3} />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(seen).not.toContain(3);
  });
});
