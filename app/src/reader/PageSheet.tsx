import type { CSSProperties, ReactNode } from "react";
import { insetsPx, sheetSize, type Insets } from "./geometry";

interface Props {
  page: number;
  /** PDF points. */
  widthPt: number;
  heightPt: number;
  zoom: number;
  /** "fixed": exactly the page's proportions (PDF canvas). "flow": at least that tall, grows with text (rule 4). */
  layout: "fixed" | "flow";
  /** Inner margins in PDF points (flow sheets only). */
  insets?: Insets;
  label?: string;
  className?: string;
  children: ReactNode;
}

/**
 * One paper sheet: the same frame for Orijinal, Türkçe, Yan yana and Öğrenme. Width always equals
 * the original page at this zoom; a flow sheet's height is at least the original's and grows when
 * the translation is longer — text is never shrunk (rule 4). The page number is drawn by the app
 * under the sheet (the engine never renders running headers/footers).
 */
export function PageSheet({ page, widthPt, heightPt, zoom, layout, insets, label, className, children }: Props) {
  const size = sheetSize(widthPt, heightPt, zoom);
  const pad = layout === "flow" && insets ? insetsPx(insets, zoom) : null;
  const style: CSSProperties & Record<`--${string}`, string | number> = {
    width: size.width,
    ...(layout === "fixed" ? { height: size.height } : { minHeight: size.height }),
    ...(pad ? { padding: `${pad.top}px ${pad.right}px ${pad.bottom}px ${pad.left}px` } : {}),
    // Engine HTML sizes text as calc(var(--scale) * Npt): pt already carries the 96/72 factor,
    // so --scale is the zoom itself and the translation keeps the original's point sizes.
    "--scale": zoom,
  };
  return (
    <figure className="rs-sheet-wrap" aria-label={label ?? `Sayfa ${page}`} data-page={page}>
      <div className={`rs-sheet rs-sheet--${layout}${className ? ` ${className}` : ""}`} style={style}>
        {children}
      </div>
      <figcaption className="rs-folio" aria-hidden="true">
        {page}
      </figcaption>
    </figure>
  );
}
