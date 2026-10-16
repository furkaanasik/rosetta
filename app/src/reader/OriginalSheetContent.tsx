import { TextLayer } from "pdfjs-dist";
import { useEffect, useRef, useState, type MouseEvent } from "react";
import type { BBox } from "../api/types";
import type { PdfDoc } from "../lib/pdf";
import { PT_TO_PX } from "./geometry";

interface Props {
  doc: PdfDoc | null;
  page: number;
  zoom: number;
  /** Block box (PDF points, top-left origin) to emphasise on the page. */
  highlight?: BBox | null;
  /** Click on the page, in PDF points (split mode: find the block under the pointer). */
  onPointClick?: (x: number, y: number) => void;
}

/**
 * The original page inside a sheet: a PDF.js canvas plus a selectable text layer. Mounted only
 * while the sheet is in the virtual window; unmounting cancels rendering and frees the page.
 */
export function OriginalSheetContent({ doc, page, zoom, highlight, onPointClick }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<{ key: string; status: "done" | "error"; message?: string } | null>(null);
  const key = `${page}:${zoom}`;
  const scale = zoom * PT_TO_PX;

  useEffect(() => {
    if (!doc) return;
    let cancelled = false;
    let task: { cancel: () => void } | null = null;
    let text: TextLayer | null = null;
    let proxy: { cleanup: () => boolean } | null = null;
    (async () => {
      try {
        const p = await doc.getPage(page);
        proxy = p;
        if (cancelled) return;
        const viewport = p.getViewport({ scale });
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ratio = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * ratio);
        canvas.height = Math.floor(viewport.height * ratio);
        const render = p.render({
          canvas,
          viewport,
          transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
        });
        task = render;
        await render.promise;
        if (cancelled) return;
        setState({ key, status: "done" });
        // Selectable text on top of the canvas; a failure here never hides the page itself.
        const container = textRef.current;
        if (container) {
          container.replaceChildren();
          try {
            text = new TextLayer({ textContentSource: p.streamTextContent(), container, viewport });
            await text.render();
          } catch {
            /* text layer is optional */
          }
        }
      } catch (e) {
        if (cancelled || (e instanceof Error && e.name === "RenderingCancelledException")) return;
        setState({ key, status: "error", message: e instanceof Error ? e.message : String(e) });
      }
    })();
    return () => {
      cancelled = true;
      task?.cancel();
      text?.cancel();
      // Free operator lists/images of a page that left the virtual window.
      proxy?.cleanup();
    };
  }, [doc, page, scale, key]);

  const current = state?.key === key ? state : null;

  const onClick = (e: MouseEvent<HTMLDivElement>) => {
    if (!onPointClick) return;
    const r = e.currentTarget.getBoundingClientRect();
    onPointClick((e.clientX - r.left) / scale, (e.clientY - r.top) / scale);
  };

  return (
    <div
      className="rs-original"
      style={{ "--scale-factor": scale, "--total-scale-factor": scale } as React.CSSProperties}
      onClick={onClick}
    >
      {!doc && <div className="rs-skeleton" aria-hidden="true" />}
      <canvas ref={canvasRef} className="rs-pdf-canvas" aria-label={`PDF sayfa ${page}`} />
      <div ref={textRef} className="textLayer rs-textlayer" />
      {doc && !current && <div className="rs-skeleton rs-skeleton--overlay" aria-hidden="true" />}
      {current?.status === "error" && (
        <p className="rs-sheet-note rs-sheet-note--error" role="alert">
          Sayfa çizilemedi: {current.message}
        </p>
      )}
      {highlight && (
        <div
          className="rs-pdf-highlight"
          data-testid="pdf-highlight"
          style={{
            left: highlight[0] * scale - 4,
            top: highlight[1] * scale - 2,
            width: (highlight[2] - highlight[0]) * scale + 8,
            height: (highlight[3] - highlight[1]) * scale + 4,
          }}
        />
      )}
    </div>
  );
}
