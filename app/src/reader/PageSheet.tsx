import type { CSSProperties, ReactNode } from "react";
import { insetsPx, sheetSize, type Insets } from "./geometry";

interface Props {
  page: number;
  /** PDF points. */
  widthPt: number;
  heightPt: number;
  zoom: number;
  /**
   * "fixed": exactly the page's proportions (PDF canvas).
   * "flow": at least that tall, grows with text (rule 4).
   * "book": a printed page of the original's size — the text is paginated to fit (continuation
   * sheets), running head and folio sit inside the margins. Still never shrinks text: an
   * unbreakable block taller than a page makes that one sheet taller.
   */
  layout: "fixed" | "flow" | "book";
  /** Inner margins in PDF points (flow/book sheets). */
  insets?: Insets;
  label?: string;
  className?: string;
  /** Book sheets: the folio printed in the bottom margin (e.g. "25", "25 · devam"). */
  folio?: string;
  /** Book sheets: running head (chapter title) in the top margin. */
  head?: string | null;
  /** Language of the running head (uppercasing is language-aware: i → İ only in Turkish). */
  headLang?: string;
  children: ReactNode;
}

/**
 * One paper sheet: the same frame for Orijinal, Türkçe, Yan yana and Öğrenme. Width always equals
 * the original page at this zoom. Original sheets show the page number under the sheet (the PDF
 * prints its own folio); book sheets print theirs inside the bottom margin like a real book.
 */
export function PageSheet({ page, widthPt, heightPt, zoom, layout, insets, label, className, folio, head, headLang = "tr", children }: Props) {
  const size = sheetSize(widthPt, heightPt, zoom);
  const pad = layout !== "fixed" && insets ? insetsPx(insets, zoom) : null;
  const style: CSSProperties & Record<`--${string}`, string | number> = {
    width: size.width,
    ...(layout === "fixed" ? { height: size.height } : { minHeight: size.height }),
    ...(pad ? { padding: `${pad.top}px ${pad.right}px ${pad.bottom}px ${pad.left}px` } : {}),
    // Engine HTML sizes text as calc(var(--scale) * Npt): pt already carries the 96/72 factor,
    // so --scale is the zoom itself and the translation keeps the original's point sizes.
    "--scale": zoom,
    ...(pad ? { "--pad-top": `${pad.top}px`, "--pad-bottom": `${pad.bottom}px` } : {}),
  };
  const book = layout === "book";
  return (
    <figure className={`rs-sheet-wrap${book ? " rs-sheet-wrap--book" : ""}`} aria-label={label ?? `Sayfa ${page}`} data-page={page}>
      <div className={`rs-sheet rs-sheet--${layout}${className ? ` ${className}` : ""}`} style={style}>
        {book && head ? (
          <div className="rs-running-head" aria-hidden="true" lang={headLang}>
            {head}
          </div>
        ) : null}
        {children}
        {book ? (
          <div className="rs-folio-in" aria-hidden="true">
            {folio ?? page}
          </div>
        ) : null}
      </div>
      {book ? null : (
        <figcaption className="rs-folio" aria-hidden="true">
          {page}
        </figcaption>
      )}
    </figure>
  );
}
