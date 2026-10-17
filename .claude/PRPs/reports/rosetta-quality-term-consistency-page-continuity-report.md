# Uygulama Raporu: Kalite paketi — (B) sayfa sonu paragraf devamı + (A) terim tutarlılığı

## Özet
(B) Sayfa sonunda bölünen paragraf artık tek öğe olarak çevriliyor ve sonuç cümle hizasına göre
iki sayfaya bölünüyor. Önbellek anahtarı değişmedi; `translations.unit_hash/unit_role` eklendi.
(A) Önbellekteki çeviriler yerel olarak taranıyor ve olası terim tutarsızlıkları bulunuyor. API,
CLI ve "Tutarlılık" paneli eklendi. Sözlüğe ekleme tek tıkla yapılıyor. Hedefli yeniden çeviri
tahmin → CostModal → onay akışıyla yapılıyor (en fazla 200 blok) ve sayfa durumunu
değiştirmiyor. Gerçek AI çağrısı yapılmadı.

## Plan ve gerçekleşen

| Metrik | Plan | Gerçek |
|---|---|---|
| Karmaşıklık | Large | Large |
| Güven | 7/10 | Testler muhasebeyi sabitledi |
| Dosya | ~22 | 34 güncelleme + 12 yeni |

## Görevler

| # | Görev | Durum | Not |
|---|---|---|---|
| B1 | `join_across` | Tamam | |
| B2 | `translate/joins.py` | Tamam | `find_link`: tek sayfa geri bakışla zincir kuralı (aralıktan bağımsız) |
| B3 | Modeller | Tamam | `JoinedUnit`'e `head_order/tail_order/merged_text` eklendi |
| B4 | Migration 007 + repo | Tamam | Tek dosya (unit kolonları + `term_ignores`) |
| B5/B6 | Servis plan/execute | Tamam | |
| B7 | Render + CSS | Tamam | Gizleme yalnız TR sayfada (`main.page`, `:not(.mode-review)`) |
| B8 | `--rejoin` | Yapılmadı | Q2: kapsam dışı. `extract` tablosundaki `↔` de yapılmadı |
| A1 | `prompt.mentions` | Tamam | |
| A2 | `pairs_for_book` | Tamam | |
| A3 | `quality/terms.py` | Tamam | Gerçek veride gürültü azaltıldı (aşağıya bakın) |
| A4 | `api/quality.py` | Tamam | |
| A5 | `only_blocks` hedefli plan | Tamam | |
| A6 | `rosetta consistency` | Tamam | |
| A7 | Uygulama API katmanı | Tamam | |
| A8 | Panel + ProfileEditor birleştirme | Tamam | Yeniden çevir düğmesi panelde (Q6) |
| A9 | Okuyucuda işaret | Yapılmadı | Q5: bu tur değil |
| D | Belgeler | Tamam | API_CONTRACT, docs/kalite.md, README |

## Doğrulama

| Seviye | Durum | Not |
|---|---|---|
| ruff check / format, mypy strict | Geçti | 0 hata |
| eslint, tsc | Geçti | 0 hata |
| Motor testleri | Geçti | 641 passed, 1 deselected (live); kapsam %95 |
| Uygulama testleri | Geçti | 127 passed, 2 skipped (önceden de skip) |
| Build (`npm run build`) | Geçti | |
| E2E (`npm run e2e`, sahte AI) | Geçti | 15 passed |
| DB göçü (gerçek DB'nin /tmp kopyası) | Geçti | sürüm 7, `(128, 0)` |

## Plandan sapmalar
- `JoinedUnit` ek alanlar: `head_order`, `tail_order`, `merged_text`. Tekrarlı bloklarda kimliği
  netleştirmek ve birleşik metni kurmak için gerekti.
- Terim analizi, gerçek önbellek kopyasında (95 satır) 28 gürültülü sonuç verdi. Bu yüzden şu
  düzeltmeler eklendi:
  - İstatistik tekrarlı cümleleri bir kez sayıyor.
  - Türkçe dolgu kelimeleri imza sayılmıyor.
  - Eşitlikte alıntı kelimeye benzeyen imza ("repli" ~ "replication") öne alınıyor.
  - Birleştirme kuralları: ünsüz yumuşaması, niteleyici ve kısa kökte ünlü eki.
  - `MERGE_PREFIX` 5 oldu.
  - Keşfedilen terimler için en az 8 farklı cümle ve Dice ≥ 0,3 gerekiyor.
  - Aynı sonucu tekrarlayan uzun ifadeler eleniyor.

  Sonuç 4'e indi, ikisi gerçek tutarsızlık.
- Paneldeki "Örnekler" yalnız sayfaya gidiyor. Blok vurgusu ReaderCanvas'ın iç durumu olduğu için
  bağlanmadı.

## Testler
`test_joins.py` (15), `test_terms.py` (16), `test_api_quality.py` (7), ve `test_service.py`
(+13), `test_store.py` (+4), `test_html_builder.py` (+2), `test_text_clean.py` (+2),
`test_cli.py` (+2) dosyalarına eklemeler. Uygulama tarafında `consistency.test.tsx` (6), ve
`book.test.tsx`, `api-v2.test.ts`, `mock.test.ts` dosyalarına eklemeler.

## Sonraki adımlar
- [ ] Gerçek ekranda manuel kontrol (DDIA s.38–39, sahte AI ile)
- [ ] `/code-review`, ardından commit
