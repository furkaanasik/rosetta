# Rosetta

Kişisel kullanım için bir masaüstü PDF okuyucu. İngilizce bir kitabı açarsınız, sayfaları
**yalnızca siz istediğinizde** Türkçeye (ya da seçtiğiniz dile) çevirir ve orijinal hiyerarşiyi
(başlık, paragraf, liste, kod, görsel, tablo) koruyan reflow HTML olarak gösterir. Dört görünüm
modu vardır: **Orijinal**, **Split** (solda PDF, sağda çeviri, paragraf bazlı senkron kaydırma),
**Sadece Çeviri** ve **Öğrenme** (orijinal metin, yalnızca bilmediğiniz kelimelerin üstünde Türkçe
karşılık). Çevrilen kitabı PDF olarak dışa aktarabilir; kelime defteri, offline sözlük ve aralıklı
tekrar (FSRS) kartlarıyla İngilizce çalışabilirsiniz. Çeviri, makinenizdeki `claude` CLI'ı üzerinden
**aboneliğinizle** yapılır; API anahtarı kullanılmaz.

Linux öncelikli (Tauri 2 + React + PDF.js arayüz, Python motoru sidecar olarak). Lisans: AGPL-3.0-or-later.

## Temel kurallar

1. **Otomatik AI çağrısı yok.** Her AI işlemi (çeviri, kitap analizi, "Bunu açıkla") yalnızca bir
   butona/komuta basınca çalışır. Prefetch, arka plan çevirisi, açılışta analiz yok.
2. **Önce tahmin, sonra onay.** Her AI işleminden önce tahmini çağrı/token/$ gösterilir; onaylamadan
   hiçbir şey çalışmaz (CLI'da onay sorusu, API'de tek kullanımlık onay belirteci).
3. **Her çeviri cache'lenir.** Aynı sayfa aynı dil + model için ikinci kez çevrilmez (yeniden çeviri
   yalnızca `--force` ile).
4. **Font küçültme yok.** Çeviri orijinal punto ve hiyerarşiyle reflow HTML olarak üretilir.
5. **HTML'i LLM üretmez.** Modele yalnızca metin gider, yalnızca metin döner; HTML'i Rosetta üretir ve
   modelin çıktısı her yerde escape edilir.
6. **Kod, görsel, diyagram, tablo, sayfa başlığı/altlığı modele gönderilmez.** Kod blokları monospace
   font tespitiyle ayrılır; görseller ve tablolar kırpılıp görsel olarak gösterilir.

## Kurulum

### Kullanıcı (AppImage / .deb)

Paketler `packaging/build-app.sh` ile üretilir (bkz. [docs/paketleme.md](docs/paketleme.md)):

| Paket | Yol |
|---|---|
| AppImage (~163 MB) | `app/src-tauri/target/release/bundle/appimage/Rosetta_0.1.0_amd64.AppImage` |
| .deb (~68 MB) | `app/src-tauri/target/release/bundle/deb/Rosetta_0.1.0_amd64.deb` |

Çalışma zamanı sistem bağımlılıkları (WebKitGTK):

- Arch: `webkit2gtk-4.1 gtk3`
- Debian/Ubuntu: `libwebkit2gtk-4.1-0 libgtk-3-0`

Ayrıca çeviri için giriş yapılmış [Claude Code](https://docs.claude.com/en/docs/claude-code) CLI'ı
(`claude`) gerekir. PDF dışa aktarım için sistemde Chromium (`chromium`, `chromium-browser` ya da
`google-chrome`) bulunmalıdır. AppImage FUSE olmadan `APPIMAGE_EXTRACT_AND_RUN=1` ile çalıştırılabilir.

### Geliştirici

| Araç | Neden |
|---|---|
| [uv](https://docs.astral.sh/uv/) (Python 3.13'ü kendisi kurar) | motor (`engine/`) |
| Node.js + npm | arayüz (`app/`) |
| Rust ([`rustup`](https://rustup.rs/)) | Tauri |
| Chromium | PDF export, E2E testleri |

Tauri derleme bağımlılıkları:

- Arch: `webkit2gtk-4.1 base-devel curl wget file openssl librsvg xdotool`
- Debian/Ubuntu: `libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev librsvg2-dev`

```bash
cd engine && uv sync && uv run rosetta --help     # motor + CLI
cd app && npm ci && scripts/prepare-dev-sidecar.sh && npx tauri dev   # uygulama (geliştirme)
packaging/build-app.sh                            # sidecar (PyInstaller) + AppImage + .deb
```

## Hızlı başlangıç

### Uygulama

1. **PDF Aç** ile kitabı açın.
2. Üst çubuktan görünüm modunu seçin: Orijinal / Split / Sadece Çeviri / Öğrenme.
3. Kontrol paneli (hepsi elle):
   - **Kitabı Analiz Et** — içindekiler + birkaç örnek sayfadan kitap profili (sözlük, çevrilmeyecek
     terimler, ton) çıkarır; profil düzenleme ekranından değiştirilebilir.
   - **Bu Sayfayı Çevir**, **Aralık Çevir** (ör. `120-140`), **Tüm Kitabı Çevir** — tahmin penceresi
     açılır, **Onayla** demeden hiçbir şey çalışmaz. Aralık ve tüm kitap bir **iş** olarak çalışır:
     ilerleme, duraklat/devam, bütçe sınırı, hatalı sayfalar ve "sadece hatalıları tekrar dene".
   - **PDF Dışa Aktar** — sadece Türkçe ya da iki dilli (EN | TR), Türkçe yer imleri ve İçindekiler.
4. Öğrenme: bir kelimeye tıklayın → offline sözlükte anlam; "Kaydet (bilmiyorum)" ile kelime defterine
   ekleyin, Öğrenme modunda kitabın tamamında üstünde Türkçe karşılık görünür. Flashcard'lar
   (Tekrar/Zor/İyi/Kolay), teknik terim listesi ve istatistik paneli. Bir cümle için **Bunu açıkla**
   (onaylı, cache'li).
5. Durum çubuğunda toplam harcama (liste fiyatı eşdeğeri) görünür.

### CLI

`--pages`: `41`, `41-44`, `41,43,50-52` (1 tabanlı). AI çağıran her komut önce tahmini gösterir ve
onay sorar; `--yes` onayı atlar, terminal yoksa `--yes` olmadan reddeder.

```bash
cd engine
B="kitap.pdf"

# Ayıklama ve tahmin (AI yok, bedava)
uv run rosetta extract "$B" --pages 25,30,59 --debug     # block tipleri renkli debug HTML
uv run rosetta estimate "$B" --pages 41-44 [--force] [--profile profil.json] [--think off]

# Çeviri: tahmin → onay → claude -p → cache → HTML (pNNN.tr.html, pNNN.review.html, index.html)
uv run rosetta translate "$B" --pages 41-44 [--lang tr] [--model sonnet|haiku] [--think off|low|medium|high]
                         [--profile profil.json] [--force] [--max-budget-usd 0.25] [--open] [--yes]

# Kitap profili (Faz 2)
uv run rosetta profile analyze "$B"                  # tek AI çağrısı, onaylı
uv run rosetta profile show|export|import "$B" ...
uv run rosetta profile set "$B" --term "replication=replikasyon" --dnt Kafka [--remove-term X] [--tur …] [--ton …]

# Toplu iş (Faz 4)
uv run rosetta job start "$B" (--pages 120-140 | --all) [--budget 2.0]
uv run rosetta job list | status ID | pause ID | resume ID | retry-failed ID | cancel ID

# PDF dışa aktarım (Faz 5, AI yok)
uv run rosetta export "$B" [--pages …] [--mode tr|bilingual] [--paper a4|letter] [-o çıktı.pdf] [--no-toc-page]

# Öğrenme (Faz 6, AI yok)
uv run rosetta dict build                            # offline sözlük (~520 MB akış, ~3 dk), bir kez
uv run rosetta lookup replicated                     # → replicate
uv run rosetta vocab add WORD --book "$B" --page 59 [--sentence …] [--unknown|--known]
uv run rosetta vocab list | mark WORD --unknown|--known
uv run rosetta review                                # sırası gelen kartlar
uv run rosetta terms "$B" [--add-all]                # profil sözlüğünden teknik terimler
uv run rosetta stats
uv run rosetta learn-html "$B" --pages 25            # pNNN.learn.html

# Bunu açıkla (Faz 7, onaylı, cache'li)
uv run rosetta explain "That's all you can hope for." [--book "$B" --page 25] [--model haiku]

# Kullanım ve API sunucusu
uv run rosetta usage [--book "$B"]
uv run rosetta serve --port 0                        # stdout'a tek satır {"port", "token"} JSON
```

## Maliyet ve güvenlik

- **Yalnızca `claude` CLI, yalnızca abonelik.** Rosetta `claude -p` çağırır; kimlik doğrulama için
  `claude` ile bir kez giriş yapın ya da `CLAUDE_CODE_OAUTH_TOKEN` ayarlayın. Doğrudan Anthropic API
  isteği hiçbir zaman atılmaz.
- **Alt sürecin ortamı temizlenir:** tüm `ANTHROPIC_*` değişkenleri (API anahtarı, base URL vb.),
  `CLAUDE_EFFORT`, `CLAUDECODE`, `AI_AGENT`, `CLAUDE_CODE_*` (yalnızca `CLAUDE_CODE_OAUTH_TOKEN`
  korunur) ve devralınan `MAX_THINKING_TOKENS` çıkarılır. Böylece Rosetta nereden çalıştırılırsa
  çalıştırılsın aynı davranır ve faturalama API'ye kaymaz.
- **Önce tahmin + onay her yerde:** CLI onay sorusu; API'de her AI uç noktası, aynı parametrelerle
  alınmış tek kullanımlık bir `confirm_token` ister (600 sn geçerli, bir kez kullanılır).
- **Çağrı başı bütçe sınırı:** varsayılan `--max-budget-usd 0.25`; aşılırsa iş durur (çıkış kodu 6).
  Toplu işlerde ayrıca iş bütçesi (`--budget`).
- **$ rakamları liste fiyatı eşdeğeridir.** Max/Pro aboneliğinde fatura değildir; asıl sınır aboneliğin
  kullanım limitidir. Limit gelince iş duraklar (çıkış kodu 4) ve kaldığı yerden devam eder.
- **Varsayılan model Sonnet.** DDIA kitabında yapılan kör karşılaştırmada (5 sayfa, ~50 cümle) Haiku
  9 anlam / 15 dil bilgisi / ~21 çeviri kokan ifade hatası yaptı, Sonnet 4 / 0 / 2 — üstelik daha ucuz
  ($0.051, tek çağrı) çünkü neredeyse hiç gizli düşünme token'ı harcamadı. `--model haiku` daha ucuz ve
  hızlı taslak seçeneği olarak duruyor. "Bunu açıkla" varsayılan olarak Haiku kullanır.
- **Düşünme (`--think off|low|medium|high`):** varsayılan medium. Haiku'da düşünme çağrı başına 9k–18k
  gizli çıktı token'ı harcayabilir; tahmin bunu model bazında ekler (`thinking_output_tokens_per_call`).
  `--think off` en hızlı ve en ucuz taslaktır.
- **Sağlam çeviri kaydı:** her batch'in ödenmiş sonucu hemen kaydedilir; `--force` eski çeviriyi ancak
  yenisi gelince değiştirir. Model çıktısı doğrulanır (JSON, id'ler, cümle sayısı); geçersizse bir kez
  sıkı modda tekrar denenir, yine olmazsa sayfa "hatalı" işaretlenir.

## Sağlayıcılar

| Sağlayıcı | Ne | Profil/bağlam | Not |
|---|---|---|---|
| `claude-cli` (varsayılan) | `claude -p`, abonelik girişi | var | model `sonnet` / `haiku` |
| `deepl` | DeepL API v2 | **yok** (arayüz bunu belirtir) | anahtar `DEEPL_AUTH_KEY` ortam değişkeninde; `:fx` → ücretsiz uç nokta |
| `ollama` | yerel model, bedava | var | `ollama_url`, `ollama_model` |
| `fake` | test için, `[TR] …` | — | bedava, ağ yok |

Ayrıntı: [docs/faz8-saglayicilar.md](docs/faz8-saglayicilar.md).

## Veri ve ayar yolları

| | Linux varsayılanı | Override |
|---|---|---|
| Veri (DB, HTML/PDF çıktıları, sözlük) | `~/.local/share/rosetta/` (`rosetta.db`, `out/<hash>/`, `dictionary.db`) | `ROSETTA_DATA_DIR` |
| Ayarlar | `~/.config/rosetta/config.toml` | `ROSETTA_CONFIG_DIR` |

`config.toml` (gösterilen değerler varsayılanlardır; dosya olmadan da çalışır). Çoğu ayar uygulamadaki
**Ayarlar** ekranından (dişli simgesi ya da `Ctrl+,`) da değiştirilebilir; ekran dosyadaki yorumları ve
`[pricing.*]` tablolarını korur. Ayarlar → **Motor durumu** bir şey çalışmadığında nedenini gösterir
(claude bulunamadı, sözlük kurulmamış, Chromium yok…); bu kontroller AI'a istek göndermez.

```toml
default_lang = "tr"
provider = "claude-cli"          # claude-cli | deepl | ollama | fake
model = "sonnet"                 # çeviri modeli
explain_model = "haiku"          # "Bunu açıkla"
batch_max_pages = 5              # bir çağrıda en fazla sayfa
batch_max_input_tokens = 6000    # bir çağrıda en fazla tahmini input token
claude_timeout_s = 240
# claude_path = "/home/ben/.local/bin/claude"  # boş: PATH + bilinen kurulum yerleri (otomatik)
claude_effort = "medium"         # claude --effort
# claude_max_thinking_tokens = 0 # 0 = düşünme kapalı (MAX_THINKING_TOKENS=0)
claude_max_budget_usd = 0.25     # çağrı başı sınır (claude --max-budget-usd)
prefetch = false                 # her zaman kapalı (Kural 1)
deepl_auth_key_env = "DEEPL_AUTH_KEY"
deepl_timeout_s = 60
ollama_url = "http://localhost:11434"
ollama_model = "qwen2.5:7b"
ollama_timeout_s = 600

[pricing.sonnet]   # $ / milyon token (yalnızca tahmin için)
in = 2.0
out = 10.0
[pricing.haiku]
in = 1.0
out = 5.0
[pricing.deepl]    # DeepL karakter başına ücretlendirir (~$25/1M karakter Pro ≈ $90/1M token); ücretsiz anahtar: in = 0
in = 90.0
out = 0.0
[pricing.ollama]
in = 0.0
out = 0.0

[thinking_output_tokens_per_call.haiku]   # tahmine eklenen gizli düşünme token'ı (çağrı başı)
low = 13000
medium = 18000
high = 24000
[thinking_output_tokens_per_call.sonnet]
low = 500
medium = 1500
high = 6000
```

Fiyatı tanımlı olmayan bir model seçilirse tahmin "$0" yerine "fiyat bilinmiyor" der. Bozuk bir
`config.toml` dosya yoluyla birlikte anlaşılır bir hata verir.

## Çıkış kodları

| Kod | Anlam |
|---|---|
| 0 | başarı |
| 1 | genel hata (ör. `claude` bulunamadı, geçersiz ayar) |
| 2 | iptal / onay verilmedi / terminal yok ve `--yes` yok |
| 3 | kısmi hata (bazı sayfalar başarısız) |
| 4 | kullanım limiti (iş duraklatıldı) |
| 5 | kimlik doğrulama |
| 6 | bütçe sınırı aşıldı |
| 7 | sağlayıcı kullanılamıyor (`claude` yok ya da üst üste 3 hata) |

## Proje yapısı

```
rosetta/
├── engine/                 Python motoru (rosetta_engine), uv projesi
│   ├── src/rosetta_engine/
│   │   ├── extract/        PyMuPDF → tipli block'lar, okuma sırası, kod/figür/tablo, ❶ işaretleri
│   │   ├── store/          SQLite şema (migrations/), repo'lar
│   │   ├── translate/      prompt, doğrulama, tahmin, claude_cli, deepl, ollama, fake, service
│   │   ├── render/         HTML üretimi (tr / review / learn / debug)
│   │   ├── profile/        kitap profili (Faz 2)
│   │   ├── jobs/           toplu iş (Faz 4)
│   │   ├── export/         PDF dışa aktarım (Faz 5)
│   │   ├── learn/          sözlük, kelime defteri, FSRS (Faz 6)
│   │   ├── explain/        "Bunu açıkla" (Faz 7)
│   │   ├── api/            FastAPI sidecar (Faz 3)
│   │   ├── commands/       CLI komut eklentileri
│   │   └── cli.py          Typer CLI
│   ├── scripts/            build_dictionary.py
│   └── tests/
├── app/                    Tauri 2 + React + Vite + PDF.js arayüz (API_CONTRACT.md, e2e/)
├── packaging/              PyInstaller spec, sidecar ve uygulama derleme betikleri
├── profiles/ddia.json      örnek kitap profili
└── docs/                   faz belgeleri
```

## Geliştirme

```bash
cd engine
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -q --cov=rosetta_engine

cd app
npm run lint && npm run typecheck && npm test
npm run e2e            # Playwright: gerçek motor (sahte AI) + Vite, sistem Chromium
```

- Testler gerçek `claude`'u hiç çağırmaz; sahte sağlayıcılar ve sahte runner'lar kullanılır.
- `uv run pytest -m live -q` gerçek `claude` çağrısı yapar (token harcar) — yalnızca açık onayla
  çalıştırın.
- Geliştirme için gizli `rosetta serve --dev-fake-ai` anahtarı AI'ı sahte yanıtlarla değiştirir;
  ortam değişkeniyle açılamaz, paketli uygulama hiçbir zaman kullanmaz.

## Belgeler

| Belge | Konu |
|---|---|
| [docs/faz2-profil.md](docs/faz2-profil.md) | Kitap profili, `complete()` sözleşmesi |
| [docs/faz3-api.md](docs/faz3-api.md) | FastAPI sidecar, uç noktalar, onay belirteçleri |
| [app/API_CONTRACT.md](app/API_CONTRACT.md) | Uygulama ↔ motor API sözleşmesi |
| [app/README.md](app/README.md) | Arayüz geliştirme |
| [docs/faz4-toplu-is.md](docs/faz4-toplu-is.md) | Toplu iş, duraklat/devam, bütçe |
| [docs/faz5-pdf-export.md](docs/faz5-pdf-export.md) | PDF dışa aktarım, yer imleri |
| [docs/faz6-ogrenme.md](docs/faz6-ogrenme.md) | Sözlük, kelime defteri, FSRS, öğrenme modu |
| [docs/faz7-acikla.md](docs/faz7-acikla.md) | "Bunu açıkla" |
| [docs/faz8-saglayicilar.md](docs/faz8-saglayicilar.md) | DeepL ve Ollama |
| [docs/kalite.md](docs/kalite.md) | Sayfa sonu paragraf devamı, terim tutarlılığı denetimi |
| [docs/paketleme.md](docs/paketleme.md) | PyInstaller, AppImage, .deb |

## Lisanslar

- **Rosetta:** [AGPL-3.0-or-later](LICENSE). Motor, AGPL-3.0 lisanslı
  [PyMuPDF](https://pymupdf.readthedocs.io/) kullandığı için depo da AGPL uyumludur.
- **Sözlük verisi:** İngilizce Wiktionary ([kaikki.org](https://kaikki.org/) çıkarımı),
  CC BY-SA 4.0 + GFDL; atıf gerekir. Veri depoya **eklenmez**; `rosetta dict build` ile yerelde
  kurulur (`dictionary.db`, ~157 MB). Kaynak ve lisans `rosetta dict info` ile görülür.
- **Python bağımlılıkları:** pydantic, typer, rich, jinja2, platformdirs, httpx, fastapi, uvicorn,
  simplemma, fsrs — MIT/BSD/Apache-2.0.
- **Arayüz bağımlılıkları:** React (MIT), pdf.js / `pdfjs-dist` (Apache-2.0), Tauri ve eklentileri
  (MIT/Apache-2.0).
