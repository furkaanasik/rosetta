import { useCallback, useEffect, useRef, useState } from "react";
import type { EngineApi } from "../api/engine";
import type { PageBlocks } from "../api/types";
import type { PdfDoc } from "../lib/pdf";
import { pdfScrollFor, translationScrollFor, type ElementBox } from "../lib/syncScroll";
import { PdfPageView } from "./PdfPageView";
import { TranslationPane } from "./TranslationPane";

interface Props {
  api: EngineApi | null;
  bookId: number | null;
  doc: PdfDoc | null;
  page: number;
  zoom: number;
  revision: number;
  onWordClick: (word: string, sentence: string, blockKey: string | null) => void;
}

function measure(container: HTMLElement): ElementBox[] {
  const base = container.getBoundingClientRect().top - container.scrollTop;
  return Array.from(container.querySelectorAll<HTMLElement>("[data-block]")).map((el) => {
    const r = el.getBoundingClientRect();
    return { key: el.dataset.block ?? "", top: r.top - base, height: r.height };
  });
}

/** Original PDF on the left, translation on the right, paragraph-synchronized scrolling. */
export function SplitView({ api, bookId, doc, page, zoom, revision, onWordClick }: Props) {
  const left = useRef<HTMLDivElement>(null);
  const right = useRef<HTMLDivElement>(null);
  const [blocks, setBlocks] = useState<PageBlocks | null>(null);
  const [highlight, setHighlight] = useState<{ block: string; sentence: number | null } | null>(null);
  const driver = useRef<"left" | "right" | null>(null);
  const release = useRef<number | undefined>(undefined);
  const scale = useRef(zoom);
  // Block boxes in the translation pane: measured once per layout (not per scroll event) and
  // invalidated when the content or the pane size changes.
  const boxes = useRef<ElementBox[] | null>(null);
  const frame = useRef<number | undefined>(undefined);

  const boxesNow = useCallback((): ElementBox[] => {
    if (!boxes.current && right.current) boxes.current = measure(right.current);
    return boxes.current ?? [];
  }, []);

  useEffect(() => {
    const el = right.current;
    if (!el) return;
    const invalidate = () => (boxes.current = null);
    const mo = new MutationObserver(invalidate);
    mo.observe(el, { childList: true, subtree: true });
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(invalidate);
    ro?.observe(el);
    return () => {
      mo.disconnect();
      ro?.disconnect();
      if (frame.current !== undefined) window.cancelAnimationFrame(frame.current);
    };
  }, []);

  /** At most one sync per animation frame; the latest scroll position wins. */
  const schedule = useCallback((fn: () => void) => {
    if (frame.current !== undefined) window.cancelAnimationFrame(frame.current);
    frame.current = window.requestAnimationFrame(() => {
      frame.current = undefined;
      fn();
    });
  }, []);

  useEffect(() => {
    if (!api || bookId === null) return;
    let cancelled = false;
    api.pageBlocks(bookId, page).then((b) => !cancelled && setBlocks(b)).catch(() => setBlocks(null));
    return () => {
      cancelled = true;
    };
  }, [api, bookId, page, revision]);

  const lock = (side: "left" | "right") => {
    driver.current = side;
    window.clearTimeout(release.current);
    release.current = window.setTimeout(() => (driver.current = null), 120);
  };

  const onLeft = useCallback(
    (top: number, s: number) => {
      scale.current = s;
      if (driver.current === "right" || !blocks || !right.current) return;
      lock("left");
      schedule(() => {
        if (!right.current) return;
        const target = translationScrollFor(blocks, top, s, boxesNow());
        if (target !== null) right.current.scrollTop = target;
      });
    },
    [blocks, schedule, boxesNow],
  );

  const onRight = useCallback(
    (top: number) => {
      if (driver.current === "left" || !blocks || !left.current || !right.current) return;
      lock("right");
      schedule(() => {
        if (!left.current) return;
        const target = pdfScrollFor(blocks, top, scale.current, boxesNow());
        if (target !== null) left.current.scrollTop = target;
      });
    },
    [blocks, schedule, boxesNow],
  );

  return (
    <div className="split">
      <PdfPageView
        ref={left}
        doc={doc}
        page={page}
        zoom={zoom}
        fitWidth
        onScroll={onLeft}
        highlight={highlight ? blocks?.blocks.find((b) => b.key === highlight.block)?.bbox : null}
      />
      <TranslationPane
        ref={right}
        api={api}
        bookId={bookId}
        page={page}
        mode="tr"
        revision={revision}
        onScroll={onRight}
        onWordClick={onWordClick}
        onBlockClick={(block, sentence) => setHighlight({ block, sentence })}
        highlight={highlight}
      />
    </div>
  );
}
