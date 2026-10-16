import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import type { EngineApi } from "../api/engine";
import type { EstimateHint, PageHtml, PageInfo } from "../api/types";
import { usd } from "../lib/format";
import { isAssetName, sanitizeEngineHtml } from "../lib/sanitize";
import { Button } from "../ui/Button";
import { EmptyState, SkeletonLines } from "../ui/Feedback";
import { paginateRendered } from "./bookLayout";
import { insetsPx, sheetInsetsPt, sheetSize, type Insets } from "./geometry";
import type { PageHtmlCache } from "./htmlCache";
import { hyphenateTree, stripSoftHyphens } from "./hyphenate";
import { folioLabel, mirrorInsets } from "./paginate";
import { PageSheet } from "./PageSheet";

export interface BlockHighlight {
  page: number;
  block: string;
  sentence: number | null;
  /** Changes on every click so the same block can be emphasised again. */
  nonce: number;
}

/** The chapter this page belongs to (running head). */
export interface ChapterRef {
  title: string;
  page: number;
}

interface Props {
  api: EngineApi | null;
  bookId: number | null;
  info: PageInfo;
  zoom: number;
  mode: "tr" | "learn";
  revision: number;
  cache: PageHtmlCache;
  chapter?: ChapterRef | null;
  highlight?: BlockHighlight | null;
  onBlockClick?: (page: number, block: string, sentence: number | null) => void;
  onWordClick?: (word: string, sentence: string, blockKey: string | null, page: number) => void;
  /** Opens the normal estimate → cost dialog flow; never runs a translation by itself. */
  onTranslatePage?: (page: number) => void;
  onTranslateRange?: (fromPage: number) => void;
}

/** Sentence text without learn-mode ruby annotations (the <rt> Turkish glosses). */
function sentenceText(el: HTMLElement | null | undefined): string {
  if (!el) return "";
  const copy = el.cloneNode(true) as HTMLElement;
  copy.querySelectorAll("rt").forEach((rt) => rt.remove());
  return stripSoftHyphens(copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

/** Resolution of the engine's figure/table crops. */
const CROP_DPI = 150;

const CHAPTER_LABEL = /^((?:BÖLÜM|BOLUM|CHAPTER|KISIM|PART)\s+[0-9IVXLC]+)\s+(?=\S)/i;

/**
 * Epigraph: short aside paragraphs opening the page (quote + "—Author" line) get the epigraph
 * style; longer asides stay note boxes.
 */
function markEpigraphs(root: HTMLElement): void {
  const blocks = Array.from(root.querySelectorAll<HTMLElement>("[data-block]"));
  for (const el of blocks.slice(0, 4)) {
    if (!el.classList.contains("aside") || el.tagName !== "P") {
      if (el.tagName === "H1" || el.tagName === "H2") continue;
      break;
    }
    const text = (el.textContent ?? "").trim();
    if (text.length > 320) break;
    el.classList.add("rs-epigraph");
    if (/^[—–-]\s*\S/.test(text)) el.classList.add("rs-attribution");
  }
}

/** "BÖLÜM 1 Veri Sistemleri…" → small spaced label + the title (only the first text node). */
function splitChapterLabels(root: HTMLElement): void {
  for (const h of Array.from(root.querySelectorAll<HTMLElement>("h1"))) {
    if (h.querySelector(".h-label")) continue;
    const walker = document.createTreeWalker(h, NodeFilter.SHOW_TEXT);
    const first = walker.nextNode() as Text | null;
    const m = first?.data.match(CHAPTER_LABEL);
    if (!first || !m) continue;
    const label = document.createElement("span");
    label.className = "h-label";
    label.textContent = m[1] ?? "";
    first.data = first.data.slice(m[0].length);
    first.parentNode?.insertBefore(label, first);
  }
}

/** Straight quotes in prose → Turkish typographic quotes (code untouched). */
function typographicQuotes(root: HTMLElement): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement?.closest("code, pre") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
    if (!n.data.includes('"')) continue;
    n.data = n.data.replace(/(^|[\s([{—–-])"/g, "$1“").replace(/"/g, "”");
  }
}

/** The chapter title of a page's HTML: first h1 without its "BÖLÜM N" label. */
export function chapterTitleFrom(html: string): string | null {
  const tpl = document.createElement("div");
  tpl.innerHTML = sanitizeEngineHtml(html);
  const h = tpl.querySelector("h1, h2");
  if (!h) return null;
  h.querySelector(".h-label")?.remove();
  const text = (h.textContent ?? "").replace(/\s+/g, " ").trim().replace(CHAPTER_LABEL, "");
  return text || null;
}

/** Book margins: never less than the space the running head / folio need (7 % of the height). */
export function bookInsetsPt(widthPt: number, heightPt: number, box?: PageHtml["content_box"]): Insets {
  const base = sheetInsetsPt(widthPt, heightPt, box);
  const tb = heightPt * 0.07;
  return { ...base, top: Math.max(base.top, tb), bottom: Math.max(base.bottom, tb) };
}

interface AssetInfo {
  url: string;
  width?: number;
  height?: number;
}

type Load = { key: string; data: PageHtml } | { key: string; error: string };

/**
 * A translated (or learn-mode) page as printed book pages: the engine's reflowed HTML, sanitized,
 * at the original point sizes, laid out on sheets of the original's size. Text that doesn't fit
 * continues on "devam" sheets (never shrunk). States inside the sheet: loading skeleton,
 * untranslated card, scanned page, nothing to translate.
 */
export function TranslatedSheet({
  api,
  bookId,
  info,
  zoom,
  mode,
  revision,
  cache,
  chapter,
  highlight,
  onBlockClick,
  onWordClick,
  onTranslatePage,
  onTranslateRange,
}: Props) {
  const page = info.page;
  const key = `${bookId ?? ""}:${page}:${mode}:${revision}`;
  const [load, setLoad] = useState<Load | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);

  const scanned = !info.has_text_layer;

  useEffect(() => {
    if (!api || bookId === null || scanned) return;
    let cancelled = false;
    cache
      .get(api, bookId, page, mode, revision)
      .then((data) => !cancelled && setLoad({ key, data }))
      .catch((e: unknown) => !cancelled && setLoad({ key, error: e instanceof Error ? e.message : String(e) }));
    return () => {
      cancelled = true;
    };
  }, [api, bookId, page, mode, revision, cache, key, scanned]);

  const current = load?.key === key ? load : null;
  const data = current && "data" in current ? current.data : null;
  const error = current && "error" in current ? current.error : null;

  const untranslated = mode === "tr" && !!data && data.translatable_blocks > 0 && data.translated_blocks === 0;
  const partial =
    mode === "tr" && !!data && data.translated_blocks > 0 && data.translated_blocks < data.translatable_blocks;
  const nothingToTranslate = mode === "tr" && !!data && data.translatable_blocks === 0;

  // Display-only cost hint for the untranslated card (no confirm token, no AI call). The
  // "Bu sayfayı çevir" button still goes through estimate → cost dialog → confirm.
  const [hint, setHint] = useState<{ key: string; hint: EstimateHint } | null>(null);
  useEffect(() => {
    if (!untranslated || !api || bookId === null) return;
    let cancelled = false;
    api
      .estimateHint(bookId, page)
      .then((h) => !cancelled && setHint({ key, hint: h }))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [untranslated, api, bookId, page, key]);
  const shownHint = hint?.key === key ? hint.hint : null;

  const html = useMemo(() => (data && !untranslated ? sanitizeEngineHtml(data.html) : ""), [data, untranslated]);

  // Figure/table crops, fetched with the bearer header → blob URLs; their natural size is
  // written onto the <img> so pagination knows the height before the image decodes.
  const [assets, setAssets] = useState<{ html: string; map: Map<string, AssetInfo> }>({ html: "", map: new Map() });
  useEffect(() => {
    if (!html || !api || bookId === null) return;
    const names = Array.from(html.matchAll(/data-asset="([^"]+)"/g), (m) => m[1] ?? "").filter(isAssetName);
    if (!names.length) return;
    let cancelled = false;
    const urls: string[] = [];
    const map = new Map<string, AssetInfo>();
    const publish = () => !cancelled && setAssets({ html, map: new Map(map) });
    for (const name of new Set(names)) {
      api
        .assetBlob(bookId, name)
        .then((blob) => {
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          urls.push(url);
          map.set(name, { url });
          publish();
          if (typeof Image === "undefined") return;
          const probe = new Image();
          probe.onload = () => {
            map.set(name, { url, width: probe.naturalWidth, height: probe.naturalHeight });
            publish();
          };
          probe.src = url;
        })
        .catch(() => {
          map.set(name, { url: "" });
          publish();
        });
    }
    return () => {
      cancelled = true;
      for (const u of urls) URL.revokeObjectURL(u);
    };
  }, [api, bookId, html]);
  const assetMap = assets.html === html ? assets.map : null;

  // The page's HTML with our presentation fixes (chapter label, epigraph, quotes, crops).
  const prepared = useMemo(() => {
    if (!html || typeof document === "undefined") return "";
    const tpl = document.createElement("div");
    tpl.innerHTML = html;
    splitChapterLabels(tpl);
    markEpigraphs(tpl);
    if (mode === "tr") {
      typographicQuotes(tpl);
      hyphenateTree(tpl);
    }
    for (const img of Array.from(tpl.querySelectorAll<HTMLImageElement>("img[data-asset]"))) {
      const a = assetMap?.get(img.dataset.asset ?? "");
      if (!a) continue;
      if (a.url) img.src = a.url;
      else img.alt = "Görsel yüklenemedi";
      if (a.width && a.height) {
        img.width = a.width;
        img.height = a.height;
        // The engine crops at 150 dpi: show the figure at its printed size (1 px = 72/150 pt),
        // like the original page, instead of stretching it to the text width.
        img.style.width = `calc(var(--scale, 1) * ${((a.width * 72) / CROP_DPI).toFixed(1)}pt)`;
      }
    }
    return tpl.innerHTML;
  }, [html, assetMap, mode]);

  // Sheet geometry (CSS px).
  const insetsPt = bookInsetsPt(info.width, info.height, data?.content_box);
  const size = sheetSize(info.width, info.height, zoom);
  const pad = insetsPx(insetsPt, zoom);
  const contentWidth = Math.max(80, size.width - pad.left - pad.right);
  const capacity = Math.max(80, size.height - pad.top - pad.bottom);

  // Fonts change line breaks: paginate again once they're in.
  const [fontsTick, setFontsTick] = useState(0);
  useEffect(() => {
    const fonts = typeof document !== "undefined" ? document.fonts : undefined;
    if (!fonts) return;
    let alive = true;
    void fonts.ready.then(() => alive && setFontsTick((t) => t + 1));
    const onDone = () => setFontsTick((t) => t + 1);
    fonts.addEventListener?.("loadingdone", onDone);
    return () => {
      alive = false;
      fonts.removeEventListener?.("loadingdone", onDone);
    };
  }, []);

  // Measure → paginate. The hidden measurer holds the full page only for the measurement.
  const layoutKey = `${key}|${contentWidth}|${capacity}|${zoom}|${fontsTick}|${prepared.length}`;
  const [sheets, setSheets] = useState<{ key: string; source: string; parts: string[] } | null>(null);
  useLayoutEffect(() => {
    const host = measureRef.current;
    if (!host || !prepared) return;
    const content = host.firstElementChild as HTMLElement | null;
    if (!content) return;
    content.innerHTML = prepared;
    let parts: string[];
    try {
      parts = paginateRendered(content, capacity);
    } catch {
      parts = [prepared];
    }
    content.innerHTML = "";
    setSheets({ key: layoutKey, source: prepared, parts: parts.length ? parts : [prepared] });
  }, [layoutKey, prepared, capacity]);
  const parts = useMemo(
    () => (sheets && sheets.source === prepared ? sheets.parts : prepared ? [prepared] : []),
    [sheets, prepared],
  );

  // Running head: the chapter's Turkish title (from its opening page, cached, no AI) or the TOC's.
  const [headTr, setHeadTr] = useState<{ key: string; title: string | null } | null>(null);
  const chapterPage = chapter?.page ?? null;
  const chapterKey = chapterPage !== null && mode === "tr" ? `${bookId}:${chapterPage}:${revision}` : null;
  useEffect(() => {
    if (!chapterKey || chapterPage === null || !api || bookId === null) return;
    let cancelled = false;
    cache
      .get(api, bookId, chapterPage, "tr", revision)
      .then((d) => {
        if (cancelled) return;
        const title = d.translated_blocks > 0 ? chapterTitleFrom(d.html) : null;
        setHeadTr((prev) => (prev?.key === chapterKey && prev.title === title ? prev : { key: chapterKey, title }));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [chapterKey, chapterPage, api, bookId, cache, revision]);
  const trHead = headTr?.key === chapterKey ? headTr.title : null;
  const head = chapter ? (trHead ?? chapter.title) : null;
  // The TOC fallback is the book's own (English) title.
  const headLang = trHead ? "tr" : "en";

  // Code wider than the sheet scrolls inside its block; mark those so CSS can fade the edge.
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    for (const pre of Array.from(root.querySelectorAll<HTMLElement>(".rs-sheet pre"))) {
      pre.classList.toggle("rs-overflow", pre.scrollWidth > pre.clientWidth + 1);
    }
  }, [parts, zoom]);

  // Block emphasis (split-mode pairing): a quiet accent bar + tint that fades after 1.2 s.
  useEffect(() => {
    const root = rootRef.current;
    if (!root || !highlight || highlight.page !== page || !parts.length) return;
    const block = root.querySelector<HTMLElement>(`.rs-html [data-block="${CSS.escape(highlight.block)}"]`);
    if (!block) return;
    const target =
      highlight.sentence !== null
        ? (block.querySelector<HTMLElement>(`[data-s="${highlight.sentence}"]`) ?? block)
        : block;
    target.classList.add("rs-hl");
    target.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
    const t = window.setTimeout(() => target.classList.remove("rs-hl"), 1200);
    return () => {
      window.clearTimeout(t);
      target.classList.remove("rs-hl");
    };
  }, [highlight, page, parts]);

  const handleClick = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      const target = e.target as HTMLElement;
      if (!target.closest(".rs-html")) return;
      const blockEl = target.closest<HTMLElement>("[data-block]");
      const blockKey = blockEl?.dataset.block ?? null;
      const sEl = target.closest<HTMLElement>("[data-s]");
      const sentence = sEl?.dataset.s !== undefined ? Number(sEl.dataset.s) : null;
      // Learn-mode HTML wraps every word as <span data-w="…" data-l="lemma">.
      const wordEl = target.closest<HTMLElement>("[data-w], [data-word]");
      if (wordEl && onWordClick) {
        const word = wordEl.dataset.w ?? wordEl.dataset.word ?? wordEl.textContent ?? "";
        onWordClick(word, sentenceText(sEl), blockKey, page);
        return;
      }
      if (blockKey) onBlockClick?.(page, blockKey, sentence);
    },
    [onWordClick, onBlockClick, page],
  );

  const handleMouseUp = useCallback(() => {
    if (!onWordClick || mode === "learn") return;
    const sel = window.getSelection();
    const text = stripSoftHyphens(sel?.toString() ?? "").trim();
    if (!text || text.length > 80) return;
    const anchor = sel?.anchorNode?.parentElement ?? null;
    if (!anchor || !rootRef.current?.contains(anchor)) return;
    const sEl = anchor.closest<HTMLElement>("[data-s]");
    const blockKey = anchor.closest<HTMLElement>("[data-block]")?.dataset.block ?? null;
    onWordClick(text, sentenceText(sEl), blockKey, page);
  }, [onWordClick, mode, page]);

  const label = mode === "learn" ? `Sayfa ${page} (öğrenme)` : `Sayfa ${page} (Türkçe)`;
  const lang = mode === "learn" ? "en" : "tr";
  const htmlClass = `rs-html engine-html mode-${mode}`;
  const opening = chapter?.page === page;

  const single = (body: React.ReactNode) => (
    <PageSheet page={page} widthPt={info.width} heightPt={info.height} zoom={zoom} layout="book" insets={mirrorInsets(insetsPt, page)} label={label} folio={String(page)} head={opening ? null : head} headLang={headLang}>
      {body}
    </PageSheet>
  );

  if (scanned) return single(<SheetCard title="Bu sayfada metin katmanı yok" body="Sayfa taranmış görünüyor; çeviri desteklenmiyor (OCR yok)." />);
  if (!api || bookId === null || (!data && !error)) return single(<SheetSkeleton />);
  if (error) return single(<SheetCard title="Sayfa yüklenemedi" body={error} tone="error" />);
  if (untranslated && data) {
    return single(
      <SheetCard
        title="Bu sayfa henüz çevrilmedi"
        body={cardBody(data.translatable_blocks, shownHint)}
        actions={
          onTranslatePage ? (
            <>
              <Button variant="primary" onClick={() => onTranslatePage(page)}>
                Bu sayfayı çevir
              </Button>
              {onTranslateRange && (
                <Button variant="ghost" onClick={() => onTranslateRange(page)}>
                  Aralık çevir…
                </Button>
              )}
            </>
          ) : null
        }
      />,
    );
  }

  return (
    <div ref={rootRef} className="rs-book" onClick={handleClick} onMouseUp={handleMouseUp} data-sheets={parts.length}>
      {/* Hidden measurer: same width and styles as a sheet's text area; empty except while measuring. */}
      <div
        ref={measureRef}
        className="rs-measure"
        aria-hidden="true"
        style={{ width: contentWidth, ["--scale" as string]: zoom }}
      >
        <div className={htmlClass} lang={lang} />
      </div>
      {parts.map((part, i) => (
        <PageSheet
          key={i}
          page={page}
          widthPt={info.width}
          heightPt={info.height}
          zoom={zoom}
          layout="book"
          insets={mirrorInsets(insetsPt, page + i)}
          label={i === 0 ? label : `${label}, devam ${i}`}
          folio={folioLabel(page, i)}
          head={opening && i === 0 ? null : head}
          headLang={headLang}
          className={i > 0 ? "rs-sheet--cont" : undefined}
        >
          {i === 0 && partial && data && (
            <div className="rs-sheet-note">
              <span>{data.translatable_blocks - data.translated_blocks} paragraf henüz çevrilmedi.</span>
              {onTranslatePage && (
                <Button variant="ghost" size="sm" onClick={() => onTranslatePage(page)}>
                  Çevir
                </Button>
              )}
            </div>
          )}
          {i === 0 && nothingToTranslate && <p className="rs-sheet-note">Bu sayfada çevrilecek metin yok.</p>}
          <div
            className={htmlClass}
            lang={lang}
            // Engine HTML is escaped server-side and sanitized (DOMPurify allowlist) above; the
            // fragments are slices of that sanitized DOM.
            dangerouslySetInnerHTML={{ __html: part }}
          />
        </PageSheet>
      ))}
    </div>
  );
}

function cardBody(paragraphs: number, hint: EstimateHint | null): string {
  const parts = [`${paragraphs} paragraf`];
  if (hint && hint.price_known && hint.usd > 0) parts.push(`tahmini ≈ ${usd(hint.usd)}`);
  if (hint && hint.seconds_hint > 0) parts.push(`~${Math.max(1, Math.round(hint.seconds_hint))} sn`);
  return parts.join(" · ");
}

function SheetSkeleton() {
  return (
    <div className="rs-skeleton-lines" aria-busy="true" aria-label="Yükleniyor">
      <SkeletonLines lines={1} className="rs-skeleton-title" />
      <SkeletonLines lines={6} />
      <SkeletonLines lines={4} />
    </div>
  );
}

function SheetCard({
  title,
  body,
  actions,
  tone,
}: {
  title: string;
  body: string;
  actions?: React.ReactNode;
  tone?: "error";
}) {
  return (
    <div className={`rs-card${tone === "error" ? " rs-card--error" : ""}`} role={tone === "error" ? "alert" : "status"}>
      <EmptyState title={title} action={actions ?? undefined}>
        {body}
      </EmptyState>
    </div>
  );
}
