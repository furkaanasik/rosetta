import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export type PdfDoc = pdfjs.PDFDocumentProxy;

export interface OutlineItem {
  title: string;
  page: number | null;
  level: number;
}

/** Same-origin PDF.js data (see vite.config.ts `pdfjsAssets`). */
const ASSETS = {
  cMapUrl: "/pdfjs/cmaps/",
  cMapPacked: true,
  standardFontDataUrl: "/pdfjs/standard_fonts/",
  wasmUrl: "/pdfjs/wasm/",
  iccUrl: "/pdfjs/iccs/",
};

export async function loadPdf(src: string | ArrayBuffer): Promise<PdfDoc> {
  const task = pdfjs.getDocument(typeof src === "string" ? { ...ASSETS, url: src } : { ...ASSETS, data: src });
  return task.promise;
}

/** Flattened outline (TOC) with 1-based page numbers. */
export async function outline(doc: PdfDoc): Promise<OutlineItem[]> {
  const items = (await doc.getOutline()) ?? [];
  const out: OutlineItem[] = [];
  type Node = (typeof items)[number];
  const walk = async (nodes: Node[], level: number) => {
    for (const n of nodes) {
      let page: number | null = null;
      try {
        const dest = typeof n.dest === "string" ? await doc.getDestination(n.dest) : n.dest;
        const ref = dest?.[0];
        if (ref && typeof ref === "object") page = (await doc.getPageIndex(ref)) + 1;
        else if (typeof ref === "number") page = ref + 1;
      } catch {
        page = null;
      }
      out.push({ title: n.title, page, level });
      if (n.items?.length) await walk(n.items, level + 1);
    }
  };
  await walk(items, 1);
  return out;
}
