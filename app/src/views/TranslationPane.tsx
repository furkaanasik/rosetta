import { forwardRef, useCallback, useEffect, useMemo, useState } from "react";
import type { EngineApi } from "../api/engine";
import type { HtmlMode, PageHtml } from "../api/types";
import { sanitizeEngineHtml } from "../lib/sanitize";

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
  const [data, setData] = useState<PageHtml | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!api || bookId === null) return;
    let cancelled = false;
    api
      .pageHtml(bookId, page, mode)
      .then((d) => !cancelled && (setData(d), setError(null)))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [api, bookId, page, mode, revision]);

  const html = useMemo(() => {
    if (!data || !api || bookId === null) return "";
    return sanitizeEngineHtml(data.html, (name) => api.assetUrl(bookId, name));
  }, [data, api, bookId]);

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
      {error && <p className="error">{error}</p>}
      {data && mode === "tr" && data.translated_blocks === 0 && data.translatable_blocks > 0 && (
        <p className="banner">Bu sayfa henüz çevrilmedi — "Bu Sayfayı Çevir" ile çevirebilirsiniz.</p>
      )}
      <div
        className="engine-html"
        onClick={handleClick}
        onMouseUp={handleMouseUp}
        // Engine HTML is escaped server-side and sanitized above.
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
});
