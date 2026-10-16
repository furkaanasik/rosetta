// Shared types for the Rosetta engine HTTP API. See app/API_CONTRACT.md.
// Page numbers in the API are 1-based (as in the CLI and PDF.js).

export type ViewMode = "original" | "split" | "translation" | "learn";
export type HtmlMode = "tr" | "review" | "learn";

export interface EngineInfo {
  baseUrl: string;
  token: string;
}

export interface BookInfo {
  id: number;
  file_hash: string;
  title: string;
  page_count: number;
  path: string;
}

export interface TocEntry {
  level: number;
  title: string;
  page: number;
}

export type BlockType =
  | "heading"
  | "paragraph"
  | "list_item"
  | "code"
  | "image"
  | "table"
  | "caption"
  | "footnote"
  | "furniture";

export type BBox = [number, number, number, number];

export interface BlockInfo {
  /** Same value as the `data-block` attribute in the page HTML. */
  key: string;
  order: number;
  type: BlockType;
  bbox: BBox;
  translatable: boolean;
  translated: boolean;
}

export interface PageBlocks {
  page: number;
  width: number;
  height: number;
  has_text_layer: boolean;
  blocks: BlockInfo[];
}

export interface PageHtml {
  page: number;
  mode: HtmlMode;
  /** HTML fragment built by the engine (escaped); img src are relative "assets/...". */
  html: string;
  translated_blocks: number;
  translatable_blocks: number;
}

export interface Estimate {
  confirm_token: string;
  operation: "translate" | "job" | "profile" | "explain";
  provider: string;
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  usd: number;
  price_known: boolean;
  thinking: string | null;
  thinking_extra_tokens: number;
  total_blocks: number;
  cached_blocks: number;
  pages: number[];
  supports_profile: boolean;
  /** Seconds until the confirm token expires. */
  expires_in: number;
  /** Things the user should know before confirming (e.g. a budget that can't be pre-applied). */
  warnings?: string[];
}

export interface TranslateEstimateRequest {
  pages: number[];
  lang?: string;
  provider?: string;
  model?: string;
  force?: boolean;
}

export type StopKind = "usage_limit" | "auth" | "budget" | "unavailable" | "paused" | null;

export interface UsageTotals {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface TranslationReport {
  done_pages: number[];
  failed_pages: Record<string, string>;
  stopped_reason: string | null;
  stop_kind: StopKind;
  usage: UsageTotals;
}

export type JobStatus = "pending" | "running" | "paused" | "done" | "failed" | "cancelled";

export interface Job {
  id: number;
  book_id: number;
  status: JobStatus;
  lang: string;
  provider: string;
  model: string;
  pages: number[];
  done_pages: number[];
  failed_pages: Record<string, string>;
  budget_usd: number | null;
  spent_usd: number;
  stop_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobEstimateRequest extends TranslateEstimateRequest {
  all?: boolean;
  budget_usd?: number | null;
}

/** Book profile; Turkish keys as stored by the engine. */
export interface BookProfile {
  tur: string;
  ton: string;
  hedef_dil: string;
  cevrilmeyecek: string[];
  sozluk: Record<string, string>;
  kod_dili: string[];
}

export type ExportMode = "tr" | "bilingual";

export interface ExportRequest {
  pages?: number[];
  mode: ExportMode;
  paper?: "a4" | "letter";
  lang?: string;
  out_path?: string;
}

export interface ExportResult {
  path: string;
  pages: number;
  untranslated_blocks: number;
}

export interface LookupResult {
  query: string;
  lemma: string;
  tr: string[];
  definitions: string[];
}

export interface VocabItem {
  id: number;
  word: string;
  lemma: string;
  sentence: string;
  book_id: number | null;
  page: number | null;
  block_key: string | null;
  meaning: string;
  unknown: boolean;
  created_at: string;
}

export interface VocabCreate {
  word: string;
  sentence?: string;
  book_id?: number;
  page?: number;
  block_key?: string;
  meaning?: string;
  unknown?: boolean;
}

export interface VocabQuery {
  book_id?: number;
  search?: string;
  since?: string;
}

export type Rating = "again" | "hard" | "good" | "easy";

export interface ReviewCard {
  vocab_id: number;
  front: string; // sentence with the word as a cloze gap "_____"
  word: string;
  meaning: string;
  sentence_tr: string | null;
  due_at: string;
}

export interface LearnStats {
  total_words: number;
  mature_words: number;
  due_today: number;
  reviewed_today: number;
  streak_days: number;
}

export interface TermInfo {
  term: string;
  tr: string;
  in_vocab: boolean;
}

export interface ExplainRequest {
  text: string;
  book_id?: number;
  page?: number;
}

export interface Explanation {
  text: string;
  explanation: string;
  model: string;
  cached: boolean;
}

export type ApiErrorKind =
  | "usage_limit"
  | "auth"
  | "budget"
  | "unavailable"
  | "invalid"
  | "not_found"
  | "bad_request"
  | "expired_token"
  | "conflict"
  | "unauthorized"
  | "internal";

export class EngineError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;

  constructor(kind: ApiErrorKind, message: string, status = 0) {
    super(message);
    this.name = "EngineError";
    this.kind = kind;
    this.status = status;
  }
}
