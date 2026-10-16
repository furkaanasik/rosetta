import type {
  BookInfo,
  BookProfile,
  Estimate,
  EstimateHint,
  Explanation,
  ExplainRequest,
  ExportRequest,
  ExportResult,
  HtmlMode,
  Job,
  JobEstimateRequest,
  LearnStats,
  LibraryBook,
  LookupResult,
  PageBlocks,
  PageHtml,
  PageInfo,
  Rating,
  ReviewCard,
  TermInfo,
  TocEntry,
  TranslateEstimateRequest,
  TranslationReport,
  UsageTotals,
  VocabCreate,
  VocabItem,
  VocabQuery,
} from "./types";

/**
 * Client view of the engine API. Every AI operation is two-step:
 * `*Estimate` returns an Estimate with a one-shot `confirm_token`, and only the
 * matching call with that token runs the AI (rules 1 and 2).
 */
export interface EngineApi {
  health(): Promise<{ ok: boolean; version: string }>;

  openBook(path: string): Promise<BookInfo>;
  getBook(bookId: number): Promise<BookInfo>;
  toc(bookId: number): Promise<TocEntry[]>;
  pageBlocks(bookId: number, page: number): Promise<PageBlocks>;
  pageHtml(bookId: number, page: number, mode: HtmlMode, lang?: string): Promise<PageHtml>;
  /** A cropped figure/table image, fetched with the bearer token (never put in a URL). */
  assetBlob(bookId: number, name: string): Promise<Blob>;
  /** The PDF bytes (browser dev mode, where the file path can't be loaded directly); null if unavailable. */
  bookFile(bookId: number): Promise<ArrayBuffer | null>;

  // v2 (reader redesign) — none of these call an AI.
  /** Library: recently opened books, newest first. */
  listBooks(): Promise<LibraryBook[]>;
  /** Size + translation status of every page (no extraction). */
  pages(bookId: number): Promise<PageInfo[]>;
  /** Remember the reading position (also bumps last_opened_at). */
  saveProgress(bookId: number, page: number): Promise<void>;
  /** Cover thumbnail PNG, fetched with the bearer token. */
  coverBlob(bookId: number, width?: number): Promise<Blob>;
  /** Up to 10 page fragments at once (1-based pages; any order, returned sorted). */
  pagesHtml(bookId: number, pages: number[], mode: HtmlMode, lang?: string): Promise<PageHtml[]>;
  /** Display-only cost hint for an untranslated sheet — issues no confirm token, never runs AI. */
  estimateHint(bookId: number, page: number): Promise<EstimateHint>;

  estimateTranslate(bookId: number, req: TranslateEstimateRequest): Promise<Estimate>;
  translate(bookId: number, confirmToken: string): Promise<TranslationReport>;

  estimateJob(bookId: number, req: JobEstimateRequest): Promise<Estimate>;
  startJob(confirmToken: string): Promise<Job>;
  listJobs(bookId?: number): Promise<Job[]>;
  getJob(jobId: number): Promise<Job>;
  pauseJob(jobId: number): Promise<Job>;
  estimateResumeJob(jobId: number): Promise<Estimate>;
  resumeJob(jobId: number, confirmToken: string): Promise<Job>;
  estimateRetryFailed(jobId: number): Promise<Estimate>;
  retryFailed(jobId: number, confirmToken: string): Promise<Job>;
  cancelJob(jobId: number): Promise<Job>;

  getProfile(bookId: number): Promise<BookProfile | null>;
  putProfile(bookId: number, profile: BookProfile): Promise<BookProfile>;
  estimateAnalyze(bookId: number): Promise<Estimate>;
  analyze(bookId: number, confirmToken: string): Promise<BookProfile>;

  exportPdf(bookId: number, req: ExportRequest): Promise<ExportResult>;

  lookup(query: string): Promise<LookupResult>;
  listVocab(query?: VocabQuery): Promise<VocabItem[]>;
  addVocab(item: VocabCreate): Promise<VocabItem>;
  setUnknown(vocabId: number, unknown: boolean): Promise<VocabItem>;
  deleteVocab(vocabId: number): Promise<void>;
  dueCards(limit?: number): Promise<ReviewCard[]>;
  review(vocabId: number, rating: Rating): Promise<ReviewCard | null>;
  stats(): Promise<LearnStats>;
  terms(bookId: number): Promise<TermInfo[]>;
  addTerms(bookId: number, terms?: string[]): Promise<number>;

  estimateExplain(req: ExplainRequest): Promise<Estimate | Explanation>;
  explain(confirmToken: string): Promise<Explanation>;

  usage(bookId?: number): Promise<UsageTotals>;
}

export function isExplanation(x: Estimate | Explanation): x is Explanation {
  return (x as Explanation).explanation !== undefined;
}
