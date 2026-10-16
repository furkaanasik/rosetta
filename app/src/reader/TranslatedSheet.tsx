import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import type { EngineApi } from "../api/engine";
import type { EstimateHint, PageHtml, PageInfo } from "../api/types";
import { usd } from "../lib/format";
import { isAssetName, sanitizeEngineHtml } from "../lib/sanitize";
import { Button } from "../ui/Button";
import { EmptyState, SkeletonLines } from "../ui/Feedback";
import { sheetInsetsPt } from "./geometry";
import type { PageHtmlCache } from "./htmlCache";
import { PageSheet } from "./PageSheet";

export interface BlockHighlight {
  page: number;
  block: string;
  sentence: number | null;
  /** Changes on every click so the same block can be emphasised again. */
  nonce: number;
}

interface Props {
  api: EngineApi | null;
  bookId: number | null;
  info: PageInfo;
  zoom: number;
  mode: "tr" | "learn";
  revision: number;
  cache: PageHtmlCache;
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
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

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

type Load = { key: string; data: PageHtml } | { key: string; error: string };

/**
 * A translated (or learn-mode) page as a paper sheet: the engine's reflowed HTML, sanitized,
 * at the original point sizes. States inside the sheet: loading skeleton, untranslated card,
 * scanned page, nothing to translate.
 */
export function TranslatedSheet({
  api,
  bookId,
  info,
  zoom,
  mode,
  revision,
  cache,
  highlight,
  onBlockClick,
  onWordClick,
  onTranslatePage,
  onTranslateRange,
}: Props) {
  const page = info.page;
  const key = `${bookId ?? ""}:${page}:${mode}:${revision}`;
  const [load, setLoad] = useState<Load | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);

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

  // Chapter labels + figure/table crops (fetched with the bearer header → blob URLs).
  useEffect(() => {
    const root = contentRef.current;
    if (!root || !html) return;
    splitChapterLabels(root);
    markEpigraphs(root);
    if (!api || bookId === null) return;
    let cancelled = false;
    const urls: string[] = [];
    for (const img of Array.from(root.querySelectorAll<HTMLImageElement>("img[data-asset]"))) {
      const name = img.dataset.asset ?? "";
      if (!isAssetName(name)) continue;
      api
        .assetBlob(bookId, name)
        .then((blob) => {
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          urls.push(url);
          img.src = url;
        })
        .catch(() => {
          if (!cancelled) img.alt = "Görsel yüklenemedi";
        });
    }
    return () => {
      cancelled = true;
      for (const u of urls) URL.revokeObjectURL(u);
    };
  }, [api, bookId, html]);

  // Block emphasis (split-mode pairing): a quiet accent bar + tint that fades after 1.2 s.
  useEffect(() => {
    const root = contentRef.current;
    if (!root || !highlight || highlight.page !== page || !html) return;
    const block = root.querySelector<HTMLElement>(`[data-block="${CSS.escape(highlight.block)}"]`);
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
  }, [highlight, page, html]);

  const handleClick = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      const target = e.target as HTMLElement;
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
    const text = sel?.toString().trim() ?? "";
    if (!text || text.length > 80) return;
    const anchor = sel?.anchorNode?.parentElement ?? null;
    if (!anchor || !contentRef.current?.contains(anchor)) return;
    const sEl = anchor.closest<HTMLElement>("[data-s]");
    const blockKey = anchor.closest<HTMLElement>("[data-block]")?.dataset.block ?? null;
    onWordClick(text, sentenceText(sEl), blockKey, page);
  }, [onWordClick, mode, page]);

  const insets = sheetInsetsPt(info.width, info.height, data?.content_box);
  const label = mode === "learn" ? `Sayfa ${page} (öğrenme)` : `Sayfa ${page} (Türkçe)`;

  return (
    <PageSheet page={page} widthPt={info.width} heightPt={info.height} zoom={zoom} layout="flow" insets={insets} label={label}>
      {scanned ? (
        <SheetCard title="Bu sayfada metin katmanı yok" body="Sayfa taranmış görünüyor; çeviri desteklenmiyor (OCR yok)." />
      ) : !api || bookId === null ? (
        <SheetSkeleton />
      ) : error ? (
        <SheetCard title="Sayfa yüklenemedi" body={error} tone="error" />
      ) : !data ? (
        <SheetSkeleton />
      ) : untranslated ? (
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
        />
      ) : (
        <>
          {partial && (
            <div className="rs-sheet-note">
              <span>
                {data.translatable_blocks - data.translated_blocks} paragraf henüz çevrilmedi.
              </span>
              {onTranslatePage && (
                <Button variant="ghost" size="sm" onClick={() => onTranslatePage(page)}>
                  Çevir
                </Button>
              )}
            </div>
          )}
          {nothingToTranslate && <p className="rs-sheet-note">Bu sayfada çevrilecek metin yok.</p>}
          <div
            ref={contentRef}
            className={`rs-html engine-html mode-${mode}`}
            lang={mode === "learn" ? "en" : "tr"}
            onClick={handleClick}
            onMouseUp={handleMouseUp}
            // Engine HTML is escaped server-side and sanitized (DOMPurify allowlist) above.
            dangerouslySetInnerHTML={{ __html: html }}
          />
        </>
      )}
    </PageSheet>
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
