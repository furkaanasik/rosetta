import type { EngineApi } from "../api/engine";
import type { HtmlMode, PageHtml } from "../api/types";

/**
 * Per-page HTML cache for the virtual list: a page fetched once is reused while it scrolls in and
 * out of view, until `revision` changes (translations changed). Failed fetches are not cached.
 */
export class PageHtmlCache {
  private readonly entries = new Map<string, Promise<PageHtml>>();
  private revision = -1;

  constructor(private readonly limit = 40) {}

  get(api: EngineApi, bookId: number, page: number, mode: HtmlMode, revision: number): Promise<PageHtml> {
    if (revision !== this.revision) {
      this.entries.clear();
      this.revision = revision;
    }
    const key = `${bookId}:${page}:${mode}`;
    const hit = this.entries.get(key);
    if (hit) {
      // Refresh recency (Map keeps insertion order).
      this.entries.delete(key);
      this.entries.set(key, hit);
      return hit;
    }
    const p = api.pageHtml(bookId, page, mode);
    this.entries.set(key, p);
    p.catch(() => {
      if (this.entries.get(key) === p) this.entries.delete(key);
    });
    while (this.entries.size > this.limit) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) break;
      this.entries.delete(oldest);
    }
    return p;
  }

  clear(): void {
    this.entries.clear();
  }
}
