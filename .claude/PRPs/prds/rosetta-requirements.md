# Rosetta — Gereksinim Dokümanı (kullanıcının orijinal metni, 2026-10-16)

> Kaynak: ilk planlama oturumunda kullanıcının `/ecc:prp-plan` argümanı (verbatim). Sonraki kararlar en altta.

# Proje: Rosetta (PDF Çeviri Okuyucu)

Projenin adı **Rosetta**. Repo/klasör adı `rosetta`, Python paketi `rosetta_engine`, uygulama penceresi başlığı "Rosetta". Kod, config ve README'de bu adı kullan.

**Hedef platform: şimdilik sadece Linux.** Paketleme `.AppImage` ve `.deb` olsun. Windows/macOS ileride eklenecek; o yüzden platforma özel kod yazma, yol (path), config ve veri dizinlerini platform bağımsız kütüphanelerle çöz (ör. Python'da `platformdirs`, Tauri'de path API). Linux'ta veri `~/.local/share/rosetta`, config `~/.config/rosetta` altında dursun. Tauri'nin Linux'ta WebKitGTK kullandığını dikkate al ve gerekli sistem bağımlılıklarını README'ye yaz. Python sidecar'ı PyInstaller ile tek binary olarak paketlemeyi planla.

## 1. Amaç

Kişisel kullanım için bir masaüstü PDF okuyucu. Elimde 650 sayfalık İngilizce bir yazılım kitabı var. Uygulama:

- PDF'i açar ve okutur.
- VS Code'un markdown önizlemesi gibi **3 görünüm modu** sunar:
  1. **Orijinal**: sadece orijinal PDF sayfası
  2. **Split**: solda orijinal, sağda çeviri; paragraf bazlı senkron scroll
  3. **Sadece Çeviri**: sadece çevrilmiş sayfa
- Sayfaları, ben istediğimde, seçtiğim dile (varsayılan Türkçe) çevirir.
- İstersem tüm kitabı adım adım çevirip PDF olarak dışa aktarır.
- İngilizce öğrenmeme yardım eder: kelimeye tıkla → anlam, kelime defteri, aralıklı tekrar flashcard'ları ve sadece bilmediğim kelimelerin karşılığını gösteren 4. bir **Öğrenme** görünüm modu (detay: 3.6).

## 2. Temel kurallar (kesin, pazarlık yok)

1. **Otomatik AI çağrısı yok.** Her AI/çeviri çağrısı yalnızca benim bir butona basmamla tetiklenir. Prefetch, arka planda otomatik çeviri, açılışta otomatik analiz yok. (Prefetch ileride ayarlardan açılabilir bir opsiyon olabilir, varsayılanı KAPALI.)
2. **Her AI işleminden önce tahmini token/maliyet gösterilir**, onaylarsam çalışır.
3. **Her çeviri cache'lenir.** Aynı sayfa aynı dil+model için asla ikinci kez çevrilmez.
4. **Font küçültme yok.** Çeviri sayfası orijinal punto ve hiyerarşiyle **reflow HTML** olarak üretilir; metin uzarsa sayfa aşağı uzar.
5. **HTML'i LLM üretmez.** LLM'e sadece metin parçaları gider, LLM sadece çeviri metni döner. HTML lokal olarak kodla üretilir.
6. **Kod blokları, görseller, diyagramlar çevrilmez ve LLM'e gönderilmez.** Kod blokları monospace font tespitiyle (Courier, Consolas, Menlo, Mono içeren fontlar vb.) ayrılır.

## 3. Mimari

### 3.1 Arayüz: Tauri + React + PDF.js
- Görünüm modu seçici (Orijinal / Split / Sadece Çeviri)
- PDF.js viewer (orijinal sayfa)
- Reflow HTML renderer (çeviri sayfası)
- Kontrol paneli (hepsi manuel): **Kitabı Analiz Et**, **Bu Sayfayı Çevir**, **Aralık Çevir (ör. 120-140)**, **Tüm Kitabı Çevir**, **PDF Dışa Aktar**
- Maliyet onay penceresi + toplam harcama sayacı
- Toplu iş ekranı: ilerleme çubuğu, duraklat/devam, bütçe limiti, hatalı sayfa listesi ve "sadece hatalıları tekrar dene"
- Kitap profili düzenleme ekranı (sözlük ve çevrilmeyecek terimler elle düzenlenebilir)

### 3.2 Çeviri motoru: Python (FastAPI), Tauri sidecar olarak
- **Extractor (PyMuPDF):** sayfadan block'ları çıkarır: tip (heading/paragraph/list/code/image/table/caption), bbox, font adı, punto, bold/italic, okuma sırası. Çok sütunlu sayfalarda okuma sırasını doğru belirle.
- **Book Profiler (sadece butonla):** içindekiler + ilk birkaç anlamlı sayfayı LLM'e gönderip kitap profili çıkarır:
  ```json
  {
    "tur": "yazılım / dağıtık sistemler",
    "ton": "teknik ama akıcı",
    "hedef_dil": "tr",
    "cevrilmeyecek": ["Kafka", "commit", "consumer group", "API"],
    "sozluk": { "replication": "replikasyon", "throughput": "verim" },
    "kod_dili": ["Java", "SQL"]
  }
  ```
  Profil DB'de saklanır ve kullanıcı tarafından düzenlenebilir.
- **Translation Orchestrator:** sayfaları 3-5'erli batch'ler halinde provider'a gönderir; her sayfa bitince cache'e yazar; pause/resume, bütçe limiti, retry; kullanım limitine takılınca işi otomatik **duraklatır** ve durumu kaydeder.
- **Cost Estimator:** çevrilmemiş sayfaların metin uzunluğundan token tahmini.
- **HTML Builder:** block yapısı + çeviri → HTML şablonu (token harcamaz).
- **PDF Exporter (Playwright/Chromium print):** "sadece Türkçe" veya "iki dilli (EN | TR)" çıktı; içindekiler ve bookmark'lar Türkçe başlıklarla korunur.

### 3.3 Translator interface
```python
class Translator(Protocol):
    name: str
    def estimate(self, blocks: list[Block], profile: BookProfile) -> CostEstimate: ...
    def translate(self, blocks: list[Block], profile: BookProfile, context: str) -> list[Translation]: ...
```
Giriş: `[{"id": 3, "text": "Replication means..."}]` → Çıkış: `[{"id": 3, "tr": "Replikasyon, ..."}]`

LLM çıktısı mutlaka doğrulanmalı: tüm id'ler dönmüş mü, fazladan id var mı, JSON geçerli mi. Hatalıysa o batch'i bir kez tekrar dene, yine olmazsa sayfayı "hatalı" işaretle.

Provider'lar:
1. **Claude Code CLI (varsayılan):**
   - Python'dan subprocess ile `claude -p --model haiku --output-format json` çalıştırılır.
   - Prompt **stdin** üzerinden verilir, sonuç **stdout**'tan okunur. Geçici dosya oluşturulmaz.
   - Kimlik doğrulama: makinedeki mevcut `claude` login'i veya `claude setup-token` ile alınan `CLAUDE_CODE_OAUTH_TOKEN` ortam değişkeni.
   - **Abonelik token'ı ile doğrudan Anthropic API'ye istek atma.** Her zaman `claude` CLI'ı kullan.
   - Kurulu `claude` sürümünde `claude --help` ile print modunda kullanılabilecek flag'leri kontrol et (session kaydını kapatma, tool'ları devre dışı bırakma, max turn vb.). Çeviri çağrısında hiçbir tool'a ihtiyaç yok; mümkünse tool'ları kapat.
   - Kullanım limiti hatası tespit edilirse orchestrator'a özel bir hata fırlat, iş duraklasın.
2. **DeepL** (opsiyonel): API key ile; bağlam/profil desteği olmadığını arayüzde belirt.
3. **Ollama** (opsiyonel): lokal model, bedava.

### 3.4 Çeviri prompt'u (LLM'e giden)
- Kitap profilini (tür, ton, sözlük, çevrilmeyecekler) içersin.
- Önceki sayfanın son 1-2 paragrafını bağlam olarak versin (çevrilmesin).
- Kurallar: anlamı koru, teknik terimlerde sözlüğe uy, inline kod (`backtick` içi), sınıf/metot adları, URL'ler aynen kalsın; sadece JSON dön.

### 3.5 Depolama: SQLite
Tablolar (öneri, gerekirse iyileştir):
- `books` (id, file_hash, title, page_count, created_at)
- `pages` (book_id, page_no, extracted_at)
- `blocks` (id, book_id, page_no, order, type, bbox, font, size, style, text)
- `translations` (block_id, lang, provider, model, text, created_at): cache key = `kitap_hash + sayfa + dil + model`
- `profiles` (book_id, json, updated_at)
- `usage` (timestamp, provider, model, input_tokens, output_tokens, estimated_cost, operation)
- `jobs` (id, book_id, type, range, status, progress, budget_limit, errors)
- `vocab` (id, word, lemma, sentence, book_id, page_no, block_id, meaning, unknown_flag, created_at)
- `reviews` (vocab_id, due_at, interval, ease/stability, reps, lapses, last_review_at)
- `explanations` (hash, text, explanation, model, created_at): "Bunu açıkla" sonuçlarının cache'i

### 3.6 İngilizce öğrenme modülü
Uygulamanın ikinci amacı İngilizce öğrenmeye destek olmak. Aynı kural geçerli: **AI sadece butonla, maliyet onaylı.** Geri kalan her şey lokal ve bedava.

**Çekirdek (AI'sız):**
- **Kelimeye tıkla → anlam:** Seçilen kelime/ifade için **lokal, offline sözlük** (ör. Wiktionary dump'ından ya da WordNet'ten üretilmiş bir SQLite sözlük; EN→TR karşılık + EN tanım). Lemmatization ile çekimli halleri köke indir (ör. `replicated` → `replicate`). Sözlük verisinin lisansını kontrol et ve README'ye yaz.
- **Kelime defteri:** "Kaydet" ile kelime, geçtiği cümle, sayfa ve block id'si saklanır. Liste ekranında arama/filtre (kitaba, tarihe göre).
- **Flashcard / aralıklı tekrar:** Kaydedilen kelimeler **FSRS** (tercihen `fsrs` Python paketi) veya SM-2 ile planlanır. Kart ön yüzü: kitaptaki cümle, kelime boşluklu (cloze). Arka yüz: kelime + anlam + Türkçe çeviri cümlesi (cache'te varsa). Değerlendirme: Again / Hard / Good / Easy.
- **Cümle eşleme:** Split modda bir cümleye/paragrafa tıklayınca karşı taraftaki karşılığı vurgulanır. Block id'leri üzerinden yapılır, ek maliyet yok. Cümle seviyesinde eşleme için çeviri prompt'unda paragraf içi cümle sınırlarını koruyacak bir işaretleme (ör. `<s1>…</s1>`) düşün; maliyet artışını değerlendir ve bana öner.
- **Öğrenme modu (4. görünüm modu):** Orijinal metin reflow HTML olarak gösterilir; sadece "bilmiyorum" işaretli kelimelerin üstünde küçük Türkçe karşılık (ruby/tooltip) çıkar. Kelime işaretlendikçe kitabın tamamında etkili olur.
- **Teknik terim listesi:** Kitap profilindeki sözlükten (Faz 2) otomatik kelime listesi oluştur, tek tıkla kelime defterine ekle.
- **Basit istatistik:** Toplam kelime, öğrenilmiş (olgun) kelime, bugünkü tekrar sayısı, seri (streak).

**Butonla AI (sonra):**
- **"Bunu açıkla":** Seçili cümlenin grameri, deyimleri, neden böyle kurulduğu, Türkçe açıklamayla. Haiku ile, `claude -p` üzerinden, maliyet onaylı, sonuç `explanations` tablosunda cache'li.

## 4. Fazlar

- **Faz 1: Motor + CLI test.** Extractor, kod bloğu tespiti, Claude Code provider, cache, HTML builder.
- **Faz 2: Kitap profili.** Analiz komutu + profilin çeviriye dahil edilmesi + profil düzenleme.
- **Faz 3: Arayüz.** Tauri + React + PDF.js, 3 görünüm modu, senkron scroll, manuel butonlar, maliyet onayı.
- **Faz 4: Toplu iş.** Aralık/tüm kitap çevirisi, pause/resume, bütçe limiti, limit durumunda otomatik duraklama, hatalı sayfalar.
- **Faz 5: PDF export.** Sadece TR ve iki dilli çıktı, bookmark/içindekiler.
- **Faz 6: İngilizce öğrenme çekirdeği.** Lokal sözlük + kelimeye tıkla, kelime defteri, FSRS flashcard, cümle eşleme, öğrenme modu, teknik terim listesi, istatistik.
- **Faz 7: "Bunu açıkla"** (butonla AI).
- **Faz 8 (opsiyonel):** DeepL ve Ollama provider'ları.

Kod kalitesi: tipli Python (type hints), küçük ve test edilebilir modüller.

---

## Sonraki kararlar (kullanıcı, 2026-10-16)
- Test kitabı: DDIA 2nd (`~/SSD/Books/Designing Data-Intensive Applications 2nd.pdf`).
- `ANTHROPIC_API_KEY` (ve tüm `ANTHROPIC_*`) alt süreçten her zaman çıkarılır; sadece yerel `claude` girişi. Asla doğrudan API isteği yok.
- Cümle eşleme: JSON `s` dizisi (Faz 1'den açık). Profil değişikliği cache'i geçersiz kılmaz; yeniden çeviri yalnızca `--force`.
- Tablolar görsel; hücre çevirisi sonraya. Açık kaynak, AGPL-3.0. Python 3.13.
- Varsayılan çeviri modeli **Sonnet** (kör testten sonra kullanıcı onayı; Haiku'nun yerine). Düşünme: medium; çağrı başı bütçe sınırı $0.25.
- Kullanıcı Max aboneliğinde: $ rakamları liste fiyatı eşdeğeri; asıl sınır kullanım limiti.
- 2026-10-16: "her şeyi hallet, soru sorma, bütün fazları ajanlarla yap". Gerçek `claude` çağrıları (maliyet) kullanıcı onayı olmadan yapılmaz; geliştirme sahte sağlayıcılarla test edilir.
