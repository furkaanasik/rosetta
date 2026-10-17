# Rosetta

A desktop PDF reader for reading English books in another language. Open a book, and Rosetta
translates pages into Turkish (or a language you choose) **only when you ask**. It shows the result
as reflowed HTML that keeps the original structure: headings, paragraphs, lists, code, images and
tables. You can read in four modes: **Original**, **Side by side** (PDF and translation with synced
scrolling), **Translation only** and **Learning** (the original text with a Turkish gloss over just
the words you don't know). You can export the translated book as a PDF, and study English with a
vocabulary notebook, an offline dictionary and spaced-repetition (FSRS) flashcards. Translation runs
through the `claude` CLI on your machine, using **your Claude subscription**. No API key is needed.

Linux first (Tauri 2 + React + PDF.js front end, Python engine as a sidecar). The user interface is
in Turkish. License: AGPL-3.0-or-later.

## Download

Get the latest build from the [Releases](https://github.com/furkaanasik/rosetta/releases) page:

- **AppImage** (any distro):
  ```bash
  chmod +x Rosetta_0.1.0_amd64.AppImage
  ./Rosetta_0.1.0_amd64.AppImage
  # without FUSE:
  APPIMAGE_EXTRACT_AND_RUN=1 ./Rosetta_0.1.0_amd64.AppImage
  ```
- **.deb** (Debian/Ubuntu): `sudo apt install ./Rosetta_0.1.0_amd64.deb`

Runtime requirements:

- WebKitGTK: Arch `webkit2gtk-4.1 gtk3`, Debian/Ubuntu `libwebkit2gtk-4.1-0 libgtk-3-0`
- A logged-in [Claude Code](https://docs.claude.com/en/docs/claude-code) CLI (`claude`) for translation
- Chromium (`chromium`, `chromium-browser` or `google-chrome`) for PDF export

## Ground rules

1. **No automatic AI calls.** Every AI action (translation, book analysis, "Explain this") runs only
   when you press a button or run a command. No prefetching, no background translation, no analysis
   on open.
2. **Estimate first, then confirm.** Before every AI action Rosetta shows the estimated calls, tokens
   and cost. Nothing runs until you confirm (a prompt in the CLI, a single-use confirm token in the API).
3. **Every translation is cached.** A page is never translated twice for the same language and model
   (re-translation only with `--force`).
4. **No font shrinking.** Translations are reflowed HTML at the original size and hierarchy.
5. **The LLM never writes HTML.** Only text goes to the model and only text comes back. Rosetta
   builds the HTML and escapes model output everywhere.
6. **Code, images, diagrams, tables, running heads and footers are never sent to the model.** Code
   blocks are detected by monospace fonts; images and tables are cropped and shown as images.

## Quick start

### App

1. Open a book with **Open PDF**.
2. Pick a view mode in the top bar.
3. Control panel (everything is manual):
   - **Analyze book**: builds a book profile (glossary, do-not-translate terms, tone) from the table
     of contents and a few sample pages. You can edit it in the profile editor.
   - **Translate this page**, **Translate range** (e.g. `120-140`), **Translate whole book**: an
     estimate dialog opens, and nothing runs until you press **Confirm**. Ranges and whole books run
     as a **job** with progress, pause/resume, a budget limit, failed pages and "retry failed only".
   - **Export PDF**: translation only or bilingual (EN | TR), with translated bookmarks and a table
     of contents.
   - **Consistency check**: finds English terms translated in different ways and adds the preferred
     one to the glossary in one click.
4. Learning: click a word to see its meaning from the offline dictionary, and save it as unknown to
   add it to your vocabulary. In Learning mode its Turkish meaning then appears above it everywhere
   in the book. There are also flashcards (Again/Hard/Good/Easy), a technical-term list and a stats
   panel. Select a sentence and use **Explain this** (confirmed and cached).
5. The status bar shows total spend (list-price equivalent).

Shortcuts: `Ctrl+K` command palette, `Ctrl+,` settings. Rosetta reopens a book at the page where
you left off.

### CLI

`--pages`: `41`, `41-44`, `41,43,50-52` (1-based). Every command that calls AI shows an estimate and
asks for confirmation first. `--yes` skips the prompt; without a terminal it refuses unless `--yes`
is given.

```bash
cd engine
B="book.pdf"

# Extraction and estimates (no AI, free)
uv run rosetta extract "$B" --pages 25,30,59 --debug     # colour-coded debug HTML of block types
uv run rosetta estimate "$B" --pages 41-44 [--force] [--profile profile.json] [--think off]

# Translate: estimate → confirm → claude -p → cache → HTML (pNNN.tr.html, pNNN.review.html, index.html)
uv run rosetta translate "$B" --pages 41-44 [--lang tr] [--model sonnet|haiku] [--think off|low|medium|high]
                         [--profile profile.json] [--force] [--max-budget-usd 0.25] [--open] [--yes]

# Book profile
uv run rosetta profile analyze "$B"                  # one AI call, confirmed
uv run rosetta profile show|export|import "$B" ...
uv run rosetta profile set "$B" --term "replication=replikasyon" --dnt Kafka [--remove-term X] [--tur …] [--ton …]

# Batch jobs
uv run rosetta job start "$B" (--pages 120-140 | --all) [--budget 2.0]
uv run rosetta job list | status ID | pause ID | resume ID | retry-failed ID | cancel ID

# Term consistency (no AI)
uv run rosetta consistency "$B"

# PDF export (no AI)
uv run rosetta export "$B" [--pages …] [--mode tr|bilingual] [--paper a4|letter] [-o out.pdf] [--no-toc-page]

# Learning (no AI)
uv run rosetta dict build                            # offline dictionary (~520 MB download, ~3 min), once
uv run rosetta lookup replicated                     # → replicate
uv run rosetta vocab add WORD --book "$B" --page 59 [--sentence …] [--unknown|--known]
uv run rosetta vocab list | mark WORD --unknown|--known
uv run rosetta review                                # cards that are due
uv run rosetta terms "$B" [--add-all]                # technical terms from the profile glossary
uv run rosetta stats
uv run rosetta learn-html "$B" --pages 25            # pNNN.learn.html

# Explain this (confirmed, cached)
uv run rosetta explain "That's all you can hope for." [--book "$B" --page 25] [--model haiku]

# Usage and API server
uv run rosetta usage [--book "$B"]
uv run rosetta serve --port 0                        # prints one line of {"port", "token"} JSON
```

## Cost and safety

- **Only the `claude` CLI, only your subscription.** Rosetta calls `claude -p`. Log in once with
  `claude` or set `CLAUDE_CODE_OAUTH_TOKEN`. It never sends requests to the Anthropic API directly.
- **The subprocess environment is cleaned.** All `ANTHROPIC_*` variables (API key, base URL, etc.),
  `CLAUDE_EFFORT`, `CLAUDECODE`, `AI_AGENT`, `CLAUDE_CODE_*` (except `CLAUDE_CODE_OAUTH_TOKEN`) and an
  inherited `MAX_THINKING_TOKENS` are removed. Rosetta behaves the same wherever it is launched from,
  and billing never shifts to the API.
- **Estimate and confirm everywhere.** The CLI asks; every AI endpoint in the API requires a
  single-use `confirm_token` obtained with the same parameters (valid for 600 s, used once).
- **Per-call budget cap:** `--max-budget-usd 0.25` by default; if exceeded the run stops (exit code 6).
  Batch jobs also have a job budget (`--budget`).
- **Dollar figures are list-price equivalents.** On a Max/Pro subscription they are not a bill; the
  real limit is your subscription's usage limit. When it is hit, the job pauses (exit code 4) and can
  resume where it stopped.
- **Default model: Sonnet.** In a blind comparison on *Designing Data-Intensive Applications*
  (5 pages, ~50 sentences), Haiku made 9 meaning / 15 grammar / ~21 translationese errors and Sonnet
  4 / 0 / 2. Sonnet was also cheaper ($0.051 in one call) because it used almost no hidden thinking
  tokens. `--model haiku` remains as a cheaper, faster draft option. "Explain this" uses Haiku by default.
- **Thinking (`--think off|low|medium|high`):** medium by default. With Haiku, thinking can use 9k–18k
  hidden output tokens per call; the estimate adds this per model (`thinking_output_tokens_per_call`).
  `--think off` is the fastest and cheapest draft.
- **Safe translation storage:** each batch's paid result is saved immediately, and `--force` only
  replaces the old translation once the new one arrives. Model output is validated (JSON, ids, sentence
  count); if invalid it is retried once in strict mode, and if that fails the page is marked as failed.

## Providers

| Provider | What | Profile/context | Notes |
|---|---|---|---|
| `claude-cli` (default) | `claude -p`, subscription login | yes | model `sonnet` / `haiku` |
| `deepl` | DeepL API v2 | **no** (the UI says so) | key in the `DEEPL_AUTH_KEY` env var; `:fx` → free endpoint |
| `ollama` | local model, free | yes | `ollama_url`, `ollama_model` |
| `fake` | for tests, `[TR] …` | — | free, no network |

## Data and config paths

| | Linux default | Override |
|---|---|---|
| Data (DB, HTML/PDF output, dictionary) | `~/.local/share/rosetta/` (`rosetta.db`, `out/<hash>/`, `dictionary.db`) | `ROSETTA_DATA_DIR` |
| Settings | `~/.config/rosetta/config.toml` | `ROSETTA_CONFIG_DIR` |

`config.toml` (the values shown are the defaults; Rosetta works without the file). Most settings can
also be changed in the app's **Settings** screen (gear icon or `Ctrl+,`), which keeps comments and the
`[pricing.*]` tables in the file. Settings → **Engine status** shows why something isn't working
(claude not found, dictionary not built, no Chromium…). These checks never send anything to the AI.

```toml
default_lang = "tr"
provider = "claude-cli"          # claude-cli | deepl | ollama | fake
model = "sonnet"                 # translation model
explain_model = "haiku"          # "Explain this"
batch_max_pages = 5              # max pages per call
batch_max_input_tokens = 6000    # max estimated input tokens per call
claude_timeout_s = 240
# claude_path = "/home/me/.local/bin/claude"  # empty: PATH + known install locations (automatic)
claude_effort = "medium"         # claude --effort
# claude_max_thinking_tokens = 0 # 0 = thinking off (MAX_THINKING_TOKENS=0)
claude_max_budget_usd = 0.25     # per-call cap (claude --max-budget-usd)
prefetch = false                 # always off (rule 1)
deepl_auth_key_env = "DEEPL_AUTH_KEY"
deepl_timeout_s = 60
ollama_url = "http://localhost:11434"
ollama_model = "qwen2.5:7b"
ollama_timeout_s = 600

[pricing.sonnet]   # $ per million tokens (estimates only)
in = 2.0
out = 10.0
[pricing.haiku]
in = 1.0
out = 5.0
[pricing.deepl]    # DeepL bills per character (~$25/1M chars Pro ≈ $90/1M tokens); free key: in = 0
in = 90.0
out = 0.0
[pricing.ollama]
in = 0.0
out = 0.0

[thinking_output_tokens_per_call.haiku]   # hidden thinking tokens added to the estimate (per call)
low = 13000
medium = 18000
high = 24000
[thinking_output_tokens_per_call.sonnet]
low = 500
medium = 1500
high = 6000
```

If you pick a model with no price defined, the estimate says "price unknown" instead of "$0". A broken
`config.toml` gives a readable error that includes the file path.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | general error (e.g. `claude` not found, invalid setting) |
| 2 | cancelled / not confirmed / no terminal and no `--yes` |
| 3 | partial failure (some pages failed) |
| 4 | usage limit (job paused) |
| 5 | authentication |
| 6 | budget cap exceeded |
| 7 | provider unavailable (`claude` missing or 3 failures in a row) |

## Building from source

| Tool | Why |
|---|---|
| [uv](https://docs.astral.sh/uv/) (installs Python 3.13 itself) | engine (`engine/`) |
| Node.js + npm | front end (`app/`) |
| Rust ([`rustup`](https://rustup.rs/)) | Tauri |
| Chromium | PDF export, E2E tests |

Tauri build dependencies:

- Arch: `webkit2gtk-4.1 base-devel curl wget file openssl librsvg xdotool`
- Debian/Ubuntu: `libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev librsvg2-dev`

```bash
cd engine && uv sync && uv run rosetta --help     # engine + CLI
cd app && npm ci && scripts/prepare-dev-sidecar.sh && npx tauri dev   # app (development)
packaging/build-app.sh                            # sidecar (PyInstaller) + AppImage + .deb
```

Bundles are written to `app/src-tauri/target/release/bundle/{appimage,deb}/`.

## Project layout

```
rosetta/
├── engine/                 Python engine (rosetta_engine), a uv project
│   ├── src/rosetta_engine/
│   │   ├── extract/        PyMuPDF → typed blocks, reading order, code/figure/table, callout markers
│   │   ├── store/          SQLite schema (migrations/), repositories
│   │   ├── translate/      prompt, validation, estimates, claude_cli, deepl, ollama, fake, service
│   │   ├── quality/        term consistency check
│   │   ├── render/         HTML output (tr / review / learn / debug)
│   │   ├── profile/        book profile
│   │   ├── jobs/           batch jobs
│   │   ├── export/         PDF export
│   │   ├── learn/          dictionary, vocabulary, FSRS
│   │   ├── explain/        "Explain this"
│   │   ├── api/            FastAPI sidecar
│   │   ├── commands/       CLI command plugins
│   │   └── cli.py          Typer CLI
│   ├── scripts/            build_dictionary.py
│   └── tests/
├── app/                    Tauri 2 + React + Vite + PDF.js front end (API_CONTRACT.md, e2e/)
├── packaging/              PyInstaller spec, sidecar and app build scripts
├── profiles/ddia.json      sample book profile
└── docs/                   design notes (Turkish)
```

## Development

```bash
cd engine
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -q --cov=rosetta_engine

cd app
npm run lint && npm run typecheck && npm test
npm run e2e            # Playwright: real engine (fake AI) + Vite, system Chromium
```

- Tests never call the real `claude`; they use fake providers and fake runners.
- `uv run pytest -m live -q` makes real `claude` calls (spends tokens). Run it only on purpose.
- The hidden `rosetta serve --dev-fake-ai` flag replaces AI with fake answers for development. It
  cannot be enabled through an environment variable, and the packaged app never uses it.

## Licenses

- **Rosetta:** [AGPL-3.0-or-later](LICENSE). The engine uses AGPL-3.0 licensed
  [PyMuPDF](https://pymupdf.readthedocs.io/), so the repository is AGPL-compatible.
- **Dictionary data:** English Wiktionary (via [kaikki.org](https://kaikki.org/)), CC BY-SA 4.0 + GFDL;
  attribution required. The data is **not** in the repository; build it locally with `rosetta dict build`
  (`dictionary.db`, ~157 MB). Source and license: `rosetta dict info`.
- **Python dependencies:** pydantic, typer, rich, jinja2, platformdirs, httpx, fastapi, uvicorn,
  simplemma, fsrs (MIT/BSD/Apache-2.0).
- **Front-end dependencies:** React (MIT), pdf.js / `pdfjs-dist` (Apache-2.0), Tauri and its plugins
  (MIT/Apache-2.0).
