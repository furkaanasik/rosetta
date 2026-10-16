# Faz 4 — Toplu çeviri işleri

Bir sayfa aralığını ya da kitabın tamamını **iş** (job) olarak çevirir. Kurallar `translate` ile aynı: önce tahmin, onay olmadan AI çağrısı yok, her çeviri cache'lenir.

## Komutlar

```bash
rosetta job start kitap.pdf --pages 120-140 [--budget 2.0] [--yes]
rosetta job start kitap.pdf --all --budget 15        # tüm kitap
rosetta job list [--book kitap.pdf]
rosetta job status 3                                  # ayrıntı + hatalı sayfalar ve nedenleri
rosetta job pause 3                                   # başka terminalden: bir sonraki batch'ten önce durur
rosetta job resume 3 [--yes]                          # kalan sayfalar yeniden tahmin edilir, onay sorulur
rosetta job retry-failed 3 [--yes]                    # sadece hatalı sayfalar
rosetta job cancel 3                                  # çevrilen sayfalar cache'te kalır
```

`start` / `resume` / `retry-failed` ayrıca `--lang`, `--provider`, `--model`, `--profile` alır (resume işin sağlayıcı/modelini kullanır).

## Nasıl çalışır

- İş, sayfa listesi + durum (`bekliyor`, `çalışıyor`, `duraklatıldı`, `bitti`, `hatalı sayfa var`, `iptal`) olarak `jobs` tablosunda tutulur (migration `003_jobs.sql`).
- Çeviri batch batch ilerler; **her batch'ten sonra** biten sayfalar, hatalı sayfalar (nedenleriyle) ve harcanan tutar kaydedilir. Çökme, Ctrl-C ya da limit durumunda en fazla o anki batch kaybolur (o da ödenmişse cache'tedir).
- **Otomatik duraklatma:** kullanım limiti, bütçe, kimlik doğrulama hatası, `claude` bulunamaması veya üst üste 3 hata → iş `duraklatıldı` olur, neden kaydedilir.
- **Bütçe (`--budget`):** her batch'ten önce, o batch'in tahmini maliyeti işin kalan bütçesini aşacaksa iş durur (önce durur, sonra harcamaz). Ayrıca çağrı başı `claude_max_budget_usd` sınırı geçerlidir.
- **Duraklat:** `rosetta job pause ID` (veya API) DB'de bir bayrak kaldırır; çalışan süreç her batch'ten önce bu bayrağa bakar. Çalışan terminalde **Ctrl-C** de aynı şeyi yapar (ikinci Ctrl-C hemen çıkar).
- **Devam:** sadece kalan sayfalar planlanır; biten sayfalar cache'ten gelir, tekrar ödenmez.
- **Hatalı sayfalar:** iş sonunda hatalı sayfa varsa durum `hatalı sayfa var`, çıkış kodu 3; `retry-failed` sadece onları yeniden dener — hiç başlamamış sayfalar varsa onlara dokunmaz (iş sonra `duraklatıldı` kalır, `resume` ile devam).
- **Onaydan önce hiçbir şey değişmez:** `resume`/`retry-failed` reddedilirse (veya stdin terminal değilse) işin hatalı sayfaları ve duraklatma isteği olduğu gibi kalır. Eski bir duraklatma isteği ancak onaydan sonra temizlenir.
- **İptal/duraklatma yarışı:** iş `çalışıyor` durumuna atomik geçer (`iptal` değilse ve bekleyen duraklatma isteği yoksa). Planlama sırasında gelen iptal ya da duraklatma işi hiç başlatmaz, sağlayıcı çağrılmaz; `iptal` hiçbir yolda üzerine yazılmaz.
- **Fiyatı bilinmeyen model + bütçe:** tahmin yapılamadığı için bütçe önceden uygulanamaz (uyarı basılır); iş, sağlayıcının bildirdiği gerçek harcama bütçeye ulaşınca durur.

## Çıkış kodları

0 bitti (veya istekle duraklatıldı) · 2 iptal/onay yok · 3 hatalı sayfa var · 4 kullanım limiti (duraklatıldı) · 5 kimlik doğrulama · 6 bütçe · 7 sağlayıcı kullanılamıyor.

## Motor arayüzü (API için)

- `rosetta_engine.jobs.runner.JobRunner(service | None, repos)`: `create`, `plan` (AI yok), `run(job, plan, on_progress=, on_update=)` (başlayamazsa `JobNotStarted`), `prepare_continue` (onaydan sonra), `request_pause`, `cancel`, `reset_failed`, `get`.
- `PageTranslationService.execute(..., should_stop=, budget_usd=, on_batch=)`: `should_stop()` True → `stop_kind="paused"`; `budget_usd` aşılacaksa `stop_kind="budget"`; `on_batch` her batch sonrası ara rapor alır.
- `JobRepo` (`repos.jobs`): `create`, `get`, `list_jobs`, `update_progress`, `set_status`, `request_pause`, `pause_requested`, `clear_pause`.
