import { useEffect, useMemo, useState } from "react";
import type { EngineApi } from "../api/engine";
import type { PageInfo } from "../api/types";
import type { PdfDoc } from "../lib/pdf";

/** US Letter, used only until the real size is known. */
export const FALLBACK_SIZE = { width: 612, height: 792 };

/** Uniform page list (every page the size of `size`) — the fallback when /pages is unavailable. */
export function uniformPages(count: number, size: { width: number; height: number }): PageInfo[] {
  return Array.from({ length: count }, (_, i) => ({
    page: i + 1,
    width: size.width,
    height: size.height,
    has_text_layer: true,
    translated: false,
    translatable_blocks: null,
  }));
}

/**
 * Size + status of every page for the virtual list. Prefers the engine's `GET /pages` (one cheap
 * call, no extraction); if that isn't available, falls back to page 1's size from PDF.js for all
 * pages. Refetched when translations change (`revision`).
 */
export function usePageInfos(
  api: EngineApi | null,
  bookId: number | null,
  doc: PdfDoc | null,
  pageCount: number,
  revision: number,
): PageInfo[] {
  const [infos, setInfos] = useState<{ key: string; pages: PageInfo[] } | null>(null);
  const key = `${bookId ?? ""}:${pageCount}`;

  useEffect(() => {
    if (pageCount <= 0) return;
    let cancelled = false;
    const fromDoc = async (): Promise<PageInfo[]> => {
      if (!doc) return uniformPages(pageCount, FALLBACK_SIZE);
      const p = await doc.getPage(1);
      const vp = p.getViewport({ scale: 1 });
      return uniformPages(pageCount, { width: vp.width, height: vp.height });
    };
    const load = async () => {
      if (api && bookId !== null) {
        try {
          const pages = await api.pages(bookId);
          if (pages.length) return pages;
        } catch {
          /* older engine without /pages: use PDF.js sizes */
        }
      }
      return fromDoc();
    };
    load()
      .then((pages) => !cancelled && setInfos({ key, pages }))
      .catch(() => !cancelled && setInfos({ key, pages: uniformPages(pageCount, FALLBACK_SIZE) }));
    return () => {
      cancelled = true;
    };
  }, [api, bookId, doc, pageCount, revision, key]);

  const fallback = useMemo(() => (pageCount > 0 ? uniformPages(pageCount, FALLBACK_SIZE) : []), [pageCount]);
  return infos?.key === key ? infos.pages : fallback;
}
