# Rosetta — Arayüz yeniden tasarımı (spec)

> Durum: analiz + uygulama planı. Kaynak: kullanıcı geri bildirimi (2026-10-16): *"çok kötü UI/UX, modern yap; sadece çeviri odaklı olmuş; çevrilen yeri de sayfa gibi gösterebiliriz"*.
> İncelenen ekranlar: `app/e2e/screenshots/01–09*.png`, `ddia-p{25,30,59,94,115}-{ceviri,split}.png` (1440×900 ve 1600×1000).
> Uygulanan tasarım rehberleri: `ecc:frontend-design-direction`, `ecc:make-interfaces-feel-better`, `high-end-visual-design` (yalnızca okuma uygulamasına uyan kısımları — "editorial luxury" dokusu; ajans-tipi iniş sayfası kalıpları bilinçli olarak alınmadı).

---

## 0. Yön (design direction)

| | |
|---|---|
| **Amaç** | Önce **iyi bir PDF okuyucu**; çeviri ve öğrenme, okumanın üstüne katman olarak gelen araçlar. |
| **Kitle** | Tek kullanıcı, uzun oturumlar (saatlerce teknik kitap). Gözü yormayan, sakin, yoğunluğu düşük arayüz. |
| **Ton** | Sakin, editoryal, "kâğıt üstünde mürekkep". Apple Books / Readwise Reader / Linear seviyesinde cila; dekorasyon yok. |
| **Akılda kalan detay** | **"Aynı sayfanın iki baskısı"**: Orijinal ve Türkçe aynı kâğıt çerçevesinde (aynı oran, kenar boşluğu, sayfa numarası, gölge) görünür; mod değiştirmek kâğıdın "çevrilmesi" gibi hissettirir (kısa çapraz geçiş). Split modunda iki kâğıt yan yana, aynı satır hizasında nefes alır. |
| **Kısıtlar** | Tauri 2 + WebKitGTK (Linux), çevrimdışı (font/ikon paketlenmeli, CDN yok, CSP sıkı), Kural 1–2 kapıları (onaysız AI yok) aynen kalır, mevcut E2E akışları geçmeli. |

---

## 1. Mevcut durum denetimi (ekran ekran)

### Genel (tüm ekranlarda)
1. **Uygulama bir "kontrol paneli" gibi görünüyor, okuyucu gibi değil.** Ekranın ~%40'ı kalıcı krom: solda 260 px İçindekiler, sağda 320 px "Kontrol" paneli, üstte araç çubuğu, altta durum çubuğu. 1440 px genişlikte kitap sayfasına kalan alan ~860 px; split'te her yarı ~430 px → orijinal PDF okunamayacak kadar küçük (`ddia-p59-split.png`: gövde metni ~6 px).
2. **Sağ panel buton yığını**: "Kitabı Analiz Et", "Bu Sayfayı Çevir (1)", "Aralık" alanı, "Bütçe" alanı, "Aralık Çevir", "Tüm Kitabı Çevir", "Dışa aktar" seçici + düğmesi, açıklama metni — hepsi her sayfada, hepsi aynı ağırlıkta, tam genişlik çerçeveli düğmeler. Hiyerarşi yok; birincil eylem (bu sayfayı çevir) yalnızca renkle ayrılıyor. Çeviri dışı hiçbir okuma aracı yok.
3. **Tipografi**: UI fontu Inter benzeri sistem sans, 14–16 px tek boyut; başlıklar ("Çeviri", "Dışa aktar", "Kitap profili") gövdeyle neredeyse aynı ağırlıkta. Sayılar (`/ 673`, `125%`, `Harcama: 8 çağrı · 81.043 tok · $0.40`) tabular değil.
4. **Renk**: tek mavi (#2c5d8f civarı) + bej arka plan + beyaz paneller; derinlik yok, odak/seçili durumlar ağır dolgu bloklar (segmented control'ün aktif öğesi koyu mavi blok). Karanlık tema ekran görüntülerinde test edilmemiş.
5. **İkonografi yok**: "≡", "‹ ›", "– +" metin karakterleri; "PDF Aç" düz metin düğme. Kitap başlığı "book" / "Designing Data-Intensive Applicatio…" kesik ve sıradan.
6. **Durum çubuğu** teknik dil konuşuyor: "Motor bağlı", "Harcama: 8 çağrı · 81.043 tok · $0.40", "PDF hazır: /tmp/rosetta-e2e-…/book.tr.pdf (4 sayfa)" — ham yol, token sayısı; kullanıcıya dönük değil.
7. **Boş durumlar yok**: kitap açık değilken ne görüldüğü tasarlanmamış; kitaplık / son açılanlar yok.

### 01 — Orijinal
- Sayfa beyaz kutu, bej zemin üstünde; gölge yok, kenar yok → kâğıt hissi zayıf. Tek sayfa görünüyor, kaydırınca sonraki sayfa yok (PDF okuyucularında beklenen sürekli kaydırma yok).
- İçindekiler'de sayfa numaraları başlığa yapışık ("Chapter 5. Replication 1"), sağa hizalı değil, tabular değil.

### 02/03/05/06 — Sadece Çeviri & Split (sentetik kitap)
- Çeviri **sayfa değil, sonsuz bir HTML sütunu**: kâğıt çerçevesi yok, sayfa numarası yok, sayfa sınırı yok; başlık 34 px kalın serif, gövde 18 px — orijinalle hiyerarşi oranı tutmuyor (orijinalde 18 pt başlık / 10 pt gövde).
- Split'te sol PDF küçük ve sabit, sağ HTML büyük ve kayıyor → iki taraf "aynı sayfa" gibi değil; senkron kaydırma bu asimetride anlamını yitiriyor.
- Vurgu: tıklanan blok sarı dolgu + turuncu çerçeve (ağır, "hata" gibi).
- Görseller/kodlar sütunda ortalanmış ama ölçek orijinalden kopuk (diyagram çok büyük).

### DDIA p25/p59 — gerçek kitap
- Türkçe başlık "BÖLÜM 1 Veri Sistemleri Mimarisinde Ödünleşimler" iki satıra kırılmış, `text-wrap: balance` yok; orijinaldeki "CHAPTER 1" üst etiketi + büyük başlık ayrımı kaybolmuş.
- Epigraf normal paragrafla aynı genişlikte; italik/girinti yok.
- p59 split: orijinal sayfa ~480 px genişlikte (okunamaz), Türkçe taraf ise sayfa olmadığı için kod bloğu sağdan taşıyor/kesiliyor (`follows.follo…`).

### 04/05 — İşler
- İş kartı: "İş #1 Bitti" + kalın mavi ilerleme çubuğu + "3/3 sayfa · harcanan $0.000". Hangi aralık, ne zaman, hangi model — yok. Duraklat/devam/yeniden dene eylemleri ancak duruma göre beliriyor, kartın içinde hiyerarşi yok.

### 06 — Profil
- Form alanları ham input; "İngilizce/Türkçe" tablo başlıkları ortalanmış, satırlar arasında ritim yok; çipler (SQL ×) ve "ekle + Enter" alanı farklı yükseklikte; "Kaydet" tam genişlik koyu blok.

### 07 — Öğrenme
- Ruby karşılıklar (`replikasyon`) başlıkta kelimenin üstünde değil, **başlığın ortasında** duruyor (konumlama hatası); paragraflarda ruby satır aralığını bozuyor (satırlar arası boşluk düzensiz).
- Görsel kırık ikon + "image" alt metni olarak görünüyor (öğrenme modunda varlık yükleme hatası).

### 08/09 — İstatistik & Açıklama
- İstatistik iki sütunlu ham etiket/değer listesi; görselleştirme yok, seri ("1 gün") önemsiz görünüyor.
- Açıklama penceresi: alıntı cümle girintili düz metin, "Cümle/Çeviri/Yapı/Kelimeler" kalın etiketler; okuma tipografisi yok; "Kapat" sağ altta küçük. Arkadaki öğrenme sayfası koyulaştırılmış ama blur yok.

### Maliyet onay penceresi (CostModal, kodda)
- İşlevsel olarak doğru (odak İptal'de, Escape, kilit), ama görsel olarak yoğun metin; tahmin rakamları vurgusuz, "liste fiyatı eşdeğeri" notu gövdeyle aynı ağırlıkta.

---

## 2. Bilgi mimarisi (yeni)

```
Uygulama
├── Kitaplık (ana ekran)            ← YENİ
│   ├── Son açılanlar (kapak küçük resmi, başlık, ilerleme %, çevrilen sayfa %, son okuma)
│   ├── "PDF aç" (büyük, sürükle-bırak alanı)
│   └── Boş durum: tek cümle + "PDF aç" düğmesi
└── Okuyucu
    ├── Üst çubuk (otomatik gizlenir, fare üstte/klavye ile görünür)
    │   ├── ← Kitaplık · Kitap başlığı (+ bölüm adı, ince)
    │   ├── Görünüm: [Orijinal | Yan yana | Türkçe | Öğrenme]  (segmented, ikonlu, kısayol 1–4)
    │   ├── Sayfa: [ 59 ] / 673   · Yakınlaştırma: −  100%  +  · Sayfaya sığdır
    │   └── [ Çevir ▾ ]  (TEK birincil eylem)   · ⌘K   · Panel ⟷
    ├── Okuma alanı (sürekli dikey kaydırma, sanal liste, kâğıt sayfalar — §3)
    ├── Yan panel (sağdan kayan, varsayılan KAPALI, 360 px, sekmeler)
    │   ├── İçindekiler (ağaç, sağa hizalı tabular sayfa no, okunan/çevrilen işaretleri)
    │   ├── Çeviri işleri (iş kartları, ilerleme, duraklat/devam/yeniden dene, bütçe)
    │   ├── Kelimeler (defter, tekrar, terimler, istatistik — alt sekmeler)
    │   └── Kitap profili (sözlük + çevrilmeyecekler + "Kitabı analiz et")
    ├── Komut paleti (Ctrl+K): tüm eylemler aranabilir (Bu sayfayı çevir, Aralık çevir, Tüm kitabı çevir, Kitabı analiz et, PDF dışa aktar, Profil, Kelime tekrarı, Git: sayfa…, Görünüm…)
    └── Alt bilgi (sabit değil; okuma alanının sağ altında yüzen küçük "hap"):
        ● motor durumu (yalnız sorun varsa görünür) · bu oturumda ≈$0.40 (tıklanınca kullanım ayrıntısı)
```

**"Çevir ▾" menüsü** (split-button): ana kısım = *Bu sayfayı çevir* (sayfa zaten çevrildiyse "Çevrildi ✓" pasif + menüde "Yeniden çevir (--force)"), açılır kısım = *Aralık çevir…* (küçük popover: `120–140`, isteğe bağlı bütçe), *Tüm kitabı çevir…*, ayraç, *Kitabı analiz et…*, *PDF olarak dışa aktar…*. Hepsi mevcut `useConfirmed` → CostModal kapısından geçer (Kural 1–2 değişmez).

**Kaldırılacaklar**: kalıcı sağ "Kontrol" paneli, kalıcı sol İçindekiler sütunu (yan panele taşınır), durum çubuğu (yüzen hapa iner), "AI işlemleri yalnızca butonla…" açıklama metni (kural UI'nin kendisinde zaten görünür: her AI eylemi onay ister).

---

## 3. Sayfa gibi çeviri: `PageSheet`

### 3.1 Kavram
Her PDF sayfası, orijinal sayfa oranında bir **kâğıt** (`PageSheet`) olarak çizilir. Aynı çerçeve dört modda da kullanılır; içerik değişir:

| Mod | Kâğıdın içi |
|---|---|
| Orijinal | PDF.js canvas (+ metin katmanı, seçilebilir) |
| Türkçe | motorun ürettiği reflow HTML (`mode=tr`), orijinal punto ve hiyerarşiyle |
| Yan yana | iki kâğıt yan yana: sol Orijinal, sağ Türkçe; blok hizalı senkron kaydırma |
| Öğrenme | `mode=learn` HTML (İngilizce, bilinmeyen kelimelerde ruby) |

### 3.2 Boyut ve ölçek
- Sayfa boyutu: `GET /api/books/{id}/pages/{n}/blocks` zaten `width`, `height` (pt) döndürüyor. Kitap açılırken tüm sayfalar için bunu tek tek çekmek yavaş → **yeni uç nokta** `GET /api/books/{id}/pages` → `[{page, width, height, translated: bool, has_text_layer}]` (PyMuPDF `page.rect`, hızlı; çeviri durumu `page_status`'tan).
- Ekrandaki genişlik: `sheetWidthPx = width_pt × zoom × (96/72)`; "sayfaya sığdır" = kullanılabilir genişliğe göre zoom. Yan yana modda iki kâğıt eşit ölçekte, aralarında 24 px.
- **Kural 4 (font küçültme yok)**: Türkçe kâğıdın **genişliği** orijinalle aynı, **yüksekliği en az** orijinal oran kadar (`min-height = height × scale`), metin uzarsa kâğıt aşağı uzar (taşmaz, küçülmez). Uzayan kâğıtlarda alt kenarda ince "devam" gölgesi yok — kâğıt sadece uzun; yan yana modda sol kâğıt üstte hizalı kalır, alttaki fark boş kâğıt tonu.
- İç kenar boşlukları: orijinal içerik kutusundan türetilir (blokların bbox birleşimi → sol/üst/sağ marj, pt); bilinmiyorsa %11 yan, %9 üst/alt. HTML'deki `font-size: calc(var(--scale) * Npt)` için `--scale = zoom × 96/72` kâğıt elemanına verilir → orijinal punto oranı korunur.
- Sayfa numarası kâğıdın altında, ortada, 9 pt UI fontu, ikincil renk (furniture bloğu render edilmiyor; numarayı uygulama çizer).

### 3.3 Sürekli kaydırma + sanallaştırma
- `@tanstack/react-virtual` ile dikey liste; her öğe bir kâğıt (tahmini yükseklik = oranlı yükseklik; Türkçe kâğıt ölçüldükten sonra `measureElement`). Görünür ±2 sayfa render edilir; PDF.js `page.cleanup()` ve canvas'lar görünmeyenlerde serbest bırakılır.
- Geçerli sayfa = görünüm alanının üst üçte birini kesen kâğıt; üst çubuktaki sayfa alanı ve URL/`state` güncellenir; sayfa alanına yazmak/İçindekiler'e tıklamak `scrollToIndex` ile gider.
- HTML parçaları sayfa başına önbelleklenir (`revision` değişene kadar), görünür olunca çekilir (kitap açılışında toplu istek yok).

### 3.4 Yan yana senkronu
- Sayfa düzeyi: iki sütun aynı sanal listeyi paylaşır (satır = sayfa çifti, satır yüksekliği = iki kâğıttan uzunu) → sayfalar her zaman hizalı.
- Sayfa içi: blok tıklanınca karşı taraftaki blok vurgulanır; vurgu = 2 px sol kenar çizgisi + %8 aksan dolgusu (sarı/turuncu çerçeve yerine), 1.2 sn sonra söner. Cümle hover'ı mevcut `data-s` ile.

### 3.5 Çevrilmemiş sayfa durumu (kâğıdın içinde)
Türkçe/yan yana modda çevirisi olmayan kâğıt boş bırakılmaz; ortada sakin bir kart:
```
        Bu sayfa henüz çevrilmedi
   12 paragraf · tahmini ≈ $0.02 · ~10 sn
        [ Bu sayfayı çevir ]   Aralık çevir…
```
- Rakamlar gösterim amaçlı **yerel tahmin** değildir; düğmeye basınca mevcut akış: `estimate` → CostModal → `Onayla` → çalıştır. Karttaki "≈ $0.02" için ucuz uç nokta yoksa satır gösterilmez (bkz. §6 `estimate_hint`, opsiyonel; AI çağrısı yapmaz).
- Kod/görsel ağırlıklı (çevrilecek blok yok) sayfa: "Bu sayfada çevrilecek metin yok" + orijinalin kırpılmış hali (kâğıt yine dolu görünür: Türkçe HTML zaten kod/görseli gösteriyor).
- Taranmış sayfa: "Bu sayfada metin katmanı yok (taranmış). Çeviri desteklenmiyor." + orijinal görüntü.
- Yükleniyor: kâğıt içinde iskelet satırlar (shimmer yok, statik %6 ton bloklar).

---

## 4. Tasarım sistemi

### 4.1 Renk token'ları (`app/src/styles/tokens.css`, `:root` + `[data-theme=dark]` + `prefers-color-scheme`)
| Token | Açık | Koyu | Kullanım |
|---|---|---|---|
| `--canvas` | `#F4F1EA` (sıcak kâğıt-gri) | `#141311` | okuma alanı zemini |
| `--sheet` | `#FFFDF8` | `#1D1B18` | kâğıt |
| `--sheet-edge` | `rgba(60,45,20,.10)` | `rgba(255,255,255,.07)` | kâğıt hairline |
| `--ink` | `#1E1B16` | `#ECE7DD` | birincil metin |
| `--ink-2` | `#5E574B` | `#A79F92` | ikincil |
| `--ink-3` | `#8F8778` | `#7C7569` | üçüncül / sayfa no |
| `--surface` | `rgba(255,253,248,.82)` + blur | `rgba(29,27,24,.80)` + blur | yüzen krom (üst çubuk, panel, hap) |
| `--line` | `rgba(30,27,22,.08)` | `rgba(236,231,221,.08)` | ayraçlar |
| `--accent` | `#B4532A` (pas/terrakota) | `#E0875C` | birincil eylem, seçili durum, ruby |
| `--accent-soft` | `rgba(180,83,42,.10)` | `rgba(224,135,92,.14)` | vurgu dolguları |
| `--sage` | `#5E7A63` | `#8FB096` | başarı / "çevrildi" |
| `--amber` | `#B7862B` | `#D8AE58` | uyarı / duraklatıldı |
| `--danger` | `#B3412F` | `#E07767` | hata |
| `--code-bg` | `#F1ECE2` | `#24211D` | kod blokları |

Mavi tamamen bırakılır (tek renk ailesi + mavi butonlar "şablon" hissinin ana kaynağı). Kâğıt tonu sıcak; aksan tek, az kullanılır.

### 4.2 Tipografi (çevrimdışı paketlenir — `@fontsource-variable/*`, Vite ile; CSP değişmez)
- **UI**: `Geist` (variable, 400/500/600) — Inter yerine; tabular rakamlar `font-variant-numeric: tabular-nums` (sayfa no, zoom, $).
- **Okuma (Türkçe sayfa ve açıklama)**: `Literata` (variable, optik boyut ekseni; Türkçe karakter tam; ekran okuması için tasarlandı). Kitabın orijinal serif/sans sınıfı korunur: `ff-serif → Literata`, `ff-sans → Geist`, `ff-mono → Geist Mono`.
- **Ölçek (UI)**: 11 / 12.5 / 13.5 (gövde) / 15 / 18 / 24 / 32 px; satır yüksekliği UI 1.4, okuma 1.55; başlıklarda `text-wrap: balance`, kısa metinlerde `pretty`.
- Bölüm başlığı (h1) özel stil: üstte küçük harf aralıklı "BÖLÜM 1" etiketi (11 px, `letter-spacing: .14em`, `--ink-3`) + altında Literata 600 büyük başlık — orijinaldeki "CHAPTER 1" düzenini taklit eder (motor h1 metnini "BÖLÜM N" + başlık olarak bölmeli değil; UI `^(BÖLÜM|CHAPTER)\s+\d+\s+` önekini span'e ayırır).
- Epigraf (`aside` paragraf + kısa): italik, %80 genişlik, sağa yaslı yazar satırı.

### 4.3 Boşluk, köşe, gölge, hareket
- Boşluk ölçeği: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64.
- Köşe: düğme 8, giriş 8, popover/menü 12, panel 16, dialog 20 (iç içe yüzeylerde dış = iç + padding).
- Kâğıt gölgesi (iki katman): `0 1px 2px rgba(40,30,15,.06), 0 8px 24px -8px rgba(40,30,15,.12)` + `--sheet-edge` hairline; koyu temada gölge yerine 1 px `--sheet-edge` + hafif üst highlight.
- Yüzen krom: `--surface` + `backdrop-filter: blur(16px) saturate(1.2)` (yalnızca sabit öğelerde), hairline `--line`.
- Hareket: `--ease: cubic-bezier(.32,.72,0,1)`; giriş 220 ms (opacity + 6 px translateY), çıkış 140 ms; mod geçişi kâğıt içeriğinde 180 ms çapraz geçiş; düğme basışı `scale(.97)`; `transition: all` yasak; `prefers-reduced-motion` ile tüm hareket kapanır.
- Üst çubuk otomatik gizlenme: kaydırma aşağı → 200 ms'de yukarı kayar; fare üstteki 48 px'e gelince / yukarı kaydırma / herhangi bir kısayol → geri gelir. Ayarlardan "her zaman göster".

### 4.4 Bileşenler
- **Button**: `primary` (aksan dolgu, beyaz metin), `secondary` (sheet zemin + hairline), `ghost` (yalnız hover dolgusu), `icon` (36×36, hit alanı 40). Yükseklik 32/36. Pasif durumda tooltip ile nedeni.
- **SegmentedControl** (görünüm modu): kap `--line` zemin, aktif öğe kâğıt rengi "kayan çip" (transform ile kayar), ikon + etiket (dar pencerede yalnız ikon).
- **SplitButton** (Çevir ▾), **Popover**, **Menu**, **Tooltip**, **Tabs** (yan panel), **Dialog**, **Toast**, **Progress** (ince 4 px, aksan; belirsiz durum için hareketli şerit), **Skeleton**, **EmptyState**, **Kbd** (kısayol rozetleri).
- **CostModal (yeniden tasarım, kurallar aynı)**:
  ```
  ┌─────────────────────────────────────────────┐
  │  Bu sayfayı çevir                           │  ← işlem adı (başlık)
  │  Sayfa 59 · 9 paragraf · Sonnet             │  ← kapsam (ikincil)
  │                                             │
  │   ≈ $0.02          1 çağrı   ~5.6k token    │  ← büyük rakam + iki küçük metrik (tabular)
  │   liste fiyatı eşdeğeri — Max planında      │
  │   faturalanmaz                              │
  │                                             │
  │  ⚠ uyarılar (varsa, amber kutu)             │
  │  ⓘ düşünme: medium, ±%40 (katlanır ayrıntı) │
  │                                             │
  │                  [ İptal ]  [ Onayla ↵ ]    │  ← odak İptal'de; Enter=İptal; Onayla açık tıklama
  └─────────────────────────────────────────────┘
  ```
  Mevcut davranışlar korunur: varsayılan odak İptal, odak tuzağı, Escape=iptal (çalışırken yok sayılır), çalışırken "Çevriliyor…" ilerleme + düğmeler pasif, istek kilidi. Cache tamamen karşılıyorsa modal yerine "Tümü önbellekte — 0 çağrı" toast + doğrudan gösterim (mevcut "0 çağrı" yolu).
- **LookupPopover**: kelimeye yapışık, 320 px; lemma + TR karşılıklar (büyük) + EN tanım (ikincil, 2 satır, "daha fazla"); eylemler: "Bilmiyorum olarak kaydet" (primary), "Biliyorum", ikon "Bunu açıkla" (AI → onaylı).
- **Açıklama paneli**: dialog yerine sağdan kayan geniş panel (480 px), Literata ile; bölümler kart değil, başlık + ince ayraç.
- **Toasts**: sağ alt, 4 sn, tek satır insan dili ("Sayfa 59 çevrildi", "PDF hazır — Klasörde göster"); ham yol gösterilmez (tıklanınca `open` ile klasör açılır).

### 4.5 İkonlar
- `@phosphor-icons/react` — **Light/Regular** ağırlık, 18 px (UI), 16 px (yoğun alanlar). Lucide'ın kalın çizgisi yerine ince, editoryal his. Kullanılacak ikonlar: `BookOpen`, `Books` (kitaplık), `Translate`, `Columns` (yan yana), `FileText` (orijinal), `GraduationCap` (öğrenme), `MagnifyingGlassPlus/Minus`, `ArrowsOutLineHorizontal` (sığdır), `ListBullets` (içindekiler), `Queue`/`Stack` (işler), `BookmarkSimple`, `Cards` (tekrar), `SlidersHorizontal` (profil), `Export`, `Command`, `Pause`, `Play`, `ArrowClockwise`, `Warning`, `Check`, `X`.

### 4.6 Klavye kısayolları
| Kısayol | Eylem |
|---|---|
| `Ctrl+K` | Komut paleti |
| `1` `2` `3` `4` | Orijinal / Yan yana / Türkçe / Öğrenme |
| `←` `→` / `PgUp` `PgDn` / `J` `K` | Önceki / sonraki sayfa |
| `G` | Sayfaya git (sayfa alanına odak) |
| `Ctrl+=` `Ctrl+-` `Ctrl+0` | Yakınlaştır / uzaklaştır / sığdır |
| `T` | Bu sayfayı çevir (onay penceresi açar — çalıştırmaz) |
| `\` | Yan paneli aç/kapat |
| `Ctrl+O` | PDF aç |
| `Esc` | Popover / panel / palet kapat |

---

## 5. Kütüphaneler

**Ekle** (hafif, çevrimdışı):
- `@phosphor-icons/react` — ikonlar.
- `@radix-ui/react-dialog`, `react-popover`, `react-dropdown-menu`, `react-tabs`, `react-tooltip`, `react-toggle-group` — erişilebilir başsız ilkel öğeler (odak tuzağı, Escape, `inert` hazır). CostModal'ın mevcut güvenlik davranışları Radix Dialog üstüne taşınır, testleri korunur.
- `cmdk` — komut paleti.
- `@tanstack/react-virtual` — sayfa sanallaştırma.
- `@fontsource-variable/geist`, `@fontsource-variable/geist-mono`, `@fontsource-variable/literata` — fontlar (yerel paket).
- Stil: mevcut düz CSS korunur, **CSS Modules + `tokens.css`** (Tailwind eklenmez; tek kişilik proje, mevcut CSS'i dönüştürmek daha ucuz).

**Kaldır / değiştir**: `app.css` içindeki ad-hoc renkler ve tek dosyalık 570 satır → `tokens.css` + bileşen başına `*.module.css`; metin karakterli ikonlar (≡ ‹ › – +); `TopBar`/`ControlPanel` bileşenleri (yerine `ReaderToolbar`, `TranslateMenu`, `SidePanel`).

---

## 6. Motor/API eklemeleri (Rosetta engine)

| Uç nokta / değişiklik | Neden | Ayrıntı |
|---|---|---|
| `GET /api/books` | Kitaplık ekranı | `[{id, title, page_count, file_path, file_exists, last_opened_at, last_page, translated_pages, cover_url}]` sıralı `last_opened_at desc`. `books` tablosuna `last_opened_at`, `last_page` (migration 007). |
| `PUT /api/books/{id}/progress` | Kaldığı yeri hatırlama | `{page}` → `last_page`, `last_opened_at`. AI yok. |
| `GET /api/books/{id}/cover?w=240` | Kapak küçük resmi | sayfa 1 (veya ilk metinli/görselli sayfa) `get_pixmap` PNG, önbellekli dosya, varlık yetkilendirmesiyle aynı (Bearer). |
| `GET /api/books/{id}/pages` | Sanal liste boyutları | `[{page, width, height, has_text_layer, translated, translatable_blocks}]` — `page.rect` + `page_status`/cache sayımı; çıkarma yapmaz (çıkarılmamış sayfa için `translatable_blocks: null`). |
| `GET /api/books/{id}/pages/{n}/html` yanıtına `content_box` | Kâğıt iç marjları | `{x0,y0,x1,y1}` pt (furniture hariç blokların birleşimi). |
| `?pages=59-61` toplu HTML (opsiyonel) | Kaydırma sırasında daha az istek | `[{page, html, ...}]`; mevcut tekil uç nokta kalır. |
| `GET /api/books/{id}/pages/{n}/estimate_hint` (opsiyonel) | Çevrilmemiş kâğıttaki "≈ $0.02" | Mevcut `plan()` ile tahmin — **onay belirteci üretmez**, AI çağrısı yok; yalnızca gösterim. Çevir düğmesi yine normal `estimate` → onay akışını kullanır. |
| Render: furniture (sayfa no) HTML'de yok kalır | Uygulama kendi sayfa numarasını çizer | değişiklik yok |
| Render: `h1` için `data-label` | "BÖLÜM 1" etiketini ayırmak | heading bloğu TOC'tan "CHAPTER N" önekli ise HTML'de `<span class="h-label">` (opsiyonel; yoksa UI regex ile ayırır). |
| Öğrenme modu varlık yolu | 07'deki kırık görsel | `mode=learn` HTML'deki `assets/` görselleri de `data-asset` yolundan yüklenmeli (uygulama tarafı sanitizer hook'u learn modunda da çalışmalı — hata ayıkla). |
| Ruby konumlama | 07'deki başlık ruby hatası | `<ruby>` yalnız kelimeyi sarmalı; başlıklarda `ruby-position: over`, `rt` 0.5em; satır aralığı ruby için `line-height` telafisi (CSS). |

`app/API_CONTRACT.md` ve `docs/faz3-api.md` bu eklemelerle güncellenir; hepsi AI'sız ve token korumalı.

---

## 7. Uygulama planı (paralel iş akışları)

### WS-A — Motor/API (sahibi: `engine/**`, `docs/faz3-api.md`, `app/API_CONTRACT.md`'nin yeni bölümleri)
1. Migration 007 (`books.last_opened_at`, `last_page`), `GET /api/books`, `PUT /progress`, `GET /cover`, `GET /pages`, `content_box`, opsiyonel `?pages=` ve `estimate_hint` (onay belirteci üretmediği testle kilitli).
2. Render: `h-label` span (opsiyonel), learn modunda ruby yalnız kelime sarmalı + CSS düzeltmesi.
3. Testler (pytest), mypy/ruff temiz. **Önce** sözleşmeyi `app/API_CONTRACT.md`'ye "v2 eklemeleri" bölümü olarak yazar (WS-B mock'u buna göre yazar).

### WS-B — Okuyucu çekirdeği (sahibi: `app/src/views/**`, `app/src/reader/**` (yeni), `app/src/lib/syncScroll.ts`, `app/src/api/{types,engine,http,mock}.ts`)
1. `PageSheet`, `ReaderCanvas` (sanal liste), `OriginalSheetContent` (PDF.js, görünürlük bazlı render/cleanup), `TranslatedSheetContent` (HTML önbelleği), `SplitRow`, çevrilmemiş/taranmış/yükleniyor durumları.
2. Zoom/sığdır, geçerli sayfa takibi, `scrollToPage`, ilerleme kaydı (`PUT /progress`, 2 sn debounce).
3. Yan yana senkron (satır = sayfa çifti) + blok vurgusu yeniden tasarımı; öğrenme modu kelime tıklama/ruby.
4. Mock API'yi v2 uç noktalarıyla genişlet.

### WS-C — Kabuk, tasarım sistemi, paneller (sahibi: `app/src/styles/**`, `app/src/ui/**` (yeni bileşen kiti), `app/src/components/**`, `app/src/App.tsx`, `app/src/library/**` (yeni), `app/package.json`)
1. `tokens.css`, fontlar, ikonlar, Radix/cmdk tabanlı bileşen kiti (`ui/`), açık/koyu tema + sistem teması.
2. Kitaplık ekranı (son açılanlar, kapaklar, sürükle-bırak, boş durum).
3. Okuyucu kromu: otomatik gizlenen üst çubuk, segmented görünüm, sayfa/zoom, **Çevir ▾** split-button, komut paleti, yüzen durum/harcama hapı, toast'lar.
4. Yan panel (İçindekiler, İşler, Kelimeler, Profil) — mevcut JobsPanel/LearnPanel/ProfileEditor mantığı korunur, yalnız sunum yenilenir.
5. CostModal + LookupPopover + açıklama paneli yeniden tasarımı (güvenlik davranışları ve mevcut testleri aynen geçmeli).

**Sözleşmeler**: WS-B, WS-C'nin `ui/` kitinden yalnız `Button`, `Skeleton`, `EmptyState` kullanır (WS-C bunları ilk gün yayınlar); WS-C okuma alanına `<ReaderCanvas mode zoom onPageChange />` olarak WS-B bileşenini yerleştirir. Ortak durum `app/src/state.ts`'te (sahibi WS-C; WS-B yalnız `currentPage`, `zoom`, `mode` okur/yazar).

### Kabul kriterleri
1. **Ekran görüntüleri** (E2E'ye eklenir, `e2e/screenshots/v2/`): kitaplık (boş + dolu), 4 görünüm × {açık, koyu} × {1280×800, 1920×1080}, çevrilmemiş kâğıt kartı, CostModal, LookupPopover, yan panel 4 sekme, komut paleti, açıklama paneli. Her biri gözle kontrol edilir; DDIA p25/30/59/94/115 yan yana modda orijinal metin 1280 px genişlikte **okunabilir** (gövde ≥ 11 px ekranda).
2. Türkçe kâğıt genişliği orijinal kâğıtla eşit (±1 px); metin uzarsa kâğıt uzar, punto küçülmez (Kural 4) — test: uzun çeviri fixture'ı.
3. Sürekli kaydırma: 673 sayfalık DDIA'da ilk açılış < 1.5 sn, kaydırma 60 fps'e yakın (DOM'da en fazla ~7 kâğıt).
4. Mevcut E2E akışlarının tamamı (11 + ddia) yeni seçicilerle geçer; Kural 1–2: her AI eylemi CostModal'dan geçer, İptal → 0 çağrı, onaysız yol yok (mevcut testler korunur + Çevir ▾ menüsünün her öğesi için test).
5. Erişilebilirlik: tüm etkileşimli öğeler klavye ile ulaşılabilir, odak halkası görünür (`--accent` 2 px offset 2), kontrast AA (metin), `prefers-reduced-motion` saygısı.
6. `tsc`, ESLint, Vitest, `cargo test`, pytest, mypy, ruff temiz; paketler (`packaging/build-app.sh`) yeniden üretilir.
