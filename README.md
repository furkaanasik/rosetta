# Rosetta

Kişisel PDF çeviri okuyucusu: İngilizce kitap sayfalarını **yalnızca istendiğinde** Türkçeye
çevirir, orijinal hiyerarşiyi (başlık, paragraf, liste, kod, görsel, tablo) koruyan reflow HTML
üretir. Çeviri, yerel `claude` CLI'ı üzerinden aboneliğinizle yapılır (API anahtarı kullanılmaz).

> Durum: **Faz 1 — motor + CLI**. Masaüstü arayüz (Tauri) Faz 3'te gelecek.

## Temel kurallar

1. Hiçbir AI çağrısı kullanıcı onayı olmadan yapılmaz (`translate` her zaman tahmini gösterip sorar; `--yes` hariç).
2. Kod blokları, görseller, tablolar, header/footer modele **gönderilmez**.
3. Aynı sayfa + dil + model ikinci kez çevrilmez (SQLite cache). Yeniden çeviri yalnızca `--force` ile.
4. Modelin çıktısı güvenilmez girdi sayılır: HTML'i Rosetta üretir, tüm metin escape edilir.

## Kurulum

Gereksinimler: [uv](https://docs.astral.sh/uv/), Python 3.13 (uv kurar), giriş yapılmış
[Claude Code](https://docs.claude.com/en/docs/claude-code) CLI (`claude`).

```bash
cd engine
uv sync
uv run rosetta --help
```

## Komutlar

```bash
# Extract (AI yok, bedava) — --debug: block tipleri renkli, bbox'lı HTML
uv run rosetta extract kitap.pdf --pages 25,30,59 --debug

# Maliyet tahmini (AI yok)
uv run rosetta estimate kitap.pdf --pages 41-44 [--force] [--profile profil.json]   # --force: cache'tekileri de say (silmez)

# Çeviri: tahmin → onay → claude -p (varsayılan sonnet) → cache → HTML
uv run rosetta translate kitap.pdf --pages 41-44 --lang tr [--profile profil.json] [--yes] [--force] \
    [--model sonnet|haiku] [--max-budget-usd 0.02] [--think off|low|medium|high]
# Örnek profil (sözlük + çevrilmeyecek terimler): profiles/ddia.json

# Ücretsiz uçtan uca deneme (sahte çevirmen)
uv run rosetta translate kitap.pdf --pages 41 --provider fake --yes

# Kullanım (gerçek token, "liste fiyatı eşdeğeri" $)
uv run rosetta usage [--book kitap.pdf]
```

`--pages`: `41`, `41-44`, `41,43,50-52` (1 tabanlı).
`--max-budget-usd`: `claude` çağrısı başına üst sınır (liste fiyatı eşdeğeri $, varsayılan 0.25); aşılırsa iş durur,
harcanan token `usage`'a yazılır. Sadece `claude-cli` sağlayıcısında geçerli.

Çıkış kodları: 0 başarı, 2 iptal, 3 kısmi hata, 4 kullanım limiti, 5 kimlik doğrulama,
6 bütçe sınırı, 7 sağlayıcı kullanılamıyor (`claude` yok ya da üst üste 3 hata).

Çıktılar `pNNN.tr.html` (çeviri), `pNNN.review.html` (EN | TR yan yana, block hizalı) ve
`index.html` olarak üretilir.

## Veri ve ayar yolları

| | Linux varsayılanı | Override |
|---|---|---|
| Veri (DB, HTML çıktıları) | `~/.local/share/rosetta/` | `ROSETTA_DATA_DIR` |
| Ayarlar | `~/.config/rosetta/config.toml` | `ROSETTA_CONFIG_DIR` |

`config.toml` örneği:

```toml
default_lang = "tr"
model = "sonnet"                   # `claude --model`; "haiku" = daha ucuz/hızlı taslak
batch_max_pages = 5
batch_max_input_tokens = 6000
claude_timeout_s = 240
claude_effort = "medium"           # `claude --effort` (varsayılan: medium)
# claude_max_thinking_tokens = 0   # alt sürece MAX_THINKING_TOKENS; 0 = düşünme kapalı (varsayılan: ayarlanmaz)
claude_max_budget_usd = 0.25       # çağrı başına güvenlik sınırı, `claude --max-budget-usd`

[pricing.sonnet]   # $ / milyon token (yalnızca tahmin için)
in = 2.0
out = 10.0

[pricing.haiku]
in = 1.0
out = 5.0
```

### Model: varsayılan Sonnet

Liste fiyatları (claude-api model tablosu, 2026-09-25): Claude Sonnet 5.5 $2 / $10,
Claude Haiku 4.5 $1 / $5 (milyon token başına, girdi / çıktı).

Fiyatı `config.toml`'da tanımlı olmayan bir model seçilirse (`--model opus` gibi), tahmin satırı
`$0.000` yerine "fiyat bilinmiyor — config.toml [pricing.<model>] ekleyin" gösterir; onay yine
sorulur. Bozuk bir `config.toml` dosya yolu ve hatayla birlikte anlaşılır bir mesaj verir (kod 1).

Sayfa 30 (10 cümle) kör karşılaştırması, aynı prompt ve sözlükle:

| | Anlam | Dil bilgisi | Kelimesi kelimesine | Karar | Maliyet |
|---|---|---|---|---|---|
| Haiku (medium) | 2 | 5 | 6 | yeniden çevrilmeli | ≈ $0.025/sayfa |
| Haiku + redaktör turu | 2 | 5 | 6 | yeniden çevrilmeli | +$0.047 |
| **Sonnet (medium)** | **0** | **0** | **0** | olduğu gibi kullanılabilir | **$0.016, ~10 sn** |

Sonnet medium'da neredeyse hiç gizli düşünme token'ı üretmedi; bu yüzden hem daha iyi hem daha
ucuz çıktı. `--model haiku` daha ucuz/hızlı taslak seçeneği olarak kalır. Cache anahtarı modeli
içerir: Haiku çevirileri `haiku` altında geçerli kalır, Sonnet ayrı başlar.

### Düşünme: varsayılan medium

Model cevaptan önce "düşünebilir"; bu gizli token'lar çıktı olarak sayılır. Aşağıdaki ölçümler
Haiku içindir. Varsayılan
`claude_effort = "medium"` ile düşünme açıktır, çünkü anlam hatalarını azaltıyor. Sayfa 25'te
(14 cümle) iki ölçüm yapıldı: düşünme kapalıyken epigraftaki anlam her iki seferde de tersine döndü,
medium'da hiç dönmedi. Diğer hatalar iki modda eşit çıktı.

Düşünme **çağrı başınadır** ve bir çağrı en fazla 5 sayfa taşır. Bu yüzden maliyet sayfa sayısıyla
doğrusal artmaz: 5 sayfalık medium çalıştırma ≈ $0.10, 4 sayfalık ≈ $0.10 tuttu (≈ $0.02/sayfa);
kitabın tamamı ≈ 650/5 çağrı × ≈ $0.10 ≈ $13 liste fiyatı eşdeğeri eder. Max aboneliğinde bu tutarlar faturalanmaz; asıl sınır
kullanım limitleridir.

Düşünme miktarı değişkendir: ölçümlerde çağrı başına gizli çıktı ~9 000 ile ~18 000 token
arasında oynadı (tek sayfa: 9 391 / 13 978 / 15 952 toplam çıktı; 4 sayfalık çağrı: 20 093).
Tahmine model başına gözlenen üst aralık eklenir (`thinking_output_tokens_per_call`:
haiku low 13 000 / medium 18 000 / high 24 000; sonnet low 500 / medium 1 500 / high 6 000,
sonnet high ölçülmedi). Bilinmeyen modelde en yüksek bilinen değer kullanılır; gerçek değer
±%40 sapabilir. Düşünmeli çağrılar tahmin
kalibrasyonuna girmez.
Her çağrı `claude_max_budget_usd = 0.25` ile sınırlıdır; aşılırsa iş durur (çıkış kodu 6).

### `--think`: çalıştırma bazında değiştirmek

`translate`/`estimate` için `--think off|low|medium|high` (yalnızca `claude-cli`) ayarı ezer.
`off` düşünmeyi kapatır (`--effort low` + `MAX_THINKING_TOKENS=0`): hızlı taslak, sayfa başına
~9 sn, ≈ $0.006. Diğer seviyeler `--effort <seviye>` verir ve `MAX_THINKING_TOKENS` ayarlamaz.

| | Tek sayfa (ölçüm) | Not |
|---|---|---|
| Haiku `off` | ≈ $0.006, ~9 sn | Hızlı taslak; deyimlerde anlam hatası riski |
| Haiku `medium` | ≈ $0.05–0.07, ~64 sn | Çok sayfalı çağrılarda sayfa başı ≈ $0.02 |
| Sonnet `medium` (varsayılan) | ≈ $0.016, ~10 sn | Sayfa 30 kör karşılaştırmasında 0 hata |

```bash
uv run rosetta translate kitap.pdf --pages 41-44 --think off   # hızlı taslak
```

## Claude girişi ve `ANTHROPIC_API_KEY`

Rosetta `claude -p` çağırır; kimlik doğrulama için `claude` ile bir kez giriş yapın ya da
`CLAUDE_CODE_OAUTH_TOKEN` ortam değişkenini ayarlayın.

`ANTHROPIC_API_KEY` ve diğer tüm `ANTHROPIC_*` değişkenleri (`ANTHROPIC_AUTH_TOKEN`,
`ANTHROPIC_BASE_URL`, …) alt sürecin ortamından **her zaman çıkarılır**: tanımlı kalırlarsa CLI
isteği API faturasına ya da başka bir uca yönlendirebilir. Rosetta yalnızca abonelik girişini
kullanır. Aynı şekilde üst bir Claude Code oturumundan miras kalan `CLAUDE_EFFORT`, `CLAUDECODE`,
`AI_AGENT`, `MAX_THINKING_TOKENS` ve `CLAUDE_CODE_*` değişkenleri (`CLAUDE_CODE_OAUTH_TOKEN`
hariç) de çıkarılır; düşünme ayarı yalnızca Rosetta'nın kendi ayarından gelir ve çeviri
davranışı Rosetta'nın nereden çalıştırıldığına bağlı olmaz.

`claude` PATH'te yoksa `translate`/`estimate` (claude-cli ile) plan yapmadan anlaşılır bir
hatayla çıkar (kod 1). Gösterilen `$`
değerleri `claude`'un bildirdiği liste fiyatı eşdeğeridir, gerçek fatura değildir.

## Geliştirme

```bash
cd engine
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -q --cov=rosetta_engine
uv run pytest -m live -q   # gerçek claude CLI çağrısı yapar (token harcar)
```

## Faz 3 için sistem bağımlılıkları (Tauri)

Rust araç zinciri: [`rustup`](https://rustup.rs/).

- Arch: `webkit2gtk-4.1 base-devel curl wget file openssl appmenu-gtk-module libappindicator-gtk3 librsvg xdotool`
- Debian/Ubuntu: `libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev`

## Lisans

[AGPL-3.0-or-later](LICENSE). Rosetta, AGPL-3.0 lisanslı [PyMuPDF](https://pymupdf.readthedocs.io/)
kullanır; bu nedenle depo da AGPL uyumludur. Diğer bağımlılıklar (pydantic, typer, rich, jinja2,
platformdirs) MIT/BSD lisanslıdır.
