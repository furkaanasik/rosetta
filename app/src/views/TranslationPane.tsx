import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EngineApi } from "../api/engine";
import type { HtmlMode, PageHtml } from "../api/types";
import { isAssetName, sanitizeEngineHtml } from "../lib/sanitize";

interface Props {
  api: EngineApi | null;
  bookId: number | null;
  page: number;
  mode: HtmlMode;
  revision: number;
  onScroll?: (scrollTop: number) => void;
  onWordClick?: (word: string, sentence: string, blockKey: string | null) => void;
  onBlockClick?: (blockKey: string, sentence: number | null) => void;
  highlight?: { block: string; sentence: number | null } | null;
}

/** Sentence text without learn-mode ruby annotations (the <rt> Turkish glosses). */
function sentenceText(el: HTMLElement | null | undefined): string {
  if (!el) return "";
  const copy = el.cloneNode(true) as HTMLElement;
  copy.querySelectorAll("rt").forEach((rt) => rt.remove());
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

/**
 * Renders the engine's HTML fragment. No scripts from the HTML ever run (sanitized + CSP);
 * interaction is handled here through data-block / data-s / data-word attributes.
 */
export const TranslationPane = forwardRef<HTMLDivElement, Props>(function TranslationPane(
  { api, bookId, page, mode, revision, onScroll, onWordClick, onBlockClick, highlight },
  ref,
) {
  // Content is tagged with the page it belongs to: after a page change (or an error) the old
  // page's HTML is never shown under the new page number. A refresh of the same page keeps it
  // on screen until the new version arrives.
  const key = `${bookId ?? ""}:${page}:${mode}`;
  const [loaded, setLoaded] = useState<{ key: string; data: PageHtml } | null>(null);
  const [error, setError] = useState<{ key: string; message: string } | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!api || bookId === null) return;
    let cancelled = false;
    api
      .pageHtml(bookId, page, mode)
      .then((d) => {
        if (cancelled) return;
        setLoaded({ key, data: d });
        setError(null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoaded(null);
        setError({ key, message: e instanceof Error ? e.message : String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [api, bookId, page, mode, revision, key]);

  const data = loaded?.key === key ? loaded.data : null;
  const errorText = error?.key === key ? error.message : null;

  const html = useMemo(() => (data ? sanitizeEngineHtml(data.html) : ""), [data]);

  // Figure/table crops: fetched with the bearer header and shown through blob URLs.
  useEffect(() => {
    const root = contentRef.current;
    if (!api || bookId === null || !root || !html) return;
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
          if (!cancelled) img.alt = img.alt || "Görsel yüklenemedi";
        });
    }
    return () => {
      cancelled = true;
      for (const u of urls) URL.revokeObjectURL(u);
    };
  }, [api, bookId, html]);

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const target = e.target as HTMLElement;
      const blockEl = target.closest<HTMLElement>("[data-block]");
      const blockKey = blockEl?.dataset.block ?? null;
      const sEl = target.closest<HTMLElement>("[data-s]");
      const sentence = sEl?.dataset.s !== undefined ? Number(sEl.dataset.s) : null;
      // Learn-mode HTML wraps every word as <span data-w="…" data-l="lemma">.
      const wordEl = target.closest<HTMLElement>("[data-w], [data-word]");
      if (wordEl && onWordClick) {
        const word = wordEl.dataset.w ?? wordEl.dataset.word ?? wordEl.textContent ?? "";
        onWordClick(word, sentenceText(sEl), blockKey);
        return;
      }
      if (blockKey) onBlockClick?.(blockKey, sentence);
    },
    [onWordClick, onBlockClick],
  );

  const handleMouseUp = useCallback(() => {
    if (!onWordClick || mode === "learn") return;
    const sel = window.getSelection();
    const text = sel?.toString().trim() ?? "";
    if (!text || text.length > 80) return;
    const anchor = sel?.anchorNode?.parentElement ?? null;
    const sEl = anchor?.closest<HTMLElement>("[data-s]");
    const blockKey = anchor?.closest<HTMLElement>("[data-block]")?.dataset.block ?? null;
    onWordClick(text, sentenceText(sEl), blockKey);
  }, [onWordClick, mode]);

  const highlightCss = highlight
    ? highlight.sentence !== null
      ? `[data-block="${CSS.escape(highlight.block)}"] [data-s="${highlight.sentence}"]`
      : `[data-block="${CSS.escape(highlight.block)}"]`
    : null;

  return (
    <div
      ref={ref}
      className={`pane html-pane mode-${mode}`}
      onScroll={(e) => onScroll?.(e.currentTarget.scrollTop)}
    >
      {highlightCss && <style>{`${highlightCss}{background:var(--hl);border-radius:3px}`}</style>}
      {bookId === null && <p className="empty">Bir PDF açın.</p>}
      {errorText && <p className="error">{errorText}</p>}
      {data && mode === "tr" && data.translated_blocks === 0 && data.translatable_blocks > 0 && (
        <p className="banner">Bu sayfa henüz çevrilmedi — "Bu Sayfayı Çevir" ile çevirebilirsiniz.</p>
      )}
      <div
        ref={contentRef}
        className="engine-html"
        onClick={handleClick}
        onMouseUp={handleMouseUp}
        // Engine HTML is escaped server-side and sanitized above.
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
});
