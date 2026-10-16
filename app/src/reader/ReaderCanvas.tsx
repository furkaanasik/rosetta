import { useVirtualizer, type Virtualizer } from "@tanstack/react-virtual";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EngineApi } from "../api/engine";
import type { BBox, PageBlocks, PageInfo, ViewMode } from "../api/types";
import type { PdfDoc } from "../lib/pdf";
import { blockAtPoint } from "../lib/syncScroll";
import { clampZoom, currentRow, fitZoom, rowEstimate, windowRange } from "./geometry";
import { PageHtmlCache } from "./htmlCache";
import { OriginalSheetContent } from "./OriginalSheetContent";
import { PageSheet } from "./PageSheet";
import { chapterFor } from "./paginate";
import { TranslatedSheet, type BlockHighlight, type ChapterRef } from "./TranslatedSheet";
import { usePageInfos } from "./usePageInfos";
// The book's own code face (DDIA sets code in Ubuntu Mono): code takes the room it takes in print.
import "@fontsource/ubuntu-mono/400.css";
import "@fontsource/ubuntu-mono/700.css";
import "./reader.css";

export interface ReaderCanvasProps {
  api: EngineApi | null;
  bookId: number | null;
  doc: PdfDoc | null;
  pageCount: number;
  mode: ViewMode;
  /** Zoom factor (1 = printed size). Ignored while `fit` is on. */
  zoom: number;
  /** Fit the sheet(s) to the reading area's width. */
  fit?: boolean;
  /** Page to show (1-based). Changing it scrolls there; scrolling reports back via onPageChange. */
  page: number;
  /** Bumped when translations change; cached page HTML is refetched. */
  revision: number;
  onPageChange: (page: number) => void;
  /** The zoom actually used (differs from `zoom` while fitting). */
  onZoomResolved?: (zoom: number) => void;
  onWordClick?: (word: string, sentence: string, blockKey: string | null, page: number) => void;
  /** "Bu sayfayı çevir" inside an untranslated sheet: must open the estimate → cost dialog flow. */
  onTranslatePage?: (page: number) => void;
  onTranslateRange?: (fromPage: number) => void;
  /** Debounce for saving the reading position (ms). */
  progressDelayMs?: number;
  /** Book outline (1-based pages): running heads on the Turkish book pages. */
  toc?: readonly { title: string; page: number | null; level: number }[];
}

export type PdfTone = "soft" | "dim" | "original";
const TONE_KEY = "rosetta.pdfTone";
function readTone(): PdfTone {
  try {
    const v = window.localStorage.getItem(TONE_KEY);
    return v === "dim" || v === "original" ? v : "soft";
  } catch {
    return "soft";
  }
}

/** Saves the reading position at most every `delay` ms (and on unmount). */
export function useProgressSaver(api: EngineApi | null, bookId: number | null, delay: number) {
  const pending = useRef<number | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const flush = useCallback(() => {
    window.clearTimeout(timer.current);
    timer.current = undefined;
    const page = pending.current;
    pending.current = null;
    if (api && bookId !== null && page !== null) void api.saveProgress(bookId, page).catch(() => undefined);
  }, [api, bookId]);
  useEffect(() => flush, [flush]);
  // Closing the window (Tauri) or hiding the app must not lose the last page.
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") flush();
    };
    window.addEventListener("pagehide", flush);
    window.addEventListener("beforeunload", flush);
    document.addEventListener("visibilitychange", onHide);
    return () => {
      window.removeEventListener("pagehide", flush);
      window.removeEventListener("beforeunload", flush);
      document.removeEventListener("visibilitychange", onHide);
    };
  }, [flush]);
  return useCallback(
    (page: number) => {
      pending.current = page;
      if (timer.current === undefined) timer.current = window.setTimeout(flush, delay);
    },
    [flush, delay],
  );
}

/**
 * The reading area: every page as a paper sheet in one continuous, virtualized vertical list.
 * Only the visible sheets ±2 are mounted; PDF canvases of sheets that leave are released.
 * Split mode renders each row as a pair (original | Turkish) so pages always line up.
 */
export function ReaderCanvas({
  api,
  bookId,
  doc,
  pageCount,
  mode,
  zoom: requestedZoom,
  fit = false,
  page,
  revision,
  onPageChange,
  onZoomResolved,
  onWordClick,
  onTranslatePage,
  onTranslateRange,
  progressDelayMs = 800,
  toc,
}: ReaderCanvasProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pages = usePageInfos(api, bookId, doc, pageCount, revision);
  const cache = useMemo(() => new PageHtmlCache(), []);
  useEffect(() => cache.clear(), [cache, bookId]);

  // Fit-to-width: track the reading area's width.
  const [areaWidth, setAreaWidth] = useState(0);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !fit) return;
    const update = () => setAreaWidth(el.clientWidth);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);

  const widest = useMemo(() => pages.reduce((w, p) => Math.max(w, p.width), 0), [pages]);
  // Geometry only (a translation finishing must not move the reader).
  const geometry = useMemo(() => pages.map((p) => `${p.width}x${p.height}`).join(","), [pages]);
  const columns: 1 | 2 = mode === "split" ? 2 : 1;
  const zoom = fit && areaWidth > 0 && widest > 0 ? fitZoom(widest, areaWidth, columns) : clampZoom(requestedZoom);
  useEffect(() => onZoomResolved?.(zoom), [zoom, onZoomResolved]);

  const reported = useRef(page);
  // Opening a book (resume at its saved page): until the page sizes are known and the list has
  // scrolled there, rows hit by the initial scroll offset (page 1) must not be reported/saved.
  const anchoring = useRef<{ page: number; until: number } | null>({ page, until: Number.POSITIVE_INFINITY });
  const openedBook = useRef(bookId);
  if (openedBook.current !== bookId) {
    openedBook.current = bookId;
    reported.current = page;
    anchoring.current = { page, until: Number.POSITIVE_INFINITY };
  }
  // A zoom/mode/geometry change re-measures rows, and the virtualizer reports rows from the old
  // scroll offset before our effects run. Pin the current page right here, during render.
  const geoKey = `${zoom}|${mode}`;
  const lastGeoKey = useRef(geoKey);
  if (lastGeoKey.current !== geoKey) {
    lastGeoKey.current = geoKey;
    anchoring.current = { page: reported.current, until: performance.now() + 450 };
  }
  const saveProgress = useProgressSaver(api, bookId, progressDelayMs);

  const virtualizer = useVirtualizer({
    count: pages.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => rowEstimate(pages[i]?.height ?? 792, zoom),
    overscan: 2,
    // Visible rows ±2 (the spec's window); tanstack passes the visible range.
    rangeExtractor: (range) => {
      const visible: number[] = [];
      for (let i = range.startIndex; i <= range.endIndex; i++) visible.push(i);
      const w = windowRange(visible, range.count, range.overscan);
      if (!w) return [];
      const out: number[] = [];
      for (let i = w[0]; i <= w[1]; i++) out.push(i);
      return out;
    },
    initialRect: { width: 1024, height: 768 },
    onChange: (instance: Virtualizer<HTMLDivElement, Element>) => {
      const el = scrollRef.current;
      if (!el) return;
      const rows = instance.getVirtualItems().map((v) => ({ index: v.index, start: v.start, end: v.end }));
      const idx = currentRow(rows, el.scrollTop, el.clientHeight || 768);
      if (idx === null) return;
      const p = idx + 1;
      // Right after a zoom/mode/geometry change rows are re-measured while scrollToIndex settles:
      // don't report whatever row the stale scroll offset hits in the meantime.
      const anchor = anchoring.current;
      if (anchor && performance.now() < anchor.until && p !== anchor.page) return;
      if (p !== reported.current) {
        reported.current = p;
        onPageChange(p);
        saveProgress(p);
      }
    },
  });

  // Size/zoom changes invalidate measured rows; keep the reader on the same page.
  useEffect(() => {
    virtualizer.measure();
    if (!pages.length) return;
    const target = Math.min(pages.length, anchoring.current?.page ?? reported.current);
    anchoring.current = { page: target, until: performance.now() + 600 };
    reported.current = target;
    virtualizer.scrollToIndex(target - 1, { align: "start" });
    // A second pass after the rows were measured (sheets taller than estimated).
    const raf = window.requestAnimationFrame(() => {
      if (anchoring.current?.page === target) virtualizer.scrollToIndex(target - 1, { align: "start" });
    });
    return () => window.cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only on geometry changes
  }, [zoom, geometry, mode, bookId]);

  // External navigation (page field, TOC, keyboard): scroll there unless we reported it ourselves.
  useEffect(() => {
    if (!pages.length || page === reported.current) return;
    const target = Math.min(pages.length, Math.max(1, page));
    reported.current = target;
    virtualizer.scrollToIndex(target - 1, { align: "start" });
  }, [page, pages.length, virtualizer]);

  // Split-mode pairing: click a block on either side → emphasise both.
  const [highlight, setHighlight] = useState<BlockHighlight | null>(null);
  const [pdfHighlight, setPdfHighlight] = useState<{ page: number; bbox: BBox } | null>(null);
  const blocksCache = useRef(new Map<number, Promise<PageBlocks>>());
  useEffect(() => blocksCache.current.clear(), [bookId, revision]);
  const blocksFor = useCallback(
    (p: number): Promise<PageBlocks> | null => {
      if (!api || bookId === null) return null;
      let hit = blocksCache.current.get(p);
      if (!hit) {
        hit = api.pageBlocks(bookId, p);
        blocksCache.current.set(p, hit);
        hit.catch(() => blocksCache.current.delete(p));
      }
      return hit;
    },
    [api, bookId],
  );
  const nonce = useRef(0);
  useEffect(() => {
    if (!pdfHighlight) return;
    const t = window.setTimeout(() => setPdfHighlight(null), 1200);
    return () => window.clearTimeout(t);
  }, [pdfHighlight]);

  const onBlockClick = useCallback(
    (p: number, block: string, sentence: number | null) => {
      if (mode !== "split") return;
      setHighlight({ page: p, block, sentence, nonce: ++nonce.current });
      void blocksFor(p)
        ?.then((b) => {
          const hit = b.blocks.find((x) => x.key === block);
          if (hit) setPdfHighlight({ page: p, bbox: hit.bbox });
        })
        .catch(() => undefined);
    },
    [mode, blocksFor],
  );

  const onPointClick = useCallback(
    (p: number, x: number, y: number) => {
      void blocksFor(p)
        ?.then((b) => {
          const hit = blockAtPoint(b, x, y);
          if (!hit) return;
          setPdfHighlight({ page: p, bbox: hit.bbox });
          setHighlight({ page: p, block: hit.key, sentence: null, nonce: ++nonce.current });
        })
        .catch(() => undefined);
    },
    [blocksFor],
  );

  const renderOriginal = (info: PageInfo) => (
    <PageSheet page={info.page} widthPt={info.width} heightPt={info.height} zoom={zoom} layout="fixed" label={`Sayfa ${info.page} (orijinal)`}>
      <OriginalSheetContent
        doc={doc}
        page={info.page}
        zoom={zoom}
        highlight={pdfHighlight?.page === info.page ? pdfHighlight.bbox : null}
        onPointClick={mode === "split" ? (x, y) => onPointClick(info.page, x, y) : undefined}
      />
    </PageSheet>
  );

  const outline = useMemo(
    () => (toc ?? []).filter((e): e is { title: string; page: number; level: number } => e.page !== null),
    [toc],
  );
  const chapterOf = useCallback(
    (p: number): ChapterRef | null => {
      const hit = chapterFor(outline, p);
      return hit ? { title: hit.title, page: hit.page } : null;
    },
    [outline],
  );

  const [tone, setToneState] = useState<PdfTone>(readTone);
  const setTone = (t: PdfTone) => {
    setToneState(t);
    try {
      window.localStorage.setItem(TONE_KEY, t);
    } catch {
      /* private mode: keep it for this session */
    }
  };

  const renderHtml = (info: PageInfo, htmlMode: "tr" | "learn") => (
    <TranslatedSheet
      api={api}
      bookId={bookId}
      info={info}
      zoom={zoom}
      mode={htmlMode}
      revision={revision}
      cache={cache}
      chapter={chapterOf(info.page)}
      highlight={highlight}
      onBlockClick={onBlockClick}
      onWordClick={onWordClick}
      onTranslatePage={onTranslatePage}
      onTranslateRange={onTranslateRange}
    />
  );

  const items = virtualizer.getVirtualItems();
  const showsPdf = mode === "original" || mode === "split";
  const progress = pageCount > 0 ? Math.min(1, Math.max(0, page / pageCount)) : 0;

  return (
    <div className="rs-canvas-wrap" data-pdf-tone={tone}>
      <div className="rs-progress" aria-hidden="true">
        <div className="rs-progress__bar" style={{ transform: `scaleX(${progress})` }} />
      </div>
      {showsPdf && (
        <div className="rs-tone" role="group" aria-label="Orijinal sayfa tonu (koyu tema)">
          {(
            [
              ["soft", "Koyu"],
              ["dim", "Kısık"],
              ["original", "Orijinal renkler"],
            ] as const
          ).map(([t, label]) => (
            <button key={t} type="button" className="rs-tone__btn" aria-pressed={tone === t} onClick={() => setTone(t)}>
              {label}
            </button>
          ))}
        </div>
      )}
    <div ref={scrollRef} className={`rs-canvas rs-canvas--${mode}`} data-testid="reader-canvas" tabIndex={-1}>
      {pageCount <= 0 ? null : (
        <div className="rs-track" style={{ height: virtualizer.getTotalSize() }}>
          {items.map((row) => {
            const info = pages[row.index];
            if (!info) return null;
            return (
              <div
                key={row.key}
                ref={virtualizer.measureElement}
                data-index={row.index}
                className={`rs-row${mode === "split" ? " rs-row--split" : ""}`}
                style={{ transform: `translateY(${row.start}px)` }}
              >
                {mode === "original" && renderOriginal(info)}
                {mode === "translation" && renderHtml(info, "tr")}
                {mode === "learn" && renderHtml(info, "learn")}
                {mode === "split" && (
                  <>
                    {renderOriginal(info)}
                    {renderHtml(info, "tr")}
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
    </div>
  );
}
