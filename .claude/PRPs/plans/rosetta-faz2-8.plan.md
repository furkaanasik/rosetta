# Plan: Rosetta Faz 2–8 (agent dalgaları)

Gereksinimler: `.claude/PRPs/prds/rosetta-requirements.md` (bağlayıcı). Faz 1 raporu: `.claude/PRPs/reports/rosetta-faz1-motor-cli-report.md`.

## Ortak kurallar (her agent)
- Gerçek `claude` CLI'ı, DeepL, Ollama veya herhangi bir AI/API ASLA çağrılmaz. Testler sahte runner/sağlayıcılarla.
- `uv add` YOK (bağımlılıklar hazır: fastapi, uvicorn, httpx, fsrs, simplemma). Ek bağımlılık gerekirse rapora yaz.
- Sadece kendi dosyalarına dokun. Paylaşılan dosyalarda (config.py, cli.py, service.py, models.py) küçük, hedefli Edit; düzenlemeden önce dosyayı yeniden oku.
- CLI komutları: `src/rosetta_engine/commands/<faz>.py` içinde `def register(app: typer.Typer) -> None` (otomatik yüklenir). `cli.py`'ye komut ekleme.
- Belgeler: `docs/<faz>.md` (Türkçe). README'yi düzenleme; README birleştirmesini koordinatör yapar.
- Migration numaraları: 003_jobs (Faz 4), 004_learning (Faz 6), 005_explanations (Faz 7), 006_profile (Faz 2, gerekirse).
- `usage.operation`: "translate" | "profile" | "explain".
- Kalite: ruff + ruff format + mypy strict + pytest; kapsam ≥%80; DDIA testleri PDF yoksa skip.
- Kurallar 1–6 (gereksinim §2) her yerde geçerli: AI sadece açık kullanıcı eylemiyle, önce tahmin+onay.

## Sözleşmeler
- **Genel LLM çağrısı (Faz 2 yazar, Faz 7 kullanır):** `translate/claude_cli.py`:
  `complete(system_prompt: str, user_message: str, *, model: str | None = None, settings: Settings | None = None, json_schema: dict | None = None, runner: Runner = run_subprocess) -> Completion` — `Completion(text: str, structured: dict | None, input_tokens: int, output_tokens: int, cost_usd: float)`. Aynı env temizliği, argv, hata sınıflandırması (UsageLimit/Auth/Budget/Unavailable/ProviderError). `ClaudeCliTranslator.translate` bunu kullanacak şekilde yeniden düzenlenir.
- **Sağlayıcı fabrikası (Faz 8):** `translate/providers.py: make_translator(provider: str, model: str | None, settings: Settings) -> Translator`; `cli._translator` bunu çağırır. İsimler: "claude-cli", "fake", "deepl", "ollama".
- **İş durdurma kancası (Faz 4):** `PageTranslationService.execute(..., should_stop: Callable[[], bool] | None = None)` — her batch öncesi kontrol; True → `stop_kind="paused"`.
- **Öğrenme görünümü (Faz 6):** `render/html_builder` yeni mod `"learn"` (orijinal metin + bilinmeyen kelimelerin üstünde `<ruby>` karşılık); export (Faz 5) render'ı yalnızca çağırır, düzenlemez.
- **Sözlük:** ayrı SQLite `data_dir()/dictionary.db` (Faz 6, build script + lisans).

## Dalgalar
1. Motor: Faz 2 profil · Faz 4 toplu iş · Faz 5 PDF export · Faz 6 öğrenme çekirdeği · Faz 8 DeepL/Ollama (paralel)
2. Faz 7 "Bunu açıkla" + Faz 3 API (FastAPI sidecar) → Faz 3 uygulama (Tauri 2 + React + Vite + PDF.js)
3. Paketleme (PyInstaller sidecar, AppImage/.deb), README birleştirme, kod incelemesi, düzeltmeler
