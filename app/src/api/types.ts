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
  /** v2: union of the page's content blocks (furniture excluded), PDF points; null if unknown. */
  content_box?: BBox | null;
  /** v2: page size in PDF points and whether it has a text layer. */
  width?: number;
  height?: number;
  has_text_layer?: boolean;
}

/** v2 `GET /api/books/{id}/html?pages=59-61`: up to 10 page fragments in one request. */
export interface PagesHtml {
  pages: PageHtml[];
}

/** v2 `GET /api/books/{id}/pages/{n}/estimate_hint`: display-only cost hint for an
 * untranslated sheet. No confirm token and no AI call — translating still needs
 * `estimateTranslate` → CostModal → `translate`. */
export interface EstimateHint {
  page: number;
  provider: string;
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  usd: number;
  price_known: boolean;
  thinking: string | null;
  total_blocks: number;
  cached_blocks: number;
  has_text_layer: boolean;
  /** Rough wall-clock guess in seconds (0 when nothing to translate). */
  seconds_hint: number;
}

/** v2 `GET /api/books/{id}/pages`: cheap per-page geometry + status for the virtual list. */
export interface PageInfo {
  page: number;
  /** PDF points. */
  width: number;
  height: number;
  /** From the DB once extracted, else "the page uses a font" (cheap; same answer in practice). */
  has_text_layer: boolean;
  /** Fully translated ('done') for the default lang/provider/model. */
  translated: boolean;
  /** null when the page hasn't been extracted yet. */
  translatable_blocks: number | null;
}

/** v2 `GET /api/books`: library entry, most recently opened first. */
export interface LibraryBook {
  id: number;
  title: string;
  page_count: number;
  file_path: string;
  file_exists: boolean;
  last_opened_at: string | null;
  last_page: number | null;
  translated_pages: number;
  cover_url: string | null;
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
  /** Targeted re-translation of these blocks (max 200; `pages` is ignored, rows are replaced). */
  blocks?: BlockRef[];
}

/** A source block: 1-based page + the block's text hash. */
export interface BlockRef {
  page: number;
  text_hash: string;
}

// --- term consistency (local analysis, no AI) ---

export interface TermExample {
  page: number;
  /** `data-block` key of the paragraph ("<0-based page>-<order>"). */
  block: string;
  en: string;
  tr: string;
}

export interface TermVariant {
  key: string;
  label: string;
  count: number;
  examples: TermExample[];
}

export interface AffectedBlock extends BlockRef {
  block: string;
}

export interface TermIssue {
  term: string;
  /** glossary: a profile glossary term; mined: discovered in the book's text. */
  source: "glossary" | "mined";
  preferred: string | null;
  occurrences: number;
  variants: TermVariant[];
  /** Paragraphs not using `preferred` (glossary terms only); at most 200 listed. */
  affected: AffectedBlock[];
  affected_count: number;
}

export interface ConsistencyReport {
  lang: string;
  provider: string;
  model: string;
  analyzed_blocks: number;
  aligned_ratio: number;
  ignored: string[];
  issues: TermIssue[];
}

export interface TermAcceptResult {
  profile: BookProfile;
  affected: AffectedBlock[];
  affected_count: number;
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
  | "busy"
  | "offline"
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

// --- settings & diagnostics (no AI) -------------------------------------------------------

/** Keys the Ayarlar screen may change (engine `config_edit.EDITABLE_KEYS`). */
export interface EditableSettings {
  default_lang: string;
  provider: string;
  model: string;
  explain_model: string;
  claude_path: string | null;
  claude_effort: string | null;
  claude_max_thinking_tokens: number | null;
  claude_max_budget_usd: number | null;
  claude_timeout_s: number;
  job_default_budget_usd: number | null;
  batch_max_pages: number;
  deepl_auth_key_env: string;
  ollama_url: string;
  ollama_model: string;
}

export interface SettingsView {
  values: EditableSettings;
  defaults: EditableSettings;
  /** Keys explicitly set in config.toml (the rest are defaults). */
  from_file: string[];
  editable: string[];
  config_path: string;
}

/** Partial update; `null` removes the key from config.toml (back to the default). */
export type SettingsPatch = { [K in keyof EditableSettings]?: EditableSettings[K] | null };

export interface Diagnostics {
  engine: { version: string; python: string; pymupdf: string; frozen: boolean };
  paths: {
    data_dir: string;
    config_dir: string;
    config_file: string;
    config_exists: boolean;
    db: string;
    db_bytes: number;
  };
  dictionary: { path: string; present: boolean; entries: number | null };
  claude: {
    configured: string | null;
    path: string | null;
    source: "settings" | "path" | "fallback" | "missing";
    version: string | null;
  };
  chromium: string | null;
  deepl: { env: string; key_set: boolean };
  ollama: {
    url?: string;
    model?: string;
    reachable: boolean | null;
    models?: string[];
    has_model?: boolean;
    note?: string;
  };
}

export interface ClaudeCandidate {
  path: string;
  version: string | null;
}
