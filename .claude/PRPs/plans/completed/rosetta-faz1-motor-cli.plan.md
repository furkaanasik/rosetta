# Plan: Rosetta — Faz 1 (Motor + CLI test)

## Summary
Rosetta'nın Python çeviri motorunu (`rosetta_engine`) sıfırdan kuruyoruz: PyMuPDF ile sayfadan tipli block çıkarma (başlık/paragraf/liste/kod/görsel/tablo/caption/dipnot), monospace font ile kod tespiti, `claude -p` üzerinden çeviri yapan provider, SQLite cache ve lokal HTML builder. Faz 1'in çıktısı tek bir CLI komutu: verilen PDF'in belirli sayfalarını maliyet onayıyla çevirip reflow HTML (+ EN|TR inceleme sayfası) üretir. Arayüz, FastAPI ve toplu iş Faz 1'de YOK.

## User Story
Kitap okuyucusu olarak, 650 sayfalık İngilizce PDF'imin seçtiğim sayfalarını tek komutla, maliyetini önceden görüp onaylayarak Türkçeye çevirmek ve orijinal hiyerarşiyi koruyan bir HTML olarak görmek istiyorum; böylece çeviri kalitesini arayüz yazılmadan önce değerlendirebileyim.

## Problem → Solution
Boş klasör, hiçbir kod yok → `uv run rosetta translate kitap.pdf --pages 41-44` komutu: extract → cache kontrol → tahmin + onay → Claude CLI → doğrulama → cache → `out/<kitap>/p041.tr.html` + `p041.review.html`.

## Metadata
- **Complexity**: XL (greenfield; ~32 dosya) — Faz 1 bilinçli olarak sadece motorla sınırlandı
- **Source PRD**: N/A (kullanıcı mesajındaki gereksinim dokümanı)
- **PRD Phase**: Faz 1 — Motor + CLI test
- **Estimated Files**: ~32 (src ~20, test ~10, config/readme ~4)

---

## UX Design

### Before
N/A — proje boş.

### After (CLI)
```
$ uv run rosetta translate ~/books/kitap.pdf --pages 41-44 --lang tr
Kitap: <başlık> (hash 3f9a…)  sayfa 41-44
Extract: 4 sayfa, 61 block (çevrilecek 47 · kod 9 · görsel 3 · header/footer 2)
Cache: 0/47 block hazır
Tahmin (claude-cli / haiku):
  çağrı: 1   input ≈ 5 900 tok   output ≈ 6 800 tok   ≈ $0.040 (liste fiyatı eşdeğeri)
Onaylıyor musun? [y/N] y
[████████████████] 4/4 sayfa   gerçek: in 5 712 / out 6 410 tok, $0.038
Çıktı: ~/.local/share/rosetta/out/3f9a…/p041.tr.html … p044.review.html
```
Ek komutlar: `rosetta extract … --debug` (block tipleri renkli, bbox'lı HTML — çeviri yok, bedava), `rosetta estimate …`, `rosetta usage`.

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| Sayfa çevirme | yok | `rosetta translate` | `--yes` yoksa her zaman onay sorar (Kural 2) |
| Kalite inceleme | yok | `pNNN.review.html` (EN \| TR yan yana, block hizalı) | Split modun prototipi |
| Extract hata ayıklama | yok | `rosetta extract --debug` | AI çağrısı yok |

---

## Mandatory Reading
Greenfield proje: okunacak mevcut kod yok. Uygulamadan önce okunacaklar:

| Priority | Kaynak | Why |
|---|---|---|
| P0 | Bu plan, "Doğrulanmış Claude CLI Bulguları" bölümü | Provider'ın tam komut satırı ve çıktı şeması |
| P0 | PyMuPDF `Page.get_text("dict")` dokümanı | span flags bitleri, block yapısı |
| P1 | PyMuPDF `Page.find_tables`, `Page.get_drawings`, `Page.get_pixmap(clip=)` | tablo/figür tespiti ve kırpma |
| P1 | platformdirs `user_data_dir`, `user_config_dir` | yollar |

## External Documentation
| Topic | Source | Key Takeaway |
|---|---|---|
| PyMuPDF text dict | pymupdf.readthedocs.io/en/latest/textpage.html | span `flags`: 1=superscript, 2=italic, 4=serif, 8=monospaced, 16=bold |
| PyMuPDF tables | pymupdf.readthedocs.io (Page.find_tables) | ≥1.23; bbox + hücre metni verir |
| PyMuPDF lisansı | AGPL-3.0 | Kişisel kullanım sorun değil; dağıtılırsa repo AGPL uyumlu olmalı (README'ye yazılacak) |
| platformdirs | platformdirs.readthedocs.io | Linux: `~/.local/share/rosetta`, `~/.config/rosetta` (XDG'ye uyar) |
| Claude Code CLI 2.1.284 | `claude --help` (yerelde doğrulandı) | Aşağıdaki bölüm |

### Doğrulanmış Claude CLI Bulguları (bu makinede, 2026-10-16, claude 2.1.284)
```
KEY_INSIGHT: Çeviri çağrısı için doğrulanmış komut:
  claude -p --model haiku --output-format json \
    --tools "" --no-session-persistence --strict-mcp-config \
    --disable-slash-commands --setting-sources "" \
    --system-prompt "<rosetta sistem prompt'u>"
  prompt stdin'den, sonuç stdout'tan. Bu ayarla küçük test: 386 input token, num_turns=1, $0.00063.
APPLIES_TO: translate/claude_cli.py
GOTCHA: --bare KULLANMA — OAuth/keychain okumaz, sadece ANTHROPIC_API_KEY ile çalışır (abonelik kuralını bozar).
GOTCHA: --max-turns bu sürümün --help'inde yok; --tools "" ile zaten tek tur.
GOTCHA: --system-prompt varsayılan Claude Code sistem prompt'unu tamamen değiştirir → ciddi token tasarrufu (zorunlu kullan).
```
```
KEY_INSIGHT: stdout JSON alanları: type="result", subtype ("success"|...), is_error (bool),
  api_error_status (null|int), result (str: modelin metni), total_cost_usd (float),
  usage.input_tokens / output_tokens / cache_*_input_tokens, modelUsage{<model_id>:{costUSD,...}},
  num_turns, terminal_reason, session_id.
APPLIES_TO: claude_cli.py parse + usage tablosu
GOTCHA: total_cost_usd abonelikte de "liste fiyatı eşdeğeri" olarak dolu gelir (costBasis: "list"); gerçek fatura değil — UI'da "≈ eşdeğer" diye göster.
```
```
KEY_INSIGHT: --json-schema çalışıyor ve `structured_output` alanında parse edilmiş obje dönüyor,
  AMA num_turns=2 ve aynı küçük istek için input 386 → 1226 token (≈ +840 token/çağrı, 2. tur).
APPLIES_TO: claude_cli.py strateji
GOTCHA: Varsayılan: --json-schema YOK, `result` metnini lokal parse+validate et (ucuz).
  İlk denemede JSON geçersizse retry'da --json-schema ile dene (güvenilir ama pahalı).
```
```
KEY_INSIGHT: ANTHROPIC_API_KEY ortamda tanımlıysa CLI API faturasına gidebilir.
APPLIES_TO: claude_cli.py subprocess env
GOTCHA: Alt sürece giden env'den ANTHROPIC_API_KEY'i çıkar (config ile kapatılabilir), CLAUDE_CODE_OAUTH_TOKEN'ı geçir.
```

---

## Patterns to Mirror
Greenfield — mirror edilecek mevcut kod yok. Bu plan konvansiyonları TANIMLAR; tüm görevler bunlara uyar.

### NAMING_CONVENTION
```python
# modüller snake_case, sınıflar PascalCase, sabitler UPPER_SNAKE
# Domain modelleri: pydantic v2, frozen
class BlockType(StrEnum):
    HEADING = "heading"; PARAGRAPH = "paragraph"; LIST_ITEM = "list_item"
    CODE = "code"; IMAGE = "image"; TABLE = "table"; CAPTION = "caption"
    FOOTNOTE = "footnote"; FURNITURE = "furniture"  # header/footer/sayfa no

class Block(BaseModel):
    model_config = ConfigDict(frozen=True)
    page_no: int            # 0-based iç, CLI'da 1-based gösterilir
    order: int              # sayfa içi okuma sırası
    type: BlockType
    bbox: tuple[float, float, float, float]
    font: str
    size: float
    bold: bool
    italic: bool
    heading_level: int | None = None
    text: str               # inline kod `backtick` ile işaretli
    sentences: list[str] = Field(default_factory=list)
    text_hash: str          # sha256(text)[:16]
    # translatable: property, type ∈ TRANSLATABLE
```

### ERROR_HANDLING
```python
# translate/errors.py — hepsi RosettaError'dan türer; service tipine göre karar verir
class RosettaError(Exception): ...
class ProviderError(RosettaError): ...            # genel
class UsageLimitError(ProviderError): ...         # iş DURAKLAR, retry YOK
class ProviderAuthError(ProviderError): ...       # iş durur, kullanıcıya login talimatı
class InvalidTranslationError(ProviderError):     # JSON/id doğrulama hatası → 1 retry
    def __init__(self, reason: str, raw: str) -> None: ...
```
Kural: hata yutulmaz; sayfa "failed" olarak DB'ye nedeniyle yazılır.

### LOGGING_PATTERN
```python
import logging
log = logging.getLogger(__name__)
log.info("translated page", extra={"book": h[:8], "page": n, "in_tok": i, "out_tok": o})
# Kullanıcıya dönük çıktı sadece cli.py'de (rich); motor modülleri print etmez.
# Prompt/yanıt içeriği DEBUG seviyesinde, varsayılan kapalı.
```

### REPOSITORY_PATTERN
```python
# store/repo.py — ham sqlite3, her repo bir Connection alır, SQL sadece burada
class TranslationRepo:
    def __init__(self, conn: sqlite3.Connection) -> None: self._c = conn
    def get_many(self, book_id: int, keys: Sequence[CacheKey]) -> dict[CacheKey, StoredTranslation]: ...
    def put_page(self, rows: Sequence[TranslationRow], status: PageStatusRow) -> None: ...  # tek transaction
```

### SERVICE_PATTERN
```python
# translate/service.py — saf orkestrasyon, I/O bağımlılıkları constructor'dan (test için Fake)
class PageTranslationService:
    def __init__(self, translator: Translator, repos: Repos, clock: Callable[[], datetime]) -> None: ...
    def plan(self, book: Book, pages: Sequence[int], lang: str) -> TranslationPlan: ...   # AI yok
    def execute(self, plan: TranslationPlan) -> TranslationReport: ...                   # sadece onaydan sonra
```

### TEST_STRUCTURE
```python
# tests/conftest.py — gerçek kitap yerine PyMuPDF ile sentetik PDF üret
@pytest.fixture
def two_column_pdf(tmp_path: Path) -> Path:
    doc = pymupdf.open(); page = doc.new_page()
    page.insert_text((50, 60), "Chapter 5. Replication", fontname="tibo", fontsize=18)
    page.insert_textbox(pymupdf.Rect(50, 80, 290, 700), LEFT_TEXT, fontname="tiro", fontsize=10)
    page.insert_textbox(pymupdf.Rect(320, 80, 560, 700), RIGHT_TEXT, fontname="tiro", fontsize=10)
    out = tmp_path / "two_col.pdf"; doc.save(out); return out
# test_<modül>.py, fonksiyon başına bir davranış, AAA düzeni,
# ağ/subprocess yok (FakeTranslator / fake runner)
```

---

## Mimari Kararlar (Faz 1)

1. **Monorepo**: `engine/` (Python, uv) + ileride `app/` (Tauri). Faz 1'de `app/` oluşturulmaz.
2. **FastAPI Faz 1'de yok.** Motor saf kütüphane + Typer CLI. Faz 3'te `rosetta_engine.api` ince bir katman olarak eklenir; servisler aynen kullanılır.
3. **Block kimliği**: DB'de `blocks.id` (int) + doğal anahtar `(book_id, page_no, ord)`. LLM'e batch içi `1..N` kısa int id gider; eşleme lokal tutulur (token tasarrufu).
4. **Cache anahtarı**: `(book_hash, page_no, block_text_hash, lang, provider, model)`. İstenen anahtara `block_text_hash` eklendi: extractor iyileşip bir block'un metni değişirse eski çeviri yanlışlıkla gösterilmez; metni değişmeyen block'lar cache'ten gelmeye devam eder. Profil değişikliği cache'i **geçersiz kılmaz** (Kural 3); yeniden çeviri yalnızca açık `--force` ile.
5. **Cümle eşleme veri modeli Faz 1'den**: block metni lokal olarak cümlelere bölünür (kendi kural tabanlı bölücümüz, `extract/sentences.py`), LLM'e `{"id":1,"s":["…","…"]}` gider, aynı uzunlukta dizi döner. `<s1>` etiketleri yerine JSON dizisi: daha az token, parse güvenli. Tahmini ek maliyet ~%6–10 (cümle başına ~3–4 token JSON yükü, ortalama cümle ~25 token). Cümle sayısı tutmazsa block birleşik metinle kabul edilir, `sentence_aligned=false` (sayfa hatalı sayılmaz). **Gerekçe**: 650 sayfayı sonra cümle eşleme için yeniden çevirmek, şimdi ~%8 fazla ödemekten pahalı. (Kullanıcı onayına sunuldu — Soru 3.)
6. **Inline kod**: paragraf içindeki monospace span'lar `` `…` `` ile sarılır; prompt "backtick içini aynen bırak" der; validator backtick içeriklerinin çeviride birebir bulunduğunu kontrol eder (uyuşmazlık = uyarı); HTML builder backtick'i `<code>`'a çevirir.
7. **LLM çıktısı güvenilmez girdi**: HTML builder her metni escape eder, sadece kendi ürettiği `<code>`/`<span>` etiketlerini ekler.
8. **Görsel/figür/tablo**: çevrilmez, `page.get_pixmap(clip=bbox, dpi=150)` ile PNG olarak kırpılıp HTML'e konur. Figür içindeki metin LLM'e gitmez. Tablolar Faz 1'de görsel olarak gösterilir (hücre çevirisi sonraya — Soru 5).
9. **Maliyet tahmini**: `input ≈ sys_prompt_tok + ceil(chars/3.6) + json_overhead`, `output ≈ input_text_tok × 1.35` (Türkçe tokenizasyonu daha pahalı). Fiyat tablosu config'te (Haiku 4.5: $1/M in, $5/M out). Her gerçek çağrıdan sonra `usage` tablosuna tahmin + gerçek token yazılır; tahmin, gerçek/tahmin oranıyla kalibre edilir.
10. **Batch**: bir çağrı ≤ 5 sayfa ve ≤ ~6 000 tahmini input token; hangisi önce dolarsa. Bağlam = batch'ten önceki sayfanın son 2 çevrilebilir paragrafı (EN; cache'te TR'si varsa o da), "çevirme" etiketiyle.
11. **Python sürümü**: `requires-python = ">=3.12"`, `uv python pin 3.13` (makinede 3.14 var; PyMuPDF/PyInstaller uyumu için 3.13 güvenli seçim).

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `README.md` | CREATE | Ad, kurulum (uv), Linux sistem bağımlılıkları, lisans notları |
| `.gitignore` | CREATE | `.venv`, `out/`, `*.pdf`, `__pycache__` |
| `engine/pyproject.toml` | CREATE | uv projesi, bağımlılıklar, ruff/mypy/pytest ayarları, `rosetta` script'i |
| `engine/.python-version` | CREATE | 3.13 |
| `engine/src/rosetta_engine/__init__.py` | CREATE | `__version__` |
| `engine/src/rosetta_engine/config.py` | CREATE | platformdirs yolları, `Settings` (`~/.config/rosetta/config.toml`), fiyat tablosu |
| `engine/src/rosetta_engine/models.py` | CREATE | `Block`, `BlockType`, `Book`, `BookProfile`, `CostEstimate`, `Translation`, `TranslationPlan`, `TranslationReport` |
| `engine/src/rosetta_engine/extract/pdf_reader.py` | CREATE | PyMuPDF → `RawSpan`/`RawLine`/`RawBlock` (tek PyMuPDF temas noktası) |
| `engine/src/rosetta_engine/extract/fonts.py` | CREATE | `is_monospace`, bold/italic çözümü |
| `engine/src/rosetta_engine/extract/stats.py` | CREATE | Kitap geneli gövde puntosu + başlık seviyeleri |
| `engine/src/rosetta_engine/extract/furniture.py` | CREATE | Tekrarlayan header/footer/sayfa no |
| `engine/src/rosetta_engine/extract/figures.py` | CREATE | Görsel, vektör çizim, tablo bölgeleri; figür-içi metni yutma |
| `engine/src/rosetta_engine/extract/layout.py` | CREATE | Sütun tespiti + okuma sırası |
| `engine/src/rosetta_engine/extract/text_clean.py` | CREATE | Tire birleştirme, ligatür, boşluk, inline kod backtick |
| `engine/src/rosetta_engine/extract/classify.py` | CREATE | Block tipi sınıflandırma |
| `engine/src/rosetta_engine/extract/sentences.py` | CREATE | Kural tabanlı cümle bölücü (pysbd YOK) |
| `engine/src/rosetta_engine/extract/extractor.py` | CREATE | Pipeline |
| `engine/src/rosetta_engine/store/db.py` | CREATE | Bağlantı + `PRAGMA user_version` migration |
| `engine/src/rosetta_engine/store/migrations/001_init.sql` | CREATE | Faz 1 şeması |
| `engine/src/rosetta_engine/store/repo.py` | CREATE | Repo'lar |
| `engine/src/rosetta_engine/translate/errors.py` | CREATE | Hata hiyerarşisi |
| `engine/src/rosetta_engine/translate/base.py` | CREATE | `Translator` Protocol, `ProviderResult` |
| `engine/src/rosetta_engine/translate/prompt.py` | CREATE | Sistem prompt'u + kullanıcı mesajı; `PROMPT_VERSION` |
| `engine/src/rosetta_engine/translate/validate.py` | CREATE | JSON parse, id seti, cümle sayısı, backtick kontrolü |
| `engine/src/rosetta_engine/translate/estimator.py` | CREATE | Token/maliyet tahmini + kalibrasyon |
| `engine/src/rosetta_engine/translate/claude_cli.py` | CREATE | Subprocess provider |
| `engine/src/rosetta_engine/translate/fake.py` | CREATE | Test + ücretsiz uçtan uca deneme |
| `engine/src/rosetta_engine/translate/service.py` | CREATE | plan → (onay) → batch → validate → retry → cache |
| `engine/src/rosetta_engine/render/html_builder.py` | CREATE | Block + çeviri → HTML, görsel kırpma |
| `engine/src/rosetta_engine/render/templates/{page,review,debug}.html.j2`, `style.css` | CREATE | Şablonlar |
| `engine/src/rosetta_engine/cli.py` | CREATE | Typer: `extract`, `estimate`, `translate`, `usage` |
| `engine/tests/conftest.py`, `engine/tests/test_*.py` | CREATE | Sentetik PDF fixture'ları + birim testler |

## NOT Building (Faz 1)
- Tauri/React arayüzü, FastAPI sunucusu, PyInstaller paketleme
- Book Profiler LLM çağrısı (Faz 2) — Faz 1'de profil `--profile profile.json` ile elle verilebilir
- Toplu iş (jobs tablosu, pause/resume, bütçe limiti) (Faz 4) — ama `UsageLimitError` ve sayfa "failed" durumu şimdiden var
- PDF export (Faz 5), öğrenme modülü (Faz 6–7), DeepL/Ollama (Faz 8)
- Tablo hücre çevirisi, figür-içi metin çevirisi, OCR (taranmış PDF)
- Sayfalar arası bölünen paragrafların birleştirilmesi (sadece `continues_on_next_page` işareti)

---

## Step-by-Step Tasks

### Task 1: Proje iskeleti ve araçlar
- **ACTION**: `engine/` altında uv projesi oluştur.
- **IMPLEMENT**: `uv init --package --name rosetta-engine engine` (paket dizini `src/rosetta_engine`), `uv python pin 3.13`. Bağımlılıklar: `pymupdf>=1.24`, `pydantic>=2.7`, `platformdirs>=4`, `typer>=0.12`, `rich>=13`, `jinja2>=3.1`. Dev: `pytest`, `pytest-cov`, `mypy`, `ruff`. `[project.scripts] rosetta = "rosetta_engine.cli:app"`. ruff: `line-length=100`, select `E,F,I,UP,B,SIM,RUF`. mypy: `strict = true`, pymupdf için `ignore_missing_imports`. pytest marker: `live`. Kök `README.md`, `.gitignore`, `git init`.
- **MIRROR**: NAMING_CONVENTION
- **GOTCHA**: PyMuPDF'in import adı `pymupdf` (eski `fitz` kullanma).
- **VALIDATE**: `cd engine && uv sync && uv run rosetta --help && uv run pytest -q`.

### Task 2: config.py — yollar ve ayarlar
- **IMPLEMENT**: `APP_NAME="rosetta"`; `data_dir() = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))`, `config_dir()` aynı şekilde. DB: `data_dir()/rosetta.db`, çıktılar: `data_dir()/out/<book_hash[:12]>/`. `Settings` (pydantic) `config_dir()/config.toml`'dan `tomllib` ile okunur, yoksa varsayılanlar: `default_lang="tr"`, `provider="claude-cli"`, `model="haiku"`, `batch_max_pages=5`, `batch_max_input_tokens=6000`, `claude_timeout_s=240`, `pricing={"haiku": {"in": 1.0, "out": 5.0}}` ($/M token), `prefetch=False`. Override: `ROSETTA_DATA_DIR`, `ROSETTA_CONFIG_DIR` (testler için).
- **GOTCHA**: `appauthor=False` vermezsen Windows'ta ekstra klasör seviyesi oluşur. Dizinleri ilk kullanımda yarat, import anında değil.
- **VALIDATE**: `test_config.py`: env override yolu değiştiriyor; config yoksa varsayılanlar; TOML override.

### Task 3: models.py
- **IMPLEMENT**: NAMING_CONVENTION'daki `Block`/`BlockType` + `TRANSLATABLE = {HEADING, PARAGRAPH, LIST_ITEM, CAPTION, FOOTNOTE}`. `Book(id, file_hash, title, page_count)`. `BookProfile(genre="", tone="", target_lang="tr", do_not_translate: list[str], glossary: dict[str,str], code_languages: list[str])` — Türkçe anahtarları (`tur`, `ton`, `hedef_dil`, `cevrilmeyecek`, `sozluk`, `kod_dili`) `Field(alias=...)` + `populate_by_name=True` ile kabul et. `CostEstimate(calls, input_tokens, output_tokens, usd)`. `Translation(block_key, sentences, text, sentence_aligned)`. `Batch`, `TranslationPlan(book, lang, pages, cached_blocks, batches, estimate)`, `TranslationReport(done_pages, failed_pages: dict[int,str], stopped_reason: str|None, usage)`.
- **VALIDATE**: mypy strict temiz; `test_models.py`: Türkçe anahtarlı profil JSON'u parse oluyor.

### Task 4: extract/pdf_reader.py + fonts.py
- **IMPLEMENT**: `open_book(path)`; `file_hash(path)` = sha256 (1 MB chunk). `read_page(doc, n) -> RawPage`: `page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP | pymupdf.TEXT_PRESERVE_IMAGES)` (ligatürleri açmak için `TEXT_PRESERVE_LIGATURES` VERİLMEZ). `RawSpan(text, font, size, flags, bbox, origin)`, `RawLine(spans, bbox)`, `RawBlock(kind: "text"|"image", lines, bbox)`. Ayrıca `page.get_drawings()` rect'leri ve `page.find_tables().tables` bbox'ları. `has_text_layer`.
  `fonts.py`: `MONO_PATTERNS = re.compile(r"(mono|courier|consolas|menlo|monaco|inconsolata|source ?code|fira ?code|jetbrains|lucida ?console|andale|cmtt|lmmono|sfmono|letter ?gothic)", re.I)`; `is_monospace(font, flags) = bool(flags & 8) or bool(MONO_PATTERNS.search(strip_subset(font)))`. `strip_subset("ABCDEF+Courier-Bold") -> "Courier-Bold"`. Bold: `flags & 16` veya `bold|black|heavy|semibold`; italik: `flags & 2` veya `italic|oblique|It$`.
- **GOTCHA**: Subset prefix font adını bozar; her zaman soy. `flags & 8` bazı PDF'lerde eksik — isim ile OR'la.
- **VALIDATE**: `test_fonts.py`: `"XYZABC+Consolas"`, `"CourierNewPSMT"`, `"UbuntuMono-Regular"` → mono; `"Minion-Regular"` → değil; `"Myriad-SemiboldIt"` → bold+italic.

### Task 5: extract/stats.py — kitap geneli tipografi
- **IMPLEMENT**: Kitaptan ≤40 sayfa örnekle (eşit aralıklı, ilk %5 hariç). Mono olmayan span'larda karakter-ağırlıklı punto histogramı (0.5 pt'ye yuvarla) → mod = `body_size`. `> body_size×1.15` ve toplam karakterin <%5'i olan puntolar azalan sırayla `h1..h3`'e eşlenir. `TypographyStats(body_size, heading_sizes: dict[float,int], body_font_family: serif|sans)`; `books.typography_json`'da cache'lenir.
- **GOTCHA**: Tek sayfa istatistiği yanıltıcı; kitap düzeyi şart.
- **VALIDATE**: `test_stats.py`: 3 sayfa (10pt gövde, 18/14pt başlık) → `body=10, {18:1, 14:2}`.

### Task 6: extract/furniture.py — header/footer
- **IMPLEMENT**: Sayfanın üst %8 / alt %8 bandındaki satırlar aday. Normalize (rakam → `#`, küçük harf, boşluk sıkıştır). Örneklem sayfalarda ≥%30 tekrar eden normalize metin veya sadece rakam/roma rakamı → FURNITURE. `FurnitureModel` (normalize metin seti) kitap düzeyinde hesaplanır.
- **GOTCHA**: Bölüm başlığı sayfa üstünde olabilir — punto `body_size×1.15`'ten büyükse furniture sayılmaz.
- **VALIDATE**: `test_furniture.py`: 5 sayfada `"Chapter 5: Replication | 1##"` header + alt sayfa no → furniture; gövde değil.

### Task 7: extract/figures.py — görsel, çizim, tablo bölgeleri
- **IMPLEMENT**: (a) image block'lar → bölge. (b) `get_drawings()` rect'lerini 6pt tolerans ile birleştir (union-find); alanı sayfanın >%3'ü olanlar aday bölge; ince yatay ayraç çizgileri (h<2pt) atlanır. (c) `find_tables()` bbox'ları → TABLE. Bölgeyle ≥%70 kesişen text span'ları bölgeye ait.
  **Kutu istisnaları**: aday bölgedeki metnin ≥%60'ı monospace → bölge figür DEĞİL, kod bloğu arka planı (metin CODE olur). Metin gövde puntosunda ve ≥3 satır düz yazı → "Note/Tip" kutusu, metin PARAGRAPH (`aside=True`).
- **VALIDATE**: `test_figures.py`: gri dikdörtgen içinde Courier → code, figür değil; dikdörtgenler + çizgiler + küçük etiketler → tek IMAGE, etiketler yutulmuş; not kutusu → paragraph.

### Task 8: extract/layout.py — sütunlar ve okuma sırası
- **IMPLEMENT**: Furniture ve figür olmayan block'larla çalış. Tam genişlik block (genişlik > içerik alanının %60'ı) "span block". Kalan (mono olmayan) block'ların x-aralıklarını projekte et; ≥12pt boş dikey koridor varsa ve iki taraftaki sütunlar ≥2 block ve ≥ sayfa yüksekliğinin %25'ini kapsıyorsa sütun sınırı. Sayfa span block'larla yatay bantlara bölünür; her bantta sütunlar soldan sağa, sütun içi y sonra x. Mono block'lar en yakın sütuna atanır. Tek sütunda doğal olarak `(y, x)` sıralaması.
- **GOTCHA**: Kenar notları sütun sayılmamalı (yukarıdaki min kapsama kuralı). Girintili kod sahte koridor üretmesin (mono hariç).
- **VALIDATE**: `test_layout.py`: (1) iki sütun → sol sütun tümüyle sağdan önce; (2) tam genişlik başlık + iki sütun + tam genişlik dipnot → başlık, sol, sağ, dipnot; (3) tek sütun + girintili kod → sıra korunur.

### Task 9: extract/text_clean.py + classify.py + sentences.py
- **IMPLEMENT**:
  - `text_clean`: satırları birleştir; satır sonu `-` ve sonraki satır küçük harfle başlıyorsa ve önceki parça ≥3 harfse tireyi kaldırıp birleştir, aksi halde koru; `­` sil; ` ` → boşluk; çoklu boşluk tekille (CODE hariç). Paragraf içindeki ardışık mono span'ları `` `…` `` ile sar (içerikte backtick varsa çift backtick).
  - `classify` (öncelik): FURNITURE → IMAGE/TABLE → CODE (karakterlerin ≥%70'i mono; satırlar ve girinti korunur) → CAPTION (`^(Figure|Fig\.|Table|Listing|Example)\s+[\dA-Z]+[-.\d]*` ve bir IMAGE/TABLE/CODE'a ≤30pt) → HEADING (punto `heading_sizes`'ta; ya da tek satır + bold + gövde puntosu + ≤12 kelime + nokta ile bitmiyor → seviye 4) → FOOTNOTE (punto ≤ body×0.85, sayfanın alt %25'i; ana metindeki superscript span'lar `[^n]` olarak işaretlenir) → LIST_ITEM (`^[•●▪◦‣–\-*]\s`, `^\(?\d{1,2}[.)]\s` veya ilk span bullet glifi; çok maddeli block'lar maddelere bölünür) → PARAGRAPH. Drop-cap (tek karakter, çok büyük punto) sonraki paragrafla birleştirilir.
  - `sentences`: kural tabanlı bölücü: `[.!?]` (+ opsiyonel `”’")`) + boşluk + büyük harf/rakam/`“`/backtick ile başlayan sınır. İstisnalar: `ABBREVIATIONS = {e.g., i.e., etc., vs., cf., Fig., Figs., Eq., Ch., Sec., No., Vol., al., Mr., Ms., Dr., Inc., Ltd., approx.}`, tek harf + nokta (`A.`), ondalık sayılar (`3.5`), sürüm/dosya adları (`v1.2`, `config.yaml`), backtick içi asla bölünmez, `[12]` atıf numarası önceki cümlede kalır. Sadece çevrilebilir block'lar.
- **VALIDATE**: `test_text_clean.py` (`replica-\ntion` → `replication`; `client-\nSide` korunur; inline mono → backtick), `test_classify.py` (her tip için bir örnek), `test_sentences.py` (`"Use e.g. Kafka. It works."` → 2; `` "Call `a.b()`. Done." `` → 2, backtick bölünmemiş).

### Task 10: extract/extractor.py
- **IMPLEMENT**: `EXTRACTOR_VERSION = 1`. `extract_book_meta(doc) -> BookMeta(title, page_count, stats, furniture)`; `extract_page(doc, n, meta) -> PageBlocks`: read → figures → furniture → clean → classify → layout → sentences → `text_hash`. Saf fonksiyonlar; DB yazımı service'te. Son block paragrafsa ve `.:!?` ile bitmiyorsa `continues_on_next_page=True`.
- **VALIDATE**: `test_extractor.py`: sentetik kitap sayfası (header, h1, 2 paragraf, kod, figür+caption, liste, dipnot, footer) → beklenen tip dizisi ve sıra.

### Task 11: store/ — SQLite şema ve repo'lar
- **IMPLEMENT**: `db.connect(path)`: `journal_mode=WAL; foreign_keys=ON; busy_timeout=5000`; `migrate(conn)`: `importlib.resources` ile `migrations/NNN_*.sql`, `PRAGMA user_version`'dan büyükleri sırayla uygula. `001_init.sql`:
  ```sql
  CREATE TABLE books(id INTEGER PRIMARY KEY, file_hash TEXT UNIQUE NOT NULL, title TEXT,
    page_count INTEGER NOT NULL, typography_json TEXT, furniture_json TEXT, file_path TEXT,
    created_at TEXT NOT NULL);
  CREATE TABLE pages(book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL, extractor_version INTEGER NOT NULL, extracted_at TEXT NOT NULL,
    has_text_layer INTEGER NOT NULL, continues_on_next_page INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(book_id, page_no));
  CREATE TABLE blocks(id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL, page_no INTEGER NOT NULL,
    ord INTEGER NOT NULL, type TEXT NOT NULL, bbox_json TEXT NOT NULL, font TEXT, size REAL,
    bold INTEGER, italic INTEGER, heading_level INTEGER, text TEXT NOT NULL,
    sentences_json TEXT NOT NULL DEFAULT '[]', text_hash TEXT NOT NULL,
    UNIQUE(book_id, page_no, ord),
    FOREIGN KEY(book_id, page_no) REFERENCES pages(book_id, page_no) ON DELETE CASCADE);
  CREATE TABLE translations(id INTEGER PRIMARY KEY, book_id INTEGER NOT NULL REFERENCES books(id),
    page_no INTEGER NOT NULL, text_hash TEXT NOT NULL, lang TEXT NOT NULL, provider TEXT NOT NULL,
    model TEXT NOT NULL, text TEXT NOT NULL, sentences_json TEXT NOT NULL,
    sentence_aligned INTEGER NOT NULL, prompt_version INTEGER NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(book_id, page_no, text_hash, lang, provider, model));
  CREATE TABLE page_status(book_id INTEGER NOT NULL, page_no INTEGER NOT NULL, lang TEXT NOT NULL,
    provider TEXT NOT NULL, model TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('done','failed')), error TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY(book_id, page_no, lang, provider, model));
  CREATE TABLE profiles(book_id INTEGER PRIMARY KEY REFERENCES books(id), json TEXT NOT NULL,
    updated_at TEXT NOT NULL);
  CREATE TABLE usage(id INTEGER PRIMARY KEY, ts TEXT NOT NULL, book_id INTEGER, provider TEXT NOT NULL,
    model TEXT NOT NULL, operation TEXT NOT NULL, input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL, cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    est_input_tokens INTEGER, est_output_tokens INTEGER, cost_usd REAL NOT NULL, ok INTEGER NOT NULL);
  ```
  Çeviri `blocks.id`'ye değil `text_hash`'e bağlı: sayfa yeniden extract edilse de cache yaşar. Repo'lar: `BookRepo.get_or_create`, `BlockRepo.replace_page` (extractor_version eskiyse), `TranslationRepo.get_many/put_page`, `PageStatusRepo`, `UsageRepo.add/total`. `jobs`, `vocab`, `reviews`, `explanations` sonraki fazların migration'larında.
- **MIRROR**: REPOSITORY_PATTERN
- **GOTCHA**: Bir sayfanın tüm block çevirileri + `page_status='done'` TEK transaction. `INSERT … ON CONFLICT DO NOTHING` (ikinci yazım asla üzerine yazmaz; `--force` açıkça `DELETE` + insert). Zaman damgaları UTC ISO-8601.
- **VALIDATE**: `test_store.py` (in-memory): migration idempotent; aynı anahtarla ikinci put değeri değiştirmiyor; `get_many` doğru eşliyor; transaction ortasında hata → yarım sayfa yok.

### Task 12: translate/prompt.py + validate.py
- **IMPLEMENT**:
  - `PROMPT_VERSION = 1`. `build_system_prompt(lang)` (sabit, kısa, İngilizce): görev; kurallar (anlamı koru; sözlük karşılıklarını kullan; `do_not_translate` terimleri, backtick içi, sınıf/metot adları, URL'ler, sayılar aynen; her öğenin `s` dizisini aynı sayıda cümleyle çevir, birleştirme/bölme yapma; `"k":"h"` öğeleri başlık üslubuyla; `CONTEXT` bölümünü ÇEVİRME; sadece JSON: `{"items":[{"id":int,"s":[str,...]}]}`).
  - `build_user_message(profile, context, items) -> str`: `PROFILE:` (boş alanlar atlanır; glossary/do_not_translate sadece batch metninde geçenlerle **filtrelenir**), `CONTEXT (do not translate):`, `ITEMS:` + kompakt JSON (`separators=(",",":")`, `ensure_ascii=False`).
  - `validate.parse_response(raw, expected: dict[int,int]) -> dict[int, ParsedItem]`: kod çitlerini soy, ilk `{` … son `}`, `json.loads`; `items` listesi; id seti == beklenen (eksik/fazla/tekrar → `InvalidTranslationError`); her `s` boş olmayan str listesi. Cümle sayısı farklı → `aligned=False` (hata değil). Backtick içerikleri çıkışta yoksa `log.warning`.
- **GOTCHA**: Kitap metni prompt'a girer (prompt injection teorik; tool yok, zarar = kötü çeviri). JSON dışı her şey reddedilir.
- **VALIDATE**: `test_prompt.py`: glossary filtreleme, context ayrı bölümde, deterministik çıktı. `test_validate.py`: geçerli; kod çitli; eksik id; fazla id; bozuk JSON; cümle sayısı farklı → aligned=False; `s` string değil → hata.

### Task 13: translate/estimator.py
- **IMPLEMENT**: `estimate_tokens(text) = ceil(len(text)/3.6)`; batch input = sistem prompt token'ı (sabit, bir kez hesaplanır) + profil + context + items + 4/cümle; output = `ceil(items_tok × 1.35) + 4/cümle + 10`. `usd = in/1e6×p_in + out/1e6×p_out`. Kalibrasyon: son 20 başarılı çağrıda `gerçek/tahmin` ortalaması (≥3 örnek, [0.5, 2.0]'a kırp). Cache'teki block'lar tahmine girmez.
- **VALIDATE**: `test_estimator.py`: boş → 0 çağrı/0$; bilinen metin → beklenen aralık; kalibrasyon çarpanı uygulanıyor.

### Task 14: translate/claude_cli.py
- **IMPLEMENT**: `ClaudeCliTranslator(model="haiku", runner: Runner = run_subprocess, settings)`, `name="claude-cli"`. Komut: `["claude","-p","--model",model,"--output-format","json","--tools","","--no-session-persistence","--strict-mcp-config","--disable-slash-commands","--setting-sources","","--system-prompt",system_prompt]`; retry modunda `+ ["--json-schema", SCHEMA_JSON]`. `subprocess.run(cmd, input=user_msg, capture_output=True, text=True, timeout=…, cwd=data_dir(), env=_env())`; `_env()` `ANTHROPIC_API_KEY`'i çıkarır (ayar açıksa). Sınıflandırma:
  - `shutil.which("claude") is None` → `ProviderError("claude CLI bulunamadı")`
  - `UsageLimitError`: `api_error_status == 429` veya result/stderr'de `/usage limit|rate limit|limit reached|resets (at|in)|quota/i`
  - `ProviderAuthError`: 401/403 veya `/not logged in|please run .*login|invalid api key|oauth token/i` → "`claude` ile giriş yap veya `CLAUDE_CODE_OAUTH_TOKEN` ayarla"
  - timeout / nonzero exit / stdout JSON değil / `is_error` → `ProviderError`
  - başarı: `structured_output` varsa o, yoksa `result` → `validate.parse_response`. `ProviderResult(items, input_tokens = input + cache_read + cache_creation, output_tokens, cost_usd = total_cost_usd)`.
- **MIRROR**: ERROR_HANDLING, SERVICE_PATTERN (runner enjekte)
- **GOTCHA**: Kitap metni yalnızca stdin'de; geçici dosya yok; `--bare` yok. Exit 0 + `is_error=true` olabilir — ikisine de bak. stderr log'lanır.
- **VALIDATE**: `test_claude_cli.py` (fake runner): argv beklenen liste; stdin'e mesaj gidiyor; gerçek örnekten alınmış başarı JSON'u parse; 429 → UsageLimitError; "usage limit reached … resets 5pm" → UsageLimitError; not logged in → ProviderAuthError; timeout → ProviderError; env'de ANTHROPIC_API_KEY yok. `@pytest.mark.live` tek test (varsayılan atlanır).

### Task 15: translate/fake.py + service.py
- **IMPLEMENT**:
  - `FakeTranslator`: her cümle → `"[TR] " + cümle`, token sayar, `$0`; `fail_mode` ile invalid/limit/auth simülasyonu.
  - `PageTranslationService.plan(book, pages, lang, force=False)`: sayfaları gerekirse extract et (DB'de yoksa/eskiyse), cache'te olmayan çevrilebilir block'ları bul, batch'le (≤5 sayfa, ≤6000 tahmini input token; tek sayfa limiti aşarsa block'lara bölünür, sayfa yine atomik kaydedilir), tahmin. **Provider'a dokunmaz.**
  - `execute(plan)`: başta cache'i tekrar kontrol et. Batch başına: `translate` → `InvalidTranslationError` → bir kez `--json-schema` ile retry → yine hata: batch sayfaları `failed`. `UsageLimitError`/`ProviderAuthError` → kalan batch'ler çalışmaz, `stopped_reason` set. Her çağrı `usage`'a; her sayfa tek transaction'da.
  - Bağlam: batch'ten önceki sayfanın son 2 çevrilebilir paragrafı.
- **GOTCHA**: Kural 1/2: `execute` sadece CLI onayından sonra; `plan` provider çağırmaz (testle kilitle).
- **VALIDATE**: `test_service.py` (Fake + in-memory DB): plan provider'ı çağırmıyor; ikinci execute 0 çağrı; geçersiz yanıt → 1 retry → failed; UsageLimitError → kalan batch'ler yok, bitenler kayıtlı; CODE/IMAGE/TABLE/FURNITURE provider'a gitmiyor.

### Task 16: render/html_builder.py + şablonlar
- **IMPLEMENT**: `build_page_html(book, page_no, blocks, translations, mode: "tr"|"review"|"debug", assets_dir) -> str` (Jinja2, `autoescape=True`). heading → `<h{level}>`, paragraph → `<p>`, ardışık list_item → `<ul>/<ol>`, code → `<pre><code>` (orijinal, whitespace aynen), image/table → `<figure><img src="assets/p041_b7.png">` (`get_pixmap(clip=bbox, dpi=150)`, varsa yeniden üretme), caption → `<figcaption>`, footnote → sayfa sonunda `<aside class="footnotes">`, furniture → yok. Her element `data-block="{page}-{ord}"`, cümleler `<span data-s="i">` (Faz 3 senkron scroll + Faz 6 cümle eşleme hazır). Font boyutu `calc(var(--scale) * {size}pt)` → orijinal punto/hiyerarşi; aile orijinalin serif/sans/mono sınıfına göre. Inline backtick → `<code>` (escape SONRASI, kendi kontrolümüzde). Çevirisi olmayan block → orijinal + `class="untranslated"`. `review`: iki sütunlu grid, her satır aynı block'un EN/TR'si, cümle hover → karşı cümle vurgu (küçük inline JS). `debug`: tip renkleri + order + bbox/font/punto tooltip. `lang="tr"`, UTF-8. `index.html`: sayfa listesi.
- **GOTCHA**: LLM çıktısını asla `|safe`/`Markup` ile basma; `<code>` dönüşümü escape edilmiş string üzerinde yapılır.
- **VALIDATE**: `test_html_builder.py`: `<script>` içeren çeviri escape; backtick → `<code>`; kod bloğu orijinal; heading seviyeleri; `data-block`; furniture yok.

### Task 17: cli.py
- **IMPLEMENT**:
  - `rosetta extract PDF --pages 41-44 [--debug]` → DB'ye yazar, özet tablo, `--debug` ise `pNNN.debug.html`. AI yok.
  - `rosetta estimate PDF --pages … [--lang] [--provider claude-cli|fake] [--model]` → plan + tahmin. AI yok.
  - `rosetta translate PDF --pages … [--lang tr] [--provider] [--model] [--profile file.json] [--yes] [--force] [--open]` → plan, tahmin, `typer.confirm(default=False)`, execute, rich progress, rapor (biten/hatalı + nedenler, gerçek token ve $ eşdeğeri), HTML'ler (`pNNN.tr.html`, `pNNN.review.html`, `index.html`). Cache tam karşılıyorsa onay sorulmaz ("0 çağrı").
  - `rosetta usage [--book PDF]`.
  - `--pages`: `41`, `41-44`, `41,43,50-52`; 1-based; aralık dışı → anlamlı hata.
  - Çıkış kodları: 0 başarı, 2 iptal, 3 kısmi hata, 4 kullanım limiti, 5 auth.
- **GOTCHA**: stdin TTY değilse ve `--yes` yoksa translate reddeder.
- **VALIDATE**: `test_cli.py` (`CliRunner`, `--provider fake`, tmp data dir): page parser; "n" → provider çağrılmıyor, exit 2; "y" → HTML'ler oluşuyor; ikinci çalıştırma "0 çağrı".

### Task 18: README + uçtan uca kalite turu
- **IMPLEMENT**: README: amaç, temel kurallar, kurulum (`uv`), komutlar, veri/config yolları, `claude` login / `CLAUDE_CODE_OAUTH_TOKEN`, ANTHROPIC_API_KEY'in neden çıkarıldığı, lisanslar (repo AGPL-3.0-or-later çünkü PyMuPDF AGPL-3.0; diğer bağımlılıklar MIT/BSD), Faz 3 Linux sistem bağımlılıkları (Arch: `webkit2gtk-4.1 base-devel curl wget file openssl appmenu-gtk-module libappindicator-gtk3 librsvg xdotool`; Debian/Ubuntu: `libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev`), Rust (`rustup`) gerekliliği.
  Kullanıcıyla: `rosetta extract --debug` ile 3–4 temsilî sayfa (kodlu, figürlü, tablolu, dipnotlu), sonra `translate` → `review.html` ile kalite değerlendirmesi.

---

## Testing Strategy

### Unit Tests
| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| fonts.is_monospace | `"ABCDEF+Consolas"`, flags=0 | True | subset prefix |
| fonts.is_monospace | `"Minion-Regular"`, flags=8 | True (flag) | |
| stats | 10pt gövde, 18/14 başlık | body=10, h1=18, h2=14 | |
| furniture | 5 sayfada tekrarlayan header | FURNITURE | tek/çift sayfa |
| figures | gri kutu + Courier | CODE (figür değil) | ✔ |
| layout | iki sütun + tam genişlik başlık | başlık, sol, sağ | ✔ |
| text_clean | `replica-\ntion` | `replication` | `client-\nSide` korunur |
| classify | `Figure 5-1. …` image yanında | CAPTION | |
| sentences | `` Call `a.b()`. Done. `` | 2 cümle | ✔ |
| validate | eksik id | InvalidTranslationError | ✔ |
| validate | cümle sayısı farklı | aligned=False | ✔ |
| claude_cli | `api_error_status=429` | UsageLimitError | ✔ |
| claude_cli | env'de ANTHROPIC_API_KEY | alt süreçte yok | ✔ |
| service | aynı sayfa 2 kez | 2. seferde 0 çağrı | Kural 3 |
| service | plan() | provider çağrılmaz | Kural 1 |
| html_builder | çeviride `<script>` | escape | ✔ |
| cli | onay "n" | provider çağrılmaz, exit 2 | Kural 2 |

### Edge Cases Checklist
- [ ] Metin katmanı olmayan sayfa → açık hata, AI çağrısı yok
- [ ] Tamamen kod/görsel sayfa → 0 çağrı, HTML yine üretilir
- [ ] Çok yoğun tek sayfa → batch token limiti aşılmıyor
- [ ] Bozuk JSON / eksik id → 1 retry (json-schema), sonra failed
- [ ] Kullanım limiti → durur, bitenler kayıtlı, exit 4
- [ ] `claude` PATH'te yok → anlaşılır hata
- [ ] Aralık dışı sayfa
- [ ] Aynı PDF farklı yolda → aynı kitap (hash)

---

## Validation Commands

### Static Analysis
```bash
cd engine && uv run ruff check . && uv run ruff format --check . && uv run mypy src
```
EXPECT: Zero errors

### Unit Tests
```bash
cd engine && uv run pytest -q --cov=rosetta_engine --cov-report=term-missing
```
EXPECT: Tümü geçer; ≥%80 kapsam

### Live smoke (isteğe bağlı, ~$0.001 eşdeğeri)
```bash
cd engine && uv run pytest -m live -q
```

### Uçtan uca (ücretsiz)
```bash
cd engine && uv run rosetta translate tests/fixtures/sample.pdf --pages 1-2 --provider fake --yes
```
EXPECT: `~/.local/share/rosetta/out/<hash>/p001.tr.html` ve `p001.review.html`

### Manual Validation
- [ ] `rosetta extract kitap.pdf --pages <4 sayfa> --debug` → tipler ve sıra doğru
- [ ] `rosetta estimate` → makul tahmin
- [ ] `rosetta translate` → onay soruldu, HTML üretildi, `usage` gerçek değerleri gösteriyor
- [ ] Aynı komut ikinci kez → "0 çağrı"
- [ ] `review.html` üzerinden kalite birlikte değerlendirildi

---

## Acceptance Criteria
- [ ] Tüm task'lar tamamlandı; ruff + mypy strict temiz; testler geçiyor
- [ ] Hiçbir yol AI'yı onaysız çağırmıyor (testle kilitli)
- [ ] Kod/görsel/tablo/furniture provider'a gitmiyor (testle kilitli)
- [ ] Aynı sayfa + dil + model ikinci kez çevrilmiyor (testle kilitli)
- [ ] HTML LLM tarafından üretilmiyor; LLM metni escape ediliyor
- [ ] 3–4 gerçek sayfada kullanıcıyla kalite değerlendirmesi

## Completion Checklist
- [ ] Patterns to Mirror uygulandı
- [ ] Hata hiyerarşisi kullanıldı, hata yutulmuyor
- [ ] Motor modülleri print etmiyor
- [ ] Sabitler config'te
- [ ] README güncel
- [ ] Faz 1 kapsamı aşılmadı

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Çok sütunlu sayfada yanlış okuma sırası | Orta | Yüksek | Koridor tabanlı sütun tespiti + `--debug` görsel kontrol |
| Tablolar (`find_tables` kaçırır/yanlış bulur) | Orta | Orta | Faz 1'de görsel; çizgisiz tablolar debug'da görülür → heuristik |
| Dipnotlar ana metne karışması | Orta | Orta | Punto + konum + superscript; ayrı `<aside>` |
| Figür içi metnin LLM'e sızması / figür sanılan kod kutusu | Orta | Orta | Mono oranı kuralı, not kutusu kuralı, debug |
| Sayfalar arası bölünen paragraf | Yüksek | Düşük-Orta | Önceki sayfa sonu bağlam; işaret; Faz 4'te birleşik çeviri |
| Kod bloğu mono olmayan fontla / mono font gövdede | Düşük | Orta | İsim + flag; profilde `extra_mono_fonts` override |
| Tire birleştirme hatası | Orta | Düşük | Muhafazakâr kural, testli |
| LLM cümle sayısını tutturamaz | Orta | Düşük | `sentence_aligned=false` fallback |
| Kullanım limiti mesaj formatı değişir | Orta | Orta | 429 + regex + is_error; bilinmeyen hata da durdurur |
| Token tahmini sapması | Orta | Düşük | Gerçek usage ile kalibrasyon |
| `claude` CLI flag'leri sürümle değişir | Orta | Orta | `claude --version` log; flag hatasında anlaşılır mesaj |
| PyMuPDF AGPL | — | Dağıtımda | README'de belirt |
| Taranmış PDF | Düşük | Yüksek | `has_text_layer`; OCR kapsam dışı |

## Notes
Klasör yapısı (Faz 1'de sadece `engine/`, README, .gitignore oluşturulur):
```
rosetta/
├── README.md
├── .gitignore
├── .claude/PRPs/plans/
├── engine/                         # Python: rosetta_engine
│   ├── pyproject.toml
│   ├── .python-version
│   ├── src/rosetta_engine/
│   │   ├── __init__.py  config.py  models.py  cli.py
│   │   ├── extract/   pdf_reader fonts stats furniture figures layout text_clean classify sentences extractor
│   │   ├── store/     db repo migrations/001_init.sql
│   │   ├── translate/ errors base prompt validate estimator claude_cli fake service
│   │   ├── render/    html_builder templates/{page,review,debug}.html.j2 style.css
│   │   ├── api/       (Faz 3: FastAPI sidecar)
│   │   ├── profile/   (Faz 2)
│   │   ├── jobs/      (Faz 4)
│   │   ├── export/    (Faz 5: Playwright PDF)
│   │   └── learn/     (Faz 6–7: sözlük, lemmatizer, FSRS, açıklama)
│   └── tests/  conftest.py fixtures/ test_*.py
├── app/                            # Faz 3: Tauri 2 + React + Vite + PDF.js
│   ├── src/
│   └── src-tauri/  (sidecar: binaries/rosetta-engine-x86_64-unknown-linux-gnu)
├── dictionaries/                   # Faz 6: sözlük üretim script'leri
└── packaging/                      # PyInstaller spec, AppImage/.deb
```
- Makinede `cargo` yok; Faz 3 öncesi `rustup` gerekli.
- Prompt değişince `PROMPT_VERSION` artar ama cache geçersiz olmaz (Kural 3); `--force` ile yenilenebilir.

---

## Kullanıcı Kararları (2026-10-16)
1. Test kitabı: `/home/furkanasikdev/SSD/Books/Designing Data-Intensive Applications 2nd.pdf`
2. Model: sadece `haiku`.
3. Cümle eşleme: JSON `s` dizisi Faz 1'den açık.
4. Profil değişikliği cache'i geçersiz kılmaz; yeniden çeviri yalnızca `--force`.
5. Tablolar Faz 1'de görsel; hücre çevirisi sonraya.
6. `ANTHROPIC_API_KEY` alt süreçten HER ZAMAN çıkarılır (ayar değil, sabit davranış) — sadece yerel `claude` girişi / `CLAUDE_CODE_OAUTH_TOKEN`.
7. Python 3.13 pin.
8. Açık kaynak → PyMuPDF AGPL-3.0 nedeniyle repo lisansı AGPL-3.0; `git init`.
9. Profil Faz 1'de opsiyonel (`--profile`); Faz 2'de otomatik.

---

## Kitap Analizi Bulguları (DDIA 2nd, PyMuPDF 1.28.2 ile doğrulandı) — EXTRACTOR BUNLARA GÖRE YAZILACAK

Kitap: `/home/furkanasikdev/SSD/Books/Designing Data-Intensive Applications 2nd.pdf` — 673 sayfa, sayfa boyutu 504×661.5 pt, **tek sütun** (içerik x≈72–432), TOC 245 girdi (`doc.get_toc()`, 1-based sayfa), Bölüm 1 = PDF sayfa 25.

| Öğe | Gözlem | Kural |
|---|---|---|
| Gövde | `MinionPro-Regular` 10.5pt, italik `MinionPro-It` (flags 6) | body_size=10.5 istatistikten çıkmalı |
| Kod bloğu | `UbuntuMono-Regular/Bold/Italic` 8.5pt, flags 12/28/14 (bit 8 = mono doğru set) | ≥%70 mono → CODE, satır girintileri (baştaki boşluk span'ları) korunur |
| Inline kod | Paragraf içinde `UbuntuMono-Regular` 10.0pt | backtick ile sar |
| Başlıklar | `MyriadPro-SemiboldCond` (flags 20=bold+serif bit), bölüm sayfasında "CHAPTER 1" 16.8pt + başlık 25.2pt AYNI block'ta; alt başlık 15.8pt, diğerleri ~12pt | **Seviye TOC'tan**: block metni normalize edilip (küçük harf, tipografik tırnak/tire sadeleştirme) o sayfadaki TOC girdisiyle eşleşirse `heading_level = toc_level`; "CHAPTER N" + başlık block'u h1. Eşleşme yoksa punto sıralaması fallback |
| Epigraf | Bölüm başında `MinionPro-It` 9pt + "—Yazar" satırı | PARAGRAPH, `aside=True` |
| Footer | Alt bant y≈610, `MyriadPro-SemiboldCond` 9pt: `"70 | Chapter 3: Data Models…"` veya `"Case Study… | 35"`; bölüm sayfasında sadece `"1"`; üstünde y≈607 yatay çizgi | FURNITURE (alt %8 bant + tekrar/rakam kuralı). Üst header YOK. y≈607 ayraç çizgisi figür bölgesi sayılmamalı |
| Figür | Raster IMG block + çevresinde 4 çizgilik çerçeve (drawings), altında `Figure 3-1. …` (MinionPro-It 10.5) | IMAGE bölgesi = img ∪ çerçeve; caption regex |
| Örnek başlığı | `Example 3-1. …` (MinionPro-It) kod bloğunun ÜSTÜNDE | CAPTION (kod bloğuna komşu, üstte de olabilir) |
| **Tablo** | `Table 1-1. …` caption ÜSTTE (MinionPro-It 10pt); hücreler `MyriadPro-Cond` 9pt, başlık satırı siyah dolgu rect; satırlar arası ince yatay çizgiler. **`find_tables()` sadece başlık satırını buluyor** (`lines`), `text` stratejisi tüm sayfayı, `lines_strict` hiçbir şey | TABLE bölgesi = "Table" caption'ının altından başlayıp, gövde fontuna (Minion 10.5) dönülene kadarki ardışık sans/küçük block'lar ∪ o aralıktaki çizimler (son yatay çizgiye kadar). `find_tables` bbox'ı sadece ipucu. Faz 1'de görsel olarak kırpılır |
| Not/İpucu kutusu | Solda küçük ikon IMG (~38×50pt), metin x≈137'den başlar, `MinionPro` 9.6pt | Alanı < sayfanın %2'si olan ve yanında metin olan görseller DEKOR → atla. Metin PARAGRAPH `aside=True` |
| Numaralı açıklama listeleri | Sayfa 115: kod sonrası x≈90'dan başlayan maddeler; numara glifi büyük ihtimalle vektör çizim (19 drawing) | LIST_ITEM: girintili (x > gövde sol kenarı + 10pt) ve öncesinde vektör işaret olan block'lar; numara metni yoksa `list_marker=""`, sıralı `<ol>` |
| Atıflar | `[6]` gibi köşeli parantez referansları metin içinde | Aynen kalır (prompt: köşeli atıfları koru) |
| Dipnot | Örneklenen sayfalarda superscript yok (flags&1 = 0); referanslar bölüm sonunda | FOOTNOTE kuralı kalsın ama bu kitapta nadiren tetiklenmeli |
| Uyarı | PyMuPDF "Consider using the pymupdf_layout package" mesajı basıyor | Faz 1'de kullanma; logging ile sustur/yok say |

**Kalite turu için önerilen sayfalar (1-based)**: 25 (bölüm başı + epigraf), 30 (tablo + not kutusu), 59 (kod + inline kod + alt başlık), 94 (figür + Example + kod), 115 (kod + numaralı liste).

---

## Mevcut Durum (bu oturumda yapıldı — /prp-implement buradan devam eder)
- `rosetta/` altında `git init` yapıldı (commit yok).
- `engine/` uv projesi oluşturuldu: `.python-version` = 3.13, bağımlılıklar kurulu (`pymupdf 1.28.2, pydantic, platformdirs, typer, rich, jinja2`; dev: `pytest, pytest-cov, mypy, ruff`). **pysbd kaldırıldı.**
- `engine/pyproject.toml`: `license = "AGPL-3.0-or-later"`, `[project.scripts] rosetta = "rosetta_engine.cli:app"`, `[tool.uv.build-backend] module-name = "rosetta_engine"`, ruff/mypy(strict)/pytest(`-m 'not live'`) ayarları HAZIR.
- `engine/src/rosetta_engine/__init__.py` hâlâ uv şablonu (`def main(): print(...)`) → Task 1'de `"""Rosetta translation engine."""\n__version__ = "0.1.0"` ile değiştir.
- Task 1'in kalanı: kök `README.md`, `.gitignore`, `LICENSE` (AGPL-3.0 metni), `engine/tests/` klasörü.
- Ek dosya: `src/rosetta_engine/errors.py` (hata hiyerarşisi `translate/errors.py` yerine paket kökünde — extractor da `ExtractionError` kullanır). Plan tablosundaki `translate/errors.py` yerine bunu kullan.
