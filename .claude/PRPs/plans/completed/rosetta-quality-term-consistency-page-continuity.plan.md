# Plan: Kalite paketi — (B) sayfa sonu paragraf devamı + (A) terim tutarlılığı denetleyicisi

## Summary
**(B)** Sayfa sonunda bölünen bir paragraf (sayfa N'nin son cümlesi yarım, sayfa N+1 küçük harfle
devam ediyor) bugün iki bağımsız blok olarak, iki ayrı öğe halinde çevriliyor. Model yarım cümleyi
tahmin etmek zorunda kalıyor. Yeni davranışta iki parça plan sırasında **tek bir çeviri birimine**
birleştirilir ve tek öğe olarak gönderilir. Sonuç cümle hizasına göre yeniden iki satıra bölünür:
baş parça sayfa N'ye, kuyruk parça N+1'e yazılır. Önbellek anahtarı değişmez, `translations`
tablosuna iki nullable kolon eklenir. **(A)** Kitabın mevcut (önbellekteki) çevirileri tamamen yerel
olarak taranır: aynı İngilizce terimin farklı Türkçe karşılıkları ve sözlüğe uymayan kullanımlar
bulunur. Bunlar yan panelde yeni bir "Tutarlılık" sekmesinde gösterilir. Tercih edilen karşılık tek
tıkla profil sözlüğüne eklenir. Etkilenen paragrafların yeniden çevirisi yalnızca kullanıcı isterse
ve mevcut tahmin → CostModal → onay akışıyla yapılır. Otomatik ücretli çağrı yoktur.

## User Story
Bir okur olarak, sayfa sonunda bölünen paragrafların tek parça gibi doğru çevrilmesini ve kitap
boyunca aynı terimin hep aynı Türkçe karşılıkla geçmesini istiyorum. Böylece çeviri hem dil bilgisi
hem terminoloji açısından tutarlı olur ve hangi düzeltmenin ne kadar tutacağını önceden bilirim.

## Problem → Solution
- (B) `extract_page` sayfa düzeyinde yalnızca `PageBlocks.continues_on_next_page` bayrağını
  koyuyor. `PageTranslationService._batch` blokları birbirinden bağımsız `TranslationItem`'lara
  çeviriyor. Sayfa N+1'in ilk bloğu, başlangıcını hiç görmeden çevriliyor (en fazla `CONTEXT`
  olarak görüyor). Planda bu iki parça **tek öğe** olur, çıktı iki satıra geri bölünür ve
  okuyucuda devam paragrafı girintisiz başlar.
- (A) Terim tutarlılığını denetleyen bir araç yok. Sözlük (`BookProfile.glossary`) yalnızca
  ileriye dönük etkili (`prompt._profile_section`). Planda yerel ve ücretsiz bir analiz, panel,
  tek tık sözlüğe ekleme ve isteğe bağlı, onaylı, blok hedefli yeniden çeviri olur.

## Metadata
- **Complexity**: Large (2 özellik, motor + API + uygulama; ~22 dosya)
- **Source PRD**: N/A (öneri: memory `rosetta-roadmap-proposals.md` → "Quality")
- **PRD Phase**: N/A
- **Estimated Files**: ~22 (8 yeni, ~14 güncelleme)
- **Sıra**: Önce B (B'deki service/cache değişikliği A'nın blok hedefli yeniden çevirisinin
  temelidir), sonra A.

---

## Yerel veriden ölçümler (2026-10-17, `~/.local/share/rosetta/rosetta.db`, salt okunur)
- DDIA: extractor v2/v3 ile çıkarılmış 306 sayfanın 118'inde `continues_on_next_page=1`. clean_code:
  41 sayfanın 15'inde. Bayrak çok gürültülü: İçindekiler satırları ("… Fault Tolerance 43"), epigraf
  imzaları ("—Kevin Scott, …") ve övgü sayfaları da işaretleniyor.
- Bayraklı 127 sayfa çiftinin **76'sında** sonraki sayfanın ilk gövde bloğu küçük harfle başlayan
  bir paragraf (gerçek devam; örn. s.38 "…designed from the ground up to be" → s.39 "cloud native
  have been shown…"). Küçük harf filtresi İçindekiler / imza yanlış pozitiflerini eliyor.
- Önbellekte çok az çeviri var: 128 satır, ~20 sayfa (DDIA sonnet 95 satır/14 sayfa, haiku
  24/5, clean_code 9/1). Satırların tamamı `sentence_aligned=1`. 76 gerçek çiftin **yalnızca 1'inde**
  iki taraf da (ayrı ayrı) çevrilmiş. **Migration riski bu yüzden çok düşük.**
- Mevcut veride (A) için analiz edilecek çeviri az. Algoritma testleri sentetik verilerle yapılmalı.

---

## UX Design

### Before
```
Sayfa 38 (TR sheet)                    Sayfa 39 (TR sheet)
┌──────────────────────────────┐       ┌──────────────────────────────┐
│ … sıfırdan tasarlanmış       │       │     Bulutta yerel olanların  │  ← yarım cümle ayrı çevrildi,
│ sistemlerin şöyle olması…    │       │ birçok avantajı gösterildi…  │    girintili "yeni paragraf"
└──────────────────────────────┘       └──────────────────────────────┘
Terimler: "replication" bir yerde "çoğaltma", başka yerde "replikasyon"; fark edecek araç yok.
```

### After
```
Sayfa 38                               Sayfa 39
┌──────────────────────────────┐       ┌──────────────────────────────┐
│ … baştan buluta özgü olacak  │       │ şekilde tasarlanan sistemlerin│ ← tek birim olarak çevrildi;
│ şekilde tasarlanan…  (cut)   │       │ çeşitli avantajları… (rs-cont)│   devam satırı girintisiz
└──────────────────────────────┘       └──────────────────────────────┘

Yan panel ▸ [İçindekiler][İşler][Kelimeler][Profil][Tutarlılık]
┌ Tutarlılık ─────────────────────────────────────────┐
│ 3 olası tutarsızlık · 412 çevrilmiş paragraf tarandı│
│ ▸ replication                    (sözlükte yok)     │
│    ○ çoğaltma      ×7   [Sözlüğe ekle]              │
│    ○ replikasyon   ×3   [Sözlüğe ekle]   [Örnekler▾]│
│                                         [Yok say]   │
│ ▸ leader          sözlük: "lider"  · 2 uyumsuz      │
│    [Uyumsuz 2 paragrafı yeniden çevir… ($ tahmin)]  │
└─────────────────────────────────────────────────────┘
"Sözlüğe ekle" → profil kaydedilir (AI yok) → toast: "Sözlüğe eklendi · 3 paragraf farklı
karşılık kullanıyor  [Yeniden çevir…]" → estimate → CostModal → Onayla → çeviri.
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| Sayfa çevir (tek/aralık/iş) | Sınır paragrafı iki öğe | Tek öğe; komşu sayfanın parçası plana çekilir | Tahmin, komşu parçanın token'larını içerir |
| TR sayfa görünümü | Devam paragrafı girintili | `cont-prev` → girintisiz; kuyruk boşsa gizli | `rs-cont` CSS kuralı yeniden kullanılır |
| Yan yana (review) | Aynı | Kuyruk boşsa TR hücresinde "↑ önceki sayfada" | review şablonu |
| PDF export | Aynı | Aynı birleştirilmiş satırlar (build_page_html ortak) | Ek iş yok |
| Yan panel | 4 sekme | + "Tutarlılık" | AI yok; GET analiz |
| Sözlüğe ekleme | Profil sekmesinde elle | Çakışma kartında tek tık | PUT profile ile aynı depo |
| Etkilenen paragraflar | — | Panelde liste + isteğe bağlı "Yeniden çevir…" | Her zaman estimate → onay |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `engine/src/rosetta_engine/translate/service.py` | 192-338, 340-516 | `_key/_uncached/plan/_batch/_context/_request` ve `execute/_store_batch`; B'nin ve A'nın blok hedefli planının değişeceği yer |
| P0 | `engine/src/rosetta_engine/models.py` | 42-75, 108-150 | `Block`, `PageBlocks.continues_on_next_page`, `Translation`, `Batch`, `TranslationPlan` |
| P0 | `engine/src/rosetta_engine/store/repo.py` | 31-52, 323-423, 523-537 | `CacheKey`, `TranslationRow`, `TranslationRepo` (+`_insert_translations` ON CONFLICT), `ProfileRepo` |
| P0 | `engine/src/rosetta_engine/store/migrations/001_init.sql` | all | `translations` UNIQUE anahtarı, `pages`, `blocks` |
| P0 | `engine/src/rosetta_engine/extract/extractor.py` | 49-55, 350-409 | `EXTRACTOR_VERSION=3`, `_SENTENCE_END`, `_continues(ordered)` (son blok PARAGRAPH + cümle sonu yok) |
| P0 | `engine/src/rosetta_engine/render/html_builder.py` | 285-338, 406-452 | `_view` (çeviri → `TextView`, `untranslated` sınıfı), `build_page_html` |
| P1 | `engine/src/rosetta_engine/extract/text_clean.py` | 48-75 | `_joiner`: satır sonu tire birleştirme kuralı; sayfa sınırında aynısı kullanılacak |
| P1 | `engine/src/rosetta_engine/extract/sentences.py` | all | `split_sentences`; yarım cümlenin ilk/son cümle olarak kalması |
| P1 | `engine/src/rosetta_engine/translate/prompt.py` | 60-90 | `_mentions` (tam kelime eşleşmesi), GLOSSARY'nin yalnızca geçen terimlerle gönderilmesi |
| P1 | `engine/src/rosetta_engine/api/ai.py` | 79-206, 419-450 | `_profile`, `translate_estimate`, `translate`, `profile_get/put`; onay belirteci deseni |
| P1 | `engine/src/rosetta_engine/api/books.py` | 236-283 | `_render_pages`: `translated_blocks` sayımı, `for_page` |
| P1 | `engine/src/rosetta_engine/api/schemas.py` | 17-45 | `_Body`, `TranslateEstimateBody` |
| P1 | `engine/src/rosetta_engine/store/db.py` | 40-120 | Migration yükleyici, `_looks_applied` (`ALTER TABLE … ADD COLUMN` desteği) |
| P1 | `app/src/reader/bookLayout.ts` | 120-140 | `rs-cont`/`rs-cut` sınıfları (devam sayfaları) |
| P1 | `app/src/reader/reader.css` | 581-597 | Girinti kuralları; `p.rs-cont { text-indent: 0 }` |
| P1 | `app/src/components/SidePanel.tsx`, `app/src/state.ts` | all, 1-100 | Sekme listesi `TABS`, `SidePanel` tipi, `PANEL_LABELS`, `refresh` → `revision+1` |
| P1 | `app/src/App.tsx` | 290-350, 690-730 | `confirmed.request(estimate, run)` → CostModal deseni, `afterAi`, panel bağlama |
| P2 | `app/src/components/ProfileEditor.tsx` | all | Profil API kullanımı, `dirty` koruması (eşzamanlı düzenleme riski) |
| P2 | `app/src/api/engine.ts`, `api/http.ts`, `api/mock.ts`, `api/types.ts` | — | Yeni uç noktaları üç yere de eklemek (arayüz + HTTP + mock) |
| P2 | `engine/tests/test_service.py` | 1-60 | `repos` fixture'ı (`:memory:` + migrate), `_service`, `_plan`, FakeTranslator |
| P2 | `engine/tests/conftest.py` | 30-110 | `make_pdf`, `book_pdf`, `ddia_path` (yoksa skip) |
| P2 | `app/API_CONTRACT.md` | 60-170 | Sözleşme belgesi; yeni uç noktalar buraya |

## External Documentation
Harici araştırma gerekmiyor. Özellik tamamen iç desenlerle (sqlite3, pydantic, FastAPI, React +
Radix Tabs) yapılıyor. Türkçe küçük harfe çevirme için `str.casefold()` yetmez (`"I".lower()=="i"`).
Bunun için `I→ı`, `İ→i` ön dönüşümü elle yapılır (bkz. Task A1).

---

## Patterns to Mirror

### NAMING_CONVENTION
```python
# SOURCE: engine/src/rosetta_engine/translate/service.py:192-199
def _key(self, block: Block, lang: str) -> CacheKey:
    return CacheKey(block.page_no, block.text_hash, lang, self._t.name, self._t.model)

def _uncached(self, book: Book, blocks: Sequence[Block], lang: str, force: bool) -> list[Block]:
```
Modeller `pydantic.BaseModel` + `ConfigDict(frozen=True)`; repo satırları `@dataclass(frozen=True)`;
sayfalar içeride 0 tabanlı, API/CLI'da 1 tabanlı. Kullanıcıya dönük metinler Türkçe.

### ERROR_HANDLING
```python
# SOURCE: engine/src/rosetta_engine/api/learn.py:192-198 / api/ai.py:440-447
if lr.s.repos.books.get(book_id) is None:
    raise not_found(f"Kitap bulunamadı: #{book_id}")
...
except ValueError as e:
    raise bad_request(f"Geçersiz profil: {e}") from e
```
Motor hataları `rosetta_engine.errors` (RosettaError, ExtractionError …). API'de `api/errors.py`
(`not_found`, `bad_request`, `ApiError(kind, msg)`).

### LOGGING_PATTERN
```python
# SOURCE: engine/src/rosetta_engine/translate/service.py:73, 221-222
log = logging.getLogger(__name__)
log.warning("skipping pages without a text layer: %s", [p + 1 for p in no_text])
```

### REPOSITORY_PATTERN (bütün SQL repo.py'de)
```python
# SOURCE: engine/src/rosetta_engine/store/repo.py:348-357, 400-405
def for_page(self, book_id: int, page_no: int, lang: str, provider: str, model: str) -> dict[str, Translation]:
    rows = self._c.execute(
        "SELECT page_no, text_hash, text, sentences_json, sentence_aligned "
        "FROM translations WHERE book_id = ? AND page_no = ? AND lang = ? "
        "AND provider = ? AND model = ?", (book_id, page_no, lang, provider, model)).fetchall()
    return {r["text_hash"]: _translation(r) for r in rows}
...
conflict = _ON_CONFLICT_REPLACE if overwrite else "ON CONFLICT DO NOTHING"
```
Migration: `NNN_name.sql`, yalnızca `CREATE TABLE/INDEX` ve `ALTER TABLE … ADD COLUMN`.
`_looks_applied` bunları tanır (`store/db.py:_CREATE_RE/_ADD_COLUMN_RE`). Sıradaki numara **007**.

### SERVICE_PATTERN (plan AI'sız, execute yalnızca onaydan sonra)
```python
# SOURCE: engine/src/rosetta_engine/api/ai.py:129-143, 185-193
plan = svc.plan(ob.book, ob.doc, ob.meta, pages, lang, profile=profile, force=body.force)
token = eng.confirm.issue("translate", f"book:{book_id}", _TranslatePayload(plan, p, profile))
...
with eng.ai_call():
    payload = eng.confirm.take(body.confirm_token, "translate", scope)
    result = svc.execute(payload.plan, profile=payload.profile)
```

### UI_AI_FLOW
```tsx
// SOURCE: app/src/App.tsx:295-311
void confirmed.request(
  () => api.estimateTranslate(bookId, force ? { pages: [page], force: true } : { pages: [page] }),
  (token) => api.translate(bookId, token) ...,
  ...);  // → CostModal → Onayla → afterAi() = dispatch({type:"refresh"}) → revision+1
```

### TEST_STRUCTURE
```python
# SOURCE: engine/tests/test_service.py:26-46
@pytest.fixture
def repos() -> Iterator[Repos]:
    conn = db.connect(":memory:"); db.migrate(conn)
    yield Repos.from_conn(conn); conn.close()

def _service(repos, fail_mode=None, fail_after=0, **settings):
    fake = FakeTranslator(fail_mode=fail_mode, fail_after=fail_after)
    return PageTranslationService(fake, repos, Settings(**settings)), fake
```
`FakeTranslator` her cümleyi `"[TR] "` önekiyle döndürür ve çağrıları `fake.calls`'a kaydeder.
Uygulama testleri `MockEngineApi` + Testing Library (`app/src/test/*.test.tsx`).

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `engine/src/rosetta_engine/translate/joins.py` | CREATE | (B) `find_split`, `merge_parts`, `split_translation`, `JoinedUnit` üretimi (saf fonksiyonlar) |
| `engine/src/rosetta_engine/extract/text_clean.py` | UPDATE | `_joiner`'ı public `join_across(prev, nxt, soft)` olarak sarmak (sayfa sınırı tire birleştirme) |
| `engine/src/rosetta_engine/models.py` | UPDATE | `JoinedUnit` modeli; `Batch.joins`; `Translation.unit_hash/unit_role`; `TranslationPlan.targeted` |
| `engine/src/rosetta_engine/store/migrations/007_joined_units_terms.sql` | CREATE | `translations.unit_hash`, `translations.unit_role`; `term_ignores` tablosu |
| `engine/src/rosetta_engine/store/repo.py` | UPDATE | `TranslationRow` alanları, `_insert_translations`, `for_page` SELECT, `pairs_for_book`, `TermIgnoreRepo`, `Repos` |
| `engine/src/rosetta_engine/translate/service.py` | UPDATE | Birleştirilmiş birim planı/önbellek kontrolü/saklama; `only_blocks` hedefli plan |
| `engine/src/rosetta_engine/render/html_builder.py` | UPDATE | `cont-next`/`cont-prev` sınıfları, boş kuyruk |
| `engine/src/rosetta_engine/render/templates/review.html.j2` | UPDATE | Boş kuyruk TR hücresi "↑ önceki sayfada" |
| `engine/src/rosetta_engine/export/templates/print.css` | UPDATE | `.joined-empty{display:none}`, `.cont-prev{text-indent:0}` |
| `engine/src/rosetta_engine/quality/__init__.py` | CREATE | Yeni paket |
| `engine/src/rosetta_engine/quality/terms.py` | CREATE | (A) yerel tutarlılık analizi (saf) |
| `engine/src/rosetta_engine/translate/prompt.py` | UPDATE | `_mentions` → public `mentions` (A yeniden kullanır), davranış aynı |
| `engine/src/rosetta_engine/api/quality.py` | CREATE | `GET consistency`, `POST accept`, `POST/DELETE ignore` (AI yok) |
| `engine/src/rosetta_engine/api/app.py` | UPDATE | `quality.router` kaydı |
| `engine/src/rosetta_engine/api/schemas.py` | UPDATE | `TermAcceptBody`, `TermIgnoreBody`, `TranslateEstimateBody.blocks` |
| `engine/src/rosetta_engine/api/ai.py` | UPDATE | `translate_estimate` içinde `blocks` → `only_blocks` |
| `engine/src/rosetta_engine/commands/consistency.py` | CREATE | `rosetta consistency PDF [--accept "term=çeviri"]` (AI yok) |
| `engine/tests/test_joins.py`, `test_terms.py`, `test_api_quality.py` | CREATE | Birim + API testleri |
| `engine/tests/test_service.py`, `test_store.py`, `test_html_builder.py` | UPDATE | Birleştirme/migration/render testleri |
| `app/src/api/types.ts`, `engine.ts`, `http.ts`, `mock.ts` | UPDATE | Tutarlılık API'si, `TranslateEstimateRequest.blocks` |
| `app/src/state.ts`, `components/SidePanel.tsx`, `App.tsx` | UPDATE | "consistency" sekmesi + bağlama |
| `app/src/components/ConsistencyPanel.tsx` | CREATE | Panel UI |
| `app/src/reader/reader.css`, `app/src/styles/panels.css` | UPDATE | `cont-prev`, `joined-empty`, panel stilleri |
| `app/src/test/consistency.test.tsx` | CREATE | Panel testleri (mock) |
| `app/API_CONTRACT.md`, `docs/kalite.md` | UPDATE/CREATE | Sözleşme + Türkçe faz belgesi (README'ye tablo satırı) |

## NOT Building
- Üç veya daha fazla sayfaya yayılan zincirler. Yalnızca **çiftler** (N → N+1) birleştirilir. Kuyruk
  bloğu aynı zamanda N+2'nin başıysa ikinci halka bağlanmaz ve `log.info` ile kaydedilir.
- Sütunlar arası ya da şekil/kod/dipnot arkasından devam eden paragraflar. Kuyruk, N+1'in **ilk gövde
  bloğu** olmak zorundadır.
- Extractor değişikliği / `EXTRACTOR_VERSION` artırımı. Bağlantı, saklanan bloklardan servis
  katmanında hesaplanır ve yeniden çıkarma gerekmez (bkz. Karar B-1).
- (A) için AI destekli terim çıkarma, çeviri yanıtına terim haritası ekleme (prompt/şema değişikliği),
  lemmatizer/morfoloji kütüphanesi. Yeni bağımlılık eklenmez.
- Otomatik yeniden çeviri. Ne sözlüğe ekleme ne de birleştirme göçü kendiliğinden ücretli çağrı yapar.
- Kullanıcının elle düzelttiği cümle (yol haritası #1). Henüz yok. Eklendiğinde, hedefli yeniden
  çevirinin override'ları ezmemesi gerekecek (bkz. Risks).

---

## Kararlar (önerilen varsayılanlar) ve AÇIK SORULAR

| # | Konu | Önerilen varsayılan | Kullanıcı kararı gerekir mi? |
|---|---|---|---|
| B-1 | Bağlantı tespiti nerede | Servis katmanında, saklanan bloklardan saf `find_split(prev, nxt)`. `continues_on_next_page` yalnızca hızlı ön filtre. Extractor v4 yok. | Hayır |
| B-2 | Sınırı aşan cümlenin TR'si hangi sayfada | **Baş sayfada (N)**. N+1 bir sonraki tam cümleyle başlar; kuyruk tamamen yarım cümleyse N+1'de boş ve gizli. | **EVET (Q1)** |
| B-3 | Hizasız sonuç (cümle sayısı tutmuyor) | Tüm TR baş satıra; kuyruk boş + `sentence_aligned=0` | Hayır |
| B-4 | Eski (ayrı çevrilmiş) çiftler | Önbellekte sayılır, otomatik yeniden çeviri yok. İsteğe bağlı `rejoin` seçeneği (CLI `--rejoin`, ayrı tahmin). | **EVET (Q2)**: `rejoin` şimdi mi yapılsın (şu an yalnızca 1 çift etkileniyor) |
| B-5 | Yalnız bir taraf eskiden çevrilmişse | Birim yeniden çevrilir ve o tarafın satırı **ezilir** (overwrite). Maliyet bir yarım paragraf. | **EVET (Q3)** |
| B-6 | Kapsam dışı komşu parça | Plana çekilir (çıkarma ücretsiz). Tahmine dahil edilir. Komşu sayfanın durumu "done" yapılmaz. | Hayır |
| A-1 | Algoritma | Yerel istatistik: aday EN terimler (sözlük + ≥3 cümlede geçen 1-3 kelimelik n-gram) × TR kök imzaları (5 harf önek), Dice skoru. Sonuç "olası tutarsızlık" olarak sunulur. | **EVET (Q4)**: yalnızca sözlük terimleri mi, yoksa keşif (madencilik) de mi? Öneri: ikisi de, keşif eşikli |
| A-2 | "Yok say" kaydı | Yeni `term_ignores` tablosu (profil JSON'una değil) | Hayır |
| A-3 | Etkilenen paragrafların işaretlenmesi | Durumsuz: her GET'te yeniden hesaplanır, panelde listelenir. Okuyucuda işaret **opsiyonel** Task A9. | **EVET (Q5)**: okuyucu sayfasında da işaret (ince alt çizgi/kenar çubuğu) istiyor musun |
| A-4 | Yeniden çeviri | Blok hedefli plan (`only_blocks`) → mevcut CostModal. Varsayılan model/düşünme ayarları. | **EVET (Q6)**: tek seferde üst sınır (öneri 200 blok) ve "Yeniden çevir" düğmesi toast'ta mı panelde mi |
| A-5 | Analiz kapsamı | Varsayılan sağlayıcı/model (`eng.default_translator()`) ve `default_lang` satırları. Haiku/sonnet karışık önbellek ayrı tutulur. | Hayır (bilgi) |

---

## Step-by-Step Tasks

### — FEATURE B: Sayfa sonu paragraf devamı —

### Task B1: `join_across` (tire birleştirme) public yap
- **ACTION**: `extract/text_clean.py` içine `join_across(prev: str, nxt: str, soft: str = ASCII_HYPHEN) -> str` ekle.
- **IMPLEMENT**: `adj, sep = _joiner(prev, nxt, soft); return clean_text(adj + sep + nxt.strip())`.
  `join_lines` davranışı değişmez.
- **MIRROR**: `join_lines` (text_clean.py:65-75).
- **GOTCHA**: `soft` kitabın satır sonu tiresidir. `BookMeta.soft_hyphen` (extractor'da `meta.soft_hyphen`) servis çağrısında geçirilmeli. Yoksa U+2010 kullanan kitaplarda "analysis-friendly" gibi bileşikler bozulur.
- **VALIDATE**: `test_text_clean.py`: `join_across("distrib-", "uted systems")=="distributed systems"`; `join_across("be", "cloud")=="be cloud"`; U+2010 senaryosu.

### Task B2: `translate/joins.py` (saf mantık)
- **ACTION**: Yeni modül.
- **IMPLEMENT**:
  ```python
  BODY_SKIP = {BlockType.FURNITURE, BlockType.FOOTNOTE}
  def head_candidate(page: PageBlocks) -> Block | None   # son gövde PARAGRAPH (dipnot/furniture atlanır), aside değil
  def tail_candidate(page: PageBlocks) -> Block | None   # ilk gövde bloğu; PARAGRAPH değilse None
  def find_split(prev: PageBlocks, nxt: PageBlocks, soft: str) -> JoinedUnit | None
  def merged_block(unit: JoinedUnit, head: Block) -> Block   # page_no/order=head, text_hash=unit.unit_hash
  def split_translation(unit: JoinedUnit, sentences: list[str], aligned: bool) -> tuple[list[str], list[str], bool]
  ```
  `find_split` kuralları:
  1. `prev.continues_on_next_page` **veya** head adayının metni `_SENTENCE_END` ile bitmiyor. Dipnotlu sayfaları da yakalamak için bayrak tek başına yeterli sayılmaz; head adayı üzerinden yeniden kontrol edilir. `_SENTENCE_END` extractor.py:55'ten import edilir ya da `extract/extractor.py`'de public yapılır.
  2. Kuyruk adayı var, `tail.aside == head.aside`, `tail.family == head.family`.
  3. Kuyruk metni küçük harfle başlıyor (`text.lstrip("“\"'(")[:1].islower()`) **veya** head tireyle bitiyor. Ölçüm: bu filtre 127 bayraklı çiftten 76 gerçek devamı tutuyor, İçindekiler ve imza yanlış pozitiflerini eliyor.
  4. Kuyruk aynı zamanda bir sonraki sayfanın başıysa (kuyruk = sayfanın tek gövde paragrafı ve sayfa da devam ediyorsa) zincir kurulmaz.

  Birleştirilmiş cümleler **yeniden bölünmez**, açıkça kurulur:
  `merged = head.sentences[:-1] + [join_across(head.sentences[-1], tail.sentences[0], soft)] + tail.sentences[1:]`.
  `head_count = len(head.sentences)`: sınırı aşan cümle dahil, baş sayfaya giden cümle sayısı (Karar B-2).
  `merged_text = join_across(head.text, tail.text, soft)`, `unit_hash = text_hash(merged_text)`.
  `split_translation`: `aligned and len(sentences)==len(merged)` ise `(sentences[:head_count], sentences[head_count:], True)`, değilse `(sentences, [], False)`.
- **MIRROR**: models.py saf fonksiyon tarzı. Bloklar `frozen` olduğundan `model_copy(update=…)`.
- **IMPORTS**: `rosetta_engine.models` (`Block, BlockType, PageBlocks, JoinedUnit, text_hash`), `extract.text_clean.join_across`.
- **GOTCHA**: `head.sentences` boş olabilir (eski bloklar). `sentences or [text]` kullan (service `_request` da böyle yapıyor). Kod içi backtick'ler `join_across`'ta korunur (`clean_text` yalnızca boşluk sıkıştırır).
- **VALIDATE**: `tests/test_joins.py` (aşağıdaki tablo).

### Task B3: Modeller
- **ACTION**: `models.py` güncelle.
- **IMPLEMENT**:
  ```python
  class JoinedUnit(BaseModel):  # frozen
      unit_hash: str
      head_page: int; head_hash: str
      tail_page: int; tail_hash: str
      head_count: int            # TR cümlelerinden baş satıra gidecek sayı
      merged_sentences: list[str]
  class Translation: + unit_hash: str | None = None; unit_role: Literal["head","tail"] | None = None
  class Batch:       + joins: dict[str, JoinedUnit] = Field(default_factory=dict)  # merged text_hash → unit
  class TranslationPlan: + targeted: bool = False   # only_blocks planı: sayfa durumu yazılmaz
                         + joined_units: int = 0     # bilgi/UI
  ```
- **GOTCHA**: `TranslationPlan` onay belirteci yükünde tutuluyor (bellek içi, `confirm.issue`), serileştirme gerekmiyor. Yine de alanlar varsayılanlı olmalı ki eski testler kırılmasın.
- **VALIDATE**: `test_models.py` varsayılanlar; mypy strict.

### Task B4: Migration 007 + repo
- **ACTION**: `store/migrations/007_joined_units_terms.sql` + `repo.py`.
- **IMPLEMENT**:
  ```sql
  -- Sayfa sonu birleşik çeviri birimi: aynı birimden gelen baş/kuyruk satırları.
  ALTER TABLE translations ADD COLUMN unit_hash TEXT;
  ALTER TABLE translations ADD COLUMN unit_role TEXT;
  -- Terim tutarlılığı: kullanıcının yok saydığı terimler (kitap + dil başına).
  CREATE TABLE term_ignores(book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    lang TEXT NOT NULL, term TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(book_id, lang, term));
  ```
  `TranslationRow` + `unit_hash: str | None = None`, `unit_role: str | None = None` (sona, varsayılanlı).
  `_INSERT_TRANSLATION` ve `_ON_CONFLICT_REPLACE` bu iki kolonu da yazar.
  `for_page` SELECT'i ve `_translation()` yeni alanları okur.
  `TermIgnoreRepo(_Repo)`: `list(book_id, lang) -> set[str]`, `add`, `remove`. `Repos` dataclass'ına `term_ignores` alanı eklenir (`from_conn`).
- **MIRROR**: 002_usage_calibrate.sql (yorum + ALTER), `ProfileRepo.put` (ON CONFLICT upsert).
- **GOTCHA**: Var olan satırlarda `unit_hash` NULL kalır ve bu "bağımsız çevrilmiş" anlamına gelir. **Veri göçü yok.** Migration tek dosyada iki konuyu içeriyor. İstenirse 007/008 diye bölünebilir; `_looks_applied` her ikisini de tanır.
- **VALIDATE**: `test_store.py`: boş DB'de migrate → kolonlar var; 006'dan 007'ye yükseltmede eski satırlar okunur, `unit_hash is None`; put/for_page round-trip.

### Task B5: Servis — planda birleştirme
- **ACTION**: `PageTranslationService.plan/_batch/_uncached` güncelle.
- **IMPLEMENT**:
  1. `plan()` içinde `extracted = self.ensure_pages(...)` sonrasında `links = self._links(book, doc, meta, extracted, pages)` çağrılır. Her `p in pages` için `(p, p+1)` ve `p-1` kapsam dışındaysa `(p-1, p)` denenir. Komşu sayfa `self._load_page` ile alınır (yalnız çıkarma, AI yok) ve `extracted`'a **eklenmez**. Plan sayfaları değişmez.
  2. `translatable[p]` içinde head ve tail blokları çıkarılır, yerlerine `merged_block(unit, head)` **baş sayfanın** kovasına head'in sırasıyla konur. Head kapsam dışıysa (yalnız N+1 istenmişse) birleşik blok N+1 kovasının başına konur. `_batch` sayfa sırasıyla yürüdüğü için sıra korunur.
  3. Önbellek kontrolü `_is_cached(book, block, lang, joins)`: normal blokta `_key` hit. Birleşik blokta **her iki** satır var ve ikisi de `unit_hash == unit.unit_hash` (B-4: ya da ikisi de `unit_hash is None` → eski çift, `rejoin=False` iken cached). `_uncached` bu yardımcıyı kullanır. `get_many` sayfa başına bir sorgu yaptığı için yeterli; `Translation.unit_hash` artık dönüyor.
  4. `_make_batch` içindeki birleşik bloklar için `Batch.joins[merged.text_hash] = unit`.
  5. `total_blocks/cached_blocks` birim sayar (birleşik = 1). `plan.joined_units = len(links_used)`.
  6. `_context`: birleşik blok baş sayfadaysa mevcut davranış korunur. Kuyruk sayfasının ilk bloğu artık kuyruk değil, sonraki bloktur. `before` hesabı `b.order < first.order` olduğundan merged head'in `order`'ı kullanılır.
- **MIRROR**: `_batch` açgözlü döngüsü (service.py:255-290). Birleşik blok sıradan bir `Block` olduğundan `_request` değişmeden `TranslationItem(sentences=merged)` üretir.
- **GOTCHA**:
  - `batch_max_pages`: `pages = {b.page_no for b in current}`. Birleşik blok tek sayfa (head) sayılır, sınır aşılmaz.
  - `execute()` başındaki `bad` kontrolü (`_needs_translation`) birleşik blokta PARAGRAPH olduğundan geçer.
  - `estimate_hint` (ai.py:151) aynı `plan()`'ı kullanır ve komşu parçayı otomatik içerir. Doğru davranış bu, ama "bu sayfa" tahmini biraz büyür.
- **VALIDATE**: test_service: iki sayfalık bölünmüş PDF → tek batch'te tek item ve item cümleleri `merged_sentences`'a eşit. Yalnız [0] istenirse de kuyruk dahil. Yalnız [1] istenirse head dahil. İkinci plan `batches == []`.

### Task B6: Servis — execute/saklama
- **ACTION**: `execute`, `_store_batch` güncelle.
- **IMPLEMENT**:
  - `needed` kurulumu: `_parts(block, batch.joins) -> list[tuple[int, str]]` yardımcısı yazılır. Birleşik blok `[(head_page, head_hash), (tail_page, tail_hash)]` döndürür, normal blok `[(page_no, text_hash)]`. Yalnız `p in plan.pages` olan parçalar `needed[p]`'ye eklenir.
  - Ödeme öncesi yeniden kontrol (service.py:430-442) `_is_cached` kullanır ve `translated` güncellemesi `_parts` üzerinden yapılır.
  - `_store_batch(..., joins)`: birleşik blok için `split_translation` → iki `TranslationRow` (`unit_hash`, `unit_role="head"|"tail"`, `sentence_aligned=ok`). Boş kuyrukta `text=""`, `sentences=[]`. Satırlar sayfa kovalarına girer. Kapsam dışı sayfanın satırları yalnız `put_rows(..., overwrite=True)` ile yazılır, **durum yazılmaz**. Birleşik satırlar her zaman `overwrite=True` (B-5: eski bağımsız satırın yerini alır). Normal satırlar mevcut `force` kuralını korur.
  - `translated` sözlüğüne yalnız plan sayfaları için ekleme yapılır (`translated.setdefault` değil, `if p in translated`).
- **GOTCHA**: `put_page(rows, status, overwrite)` tek bir `overwrite` alır. Aynı sayfada hem normal (`overwrite=force`) hem birleşik (`overwrite=True`) satır olabileceği için iki çağrı yapılır: önce birleşik satırlar `put_rows(overwrite=True)`, sonra normal satırlar + durum `put_page`. İkisi ayrı transaction'lardır; araya bir durma girerse satırlar yine önbellekte kalır (mevcut "paid work never lost" ilkesi).
- **VALIDATE**: test_service: iki satır, `unit_role` doğru. Baş satır `head_count` cümle içeriyor. Kuyruk yarım cümleyse boş. Hizasız durum (`FakeTranslator` alt sınıfı bir cümle eksik döndürür) → baş satır tüm TR, kuyruk boş, aligned=0. Durdurulan çalıştırmada (usage_limit) eski satırlar korunuyor.

### Task B7: Render
- **ACTION**: `html_builder._view` + şablonlar + CSS.
- **IMPLEMENT**: `t.unit_role == "head"` → `classes.append("cont-next")`. `"tail"` → `"cont-prev"`, ve `not t.sentences and not t.text` ise `"joined-empty"`, `tr = TextView([])`.
  `review.html.j2`: TR hücresinde `joined-empty` için `<span class="joined-note">↑ önceki sayfada</span>`.
  `app/src/reader/reader.css`: `.rs-html .joined-empty{display:none}` ve `.rs-sheet--book .rs-html p.cont-prev{ text-indent:0 !important }`. Son sayfa satırı için `p.cont-next` iki yana yaslı son satır olarak `.rs-cut` kuralını paylaşır.
  `export/templates/print.css`: aynı iki kural.
  `sanitize.ts` yalnızca `class` özniteliğine izin veriyor (satır 22) ve bu yeterli.
- **MIRROR**: `classes.append("untranslated")` (html_builder.py:310).
- **GOTCHA**: `bookLayout.paginate` ölçüm yaparken `display:none` bir öğe yükseklik 0 döndürür ve `planSheets` buna dayanıklıdır (öğe yine sheet'e girer). Learn modunda `with_tr=False` olduğundan sınıf eklenmez, orijinal metin olduğu gibi kalır.
- **VALIDATE**: `test_html_builder.py`: head/tail sınıfları, boş kuyruk TR modunda metin yok, review'da not var. `app/src/test/book.test.tsx`: `cont-prev` paragrafına `text-indent` uygulanmıyor (computed style yerine sınıf kontrolü).

### Task B8: CLI/API yüzeyi + `rejoin` (Q2'ye bağlı)
- **ACTION**: `plan(..., rejoin: bool = False)`; CLI `translate --rejoin`; API `TranslateEstimateBody.rejoin`.
- **IMPLEMENT**: `rejoin=True` ise eski (unit_hash NULL) çiftler cached sayılmaz. `rosetta extract` tablosundaki "devam" sütunu birleşik çiftlerde `↔` gösterir (`find_split` ile).
- **VALIDATE**: test_cli / test_api: `rejoin` yalnız eski çifti plana alıyor.

### — FEATURE A: Terim tutarlılığı —

### Task A1: `prompt.mentions` public + Türkçe normalize
- **ACTION**: `prompt._mentions` → `mentions` (eski isim takma ad olarak kalabilir). `quality/terms.py` içinde `tr_fold(s) = s.replace("I","ı").replace("İ","i").lower()`.
- **VALIDATE**: test_prompt değişmeden geçiyor.

### Task A2: Repo — analiz girdisi
- **ACTION**: `TranslationRepo.pairs_for_book(book_id, lang, provider, model) -> list[PairRow]`.
- **IMPLEMENT**: `SELECT t.page_no, t.text_hash, t.sentences_json, t.text, t.sentence_aligned, t.unit_hash, t.unit_role, b.ord, b.sentences_json AS en_sentences, b.text AS en_text, b.type FROM translations t JOIN blocks b ON b.book_id=t.book_id AND b.page_no=t.page_no AND b.text_hash=t.text_hash WHERE …`. `PairRow` frozen dataclass olarak tanımlanır.
- **GOTCHA**: Birleşik çiftlerde EN tarafı `blocks`'tan parça parça gelir (head/tail). Analiz cümle düzeyinde yapıldığı için sınırı aşan cümle head satırında eksik EN ile eşleşir. Birleşik çiftleri `unit_hash` ile gruplayıp EN'yi `join_across` ile, TR'yi birleştirerek tek çift olarak analiz et. Aynı `text_hash` bir sayfada birden çok kez geçebilir (tekrarlı blok). `DISTINCT` kullanma, tekrarları say.
- **VALIDATE**: test_store: join, eski + birleşik satırlar.

### Task A3: `quality/terms.py` (saf, AI'sız)
- **ACTION**: Yeni modül.
- **IMPLEMENT**:
  ```python
  @dataclass(frozen=True) class Occurrence: page_no: int; block_ord: int; text_hash: str; en: str; tr: str
  @dataclass(frozen=True) class Variant: key: str; label: str; count: int; examples: list[Occurrence]
  @dataclass(frozen=True) class TermIssue: term: str; source: Literal["glossary","mined"]; preferred: str | None
                                           variants: list[Variant]; affected: list[Occurrence]
  def sentence_pairs(rows: Sequence[PairRow]) -> list[SentencePair]   # hizalı: cümle cümle; hizasız: blok bütün
  def candidate_terms(pairs, profile, *, min_occ=3, limit=300) -> list[str]
  def analyze(pairs, profile, ignored: set[str], *, min_share=0.15) -> list[TermIssue]
  ```
  Algoritma:
  - **Adaylar**: sözlük anahtarları (her zaman) ve madencilik. Madencilikte EN cümleleri backtick içi atılarak tokenize edilir; 1-3 kelimelik n-gram'lar alınır; uçlarda stopword olmamalı (küçük gömülü İngilizce stopword listesi), tümü harf olmalı, unigram ≥4 harf; ≥`min_occ` farklı cümlede geçmeli; frekansa göre ilk `limit` alınır. `do_not_translate` ve `ignored` hariç tutulur.
  - **TR imzaları**: TR cümlesi `tr_fold` → kelimeler → her kelimenin ilk 5 harfi (≤5 ise kendisi). 1-2 kelimelik imza n-gram'ları çıkarılır.
  - Her terim için `occ(term)` = terimi içeren cümle çiftleri (`mentions`). Her aday imza için Dice = `2·co/(occ(term)+occ_tr(sig))`. İlk 5 imza tutulur. Her geçiş, cümlesinde bulunan en yüksek Dice'lı imzaya atanır. Hiçbiri yoksa ve TR cümlesi EN terimi aynen içeriyorsa `"(İngilizce bırakılmış)"` varyantına, yoksa "belirsiz"e (raporlanmaz) atanır.
  - **Birleştirme**: boşluksuz yüzey biçimleri ≥6 harf ortak önek paylaşan varyantlar tek varyant olur ("veri tabanı" ~ "veritabanı").
  - **Çakışma**: payı ≥`min_share` ve sayısı ≥2 olan ≥2 varyant varsa issue üretilir. Sözlük terimlerinde `preferred = glossary[term]` olur. `affected` = TR'si tercihin imzasını içermeyen geçişlerdir; tek varyant olsa bile `affected` boş değilse issue üretilir ("sözlüğe uyumsuz").
  - `label`: varyantın en sık görülen tam yüzey biçimi (TR cümlesinden, imzayla başlayan kelime(ler)). Türkçe ekler olduğu gibi kalır ("çoğaltmanın") ve UI ek almamış en kısa biçimi önerir.
  - Sıralama: sözlük uyumsuzlukları önce, sonra toplam etkilenen sayısı.
- **GOTCHA**: 5 harf önek farklı kelimeleri birleştirebilir ("işlem"/"işlemci"). Bu yüzden UI "olası" der ve örnekleri gösterir. Performans hedefi: 10k cümlede < 2 sn (n-gram sayımı `Counter`, terim başına yalnız ilgili cümleler). Madencilik 1-3 gram × cümle → bellek kontrolü için `min_occ` ön filtresi iki geçişte uygulanır.
- **VALIDATE**: `tests/test_terms.py` (tablo aşağıda).

### Task A4: API — `api/quality.py`
- **ACTION**: Yeni router, `api/app.py`'de `include_router`.
- **IMPLEMENT**:
  - `GET /api/books/{id}/consistency?lang=` → `{analyzed_blocks, aligned_ratio, provider, model, issues:[{term, source, preferred, variants:[{label, count, examples:[{page(1-based), block:"p-o", en, tr}]}], affected:[{page, block, text_hash}], affected_count}]}`. Örnekler varyant başına en fazla 3, `affected` en fazla 200 (sayı ayrıca verilir).
  - `POST /api/books/{id}/consistency/accept` `{term, tr}` → profil yoksa `BookProfile(target_lang=default_lang)` oluşturulur, `glossary[term]=tr` yazılır, `profiles.put`. Yanıt: `{profile, affected:[…]}` (yeni tercihe göre yeniden hesaplanır). Cache'e dokunulmaz.
  - `POST /api/books/{id}/consistency/ignore` `{term}` / `DELETE …/ignore?term=`.
- **MIRROR**: `api/learn.py:192-221` (kitap yoksa 404, `_learn` bağlamı), `api/ai.py:profile_put` (`model_validate`, `bad_request`).
- **GOTCHA**: Analiz `eng.default_translator()` (name/model) satırlarını kullanır (`api/books.py:_render_pages` ile aynı). Kitap PDF'i açılmaz, yalnız DB okunur (`library()` gibi). `term`, `strip_controls` ile temizlenir (`textsafe`). Boş ya da 200 karakterden uzun değer 400 döner.
- **VALIDATE**: `tests/test_api_quality.py` (`make_client` fixture'ı, sahte AI): satırlar `put_page` ile tohumlanır → GET issue döner; accept profili günceller ve `usage` tablosu değişmez (AI yok); ignore sonrası issue kaybolur.

### Task A5: Servis + API — blok hedefli yeniden çeviri
- **ACTION**: `plan(..., only_blocks: frozenset[tuple[int, str]] | None = None)`; `TranslateEstimateBody.blocks: list[BlockRef] | None` (`{page:int(1-based), text_hash:str}`, en fazla 200).
- **IMPLEMENT**: `only_blocks` verilirse `pages` = blokların sayfaları olur. `translatable[p]` yalnız bu (page, hash) çiftleriyle filtrelenir. Bu bloklar için `force=True` davranışı uygulanır. Blok birleşik bir birimin parçasıysa tüm birim alınır. `TranslationPlan.targeted=True` olur. `execute` içinde `targeted` ise: `_save_page` / `_fail_page` çağrılmaz, satırlar `put_rows(overwrite=True)` ile yazılır, `done_pages` = dokunulan sayfalar (rapor için). **Sayfa durumu değiştirilmez.** Böylece kısmen çevrilmiş bir sayfa yanlışlıkla "done" olmaz.
  `api/ai.py:translate_estimate`: `body.blocks` varsa `pages` yok sayılır, `check_pages` blok sayfalarıyla çağrılır, sonra `svc.plan(..., only_blocks=…)`. Onay belirteci ve CostModal akışı aynen kalır.
- **GOTCHA**: `execute`'un mevcut "needed boş → `_save_page(... overwrite=force)` ve done" dalı (service.py:388-391) targeted modda **atlanmalı**. Bu en kolay gözden kaçacak hata. Tahmin, güncel profili (yeni sözlük girdisiyle) `_profile()` üzerinden alır. Kullanıcı "Sözlüğe ekle"den sonra tahmin istediği için doğru.
- **VALIDATE**: test_service: kısmen çevrilmiş sayfada tek blok hedefli → page_status değişmez, yalnız o satır ezilir, FakeTranslator yalnız o item'ı alır. test_api: `blocks` ile estimate → `/translate` → satır güncellendi.

### Task A6: CLI — `commands/consistency.py`
- **ACTION**: `def register(app)` → `rosetta consistency PDF [--lang] [--min-occ 3] [--accept "term=çeviri"] [--ignore term]`.
- **IMPLEMENT**: Rich tablo (terim, kaynak, varyantlar ×sayı, etkilenen). `--accept`, `profile set --term` ile aynı ayrıştırmayı yapar. Yeniden çeviri CLI'da yok; kullanıcıya `rosetta translate --pages …` önerilir. Opsiyonel: `--blocks` ile hedefli çeviri ileride.
- **MIRROR**: `commands/profile.py:_open`, `set_` (satır 210-260).
- **VALIDATE**: test_cli: `CliRunner`, tohumlanmış DB, AI çağrısı yok.

### Task A7: Uygulama API katmanı
- **ACTION**: `types.ts` (`ConsistencyReport`, `TermIssue`, `TermVariant`, `BlockRef`; `TranslateEstimateRequest.blocks?`), `engine.ts` (`consistency`, `acceptTerm`, `ignoreTerm`, `unignoreTerm`), `http.ts`, `mock.ts` (deterministik 2 issue'luk sahte veri; accept, mock profilin `sozluk`'unu günceller).
- **VALIDATE**: `npm run typecheck`; `api-v2.test.ts` ve `mock.test.ts`'e birer test.

### Task A8: Panel UI
- **ACTION**: `state.ts`: `SidePanel` tipine `"consistency"`, `PANEL_LABELS.consistency = "Tutarlılık"`. `SidePanel.tsx`: `TABS` + `consistency` prop'u. `App.tsx`: `<ConsistencyPanel api bookId refreshKey={state.revision} onGoto={...} onRetranslate={(blocks)=>confirmed.request(()=>api.estimateTranslate(bookId,{blocks}), (t)=>api.translate(bookId,t), …)} onChanged={afterAi} onMessage={say}/>`.
  `ConsistencyPanel.tsx`: yükleme iskeleti → issue kartları. Varyant satırında "Sözlüğe ekle" (tek tık → `acceptTerm` → toast + `onChanged()`). Toast'ta etkilenen sayısı ve "Yeniden çevir…" eylemi (Q6). Kartta "Örnekler" açılır listesi: EN/TR + sayfa bağlantısı, `onGoto(page, block)` mevcut highlight mekanizmasıyla. "Yok say" düğmesi var. Boş durum: "Tutarsızlık bulunmadı · N paragraf tarandı". Çeviri yoksa: "Henüz çevrilmiş sayfa yok".
- **MIRROR**: `ProfileEditor.tsx` (yükleme/iptal deseni, `EmptyState`), `LearnPanel.tsx` (liste + eylem), `ui/Button`, `ui/Toast`.
- **GOTCHA**: `ProfileEditor` açıkken kaydedilmemiş düzenleme varsa (`dirty`), accept onu ezmez: ProfileEditor yeniden yüklemeyi atlar. Ancak ProfileEditor sonra kaydederse accept'in eklediği terimi **siler** (PUT tüm profili yazar). Çözüm: accept sonrası `afterAi()` ile revision artar. ProfileEditor `dirty` iken bir uyarı gösterir ya da `putProfile` öncesi sunucudaki sözlükle birleştirir. Basit yol: ProfileEditor kaydederken `getProfile` → yalnız değişen anahtarları uygular. Bu Task'ta küçük bir düzeltme olarak yapılır.
- **VALIDATE**: `app/src/test/consistency.test.tsx`: render → varyant tıkla → `acceptTerm` çağrıldı, toast görünür. "Yeniden çevir" → `estimateTranslate` `{blocks}` ile çağrıldı, CostModal açıldı, onaysız `translate` **çağrılmadı**. "Yok say" kartı kaldırıyor.

### Task A9 (opsiyonel, Q5'e bağlı): Okuyucuda işaret
- **ACTION**: Panel açıkken ya da ayarla, `TranslatedSheet`'e `flags: Set<string>` (blok anahtarları) geçirilir ve render sonrası `[data-block]` öğelerine `rs-term-flag` sınıfı eklenir (ince noktalı alt kenar). Tıklayınca panel ilgili terime gider.
- **GOTCHA**: `htmlCache` revision ile temizleniyor. İşaretler HTML'e gömülmez, istemci tarafında uygulanır. Böylece motor HTML'i durumsuz kalır.
- **VALIDATE**: reader.test.tsx'e bir test.

### Task D: Belgeler
- `app/API_CONTRACT.md`: yeni uç noktalar, `estimate.blocks`, `Translation`'da yeni roller, `total_blocks` birim sayımı notu. `docs/kalite.md` (Türkçe): algoritma, sınırlar, maliyet ilkesi. README belgeler tablosuna bir satır.

---

## Testing Strategy (gerçek AI çağrısı yok; FakeTranslator / MockEngineApi / `--dev-fake-ai`)

### Unit Tests
| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `find_split` gerçek devam | N son paragraf "…from the ground up to be" (nokta yok), N+1 ilk paragraf "cloud native have…" | `JoinedUnit`, `head_count=len(head.sentences)` | |
| `find_split` İçindekiler | "…Fault Tolerance 43" → "Hardware and Software Faults 44" | `None` (büyük harf) | ✓ |
| `find_split` epigraf/aside | head aside, tail aside değil | `None` | ✓ |
| `find_split` dipnotlu sayfa | son blok FOOTNOTE, ondan önceki paragraf yarım | birim bulunur | ✓ |
| `find_split` tail başlık/kod | N+1 ilk blok HEADING/CODE | `None` | ✓ |
| `find_split` tire | head "distrib-", tail "uted systems are…" | merged "distributed systems…" | ✓ |
| `find_split` zincir | N+1 tek paragraf ve o da devam ediyor | yalnız (N, N+1); (N+1, N+2) bağlanmaz | ✓ |
| `split_translation` hizalı | 3+1+2 cümle, head_count=4 | (4 TR, 2 TR, True) | |
| `split_translation` kuyruk tamamen yarım cümle | tail tek cümle (kalan parça) | (hepsi, [], True) | ✓ |
| `split_translation` hizasız | cümle sayısı −1 | (hepsi, [], False) | ✓ |
| plan: birleşik tek item | 2 sayfa PDF, pages [0,1] | 1 batch, 1 item = merged | |
| plan: komşu çekme | pages [0] / [1] | birim yine tam; `plan.pages` değişmez | ✓ |
| plan: eski çift cached | iki satır `unit_hash=None` | `batches==[]`; `rejoin=True` → 1 item | ✓ |
| plan: tek taraf eski | yalnız head satırı | birim planlanır; execute head'i ezer | ✓ |
| execute: kapsam dışı komşu durum | pages [0] | N+1 satırı var, `page_status(N+1)` yok | ✓ |
| execute: durma | usage_limit ilk batch'te | hiçbir yarım çift satırı yazılmaz | ✓ |
| render: sınıflar + boş kuyruk | head/tail satırları | `cont-next`, `cont-prev joined-empty`, TR metni yok | |
| migration 006→007 | eski DB dosyası | kolonlar eklendi, eski satır okunur | ✓ |
| terms: Türkçe ek birleştirme | "çoğaltma/çoğaltmanın/çoğaltmayı" × 5, "replikasyon/replikasyonu" × 3 | 1 issue, 2 varyant (5, 3) | |
| terms: tek varyant | hepsi "çoğaltma" | issue yok | ✓ |
| terms: sözlük uyumsuz | sözlük `leader=lider`, 2 TR "önder" | issue, `affected` = 2 | |
| terms: İngilizce bırakılmış | TR "replication" içeriyor | varyant "(İngilizce bırakılmış)" | ✓ |
| terms: `I/İ` katlama | "İndeks"/"indeks" | aynı imza | ✓ |
| terms: "set"≠"dataset" | `mentions` tam kelime | dataset sayılmaz | ✓ |
| terms: ignore + do_not_translate | terim yok sayılmış | issue yok | ✓ |
| terms: hizasız blok | sentence_aligned=0 | blok bütün çift olarak sayılır | ✓ |
| api: accept AI'sız | POST accept | profil güncel, `usage` satır sayısı aynı | |
| api: targeted estimate | `blocks=[…]` | `operation:"translate"`, calls ≥1, onay olmadan çeviri yok | |
| app: panel → CostModal | mock | `translate` yalnız onaydan sonra | |

### Edge Cases Checklist
- [ ] Çevrilmiş sayfası olmayan kitap (boş panel)
- [ ] 600+ sayfalık kitapta analiz süresi (DDIA varsa `ddia_path` testinde < 3 sn; yoksa skip)
- [ ] Taranmış (metin katmanı yok) komşu sayfa → bağlantı yok
- [ ] Son sayfa (N+1 yok) / ilk sayfa (N-1 yok)
- [ ] Eşzamanlı iş: iş çalışırken accept/estimate (`busy` hata türü, `eng.ai_call()` kilidi)
- [ ] `--force` sayfa N → birleşik satırlar N+1'de de ezilir (belgelenmiş davranış)
- [ ] DeepL/Ollama sağlayıcıları: birleşik item sıradan item, profil desteklemeyenlerde sözlük yok sayılır (`supports_profile`)

---

## Validation Commands

### Static Analysis
```bash
cd engine && uv run ruff check . && uv run ruff format --check . && uv run mypy src
cd app && npm run lint && npm run typecheck
```
EXPECT: Sıfır hata

### Unit Tests
```bash
cd engine && uv run pytest -q tests/test_joins.py tests/test_terms.py tests/test_service.py tests/test_store.py tests/test_html_builder.py tests/test_api_quality.py
cd app && npx vitest run --dir src src/test/consistency.test.tsx src/test/book.test.tsx
```
EXPECT: Hepsi geçer

### Full Test Suite
```bash
cd engine && uv run pytest -q --cov=rosetta_engine     # -m live ASLA çalıştırılmaz
cd app && npm test && npm run e2e                      # e2e: gerçek motor + sahte AI
```
EXPECT: Gerileme yok, kapsam ≥%80

### Database Validation
```bash
cp ~/.local/share/rosetta/rosetta.db /tmp/rosetta-copy.db
cd engine && uv run python -c "from rosetta_engine.store import db; c=db.connect('/tmp/rosetta-copy.db'); db.migrate(c); print(db.current_version(c)); print(c.execute('select count(*), count(unit_hash) from translations').fetchone())"
```
EXPECT: version 7; `(128, 0)`. Eski satırlar korunur. **Gerçek DB'ye değil, kopyaya.**

### Browser Validation
```bash
cd app && npm run dev   # motor: rosetta serve --dev-fake-ai
```
EXPECT: DDIA s.38–39 sahte AI ile çevrilir, s.39 girintisiz başlar. Tutarlılık sekmesi açılır.

### Manual Validation
- [ ] Sahte AI ile s.38 tek başına çevir → s.39'da devam parçası görünür, s.39 "kısmi" durumda
- [ ] Yan yana modunda boş kuyruk "↑ önceki sayfada" gösterir
- [ ] PDF export'ta devam paragrafında boşluk/girinti yok
- [ ] Tutarlılık: "Sözlüğe ekle" sonrası Profil sekmesinde terim görünür, harcama göstergesi (SpendPill) değişmez
- [ ] "Yeniden çevir…" CostModal'ı açar, İptal'de hiçbir şey çalışmaz
- [ ] (Gerçek claude ile doğrulama yalnızca kullanıcının açık onayı ve tutar sınırıyla: tek sayfa çifti, `--max-budget-usd`, ilk çağrıdan sonra ekstrapolasyon kontrolü.)

---

## Acceptance Criteria
- [ ] Bölünmüş paragraf tek item olarak gönderiliyor. Sonuç iki sayfada doğru yerde, devam satırı girintisiz.
- [ ] Mevcut önbellek bozulmuyor. Eski çiftler otomatik yeniden çevrilmiyor.
- [ ] Tutarlılık analizi AI'sız. Sözlüğe ekleme tek tık. Yeniden çeviri yalnız estimate → onay ile.
- [ ] Bütün doğrulama komutları geçiyor. Yeni testler var. Tip/lint hatası yok.
- [ ] API_CONTRACT ve docs güncel.

## Completion Checklist
- [ ] Bütün SQL `store/repo.py`'de; migration `007_…sql`
- [ ] Hata mesajları Türkçe, `not_found/bad_request` deseni
- [ ] `log = logging.getLogger(__name__)` deseni
- [ ] Hiçbir testte gerçek `claude`/DeepL/Ollama yok
- [ ] Sabitler modül düzeyinde (`MIN_OCC`, `STEM_LEN`, `MIN_SHARE`, `MAX_TARGET_BLOCKS`)
- [ ] Gereksiz kapsam yok (NOT Building'e uyuldu)

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Sınır sezgisinin yanlış pozitif vermesi (iki ayrı paragrafı birleştirmek) | Orta | Orta | Küçük harf + aynı aside/family + ilk gövde bloğu şartları; ölçümde İçindekiler/imza elendi; testler |
| Model birleşik item'da cümle sayısını tutturamaması → kuyruk boş, tüm TR baş sayfada | Düşük (mevcut satırların %100'ü hizalı) | Düşük | B-3 geri dönüşü; `sentence_aligned=0` ile işaretli; review modunda görünür |
| Sınırı aşan cümlenin N'de durması, Yan yana modunda N+1 orijinalindeki ilk satırların TR karşılığının N'de olması | Kesin | Düşük | Q1 kararı; "↑ önceki sayfada" notu |
| Sayfa N çevirisinin N+1 satırlarını da ezmesi (`force`, B-5) | Orta | Düşük | Belgelenir; yarım paragraf maliyeti; ileride override tablosu ezilmez kuralı |
| Terim analizinin gürültülü olması (5 harf önek, Dice) | Yüksek | Orta | "Olası" ifadesi, örnekler, Yok say, eşikler; sözlük terimleri kesin modda |
| Aynı anda ProfileEditor kaydı accept'i silmesi | Orta | Orta | A8 GOTCHA: kaydederken birleştir |
| Hedefli planın sayfayı yanlışlıkla "done" yapması | Orta | Yüksek | `targeted` dalı + açık test |
| Maliyet disiplini: komşu parçayı plana çekmek tahmini büyütür | Kesin | Düşük | Tahminde görünür; onaysız hiçbir şey yok |
| Gelecekteki "elle düzeltme" özelliğiyle çakışma | Orta | Orta | Override özelliği eklenince `put_rows(overwrite)` override'lı satırları atlamalı (not) |

## Notes
- Gerçek AI çağrısı bu planın uygulanmasında **gerekmez**. Canlı doğrulama istenirse önce tutar
  onayı alınır: tek çift (s.38–39) yaklaşık 1 çağrı, sonnet + `--effort medium` ile ≈ $0.02–0.05
  (düşünme payı dahil). `--max-budget-usd 0.10` verilir ve ilk çağrıdan sonra durulur.
- `PROMPT_VERSION` değişmez (prompt aynı). Birleşik item sıradan bir paragraf item'ı.
- Uygulama sırası: B1 → B2 → B3 → B4 → B5 → B6 → B7 → (B8) → A1 → A2 → A3 → A4 → A5 → A6 → A7 → A8 → (A9) → D.
  B ve A'nın motor kısmı (A1–A4) paralel yürütülebilir. A5, B5/B6'ya bağlı.
- Confidence: 7/10 (en riskli kısım `execute`'un needed/translated muhasebesi; testler bunu
  sabitlemeli).
