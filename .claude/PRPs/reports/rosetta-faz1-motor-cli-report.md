# Implementation Report: Rosetta — Faz 1 (Motor + CLI)

## Summary
`rosetta_engine` sıfırdan kuruldu: PyMuPDF extract pipeline (DDIA'ya göre ayarlı), SQLite store,
`claude -p` provider + prompt/validate/estimator, FakeTranslator, PageTranslationService,
Jinja2 HTML render (tr / review / debug / index) ve Typer CLI (`extract`, `estimate`, `translate`, `usage`).
Kalite turunda maliyet sorunu (gizli düşünme token'ları) bulunup düzeltildi; kör karşılaştırma sonrası
varsayılan model **Sonnet** oldu (kullanıcı onayıyla; plan "sadece haiku" diyordu).

## Assessment vs Reality
| Metric | Predicted | Actual |
|---|---|---|
| Complexity | XL | XL |
| Files | ~32 | 61 (src + tests + templates + migrations) + README, LICENSE, .gitignore, `profiles/ddia.json` |

## Tasks
| # | Task | Status | Notes |
|---|---|---|---|
| 1 | İskelet | done | LICENSE (AGPL-3.0-or-later), .gitignore, README; pydantic mypy plugin eklendi |
| 2-3 | config, models | done | `errors.py` paket kökünde (plan "Mevcut Durum") |
| 4-10 | extract | done | agent; +`geometry.py` |
| 11 | store | done | agent; + migration 002 (usage.calibrate) |
| 12-14 | prompt/validate/estimator/claude_cli | done | agent; live test kullanıcı onayıyla çalıştırıldı, geçti |
| 15 | fake + service | done | agent |
| 16 | render | done | agent |
| 17 | cli | done | + `--think`, `--max-budget-usd`, `estimate --force/--profile` |
| 18 | README + kalite turu | done | 5 DDIA sayfası debug + çeviri + kör kalite karşılaştırması |

## Validation
| Level | Status |
|---|---|
| ruff check + format | pass (52 dosya) |
| mypy strict (src) | pass (31 dosya) |
| pytest | 265 passed, 1 deselected (live); kapsam %97 |
| live (`-m live`) | 1 passed (kullanıcı onayıyla, tek çağrı) |
| DDIA extract --debug 25,30,59,94,115 | üretildi ve kullanıcıyla incelendi: `~/.local/share/rosetta/out/bca051a41972/` |
| DDIA translate 25,30,59,94,115 | Sonnet, tek çağrı, $0.051; `pNNN.tr.html` + `pNNN.review.html` |
| Cache | ikinci çalıştırma "0 çağrı", usage sayısı değişmedi |

## Deviations
- Şema: `pages.width/height`, `blocks.family/aside/list_marker` sütunları eklendi (Block alanları).
- Migration `002_usage_calibrate.sql`: `usage.calibrate`; düşünmeli ve maliyeti bozuk çağrılar kalibrasyona girmez.
- `BookMeta` tek JSON blob olarak `books.typography_json`'da; `furniture_json` NULL.
- Caption regex etiketten sonra `.`/`:` istiyor ("Figure 6-11 shows…" düz yazısı caption olmasın).
- Satır sonu tire kuralı kitap başına: DDIA satır kırma için U+2010, gerçek bileşik için ASCII `-` kullanıyor; `BookMeta.soft_hyphen` örneklemden tespit.
- Furniture: `# | metin` / `metin | #` numaralı footer kalıbı da tanınıyor (bölüm başına değişen footer).
- `find_tables` sadece "Table" caption'ı ile bulunan bölgeyi genişletir.
- Ardışık kod block'ları tek listing'e birleşir; çizimli kenar kutuları (sidebar) aside.
- Estimator input = max(tam kullanıcı mesajı tahmini, item token) + 4/cümle; sistem prompt token'ı hedef dil prompt'undan.
- `FakeTranslator(fail_after=N)` ve `fail_mode="budget"` eklendi; bağlam, batch sayfa ortasında başlıyorsa aynı sayfanın önceki paragraflarından.
- Asset adları 1-based (`p094_b0.png`); `style.css` templates/ altında.
- `report.done_pages/failed_pages` 0-based (CLI 1-based gösterir).
- **Model**: plan ve Kullanıcı Kararı 2 "sadece haiku" diyordu → kör test sonrası kullanıcı onayıyla varsayılan `sonnet`; `--model haiku` hızlı/ucuz taslak seçeneği olarak duruyor. Cache anahtarı modeli içerdiği için Haiku çevirileri ayrı kalır.
- **claude çağrısı** (planın doğrulanmış komutuna ekler): `--effort <level>`, `--max-budget-usd <x>`; alt süreç ortamından `ANTHROPIC_API_KEY`'e ek olarak `CLAUDE_EFFORT`, `CLAUDECODE`, `AI_AGENT` ve `CLAUDE_CODE_*` (`CLAUDE_CODE_OAUTH_TOKEN` hariç) çıkarılır; `claude_max_thinking_tokens` ayarlıysa `MAX_THINKING_TOKENS` verilir.
- Prompt `PROMPT_VERSION` 1 → 4: epigraf/atıf satırları da çevrilir; anlam ve olumsuzluk asla tersine çevrilmez; kaynakta yoksa parantez içinde İngilizce açıklama eklenmez; kısaltmanın açılımı çevrilir, kısaltma parantezde kalır; doğal Türkçe söz dizimi.
- Sözlük / do_not_translate filtresi tam kelime eşleşmesi (`(?<!\w)term(?!\w)`): "set" ≠ "dataset", "SQL" ≠ "NoSQL".
- Yeni hata: `BudgetExceededError` → iş durur, `stop_kind="budget"`, çıkış kodu 6.
- Çıktı sağlık uyarısı: gerçek çıktı > 2× tahmin ise `log.warning` ("thinking may be enabled").

## Kalite turu (2026-10-16)

### Extract / debug HTML
- Debug HTML (25, 30, 59, 94, 115) kullanıcıyla incelendi: block tipleri ve sıra doğru kabul edildi.
- Karar: vektör çizimli kod işaretleri (❶–❻) Faz 1'de olduğu gibi kalır (seçenek A) — kodda görünmezler,
  liste `<ol>` ile 1'den başlar.
- İşaret taraması (AI yok): 673 sayfanın yalnızca 8'inde (107, 114–116, 325, 329, 478–480; ≈%1).
  20 kod işareti ↔ 20 liste maddesi birebir; 2 liste sayfa sınırını aşıyor (116, 479).
  Rakam vektör geometrisinden OCR'sız okunabiliyor (her rakamın çizim komut dizisi farklı, 1–6).
  Seçenek B (doğru `<ol start=N>` + koda ❶ karakteri) tahmini 0.5–1 gün.

### Maliyet: gizli düşünme token'ları
- Live test geçti. İlk çeviri (5 sayfa, Haiku, tek çağrı): **$0.099, tahmin $0.016** (çıktı 19 255 tok, tahmin 2 645).
- Sebep: Rosetta bir Claude Code oturumu içinden çalıştı; alt süreç `CLAUDE_EFFORT=medium` ve `CLAUDE_CODE_*`
  değişkenlerini devraldı → Haiku düşündü, düşünme çıktı olarak faturalandı.
- Ölçüm (sayfa 25, aynı prompt, 4 çağrı, Haiku):

  | Varyant | Ayar | Çıktı tok | Gizli ≈ | Tutar | Süre |
  |---|---|---|---|---|---|
  | A | devralınan env (`CLAUDE_EFFORT=medium`) | 9 391 | 8 837 | $0.048 | 64 sn |
  | D | temiz env, `--effort` yok | 15 952 | 15 353 | $0.081 | 117 sn |
  | B | temiz env + `--effort low` | 12 817 | 12 215 | $0.065 | 86 sn |
  | C | B + `MAX_THINKING_TOKENS=0` | 867 | 297 | $0.005 | 9 sn |

  `--effort low` düşünmeyi kapatmıyor; yalnızca `MAX_THINKING_TOKENS=0` kapatıyor.
- **Onay aşımı**: ölçüm ≈ $0.03 olarak onaylanmıştı, **≈ $0.20** tuttu (tek sayfanın düşünmeli maliyeti
  önceden hesaplanmamıştı). Sonrasında her gerçek çağrıya `--max-budget-usd` sınırı konuldu.
- Haiku'da düşünme kapalı (C) epigrafı iki çalıştırmada da ters çevirdi ("that's all you can hope for" →
  "umutsuzluğunuz o kadardır"); medium iki çalıştırmada da doğru. Haiku medium'un gizli düşünmesi çağrıdan
  çağrıya ~9k–18k token oynuyor (4 sayfalık çağrı: $0.103, tahmin $0.082).

### Model kararı: kör karşılaştırma
- Sayfa 30 (10 cümle), etiketler gizli puanlandı:

  | | Anlam | Dil bilgisi | Kelimesi kelimesine | Karar | Maliyet |
  |---|---|---|---|---|---|
  | Haiku (medium) | 2 | 5 | 6 | yeniden çevrilmeli | ~$0.025 (4 sayfalık çağrının payı) |
  | Haiku + redaktör turu | 2 | 5 | 6 | yeniden çevrilmeli | +$0.047 |
  | Sonnet (medium) | 0 | 0 | 0 | olduğu gibi kullanılabilir | $0.016, ~10 sn |

  Redaktör turu yalnızca bir sözlük terimini düzeltti, anlam hatalarını görmedi.
- 5 sayfa (~50 cümle), kör: Haiku 9 anlam / 15 dil bilgisi / ~21 kelimesi kelimesine; **Sonnet 4 / 0 / 2**.
  Sonnet her sayfada daha iyi. Sonnet ile 5 sayfa tek çağrı: **$0.051** (tahmin $0.047, onay ≈ $0.08).
  Sonnet `--effort medium`'da neredeyse hiç gizli düşünme üretmiyor.
- Sonnet'te kalan hatalar: p59 başlık "Materializing" → "Gerçekleştirme" (doğrusu "Somutlaştırma"),
  p59 "istemci çevrimiçi" belirsizliği, p115 [2.1] kenar yönü ters ("düğümlere gelen" → "düğümlerden gelen";
  Haiku da aynı), p25 "no longer" → "artık" eksik, "fan-out" İngilizce kaldı.
- Sözlük (`profiles/ddia.json`) güncellendi: fan-out → "yayılım (fan-out)", failure(s) → arıza(lar),
  materializing → somutlaştırma; çoğullar (sets, edges, timestamps, trade-offs); SaaS do_not_translate'ten çıkarıldı.

### Kalite turunda yapılan değişiklikler
- Alt süreç ortam temizliği + `--effort` ve `MAX_THINKING_TOKENS` ayarları (`claude_effort`, `claude_max_thinking_tokens`).
- Prompt v2 → v4 kuralları (yukarıda), tam kelime sözlük eşleşmesi, çıktı sağlık uyarısı.
- Kalibrasyon bayrağı + migration 002; gerçek DB'deki pahalı ilk çağrı kalibrasyondan çıkarıldı.
- `--max-budget-usd` (çağrı başı, varsayılan $0.25) + `BudgetExceededError` + çıkış kodu 6.
- `--think off|low|medium|high` (varsayılan medium; `off` hızlı taslak).
- `estimate --force` (cache'i yeniden çevrilecekmiş gibi sayar, silmez) ve `estimate --profile`.
- Model başına düşünme payı tahmini: sonnet low/medium/high 500/1 500/6 000, haiku 13 000/18 000/24 000 tok/çağrı.
- Varsayılan model `sonnet`; fiyatlar claude-api skill'inden: Sonnet 5.5 $2/$10, Haiku 4.5 $1/$5 (milyon token, girdi/çıktı).
- Gösterilen $ değerleri liste fiyatı eşdeğeri; kullanıcı Max aboneliğinde, fatura yok, asıl sınır kullanım limiti.

## Kod incelemesi (2026-10-16)
Salt okunur inceleme (python-reviewer agent); temel kurallar sağlam bulundu: onaysız AI çağrısı yok,
kod/görsel/tablo/furniture modele gitmiyor, model çıktısı escape ediliyor, `ANTHROPIC_API_KEY` sızmıyor,
sayfa numarası dönüşümleri ve çıkış kodları doğru.

**Düzeltilenler (commit öncesi):**
- `-v` her gerçek çeviriyi çökertiyordu (`extra={"message": …}` LogRecord'da ayrılmış anahtar); tüm loglar
  `%s` biçimine geçti, `extra=` kalmadı — stderr/limit uyarıları artık görünüyor.
- `--force` eski çevirileri yenisi gelmeden siliyordu → silme kaldırıldı; tamamlanan sayfa aynı transaction'da
  `ON CONFLICT DO UPDATE` ile değiştiriliyor, ulaşılamayan sayfalar eski çevirisini koruyor.
- Sayfa iki batch'e bölünüp ikinci çağrı durunca ödenmiş satırlar kayboluyordu → her batch'in satırları hemen
  yazılıyor (`put_rows`), `done` durumu yalnızca sayfa tamamlanınca; tekrar çalıştırmada sadece eksikler gider.
- Alt süreç ortamı: tüm `ANTHROPIC_*` ve devralınan `MAX_THINKING_TOKENS` çıkarılıyor
  (`CLAUDE_CODE_OAUTH_TOKEN` korunuyor).
- Başarısız/geçersiz çağrılar 0 token/$0 kaydediliyordu → `ProviderError` token/maliyet taşıyor, usage'a yazılıyor.
- Fiyatı bilinmeyen model "$0.000" gösteriyordu → `price_known=False`, CLI "fiyat bilinmiyor" yazıyor.
- `claude` yoksa her batch deneniyordu → CLI çalışmadan önce kontrol ediyor; `ProviderUnavailableError` ve üst
  üste 3 sağlayıcı hatası işi durduruyor (çıkış kodu 7).
- Boş metinli çevrilebilir block tüm batch'i bozuyordu → planlanmıyor; `execute` savunmacı kontrol yapıyor.
- Alt süreç `encoding="utf-8", errors="replace"`; bütçe tespiti stderr'e değil subtype/result'a bakıyor;
  bozuk `config.toml` → `ConfigError` ile anlaşılır mesaj; `open_book` hata durumunda PDF'i kapatıyor.

**Ertelenen bilinen sorunlar:**
- Tek bir taranmış (metin katmanı olmayan) sayfa tüm planı durduruyor; atlayıp raporlamak daha iyi.
- Eski figür kırpmaları yeniden kullanılıyor (dosya varsa); geçici dosya + rename ve dosya adına bbox/extractor sürümü.
- Aynı anda iki ilk çalıştırmada `migrate` yarışı → `BEGIN IMMEDIATE` + sürümü içeride yeniden oku.
- `get_many` block başına bir SELECT (tüm kitapta ~50k sorgu) → sayfa başına toplu sorgu.
- Prompt'taki CONTEXT bölümü JSON ile kodlanmıyor (düşük risk: araç yok, çıktı doğrulanıyor).
- Farklı sayfalardaki aynı block iki kez ödeniyor (cache sayfa bazlı).
- Tek block `batch_max_input_tokens`'ı aşarsa yine gönderiliyor; yalnızca çağrı başı bütçe sınırı koruyor.
- `TranslationRepo.delete_page` artık servis tarafından kullanılmıyor.

**Çıkış kodları:** 0 başarı, 1 genel hata, 2 iptal, 3 kısmi hata, 4 kullanım limiti, 5 kimlik doğrulama,
6 bütçe sınırı, 7 sağlayıcı kullanılamıyor.

## Known Issues
- U+2010 ile satır sonunda bölünen gerçek bileşik kelimeler birleşiyor ("human‐readable" → "humanreadable") — ayırt edilemiyor.
- Bölüm sonu kaynakçada rakamla biten girdi `continues_on_next_page=True` tetikliyor.
- TOC'ta olmayan başlıklar punto sıralamasıyla (sidebar → h3, run-in bold → h4); ön madde sayfalarında tuhaf h4/dipnot.
- Vektör kod işaretleri (❶–❻) kodda görünmüyor; sayfa aşan liste 1'den başlıyor (8 sayfa).
- Sonnet çevirisinde sayfa başına ortalama ~1 küçük hata (yukarıdaki liste); p115 kenar yönü hatası iki modelde de var.
- `claude`'un bildirdiği Sonnet maliyeti fiyat tablosundan biraz yüksek ($0.016 vs hesap $0.0125) → tahminler biraz düşük kalabilir.
- Sözlük güncellemesi mevcut çevirilere uygulanmadı (cache); `--force` ile yenilenebilir.
- Ölçümde alt süreç ortamında yalnızca `CLAUDE_PID` kaldı (zararsız süreç numarası).

## Next Steps
- [x] Kod incelemesi bulguları uygulandı (ertelenenler yukarıda)
- [ ] İlk commit — kullanıcı onayıyla
- [ ] Seçenek B: vektör işaretleri (geometriden rakam okuma, `<ol start>`), ≈0.5–1 gün
- [ ] Faz 2: Book Profiler (otomatik profil/sözlük)
