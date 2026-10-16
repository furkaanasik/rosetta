# Faz 3 — Motor HTTP API (Tauri sidecar)

Masaüstü uygulaması motorla yerel bir HTTP API üzerinden konuşur. Sözleşme:
[`app/API_CONTRACT.md`](../app/API_CONTRACT.md) (bağlayıcı); uygulama: `engine/src/rosetta_engine/api/`.

## Başlatma

```bash
uv run rosetta serve [--port 0] [--token <hex>] [--host 127.0.0.1]
```

- Yalnızca yerel adres (`127.0.0.1`, `::1`); başka bir `--host` reddedilir (çıkış 2).
- `--port 0` boş bir port seçer. Hazır olunca stdout'a **tek satır** basılır:
  `{"port": 41234, "token": "…"}`. stdout'a başka hiçbir şey yazılmaz (loglar stderr'e).
- `--token` verilmezse rastgele 64 hex karakterlik belirteç üretilir.

## Güvenlik

- Her istek `Authorization: Bearer <token>` ister (sabit zamanlı karşılaştırma). Yalnızca
  görsel kırpmaları (`/api/books/{id}/assets/…`) `?token=` kabul eder (`<img>` başlık gönderemez).
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

## Uç noktalar

Sözleşmedeki tüm uç noktalar uygulanmıştır: sağlık, kitap aç/oku/içindekiler, sayfa block'ları
(`key` = HTML'deki `data-block`), sayfa HTML'i (`tr|review|learn`), görseller, çeviri tahmini ve
çalıştırma, toplu işler (tahmin, başlat, liste, durum, duraklat, devam, hatalıları tekrar,
iptal), kitap profili (oku, yaz, analiz tahmini, analiz), PDF dışa aktarma, öğrenme (sözlük,
kelime defteri, sırası gelen kartlar, değerlendirme, istatistik, terimler), "Bunu açıkla" ve
kullanım toplamları. Sayfa numaraları API'de 1 tabanlıdır.

## Geliştirme / E2E modu

`rosetta serve --dev-fake-ai [--dev-fake-delay SN]` (gizli bayraklar, `--help`'te görünmez): çeviri
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
  çalışır; ikincisi `503 unavailable` alır.
- Motor yeniden başlarsa kitaplar DB'deki dosya yolundan tembel olarak yeniden açılır.

## Hata biçimi

`{"error": {"kind", "message"}}` — `bad_request` 400, `unauthorized` 401, `not_found` 404,
`expired_token` 409, `invalid` 422, `usage_limit` 429, `budget` 402, `auth` 401,
`unavailable` 503 (claude yok, sağlayıcı hatası, Chromium yok, meşgul), `internal` 500.

## Testler

- `engine/tests/test_api.py` (TestClient, sahte çevirmen ve sahte `complete`): yetki, CORS,
  her AI uç noktasında onay belirteci zorunluluğu, çeviri akışı ve cache, escape, görsel yolu,
  toplu iş (arka plan, duraklat/devam, hatalıları tekrar, iptal), profil, açıklama, öğrenme,
  dışa aktarma (Chromium yoksa atlanır).
- `engine/tests/test_api_serve.py`: gerçek `rosetta serve` alt süreci, el sıkışma satırı.
- `app/src/api/http.integration.test.ts`: uygulamanın `HttpEngineApi`'si gerçek sunucuya karşı;
  yalnızca `ROSETTA_ENGINE_URL` verilirse çalışır (sunucu `provider = "fake"` ile başlatılmalı).
