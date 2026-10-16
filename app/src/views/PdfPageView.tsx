import { forwardRef, useEffect, useRef, useState } from "react";
import type { BBox } from "../api/types";
import type { PdfDoc } from "../lib/pdf";

interface Props {
  doc: PdfDoc | null;
  page: number;
  zoom: number;
  onScroll?: (scrollTop: number, scale: number) => void;
  onRendered?: (scale: number) => void;
  /** Block box (PDF points) to outline on the page. */
  highlight?: BBox | null;
}

/** One PDF page rendered to a canvas inside its own scroll container. */
export const PdfPageView = forwardRef<HTMLDivElement, Props>(function PdfPageView(
  { doc, page, zoom, onScroll, onRendered, highlight },
  ref,
) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [scale, setScale] = useState(zoom);

  useEffect(() => {
    if (!doc) return;
    let cancelled = false;
    let task: { cancel: () => void } | null = null;
    (async () => {
      try {
        const p = await doc.getPage(page);
        if (cancelled) return;
        const viewport = p.getViewport({ scale: zoom });
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ratio = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * ratio);
        canvas.height = Math.floor(viewport.height * ratio);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        const render = p.render({
          canvas,
          viewport,
          transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
        });
        task = render;
        await render.promise;
        if (!cancelled) {
          setError(null);
          setScale(zoom);
          onRendered?.(zoom);
        }
      } catch (e) {
        if (!cancelled && !(e instanceof Error && e.name === "RenderingCancelledException"))
          setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [doc, page, zoom, onRendered]);

  return (
    <div
      ref={ref}
      className="pane pdf-pane"
      onScroll={(e) => onScroll?.(e.currentTarget.scrollTop, scale)}
    >
      {!doc && <p className="empty">Orijinal sayfa için bir PDF açın.</p>}
      {error && <p className="error">Sayfa çizilemedi: {error}</p>}
      <div className="pdf-page">
        <canvas ref={canvasRef} className="pdf-canvas" aria-label={`PDF sayfa ${page}`} />
        {highlight && (
          <div
            className="pdf-highlight"
            data-testid="pdf-highlight"
            style={{
              left: highlight[0] * scale,
              top: highlight[1] * scale,
              width: (highlight[2] - highlight[0]) * scale,
              height: (highlight[3] - highlight[1]) * scale,
            }}
          />
        )}
      </div>
    </div>
  );
});
