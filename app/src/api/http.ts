import type { EngineApi } from "./engine";
import {
  EngineError,
  type ApiErrorKind,
  type BookInfo,
  type BookProfile,
  type ClaudeCandidate,
  type ConsistencyReport,
  type Diagnostics,
  type EngineInfo,
  type Estimate,
  type EstimateHint,
  type Explanation,
  type ExplainRequest,
  type ExportRequest,
  type ExportResult,
  type HtmlMode,
  type Job,
  type JobEstimateRequest,
  type LearnStats,
  type LibraryBook,
  type LookupResult,
  type PageBlocks,
  type PageHtml,
  type PageInfo,
  type PagesHtml,
  type Rating,
  type ReviewCard,
  type SettingsPatch,
  type SettingsView,
  type TermAcceptResult,
  type TermInfo,
  type TocEntry,
  type TranslateEstimateRequest,
  type TranslationReport,
  type UsageTotals,
  type VocabCreate,
  type VocabItem,
  type VocabQuery,
} from "./types";

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
type Query = Record<string, string | number | boolean | undefined>;

const KNOWN_KINDS: ReadonlySet<string> = new Set<ApiErrorKind>([
  "conflict",
  "busy",
  "usage_limit",
  "auth",
  "budget",
  "unavailable",
  "invalid",
  "not_found",
  "bad_request",
  "expired_token",
  "unauthorized",
  "internal",
]);

/** HTTP client for the engine sidecar (FastAPI on 127.0.0.1, bearer token auth). */
export class HttpEngineApi implements EngineApi {
  private readonly base: string;
  private readonly token: string;
  private readonly fetchFn: typeof fetch;

  constructor(info: EngineInfo, fetchFn: typeof fetch = globalThis.fetch.bind(globalThis)) {
    this.base = info.baseUrl.replace(/\/+$/, "");
    this.token = info.token;
    this.fetchFn = fetchFn;
  }

  url(path: string, query?: Query): string {
    const u = new URL(this.base + path);
    for (const [k, v] of Object.entries(query ?? {})) {
      if (v !== undefined) u.searchParams.set(k, String(v));
    }
    return u.toString();
  }

  async bookFile(bookId: number): Promise<ArrayBuffer | null> {
    let res: Response;
    try {
      res = await this.fetchFn(this.url(`/api/books/${bookId}/file`), {
        headers: { Authorization: `Bearer ${this.token}` },
      });
    } catch (e) {
      throw new EngineError("offline", `Motor bağlantısı yok: ${String(e)}`);
    }
    if (!res.ok) return null;
    return res.arrayBuffer();
  }

  private async call<T>(method: Method, path: string, body?: unknown, query?: Query): Promise<T> {
    let res: Response;
    try {
      res = await this.fetchFn(this.url(path, query), {
        method,
        headers: {
          Authorization: `Bearer ${this.token}`,
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      throw new EngineError("offline", `Motor bağlantısı yok: ${String(e)}`);
    }
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    const data: unknown = text ? safeJson(text) : null;
    if (!res.ok) {
      const err = (data as { error?: { kind?: string; message?: string } } | null)?.error;
      const kind = err?.kind && KNOWN_KINDS.has(err.kind) ? (err.kind as ApiErrorKind) : "internal";
      throw new EngineError(kind, err?.message ?? `HTTP ${res.status}`, res.status);
    }
    return data as T;
  }

  health() {
    return this.call<{ ok: boolean; version: string }>("GET", "/api/health");
  }
  openBook(path: string) {
    return this.call<BookInfo>("POST", "/api/books/open", { path });
  }
  getBook(bookId: number) {
    return this.call<BookInfo>("GET", `/api/books/${bookId}`);
  }
  toc(bookId: number) {
    return this.call<TocEntry[]>("GET", `/api/books/${bookId}/toc`);
  }
  pageBlocks(bookId: number, page: number) {
    return this.call<PageBlocks>("GET", `/api/books/${bookId}/pages/${page}/blocks`);
  }
  pageHtml(bookId: number, page: number, mode: HtmlMode, lang?: string) {
    return this.call<PageHtml>("GET", `/api/books/${bookId}/pages/${page}/html`, undefined, {
      mode,
      lang,
    });
  }
  /** Binary GET with the bearer header (the token never goes into a URL). */
  private async blob(path: string, what: string, query?: Query): Promise<Blob> {
    let res: Response;
    try {
      res = await this.fetchFn(this.url(path, query), {
        headers: { Authorization: `Bearer ${this.token}` },
      });
    } catch (e) {
      throw new EngineError("offline", `Motor bağlantısı yok: ${String(e)}`);
    }
    if (!res.ok) throw new EngineError("not_found", `${what} yüklenemedi`, res.status);
    return res.blob();
  }
  assetBlob(bookId: number, name: string): Promise<Blob> {
    return this.blob(`/api/books/${bookId}/assets/${encodeURIComponent(name)}`, `Görsel (${name})`);
  }

  listBooks() {
    return this.call<LibraryBook[]>("GET", "/api/books");
  }
  pages(bookId: number) {
    return this.call<PageInfo[]>("GET", `/api/books/${bookId}/pages`);
  }
  async saveProgress(bookId: number, page: number): Promise<void> {
    await this.call<unknown>("PUT", `/api/books/${bookId}/progress`, { page });
  }
  coverBlob(bookId: number, width?: number): Promise<Blob> {
    return this.blob(`/api/books/${bookId}/cover`, "Kapak", { w: width });
  }
  async pagesHtml(bookId: number, pages: number[], mode: HtmlMode, lang?: string): Promise<PageHtml[]> {
    if (pages.length === 0) return [];
    const res = await this.call<PagesHtml>("GET", `/api/books/${bookId}/html`, undefined, {
      pages: pages.join(","),
      mode,
      lang,
    });
    return res.pages;
  }
  estimateHint(bookId: number, page: number) {
    return this.call<EstimateHint>("GET", `/api/books/${bookId}/pages/${page}/estimate_hint`);
  }

  estimateTranslate(bookId: number, req: TranslateEstimateRequest) {
    return this.call<Estimate>("POST", `/api/books/${bookId}/estimate`, req);
  }
  translate(bookId: number, confirmToken: string) {
    return this.call<TranslationReport>("POST", `/api/books/${bookId}/translate`, {
      confirm_token: confirmToken,
    });
  }

  estimateJob(bookId: number, req: JobEstimateRequest) {
    return this.call<Estimate>("POST", `/api/books/${bookId}/jobs/estimate`, req);
  }
  startJob(confirmToken: string) {
    return this.call<Job>("POST", "/api/jobs", { confirm_token: confirmToken });
  }
  listJobs(bookId?: number) {
    return this.call<Job[]>("GET", "/api/jobs", undefined, { book_id: bookId });
  }
  getJob(jobId: number) {
    return this.call<Job>("GET", `/api/jobs/${jobId}`);
  }
  pauseJob(jobId: number) {
    return this.call<Job>("POST", `/api/jobs/${jobId}/pause`);
  }
  estimateResumeJob(jobId: number) {
    return this.call<Estimate>("POST", `/api/jobs/${jobId}/resume/estimate`);
  }
  resumeJob(jobId: number, confirmToken: string) {
    return this.call<Job>("POST", `/api/jobs/${jobId}/resume`, { confirm_token: confirmToken });
  }
  estimateRetryFailed(jobId: number) {
    return this.call<Estimate>("POST", `/api/jobs/${jobId}/retry-failed/estimate`);
  }
  retryFailed(jobId: number, confirmToken: string) {
    return this.call<Job>("POST", `/api/jobs/${jobId}/retry-failed`, {
      confirm_token: confirmToken,
    });
  }
  cancelJob(jobId: number) {
    return this.call<Job>("POST", `/api/jobs/${jobId}/cancel`);
  }

  getProfile(bookId: number) {
    return this.call<BookProfile | null>("GET", `/api/books/${bookId}/profile`);
  }
  putProfile(bookId: number, profile: BookProfile) {
    return this.call<BookProfile>("PUT", `/api/books/${bookId}/profile`, profile);
  }
  estimateAnalyze(bookId: number) {
    return this.call<Estimate>("POST", `/api/books/${bookId}/profile/analyze/estimate`);
  }
  analyze(bookId: number, confirmToken: string) {
    return this.call<BookProfile>("POST", `/api/books/${bookId}/profile/analyze`, {
      confirm_token: confirmToken,
    });
  }

  exportPdf(bookId: number, req: ExportRequest) {
    return this.call<ExportResult>("POST", `/api/books/${bookId}/export`, req);
  }

  consistency(bookId: number) {
    return this.call<ConsistencyReport>("GET", `/api/books/${bookId}/consistency`);
  }
  acceptTerm(bookId: number, term: string, tr: string) {
    return this.call<TermAcceptResult>("POST", `/api/books/${bookId}/consistency/accept`, { term, tr });
  }
  async ignoreTerm(bookId: number, term: string) {
    const r = await this.call<{ ignored: string[] }>("POST", `/api/books/${bookId}/consistency/ignore`, { term });
    return r.ignored;
  }
  async unignoreTerm(bookId: number, term: string) {
    const r = await this.call<{ ignored: string[] }>(
      "DELETE",
      `/api/books/${bookId}/consistency/ignore`,
      undefined,
      { term },
    );
    return r.ignored;
  }

  lookup(query: string) {
    return this.call<LookupResult>("GET", "/api/lookup", undefined, { q: query });
  }
  listVocab(query?: VocabQuery) {
    return this.call<VocabItem[]>("GET", "/api/vocab", undefined, { ...query });
  }
  addVocab(item: VocabCreate) {
    return this.call<VocabItem>("POST", "/api/vocab", item);
  }
  setUnknown(vocabId: number, unknown: boolean) {
    return this.call<VocabItem>("PATCH", `/api/vocab/${vocabId}`, { unknown });
  }
  deleteVocab(vocabId: number) {
    return this.call<void>("DELETE", `/api/vocab/${vocabId}`);
  }
  dueCards(limit?: number) {
    return this.call<ReviewCard[]>("GET", "/api/review/due", undefined, { limit });
  }
  review(vocabId: number, rating: Rating) {
    return this.call<ReviewCard | null>("POST", `/api/review/${vocabId}`, { rating });
  }
  stats() {
    return this.call<LearnStats>("GET", "/api/stats");
  }
  terms(bookId: number) {
    return this.call<TermInfo[]>("GET", `/api/books/${bookId}/terms`);
  }
  async addTerms(bookId: number, terms?: string[]) {
    const r = await this.call<{ added: number }>("POST", `/api/books/${bookId}/terms/add`, {
      terms: terms ?? null,
    });
    return r.added;
  }

  estimateExplain(req: ExplainRequest) {
    return this.call<Estimate | Explanation>("POST", "/api/explain/estimate", req);
  }
  explain(confirmToken: string) {
    return this.call<Explanation>("POST", "/api/explain", { confirm_token: confirmToken });
  }

  usage(bookId?: number) {
    return this.call<UsageTotals>("GET", "/api/usage", undefined, { book_id: bookId });
  }

  getSettings() {
    return this.call<SettingsView>("GET", "/api/settings");
  }
  putSettings(patch: SettingsPatch) {
    return this.call<SettingsView>("PUT", "/api/settings", { values: patch });
  }
  diagnostics() {
    return this.call<Diagnostics>("GET", "/api/diagnostics");
  }
  async detectClaude() {
    const r = await this.call<{ candidates: ClaudeCandidate[] }>("GET", "/api/diagnostics/claude");
    return r.candidates;
  }
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
