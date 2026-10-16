# Rosetta engine HTTP API — contract for the desktop app

The app (`app/src/api/http.ts`, types in `app/src/api/types.ts`) calls exactly these endpoints.
The engine implements them in `rosetta_engine.api` (FastAPI) and is started as the Tauri sidecar.

## Startup (sidecar protocol)

```
rosetta serve --port 0 --token <64-hex>
```

- Bind **127.0.0.1 only**. `--port 0` means pick a free port.
- When ready, print **one JSON line to stdout**: `{"port": 41234, "token": "<same token>"}` and flush.
  Nothing else may be printed to stdout before it (logs → stderr). The Rust side parses the first
  JSON line and checks that `token` matches.
- The process is killed when the app exits; no cleanup is required beyond SQLite's WAL.
- Dev: `ROSETTA_ENGINE_URL=http://127.0.0.1:8765 ROSETTA_ENGINE_TOKEN=x npm run tauri dev`
  (or `VITE_ENGINE_URL` / `VITE_ENGINE_TOKEN` for `npm run dev` in a browser).

## Conventions

- Base: `http://127.0.0.1:<port>`; every route below is under `/api`.
- Auth: `Authorization: Bearer <token>` on every request (401 otherwise). Exception: asset
  images, which accept `?token=<token>` because `<img>` can't send headers.
- CORS: allow origins `tauri://localhost`, `http://tauri.localhost`, `http://localhost:1420`.
- JSON in/out, UTF-8. **Page numbers are 1-based** everywhere in the API.
- `BlockInfo.key` equals the `data-block` attribute the HTML builder emits (currently `"{page_no0}-{order}"`).
- Errors: HTTP status + body `{"error": {"kind": "<kind>", "message": "<Turkish, user-facing>"}}`.

| kind | status | when |
|---|---|---|
| `bad_request` | 400 | invalid input, page out of range |
| `unauthorized` | 401 | missing/bad token |
| `not_found` | 404 | unknown book/job/vocab |
| `expired_token` | 409 | confirm token unknown, used or expired |
| `invalid` | 422 | provider returned invalid output after retry |
| `usage_limit` | 429 | Claude usage limit (job → paused) |
| `budget` | 402 | per-call budget cap or job budget reached |
| `auth` | 401* | `claude` not logged in (*kind distinguishes from `unauthorized`) |
| `unavailable` | 503 | `claude` missing / provider down / engine busy |
| `internal` | 500 | anything else |

## Two-step AI operations (rules 1 and 2)

Every AI call is split into **estimate** (free, no AI) and **run** (needs the token):

1. `POST …/estimate` → `Estimate` with `confirm_token` (random, one-shot, expires after
   `expires_in` seconds, default 600). The engine stores the plan server-side keyed by the token.
2. `POST …` with `{"confirm_token": "…"}` runs exactly that plan. Unknown/used/expired → 409 `expired_token`.

No endpoint ever calls an AI provider without a valid confirm token.

```ts
Estimate {
  confirm_token: string; operation: "translate"|"job"|"profile"|"explain";
  provider: string; model: string; calls: number;
  input_tokens: number; output_tokens: number; usd: number; price_known: boolean;
  thinking: string|null; thinking_extra_tokens: number;
  total_blocks: number; cached_blocks: number; pages: number[];
  supports_profile: boolean; expires_in: number;
}
```

## Endpoints

### Health
| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/api/health` | – | `{ok: true, version}` |

### Books and pages (no AI)
| Method | Path | Body / query | Response |
|---|---|---|---|
| POST | `/api/books/open` | `{path}` | `BookInfo {id, file_hash, title, page_count, path}` |
| GET | `/api/books/{id}` | – | `BookInfo` |
| GET | `/api/books/{id}/toc` | – | `[{level, title, page}]` |
| GET | `/api/books/{id}/pages/{n}/blocks` | – | `PageBlocks {page, width, height, has_text_layer, blocks: [{key, order, type, bbox:[x0,y0,x1,y1] (PDF pt, top-left origin), translatable, translated}]}` (extracts on demand) |
| GET | `/api/books/{id}/pages/{n}/html` | `?mode=tr\|review\|learn&lang=tr` | `PageHtml {page, mode, html, translated_blocks, translatable_blocks}` |
| GET | `/api/books/{id}/assets/{name}` | `?token=` | image bytes (figure/table crops) |

`html` is a **fragment** (no `<html>`, `<head>`, `<script>`, `<link>`), built by the engine's
HTML builder with all book/model text escaped. It keeps `data-block`, `data-s` (sentence index) and,
in `learn` mode, `data-word` / `data-lemma` attributes and `<ruby>` for unknown words. Image `src`
values stay relative: `assets/<name>`; the app rewrites them to the assets endpoint. Untranslated
blocks in `tr` mode are rendered in the original with `class="untranslated"`.

### Translation
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/books/{id}/estimate` | `{pages:number[], lang?, provider?, model?, force?}` | `Estimate` (`operation:"translate"`) |
| POST | `/api/books/{id}/translate` | `{confirm_token}` | `TranslationReport {done_pages, failed_pages:{page:reason}, stopped_reason, stop_kind: "usage_limit"\|"auth"\|"budget"\|"unavailable"\|"paused"\|null, usage}` |

A fully cached request returns `calls: 0`; the app still shows the modal, and running it costs nothing.

### Batch jobs
| Method | Path | Body / query | Response |
|---|---|---|---|
| POST | `/api/books/{id}/jobs/estimate` | `{pages, all?, budget_usd?, lang?, provider?, model?}` | `Estimate` (`operation:"job"`) |
| POST | `/api/jobs` | `{confirm_token}` | `Job` (starts running in the background) |
| GET | `/api/jobs` | `?book_id=` | `Job[]` |
| GET | `/api/jobs/{id}` | – | `Job` (the app polls this every ~1.5 s while running) |
| POST | `/api/jobs/{id}/pause` | – | `Job` |
| POST | `/api/jobs/{id}/resume/estimate` | – | `Estimate` for the remaining pages |
| POST | `/api/jobs/{id}/resume` | `{confirm_token}` | `Job` |
| POST | `/api/jobs/{id}/retry-failed/estimate` | – | `Estimate` for failed pages only |
| POST | `/api/jobs/{id}/retry-failed` | `{confirm_token}` | `Job` |
| POST | `/api/jobs/{id}/cancel` | – | `Job` |

```ts
Job { id, book_id, status: "pending"|"running"|"paused"|"done"|"failed"|"cancelled",
      lang, provider, model, pages:number[], done_pages:number[], failed_pages:{[page]:reason},
      budget_usd:number|null, spent_usd:number, stop_reason:string|null, created_at, updated_at }
```

### Book profile
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/books/{id}/profile` | – | `BookProfile \| null` |
| PUT | `/api/books/{id}/profile` | `BookProfile` | `BookProfile` (never invalidates cache) |
| POST | `/api/books/{id}/profile/analyze/estimate` | – | `Estimate` (`operation:"profile"`) |
| POST | `/api/books/{id}/profile/analyze` | `{confirm_token}` | `BookProfile` (saved) |

`BookProfile` uses the Turkish keys: `{tur, ton, hedef_dil, cevrilmeyecek: string[], sozluk: {en: tr}, kod_dili: string[]}`.

### PDF export (no AI)
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/books/{id}/export` | `{pages?, mode: "tr"\|"bilingual", paper?: "a4"\|"letter", lang?, out_path?}` | `{path, pages, untranslated_blocks}` |

Default `out_path`: `<data_dir>/out/<hash12>/<title>.<mode>.pdf`.

### Learning (no AI)
| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/api/lookup` | `?q=` | `{query, lemma, tr: string[], definitions: string[]}` |
| GET | `/api/vocab` | `?book_id=&search=&since=` | `VocabItem[]` |
| POST | `/api/vocab` | `{word, sentence?, book_id?, page?, block_key?, meaning?, unknown?}` | `VocabItem` |
| PATCH | `/api/vocab/{id}` | `{unknown: boolean}` | `VocabItem` |
| DELETE | `/api/vocab/{id}` | – | 204 |
| GET | `/api/review/due` | `?limit=` | `ReviewCard[]` |
| POST | `/api/review/{vocab_id}` | `{rating: "again"\|"hard"\|"good"\|"easy"}` | next `ReviewCard \| null` |
| GET | `/api/stats` | – | `{total_words, mature_words, due_today, reviewed_today, streak_days}` |
| GET | `/api/books/{id}/terms` | – | `[{term, tr, in_vocab}]` (from the profile glossary) |
| POST | `/api/books/{id}/terms/add` | `{terms: string[] \| null}` (null = all) | `{added: number}` |

```ts
VocabItem { id, word, lemma, sentence, book_id|null, page|null, block_key|null, meaning, unknown, created_at }
ReviewCard { vocab_id, front /* sentence with "_____" cloze */, word, meaning, sentence_tr|null, due_at }
```

### "Bunu açıkla" (AI, Faz 7)
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/explain/estimate` | `{text, book_id?, page?}` | `Explanation` if cached (no cost), else `Estimate` (`operation:"explain"`) |
| POST | `/api/explain` | `{confirm_token}` | `Explanation {text, explanation, model, cached}` |

The app distinguishes the two estimate responses by the presence of `explanation`.

### Usage
| Method | Path | Query | Response |
|---|---|---|---|
| GET | `/api/usage` | `?book_id=` | `{calls, input_tokens, output_tokens, cost_usd}` (all recorded calls; list-price equivalent) |
