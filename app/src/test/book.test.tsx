import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MockEngineApi } from "../api/mock";
import { App } from "../App";
import { buildSheets, type Entry } from "../reader/bookLayout";
import { hyphenateTurkish, stripSoftHyphens, syllableBreaks } from "../reader/hyphenate";
import { chapterFor, folioLabel, mirrorInsets, planSheets, type MeasuredItem } from "../reader/paginate";
import { ReaderCanvas, useProgressSaver } from "../reader/ReaderCanvas";
import { renderHook } from "@testing-library/react";

vi.mock("../lib/pdf", () => ({
  loadPdf: vi.fn(),
  outline: vi.fn(async () => []),
}));

/** n stacked blocks of height h with a gap g (px, one origin). */
function stack(heights: number[], gap = 10, extra: Partial<MeasuredItem>[] = []): MeasuredItem[] {
  let y = 0;
  return heights.map((h, i) => {
    const it: MeasuredItem = { top: y, bottom: y + h, ...extra[i] };
    y += h + gap;
    return it;
  });
}

/** A paragraph of `lines` lines (lineHeight px) starting at `top`. */
function para(top: number, lines: number, lineHeight = 20): MeasuredItem {
  const units = Array.from({ length: lines }, (_, i) => ({ top: top + i * lineHeight, bottom: top + (i + 1) * lineHeight }));
  return { top, bottom: top + lines * lineHeight, units };
}

/** Span (first top → last bottom) of a sheet's content, for overflow checks. */
function span(items: MeasuredItem[], sheet: { index: number; from?: number; to?: number }[]): number {
  const first = sheet[0]!;
  const last = sheet[sheet.length - 1]!;
  const fi = items[first.index]!;
  const li = items[last.index]!;
  const top = first.from !== undefined && fi.units ? fi.units[first.from]!.top : fi.top;
  const bottom = last.to !== undefined && li.units ? li.units[last.to - 1]!.bottom : li.bottom;
  return bottom - top;
}

describe("book pagination planner", () => {
  it("keeps everything on one sheet when it fits", () => {
    expect(planSheets(stack([100, 100, 100]), 400)).toEqual([[{ index: 0 }, { index: 1 }, { index: 2 }]]);
  });

  it("never lets a sheet's content exceed its height, and keeps every block (in order)", () => {
    const items = stack([120, 200, 90, 300, 60, 150, 220]);
    const plans = planSheets(items, 400);
    for (const s of plans) expect(span(items, s)).toBeLessThanOrEqual(400);
    expect(plans.flat().map((s) => s.index)).toEqual([0, 1, 2, 3, 4, 5, 6]);
  });

  it("breaks a long paragraph between lines and continues it on the next sheet", () => {
    const items = [{ top: 0, bottom: 300 }, para(310, 10)]; // 300 + 200 > 400
    const plans = planSheets(items, 400);
    expect(plans).toHaveLength(2);
    expect(plans[0]).toEqual([{ index: 0 }, { index: 1, from: 0, to: 4 }]);
    expect(plans[1]).toEqual([{ index: 1, from: 4 }]);
    for (const s of plans) expect(span(items, s)).toBeLessThanOrEqual(400);
  });

  it("avoids widows (last line alone) and orphans (first line alone)", () => {
    // 5 lines, 4 would fit → 3 + 2 instead of 4 + 1.
    const widow = planSheets([{ top: 0, bottom: 300 }, para(310, 5)], 395);
    expect(widow[0]![1]).toEqual({ index: 1, from: 0, to: 3 });
    // Only one line would fit at the bottom → the whole paragraph moves on.
    const orphan = planSheets([{ top: 0, bottom: 360 }, para(370, 6)], 395);
    expect(orphan[0]).toEqual([{ index: 0 }]);
    expect(orphan[1]![0]).toEqual({ index: 1 });
  });

  it("never splits code/figures (atomic) and moves a heading along with its paragraph", () => {
    const items = stack([250, 40, 200], 10, [{}, { keepWithNext: true }, {}]); // heading at 260–300
    const plans = planSheets(items, 320);
    expect(plans[0]).toEqual([{ index: 0 }]);
    expect(plans[1]).toEqual([{ index: 1 }, { index: 2 }]);
  });

  it("gives an over-tall atomic block a sheet of its own instead of shrinking it", () => {
    const plans = planSheets(stack([100, 900, 100]), 400);
    expect(plans).toEqual([[{ index: 0 }], [{ index: 1 }], [{ index: 2 }]]);
  });

  it("labels continuation sheets and mirrors margins on even pages", () => {
    expect(folioLabel(25, 0)).toBe("25");
    expect(folioLabel(25, 1)).toBe("25 · devam");
    expect(folioLabel(25, 2)).toBe("25 · devam 2");
    expect(mirrorInsets({ left: 1, right: 2, top: 0, bottom: 0 }, 2)).toEqual({ left: 2, right: 1, top: 0, bottom: 0 });
    expect(mirrorInsets({ left: 1, right: 2, top: 0, bottom: 0 }, 3)).toEqual({ left: 1, right: 2, top: 0, bottom: 0 });
  });

  it("finds the chapter (top-level TOC entry) a page belongs to", () => {
    const toc = [
      { title: "Önsöz", page: 3, level: 1 },
      { title: "Bölüm 1", page: 25, level: 1 },
      { title: "Alt başlık", page: 30, level: 2 },
      { title: "Bölüm 2", page: 49, level: 1 },
    ];
    expect(chapterFor(toc, 30)?.title).toBe("Bölüm 1");
    expect(chapterFor(toc, 49)?.title).toBe("Bölüm 2");
    expect(chapterFor(toc, 1)).toBeNull();
  });
});

describe("sheet fragments keep the engine's attributes", () => {
  it("slices a list between items (numbering continues) and a paragraph at a line start", () => {
    const root = document.createElement("div");
    root.innerHTML =
      '<main class="page" data-page="7"><p data-block="6-1" class="b-paragraph"><span data-s="0">Birinci cümle burada.</span> <span data-s="1">İkinci cümle.</span></p>' +
      '<ol class="list" start="3"><li data-block="6-2">a</li><li data-block="6-3">b</li><li data-block="6-4">c</li></ol></main>';
    const main = root.querySelector("main")!;
    const p = main.children[0] as HTMLElement;
    const ol = main.children[1] as HTMLElement;
    const second = p.querySelector('[data-s="1"]')!.firstChild!;
    const entries: Entry[] = [
      {
        el: p,
        kind: "para",
        item: { top: 0, bottom: 40 },
        lines: [
          { top: 0, bottom: 20, start: null },
          { top: 20, bottom: 40, start: { node: second, offset: 0 } },
        ],
      },
      { el: ol, kind: "list", item: { top: 50, bottom: 110 } },
    ];
    const sheets = buildSheets(root, entries, [
      [{ index: 0, from: 0, to: 1 }],
      [
        { index: 0, from: 1 },
        { index: 1, from: 0, to: 1 },
      ],
      [{ index: 1, from: 1 }],
    ]);
    const doc = sheets.map((h) => {
      const d = document.createElement("div");
      d.innerHTML = h;
      return d;
    });
    // The engine's <main> wrapper survives on every sheet.
    for (const d of doc) expect(d.querySelector('main.page[data-page="7"]')).not.toBeNull();
    // Paragraph: cut sheet keeps sentence 0 and is marked; continuation starts flush with sentence 1.
    const cut = doc[0]!.querySelector("p")!;
    expect(cut.dataset.block).toBe("6-1");
    expect(cut.classList.contains("rs-cut")).toBe(true);
    expect(cut.textContent).toContain("Birinci cümle");
    expect(cut.textContent).not.toContain("İkinci");
    const cont = doc[1]!.querySelector("p")!;
    expect(cont.dataset.block).toBe("6-1");
    expect(cont.classList.contains("rs-cont")).toBe(true);
    expect(cont.querySelector('[data-s="1"]')?.textContent).toBe("İkinci cümle.");
    // List: second slice continues the numbering.
    expect(doc[1]!.querySelectorAll("li")).toHaveLength(1);
    const rest = doc[2]!.querySelector("ol")!;
    expect(rest.getAttribute("start")).toBe("4");
    expect(Array.from(rest.querySelectorAll("li")).map((l) => l.dataset.block)).toEqual(["6-3", "6-4"]);
  });
});

describe("Turkish hyphenation", () => {
  it("breaks at syllables (consonant before a vowel; vowel pairs)", () => {
    const cut = (w: string) => {
      const b = syllableBreaks(w);
      let out = "";
      let last = 0;
      for (const i of b) {
        out += w.slice(last, i) + "-";
        last = i;
      }
      return out + w.slice(last);
    };
    expect(cut("kapı")).toBe("ka-pı");
    expect(cut("arka")).toBe("ar-ka");
    expect(cut("korkmak")).toBe("kork-mak");
    expect(cut("santral")).toBe("sant-ral");
    expect(cut("saat")).toBe("sa-at");
    expect(cut("trafik")).toBe("tra-fik");
  });

  it("inserts soft hyphens only into long words, keeping 2 + 3 letters around a break", () => {
    const out = hyphenateTurkish("Kullanıcılar ve SQL sorguları 2024");
    expect(stripSoftHyphens(out)).toBe("Kullanıcılar ve SQL sorguları 2024");
    expect(out).toContain("Kul­la­nı­cı­lar");
    expect(out).toContain(" ve SQL ");
    expect(out.split(" ")[4]).toBe("2024");
  });
});

describe("resume where the reader left off", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("opening a book jumps to its saved page and offers 'Başa dön'", async () => {
    const api = new MockEngineApi();
    api.lastPage = 7;
    vi.spyOn(window, "prompt").mockReturnValue("/books/kitap.pdf");
    const user = userEvent.setup();
    render(<App api={api} mock />);
    await user.click(await screen.findByRole("button", { name: "PDF aç" }));
    const toast = await screen.findByText("Kaldığınız yer: sayfa 7");
    expect(screen.getByLabelText("Sayfa numarası")).toHaveValue("7");
    await user.click(within(toast.closest("[role=status], .toast, li, div")!.parentElement!).getByRole("button", { name: "Başa dön" }));
    await waitFor(() => expect(screen.getByLabelText("Sayfa numarası")).toHaveValue("1"));
  });

  it("the initial scroll offset never overwrites the saved page with page 1", async () => {
    const api = new MockEngineApi({ pageCount: 9 });
    await api.openBook("/k.pdf");
    const saved: number[] = [];
    const orig = api.saveProgress.bind(api);
    api.saveProgress = (b, p) => {
      saved.push(p);
      return orig(b, p);
    };
    const pages: number[] = [];
    render(
      <ReaderCanvas api={api} bookId={1} doc={null} pageCount={9} mode="translation" zoom={1} page={6} revision={0} progressDelayMs={5} onPageChange={(p) => pages.push(p)} />,
    );
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60));
    });
    expect(saved).not.toContain(1);
    expect(pages).not.toContain(1);
  });

  it("flushes the pending page when the window is hidden or closed", () => {
    const api = new MockEngineApi({ pageCount: 5 });
    const saved: number[] = [];
    api.saveProgress = async (_b, p) => {
      saved.push(p);
    };
    const { result } = renderHook(() => useProgressSaver(api, 1, 10_000));
    act(() => result.current(4));
    expect(saved).toEqual([]);
    act(() => {
      window.dispatchEvent(new Event("pagehide"));
    });
    expect(saved).toEqual([4]);
    act(() => result.current(5));
    act(() => {
      window.dispatchEvent(new Event("beforeunload"));
    });
    expect(saved).toEqual([4, 5]);
  });
});

describe("paragraph joined across a PDF page break", () => {
  it("keeps the continuation classes through sanitizing and slicing", async () => {
    const { sanitizeEngineHtml } = await import("../lib/sanitize");
    const html = sanitizeEngineHtml(
      '<main class="page" data-page="38"><p data-block="38-0" class="b-paragraph cont-prev">şekilde tasarlanan.</p>' +
        '<p data-block="38-1" class="b-paragraph ff-serif cont-prev joined-empty"></p></main>',
    );
    const root = document.createElement("div");
    root.innerHTML = html;
    const [cont, empty] = Array.from(root.querySelectorAll("p"));
    expect(cont!.classList.contains("cont-prev")).toBe(true);
    expect(empty!.className).toContain("joined-empty");
  });

  it("reader CSS starts a continuation flush and hides an empty tail outside side-by-side", async () => {
    const { readFileSync } = await import("node:fs");
    const css = readFileSync(`${process.cwd()}/src/reader/reader.css`, "utf8");
    expect(css).toMatch(/p\.cont-prev\s*\{\s*text-indent:\s*0 !important;/);
    expect(css).toMatch(/\.rs-html:not\(\.mode-review\) \.joined-empty\s*\{\s*display:\s*none;/);
  });
});
