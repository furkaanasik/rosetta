# Faz 3 — Motor HTTP API (Tauri sidecar)

Masaüstü uygulaması motorla yerel bir HTTP API üzerinden konuşur. Sözleşme:
[`app/API_CONTRACT.md`](../app/API_CONTRACT.md) (bağlayıcı); uygulama: `engine/src/rosetta_engine/api/`.

## Başlatma

```bash
ROSETTA_SERVE_TOKEN=<hex> uv run rosetta serve [--port 0] [--host 127.0.0.1]
uv run rosetta serve --token <hex>   # yalnızca geliştirme: argv `ps` ile herkese görünür
```

- Yalnızca yerel adres (`127.0.0.1`, `::1`); başka bir `--host` reddedilir (çıkış 2).
- `--port 0` boş bir port seçer. Hazır olunca stdout'a **tek satır** basılır:
  `{"port": 41234, "token": "…"}`. stdout'a başka hiçbir şey yazılmaz (loglar stderr'e).
- Belirteç sırası: `--token` (geliştirme; komut satırı `/proc/<pid>/cmdline` üzerinden diğer
  kullanıcılara görünür) → `$ROSETTA_SERVE_TOKEN` (uygulamanın yolu; ortam yalnızca sahibine
  açık) → rastgele 64 hex. Ortam değişkeni okunduktan sonra silinir; `claude`/Chromium alt
  süreçleri onu devralmaz. Belirteç yalnızca el sıkışma satırında basılır.
- **Ebeveyn ölünce kapanma:** stdin bir **pipe** ise (masaüstü uygulaması) bir iş parçacığı
  onu okur; EOF = uygulama kapandı → zarif kapanış, 5 sn içinde bitmezse `os._exit(0)`. Terminal
  ya da `/dev/null` stdin izlenmez (elle ve test çalıştırmaları etkilenmez). Linux'ta ayrıca
  `prctl(PR_SET_PDEATHSIG, SIGTERM)` (PyInstaller önyükleyicisi öldürülse de süreç kapanır).
- `SIGTERM` (el sıkışmadan hemen sonra gelse bile) zarif kapanıştır.

## Güvenlik

- Her istek `Authorization: Bearer <token>` ister (sabit zamanlı karşılaştırma). Yalnızca
  görsel kırpma **rotası** (`/api/books/{id}/assets/…`, rota adıyla eşlenir; URL'de geçen bir
  `/assets/` metni yetmez) `?token=` kabul eder (`<img>` başlık gönderemez).
- CORS yalnızca `tauri://localhost`, `http://tauri.localhost`, `http://localhost:1420`.
- Görsel dosya adı sıkı bir kalıba uymalı ve kitabın `assets/` klasöründe olmalı (`../` engelli).
- HTML parçaları motorun HTML builder'ından gelir (her metin escape'li), yalnızca `<main>`
  öğesi döner; `<script>`, `<link>`, `<html>` yoktur.

## İki adımlı AI (Kural 1 ve 2) — sunucu tarafında zorunlu

Her AI işlemi önce ücretsiz `…/estimate` ile planlanır; motor planı tek kullanımlık bir
`confirm_token` altında saklar (600 sn). Çalıştırma uç noktası yalnızca bu belirteçle, tam o planı
çalıştırır. Belirteç işleme (translate / job / resume / retry / profile / explain) ve kapsama
(kitap ya da iş numarası) bağlıdır; eksik, sahte, kullanılmış, süresi dolmuş ya da başka işlem
için verilmiş belirteç → `409 expired_token`, sağlayıcı hiç çağrılmaz (testlerle kilitli).

- **Devam / hatalıları tekrar** belirteci tahmindeki sayfa kümesine bağlıdır; çalıştırma tam bu
  sayfaları planlar (ör. "2 hatalı sayfayı tekrar dene" hiç başlamamış 148 sayfaya dokunmaz).
  Arada işin sayfaları değiştiyse → `409 expired_token`, yeniden tahmin alınır.
- Tahmin yanıtında `warnings: string[]` vardır; ör. modelin fiyatı bilinmiyorsa bütçe önceden
  uygulanamaz (iş yalnızca gerçek harcama bütçeye ulaşınca durur).

## Uç noktalar

Sözleşmedeki tüm uç noktalar uygulanmıştır: sağlık, kitap aç/oku/içindekiler, sayfa block'ları
(`key` = HTML'deki `data-block`), sayfa HTML'i (`tr|review|learn`), görseller, çeviri tahmini ve
çalıştırma, toplu işler (tahmin, başlat, liste, durum, duraklat, devam, hatalıları tekrar,
iptal), kitap profili (oku, yaz, analiz tahmini, analiz), PDF dışa aktarma, öğrenme (sözlük,
kelime defteri, sırası gelen kartlar, değerlendirme, istatistik, terimler), "Bunu açıkla" ve
kullanım toplamları. Sayfa numaraları API'de 1 tabanlıdır.

### v2 (okuyucu yeniden tasarımı) — hepsi AI'sız ve token korumalı
- `GET /api/books`: kitaplık (son açılan önce; kapak yolu, kaldığı sayfa, çevrilmiş sayfa sayısı,
  dosya hâlâ yerinde mi). `PUT /api/books/{id}/progress {page}`: kaldığı yer. Migration 006
  `books.last_opened_at`, `books.last_page` ekler; kitap açılınca `last_opened_at` güncellenir.
- `GET /api/books/{id}/cover?w=240`: kapak PNG'si (genişlik başına önbellek, yalnız Bearer).
- `GET /api/books/{id}/pages`: tüm sayfaların boyutu, metin katmanı, çevrilebilir blok sayısı
  (çıkarılmamışsa null) ve çeviri durumu; çıkarma yapmaz (~0.1 sn / 670 sayfa).
- Sayfa HTML yanıtına `width`, `height`, `has_text_layer`, `content_box [x0,y0,x1,y1]` eklendi;
  `GET /api/books/{id}/html?pages=59-61` en çok 10 sayfayı tek istekte döndürür.
- `GET /api/books/{id}/pages/{n}/estimate_hint`: çevrilmemiş kâğıttaki "≈ $" gösterimi için
  tahmin. **Onay belirteci üretmez, AI çağırmaz** (testle kilitli); çevirmek yine
  `/estimate` → onay → `/translate` ister.
- HTML: bölüm başlıklarında "CHAPTER 1"/"BÖLÜM 1" etiketi `<span class="h-label">`; öğrenme
  modunda ruby yalnız kelimeyi sarar, başlıklarda küçük kalır (CSS).

## Geliştirme / E2E modu

`ROSETTA_DATA_DIR=<geçici dizin> rosetta serve --dev-fake-ai [--dev-fake-delay SN]` (gizli
bayraklar, `--help`'te görünmez; `ROSETTA_DATA_DIR` yoksa reddedilir, böylece gerçek veritabanına
sahte profil/açıklama yazılamaz): çeviri
sahte çevirmenle, profil ve "Bunu açıkla" sahte `complete` ile yanıtlanır; gerçek AI çağrısı
yapılamaz. `provider = "fake"` dışındaki sağlayıcı adları bu modda yalnızca okumak içindir (mevcut
çeviriler görünür, yeni çeviri `unavailable` döner). Paketli uygulama bu bayrağı hiç geçirmez.
`GET /api/books/{id}/file` (yalnızca Bearer) PDF'in kendisini döner; tarayıcıda çalışan uygulama
yerel dosyayı okuyamadığı için PDF.js bunu kullanır.

## Eşzamanlılık

- Her istek kendi SQLite bağlantısını açar (WAL). PyMuPDF belgeleri kitap başına önbelleğe alınır
  ve her kullanım kitabın kilidi altındadır.
- Toplu işler arka plan iş parçacığında, kendi bağlantısıyla çalışır; ilerleme her batch sonrası
  `jobs` tablosuna yazılır. Duraklatma DB bayrağıyla istenir (CLI ile aynı). Aynı anda tek toplu iş
  çalışır; ikincisi `409 busy` alır — **belirteç harcanmadan ve iş satırı oluşmadan**
  (yuva önce ayrılır), yani aynı belirteçle sonra tekrar denenebilir.
- İş, `running` durumuna atomik bir `UPDATE … WHERE status IN (…) AND pause_requested = 0` ile
  geçer: planlama sırasında gelen iptal ya da duraklatma işi hiç başlatmaz (sağlayıcı çağrılmaz);
  iptal edilmiş bir iş hiçbir yolda başka bir duruma yazılmaz.
- **AI tek seferde bir:** çeviri, profil analizi ve açıklama süreç genelinde bir kilit alır; bir
  toplu iş çalıştığı sürece kilidi tutar. Meşgulken `409 busy` (belirteç harcanmaz); mesaj işin
  numarasını söyler. Duraklatılan ya da iptal edilen bir iş **mevcut partisini bitirene kadar**
  kilidi tutar (ödenmiş sonuç kaybolmasın diye çağrı kesilmez); o arada çeviri `busy` alır.
  Ayrıca her batch, sağlayıcıya gitmeden hemen önce cache'e yeniden bakar.
- Motor yeniden başlarsa kitaplar DB'deki dosya yolundan tembel olarak yeniden açılır; o yolda
  artık başka bir dosya (farklı hash) varsa `409 conflict` döner (kimlikler karışmaz).
- Dışa aktarma kitap kilidini yalnızca belge işi (block, kırpma) için tutar; Chromium baskısı
  kilit dışında, geçici dosyaya yapılır ve `os.replace` ile yerine konur. Çıktı yolu herhangi bir
  kitabın kaynak PDF'i olamaz (`400`).

## Ayarlar ve tanılama (AI'sız)

- `GET /api/settings` / `PUT /api/settings {values}`: Ayarlar ekranı. Yalnızca beyaz listedeki üst düzey
  anahtarlar değiştirilebilir; `config.toml` satır satır güncellenir (yorumlar, `[pricing.*]` tabloları ve
  bilinmeyen anahtarlar korunur), bütün dosya doğrulanır, sonra geçici dosya + `os.replace` ile yazılır ve
  çalışan motora hemen uygulanır. `null` → anahtar silinir (varsayılan).
- `GET /api/diagnostics`: motor sürümü, klasörler, DB boyutu, sözlük, claude yolu + `claude --version`,
  Chromium, DeepL anahtar değişkeni tanımlı mı, Ollama (yalnızca localhost, 1 sn). `GET /api/diagnostics/claude`:
  "Bul" düğmesi için bulunan kurulumlar.
- **claude bulma sırası:** `claude_path` ayarı (geçersizse başka yere bakılmaz) → `PATH` → bilinen kurulum
  yerleri (`~/.local/bin`, `~/.claude/local`, `~/.local/share/mise/installs/claude/*` (en yeni), mise shim,
  `~/.npm-global/bin`, `~/.bun/bin`, `/usr/local/bin`, `/usr/bin`). Masaüstünden açılan uygulamanın PATH'i
  kabuktakinden kısa olabildiği için.
- Paketli motorda (PyInstaller + AppImage) `claude` alt sürecine kullanıcının kendi `LD_LIBRARY_PATH`'i verilir
  (`LD_LIBRARY_PATH_ORIG`; `_MEI…` ve `$APPDIR` kütüphaneleri çıkarılır).

## Hata biçimi

`{"error": {"kind", "message"}}` — `bad_request` 400, `unauthorized` 401, `not_found` 404,
`expired_token` 409, `conflict` 409 (kitap dosyası değişmiş), `invalid` 422, `usage_limit` 429, `budget` 402, `auth` 401,
`busy` 409 (başka bir AI işlemi/toplu iş sürüyor), `unavailable` 503 (claude CLI bulunamadı, sağlayıcı
hatası, Chromium yok), `internal` 500. Uygulama ayrıca motora hiç ulaşamadığında `offline` gösterir.

## Testler

- `engine/tests/test_api.py` (TestClient, sahte çevirmen ve sahte `complete`): yetki, CORS,
  her AI uç noktasında onay belirteci zorunluluğu, çeviri akışı ve cache, escape, görsel yolu,
  toplu iş (arka plan, duraklat/devam, hatalıları tekrar, iptal), profil, açıklama, öğrenme,
  dışa aktarma (Chromium yoksa atlanır).
- `engine/tests/test_api_serve.py`: gerçek `rosetta serve` alt süreci, el sıkışma satırı,
  `$ROSETTA_SERVE_TOKEN` (argv'de yok), stdin kapanınca çıkış, SIGTERM.
- `app/src/api/http.integration.test.ts`: uygulamanın `HttpEngineApi`'si gerçek sunucuya karşı;
  yalnızca `ROSETTA_ENGINE_URL` verilirse çalışır (sunucu `provider = "fake"` ile başlatılmalı).
