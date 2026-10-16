import type { EngineApi } from "./engine";
import {
  EngineError,
  type BlockInfo,
  type BookInfo,
  type BookProfile,
  type ClaudeCandidate,
  type Diagnostics,
  type EditableSettings,
  type SettingsPatch,
  type SettingsView,
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
  type Rating,
  type ReviewCard,
  type TermInfo,
  type TocEntry,
  type TranslateEstimateRequest,
  type TranslationReport,
  type UsageTotals,
  type VocabCreate,
  type VocabItem,
  type VocabQuery,
} from "./types";

const PAGE_W = 504;
const PAGE_H = 661.5;

const SAMPLE: { type: BlockInfo["type"]; en: string[]; tr: string[]; h: number }[] = [
  { type: "heading", en: ["Replication"], tr: ["Replikasyon"], h: 30 },
  {
    type: "paragraph",
    en: [
      "Replication means keeping a copy of the same data on multiple machines.",
      "There are several reasons why you might want to replicate data.",
    ],
    tr: [
      "Replikasyon, aynı verinin bir kopyasını birden fazla makinede tutmak demektir.",
      "Veriyi çoğaltmak istemenizin birkaç nedeni vardır.",
    ],
    h: 60,
  },
  {
    type: "code",
    en: ["SELECT * FROM users\n  WHERE id = 42;"],
    tr: ["SELECT * FROM users\n  WHERE id = 42;"],
    h: 40,
  },
  {
    type: "paragraph",
    en: ["Each node that stores a copy of the database is called a `replica`."],
    tr: ["Veritabanının bir kopyasını saklayan her düğüme `replica` denir."],
    h: 50,
  },
];

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** In-memory engine for development and tests. Counts AI calls in `aiCalls`. */
export class MockEngineApi implements EngineApi {
  aiCalls = 0;
  private book: BookInfo | null = null;
  private readonly translated = new Set<number>();
  private readonly tokens = new Map<string, () => Promise<unknown>>();
  private tokenSeq = 0;
  private spent: UsageTotals = { calls: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0 };
  private profile: BookProfile | null = null;
  private jobs: Job[] = [];
  private vocab: VocabItem[] = [];
  private readonly latencyMs: number;

  constructor(opts: { latencyMs?: number; pageCount?: number } = {}) {
    this.latencyMs = opts.latencyMs ?? 0;
    this.pageCount = opts.pageCount ?? 12;
  }
  private readonly pageCount: number;

  private async delay<T>(v: T): Promise<T> {
    if (this.latencyMs) await new Promise((r) => setTimeout(r, this.latencyMs));
    return v;
  }

  private requireBook(bookId: number): BookInfo {
    if (!this.book || this.book.id !== bookId) throw new EngineError("not_found", "Kitap yok", 404);
    return this.book;
  }

  private issue(
    operation: Estimate["operation"],
    pages: number[],
    run: () => Promise<unknown>,
    blocks = pages.length * 3,
  ): Estimate {
    const token = `tok-${++this.tokenSeq}`;
    this.tokens.set(token, run);
    const input = blocks * 120;
    const output = blocks * 160;
    return {
      confirm_token: token,
      operation,
      provider: "claude-cli",
      model: "sonnet",
      calls: blocks ? Math.ceil(pages.length / 5) || 1 : 0,
      input_tokens: input,
      output_tokens: output,
      usd: (input * 2 + output * 10) / 1e6,
      price_known: true,
      thinking: "medium",
      thinking_extra_tokens: 1500,
      total_blocks: blocks,
      cached_blocks: 0,
      pages,
      supports_profile: true,
      expires_in: 600,
    };
  }

  private async redeem<T>(token: string): Promise<T> {
    const run = this.tokens.get(token);
    if (!run) throw new EngineError("expired_token", "Onay süresi doldu; tahmini yenileyin", 409);
    this.tokens.delete(token);
    return (await run()) as T;
  }

  private charge(pages: number): void {
    this.aiCalls += 1;
    this.spent = {
      calls: this.spent.calls + 1,
      input_tokens: this.spent.input_tokens + pages * 360,
      output_tokens: this.spent.output_tokens + pages * 480,
      cost_usd: this.spent.cost_usd + pages * 0.0055,
    };
  }

  health() {
    return this.delay({ ok: true, version: "mock" });
  }

  openBook(path: string) {
    const title = path.split("/").pop()?.replace(/\.pdf$/i, "") || "Kitap";
    this.book = { id: 1, file_hash: "mock", title, page_count: this.pageCount, path };
    return this.delay(this.book);
  }
  getBook(bookId: number) {
    return this.delay(this.requireBook(bookId));
  }
  toc(bookId: number): Promise<TocEntry[]> {
    this.requireBook(bookId);
    return this.delay([
      { level: 1, title: "Replication", page: 1 },
      { level: 2, title: "Leaders and Followers", page: 3 },
      { level: 1, title: "Partitioning", page: 7 },
    ]);
  }

  pageBlocks(bookId: number, page: number): Promise<PageBlocks> {
    this.requireBook(bookId);
    let y = 72;
    const blocks = SAMPLE.map((b, i) => {
      const bbox: BlockInfo["bbox"] = [72, y, 432, y + b.h];
      y += b.h + 18;
      return {
        key: `${page - 1}-${i}`,
        order: i,
        type: b.type,
        bbox,
        translatable: b.type !== "code",
        translated: this.translated.has(page) && b.type !== "code",
      };
    });
    return this.delay({ page, width: PAGE_W, height: PAGE_H, has_text_layer: true, blocks });
  }

  pageHtml(bookId: number, page: number, mode: HtmlMode): Promise<PageHtml> {
    this.requireBook(bookId);
    const done = this.translated.has(page);
    const unknown = new Set(this.vocab.filter((v) => v.unknown).map((v) => v.lemma));
    const parts = SAMPLE.map((b, i) => {
      const key = `${page - 1}-${i}`;
      const sents = mode === "tr" && done ? b.tr : b.en;
      const spans = sents
        .map((s, j) => {
          let inner = escapeHtml(s).replace(/`([^`]+)`/g, "<code>$1</code>");
          if (mode === "learn") {
            inner = inner.replace(/\b([A-Za-z]+)\b/g, (w) =>
              unknown.has(w.toLowerCase())
                ? `<ruby data-word="${w}">${w}<rt>?</rt></ruby>`
                : `<span class="w" data-word="${w}">${w}</span>`,
            );
          }
          return `<span data-s="${j}">${inner}</span>`;
        })
        .join(" ");
      if (b.type === "heading") return `<h2 data-block="${key}">${spans}</h2>`;
      if (b.type === "code")
        return `<pre data-block="${key}"><code>${escapeHtml(b.en[0] ?? "")}</code></pre>`;
      const cls = mode === "tr" && !done ? ' class="untranslated"' : "";
      return `<p data-block="${key}"${cls}>${spans}</p>`;
    });
    return this.delay({
      page,
      mode,
      html: `<article class="page">${parts.join("\n")}</article>`,
      translated_blocks: done ? 3 : 0,
      translatable_blocks: 3,
      content_box: [72, 72, 432, 72 + SAMPLE.reduce((h, b) => h + b.h + 18, 0)],
      width: PAGE_W,
      height: PAGE_H,
      has_text_layer: true,
    });
  }

  async pagesHtml(bookId: number, pages: number[], mode: HtmlMode): Promise<PageHtml[]> {
    const wanted = [...new Set(pages)].sort((a, b) => a - b);
    if (wanted.length > 10) throw new EngineError("bad_request", "Tek istekte en çok 10 sayfa", 400);
    return Promise.all(wanted.map((p) => this.pageHtml(bookId, p, mode)));
  }

  estimateHint(bookId: number, page: number): Promise<EstimateHint> {
    this.requireBook(bookId);
    const todo = this.translated.has(page) ? 0 : 3;
    return this.delay({
      page,
      provider: "mock",
      model: "mock",
      calls: todo ? 1 : 0,
      input_tokens: todo * 400,
      output_tokens: todo * 500,
      usd: todo * 0.004,
      price_known: true,
      thinking: null,
      total_blocks: 3,
      cached_blocks: 3 - todo,
      has_text_layer: true,
      seconds_hint: todo ? 10 : 0,
    });
  }

  bookFile(_bookId: number): Promise<ArrayBuffer | null> {
    return Promise.resolve(null);
  }

  /** Last reading position per book (v2 progress). */
  lastPage: number | null = null;
  private openedAt: string | null = null;

  listBooks(): Promise<LibraryBook[]> {
    const b = this.book;
    if (!b) return this.delay([]);
    return this.delay([
      {
        id: b.id,
        title: b.title,
        page_count: b.page_count,
        file_path: b.path,
        file_exists: true,
        last_opened_at: this.openedAt,
        last_page: this.lastPage,
        translated_pages: this.translated.size,
        cover_url: `/api/books/${b.id}/cover`,
      },
    ]);
  }

  pages(bookId: number): Promise<PageInfo[]> {
    const b = this.requireBook(bookId);
    return this.delay(
      Array.from({ length: b.page_count }, (_, i) => ({
        page: i + 1,
        width: PAGE_W,
        height: PAGE_H,
        has_text_layer: true,
        translated: this.translated.has(i + 1),
        translatable_blocks: 3,
      })),
    );
  }

  saveProgress(bookId: number, page: number): Promise<void> {
    this.requireBook(bookId);
    this.lastPage = page;
    this.openedAt = new Date().toISOString();
    return this.delay(undefined);
  }

  coverBlob(bookId: number, _width?: number): Promise<Blob> {
    return this.assetBlob(bookId, "cover.png");
  }

  assetBlob(_bookId: number, _name: string): Promise<Blob> {
    // 1×1 transparent PNG.
    const png = Uint8Array.from(
      atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="),
      (c) => c.charCodeAt(0),
    );
    return this.delay(new Blob([png], { type: "image/png" }));
  }

  estimateTranslate(bookId: number, req: TranslateEstimateRequest) {
    this.requireBook(bookId);
    const pages = req.force ? req.pages : req.pages.filter((p) => !this.translated.has(p));
    const est = this.issue("translate", req.pages, async () => {
      if (pages.length) this.charge(pages.length);
      pages.forEach((p) => this.translated.add(p));
      const report: TranslationReport = {
        done_pages: req.pages,
        failed_pages: {},
        stopped_reason: null,
        stop_kind: null,
        usage: this.spent,
      };
      return report;
    }, pages.length * 3);
    return this.delay({ ...est, cached_blocks: (req.pages.length - pages.length) * 3 });
  }
  translate(_bookId: number, confirmToken: string) {
    return this.redeem<TranslationReport>(confirmToken);
  }

  private newJob(pages: number[], budget: number | null): Job {
    const now = new Date().toISOString();
    const job: Job = {
      id: this.jobs.length + 1,
      book_id: this.book?.id ?? 1,
      status: "running",
      lang: "tr",
      provider: "claude-cli",
      model: "sonnet",
      pages,
      done_pages: [],
      failed_pages: {},
      budget_usd: budget,
      spent_usd: 0,
      stop_reason: null,
      created_at: now,
      updated_at: now,
    };
    this.jobs.push(job);
    return job;
  }

  estimateJob(bookId: number, req: JobEstimateRequest) {
    const book = this.requireBook(bookId);
    const pages = req.all ? Array.from({ length: book.page_count }, (_, i) => i + 1) : req.pages;
    return this.delay(
      this.issue("job", pages, async () => {
        this.charge(1);
        return this.newJob(pages, req.budget_usd ?? null);
      }),
    );
  }
  startJob(confirmToken: string) {
    return this.redeem<Job>(confirmToken);
  }
  listJobs() {
    return this.delay([...this.jobs]);
  }
  getJob(jobId: number) {
    const job = this.jobs.find((j) => j.id === jobId);
    if (!job) throw new EngineError("not_found", "İş yok", 404);
    // Simulate progress: one page per poll.
    if (job.status === "running") {
      const next = job.pages.find((p) => !job.done_pages.includes(p));
      if (next === undefined) job.status = "done";
      else {
        job.done_pages = [...job.done_pages, next];
        this.translated.add(next);
        job.spent_usd += 0.0055;
      }
    }
    return this.delay({ ...job });
  }
  private setStatus(jobId: number, status: Job["status"]): Promise<Job> {
    const job = this.jobs.find((j) => j.id === jobId);
    if (!job) throw new EngineError("not_found", "İş yok", 404);
    job.status = status;
    return this.delay({ ...job });
  }
  pauseJob(jobId: number) {
    return this.setStatus(jobId, "paused");
  }
  estimateResumeJob(jobId: number) {
    const job = this.jobs.find((j) => j.id === jobId);
    const rest = job ? job.pages.filter((p) => !job.done_pages.includes(p)) : [];
    return this.delay(this.issue("job", rest, () => this.setStatus(jobId, "running")));
  }
  resumeJob(_jobId: number, confirmToken: string) {
    return this.redeem<Job>(confirmToken);
  }
  estimateRetryFailed(jobId: number) {
    const job = this.jobs.find((j) => j.id === jobId);
    const failed = job ? Object.keys(job.failed_pages).map(Number) : [];
    return this.delay(
      this.issue("job", failed, async () => {
        if (job) job.failed_pages = {};
        return this.setStatus(jobId, "running");
      }),
    );
  }
  retryFailed(_jobId: number, confirmToken: string) {
    return this.redeem<Job>(confirmToken);
  }
  cancelJob(jobId: number) {
    return this.setStatus(jobId, "cancelled");
  }

  getProfile(bookId: number) {
    this.requireBook(bookId);
    return this.delay(this.profile);
  }
  putProfile(bookId: number, profile: BookProfile) {
    this.requireBook(bookId);
    this.profile = profile;
    return this.delay(profile);
  }
  estimateAnalyze(bookId: number) {
    this.requireBook(bookId);
    return this.delay(
      this.issue("profile", [1, 2, 3], async () => {
        this.charge(3);
        this.profile = {
          tur: "yazılım / dağıtık sistemler",
          ton: "teknik ama akıcı",
          hedef_dil: "tr",
          cevrilmeyecek: ["Kafka", "API"],
          sozluk: { replication: "replikasyon", throughput: "işlem hacmi" },
          kod_dili: ["SQL"],
        };
        return this.profile;
      }),
    );
  }
  analyze(_bookId: number, confirmToken: string) {
    return this.redeem<BookProfile>(confirmToken);
  }

  exportPdf(bookId: number, req: ExportRequest): Promise<ExportResult> {
    const book = this.requireBook(bookId);
    return this.delay({
      path: req.out_path ?? `/tmp/${book.title}.${req.mode}.pdf`,
      pages: req.pages?.length ?? this.translated.size,
      untranslated_blocks: 0,
    });
  }

  lookup(query: string): Promise<LookupResult> {
    const lemma = query.toLowerCase().replace(/(ed|s)$/, "");
    return this.delay({
      query,
      lemma,
      tr: lemma.startsWith("replic") ? ["çoğaltmak", "kopyalamak"] : ["(mock) karşılık"],
      definitions: [`(mock) definition of ${lemma}`],
    });
  }
  listVocab(query?: VocabQuery) {
    const s = query?.search?.toLowerCase();
    return this.delay(this.vocab.filter((v) => !s || v.word.toLowerCase().includes(s)));
  }
  addVocab(item: VocabCreate): Promise<VocabItem> {
    const v: VocabItem = {
      id: this.vocab.length + 1,
      word: item.word,
      lemma: item.word.toLowerCase(),
      sentence: item.sentence ?? "",
      book_id: item.book_id ?? null,
      page: item.page ?? null,
      block_key: item.block_key ?? null,
      meaning: item.meaning ?? "",
      unknown: item.unknown ?? true,
      created_at: new Date().toISOString(),
    };
    this.vocab.push(v);
    return this.delay(v);
  }
  setUnknown(vocabId: number, unknown: boolean) {
    const v = this.vocab.find((x) => x.id === vocabId);
    if (!v) throw new EngineError("not_found", "Kelime yok", 404);
    v.unknown = unknown;
    return this.delay({ ...v });
  }
  deleteVocab(vocabId: number) {
    this.vocab = this.vocab.filter((v) => v.id !== vocabId);
    return this.delay(undefined);
  }
  dueCards(): Promise<ReviewCard[]> {
    return this.delay(
      this.vocab.map((v) => ({
        vocab_id: v.id,
        front: v.sentence.replace(new RegExp(`\\b${v.word}\\b`, "i"), "_____") || "_____",
        word: v.word,
        meaning: v.meaning,
        sentence_tr: null,
        due_at: new Date().toISOString(),
      })),
    );
  }
  review(_vocabId: number, _rating: Rating) {
    return this.delay(null);
  }
  stats(): Promise<LearnStats> {
    return this.delay({
      total_words: this.vocab.length,
      mature_words: 0,
      due_today: this.vocab.length,
      reviewed_today: 0,
      streak_days: 0,
    });
  }
  terms(): Promise<TermInfo[]> {
    return this.delay(
      Object.entries(this.profile?.sozluk ?? {}).map(([term, tr]) => ({
        term,
        tr,
        in_vocab: this.vocab.some((v) => v.lemma === term),
      })),
    );
  }
  async addTerms(bookId: number, terms?: string[]) {
    const all = await this.terms();
    let n = 0;
    for (const t of all) {
      if ((!terms || terms.includes(t.term)) && !t.in_vocab) {
        await this.addVocab({ word: t.term, meaning: t.tr, book_id: bookId });
        n += 1;
      }
    }
    return n;
  }

  estimateExplain(req: ExplainRequest): Promise<Estimate | Explanation> {
    return this.delay(
      this.issue("explain", [], async () => {
        this.charge(1);
        const e: Explanation = {
          text: req.text,
          explanation: "(mock) Bu cümle edilgen yapıdadır…",
          model: "haiku",
          cached: false,
        };
        return e;
      }),
    );
  }
  explain(confirmToken: string) {
    return this.redeem<Explanation>(confirmToken);
  }

  usage() {
    return this.delay({ ...this.spent });
  }

  // --- settings & diagnostics ---
  private settingsValues: EditableSettings = { ...MOCK_DEFAULT_SETTINGS };
  private settingsFromFile = new Set<string>();

  private settingsView(): SettingsView {
    return {
      values: { ...this.settingsValues },
      defaults: { ...MOCK_DEFAULT_SETTINGS },
      from_file: [...this.settingsFromFile].sort(),
      editable: Object.keys(MOCK_DEFAULT_SETTINGS).sort(),
      config_path: "/home/mock/.config/rosetta/config.toml",
    };
  }
  getSettings() {
    return this.delay(this.settingsView());
  }
  putSettings(patch: SettingsPatch) {
    for (const [k, v] of Object.entries(patch) as [keyof EditableSettings, unknown][]) {
      if (!(k in MOCK_DEFAULT_SETTINGS)) {
        return Promise.reject(new EngineError("bad_request", `bu ayar buradan değiştirilemez: ${k}`, 400));
      }
      if (k === "ollama_url" && typeof v === "string" && !/^https?:\/\/[^/]+/.test(v)) {
        return Promise.reject(new EngineError("bad_request", "Ollama adresi http(s)://sunucu:port biçiminde olmalı", 400));
      }
      if (v === null) {
        (this.settingsValues as unknown as Record<string, unknown>)[k] = MOCK_DEFAULT_SETTINGS[k];
        this.settingsFromFile.delete(k);
      } else {
        (this.settingsValues as unknown as Record<string, unknown>)[k] = v;
        this.settingsFromFile.add(k);
      }
    }
    return this.delay(this.settingsView());
  }
  diagnostics(): Promise<Diagnostics> {
    const claude = this.settingsValues.claude_path ?? "/home/mock/.local/bin/claude";
    return this.delay({
      engine: { version: "0.1.0-mock", python: "3.13", pymupdf: "1.28.2", frozen: false },
      paths: {
        data_dir: "/home/mock/.local/share/rosetta",
        config_dir: "/home/mock/.config/rosetta",
        config_file: "/home/mock/.config/rosetta/config.toml",
        config_exists: this.settingsFromFile.size > 0,
        db: "/home/mock/.local/share/rosetta/rosetta.db",
        db_bytes: 1_048_576,
      },
      dictionary: { path: "/home/mock/.local/share/rosetta/dictionary.db", present: true, entries: 662_319 },
      claude: {
        configured: this.settingsValues.claude_path,
        path: claude,
        source: this.settingsValues.claude_path ? "settings" : "path",
        version: "2.1.284 (Claude Code)",
      },
      chromium: "/usr/bin/chromium",
      deepl: { env: this.settingsValues.deepl_auth_key_env, key_set: false },
      ollama: { url: this.settingsValues.ollama_url, model: this.settingsValues.ollama_model, reachable: false },
    });
  }
  detectClaude(): Promise<ClaudeCandidate[]> {
    return this.delay([{ path: "/home/mock/.local/bin/claude", version: "2.1.284 (Claude Code)" }]);
  }
}

export const MOCK_DEFAULT_SETTINGS: EditableSettings = {
  default_lang: "tr",
  provider: "claude-cli",
  model: "sonnet",
  explain_model: "haiku",
  claude_path: null,
  claude_effort: "medium",
  claude_max_thinking_tokens: null,
  claude_max_budget_usd: 0.25,
  claude_timeout_s: 240,
  job_default_budget_usd: null,
  batch_max_pages: 5,
  deepl_auth_key_env: "DEEPL_AUTH_KEY",
  ollama_url: "http://localhost:11434",
  ollama_model: "qwen2.5:7b",
};
