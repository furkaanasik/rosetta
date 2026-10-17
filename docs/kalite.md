# Kalite paketi — sayfa sonu paragraf devamı ve terim tutarlılığı

İki özellik, ikisi de çevirinin kalitesi için: sayfa sonunda bölünen paragraflar tek parça gibi
çevrilir, kitap boyunca aynı terimin farklı karşılıklarla çevrildiği yerler bulunur. **Hiçbiri
kendiliğinden AI çağırmaz.** Yeniden çeviri her zaman tahmin → onay akışıyla yapılır.

## Sayfa sonu paragraf devamı

PDF'te bir paragraf sayfa N'de yarım kalıp sayfa N+1'de devam edebilir. Eskiden iki parça iki
ayrı öğe olarak çevriliyordu; model yarım cümleyi tahmin etmek zorunda kalıyordu. Artık bu iki
parça **tek öğe** olarak gönderilir.

**Tespit** (`translate/joins.py`, saklanan bloklardan, yeniden çıkarma gerekmez):
- Baş: sayfa N'nin son gövde bloğu (dipnot ve üst/alt bilgi atlanır). Paragraf olmalı ve cümle
  sonu işaretiyle (`.` `:` `!` `?`) bitmemelidir.
- Kuyruk: sayfa N+1'in ilk gövde bloğu. Paragraf olmalı, aynı türde olmalı (kutu/epigraf, yazı
  ailesi) ve **küçük harfle** başlamalıdır (ya da baş tireyle bitmelidir). Bu filtre
  İçindekiler satırlarını ve epigraf imzalarını eler.
- Yalnızca çiftler birleştirilir. Kuyruk aynı zamanda bir sonraki sayfa sonunun başıysa zincir
  kurulmaz. Karar yalnızca N-1, N ve N+1 sayfalarına bakar, bu yüzden hangi aralığı
  çevirirseniz çevirin sonuç aynıdır.
- Satır sonu tiresi (`distrib-` + `uted`) satır birleştirmeyle aynı kuralla kaldırılır.

**Çeviri ve saklama:**
- İstenen sayfaya komşu yarı plana çekilir (çıkarma ücretsizdir) ve tahmine dahil edilir. Komşu
  sayfanın durumu "bitti" yapılmaz; o sayfa "kısmi" görünür.
- Sonuç cümle hizasına göre iki satıra bölünür. **Sınırı aşan cümle N'de kalır**, N+1 bir
  sonraki tam cümleyle başlar. Kuyruk tamamen o cümleden oluşuyorsa N+1'in satırı boştur.
- Model cümle sayısını tutturamazsa çevirinin tamamı N'ye yazılır, kuyruk boş kalır ve satır
  `sentence_aligned=0` ile işaretlenir.
- Satırlar `unit_hash` ve `unit_role` (`head`/`tail`) taşır (migration 007). Önceden iki parçası
  ayrı ayrı çevrilmiş çiftler önbellekte sayılır ve **otomatik yeniden çevrilmez**. Yalnız bir
  yarısı çevrilmişse birim yeniden çevrilir ve o yarının satırı ezilir. Bu da her zaman
  tahmin → onay akışıyla olur.
- `--force` ile sayfa N çevrilirse birimin N+1'deki satırı da yenilenir.

**Görünüm:** Türkçe sayfada devam satırı girintisiz başlar (`cont-prev`), boş kuyruk gizlenir
(`joined-empty`). Yan yana (inceleme) sayfasında boş kuyruğun TR hücresinde "↑ önceki sayfada"
yazar. PDF dışa aktarım aynı kuralları kullanır.

## Terim tutarlılığı denetimi

Yan panel ▸ **Tutarlılık** sekmesi ya da `rosetta consistency kitap.pdf` komutu. Kitabın
önbellekteki çevirileri **yerel olarak** taranır. AI çağrılmaz, `usage` tablosuna yazılmaz,
önbelleğe dokunulmaz.

**Algoritma** (`quality/terms.py`):
1. Çeviriler cümle çiftlerine ayrılır: hizalı satırlar cümle cümle, hizasız satırlar paragraf
   bütün olarak. Sayfa sonu birimleri tek paragraf olarak yeniden birleştirilir.
2. Aday terimler: sözlükteki terimlerin hepsi, artı metinden çıkarılan 1-3 kelimelik ifadeler.
   Çıkarılan ifadeler en az 3 cümlede geçmeli, uçlarında İngilizce dolgu kelimesi olmamalı ve
   tek kelimeyse en az 4 harf olmalıdır. Terim eşleşmesi tam kelimedir ("set" ≠ "dataset").
3. Türkçe kelimeler Türkçeye uygun küçük harfe çevrilir (`I→ı`, `İ→i`) ve ilk 5 harflik bir
   imzaya indirgenir. Böylece ekli biçimler birlikte sayılır ("çoğaltma", "çoğaltmanın" →
   "çoğal"). Türkçe dolgu kelimeleri ("bir", "bu", "ve" …) imza sayılmaz.
4. Terimle en güçlü ilişkili imzalar (Dice katsayısı, tekrarlı paragraflar bir kez sayılır)
   karşılık adaylarıdır. Her geçiş, cümlesinde bulunan en güçlü imzaya atanır. Türkçe cümlede
   İngilizce terim aynen geçiyorsa geçiş "(İngilizce bırakılmış)" sayılır.
5. Aynı kelimenin biçimleri tek karşılıkta birleşir: boşluk farkı ("veri tabanı" ~
   "veritabanı"), uzun ortak kök, ünsüz yumuşaması ("örnek" ~ "örneği"), niteleyici
   ("bulut sağlayıcısı" ~ "sağlayıcı"), kısa kökte ünlü eki ("yükü" ~ "yüke").
6. Payı en az %15 ve sayısı en az 2 olan iki ya da daha fazla karşılık varsa **olası
   tutarsızlık** raporlanır. Sözlük terimlerinde sözlükteki karşılığı kullanmayan paragraflar
   "uyumsuz" olarak listelenir. Metinden çıkarılan terimler daha sıkı eşiklerle değerlendirilir:
   en az 8 farklı cümle ve güçlü ilişki gerekir. Küçük önbellekte bağlam kelimeleri karşılık
   gibi görünmesin diye.

**Sınırlar:** 5 harflik imza farklı kelimeleri birleştirebilir ("işlem"/"işlemci"), bu yüzden
sonuçlar "olası" diye sunulur ve örneklerle gösterilir. Az çevrilmiş kitapta keşif sonuçları
seyrek olur, çevrildikçe artar. Analiz varsayılan sağlayıcı/modelin satırlarını kullanır.

**Eylemler:**
- **Sözlüğe ekle**: tek tık, terimi profil sözlüğüne yazar. Profil kaydı gibi ücretsizdir ve
  mevcut çeviriler değişmez. Sonraki çeviriler bu karşılığı kullanır. Profil düzenleyicide
  kaydedilmemiş değişiklik varken eklenen terim, düzenleyici kaydedilince silinmez.
- **Uyumsuz N paragrafı yeniden çevir…**: yalnız o paragraflar için hedefli bir plan yapılır
  (`/estimate` → `blocks`, tek seferde en fazla 200 blok). CostModal'da onaylanmadan hiçbir şey
  çalışmaz. Hedefli çeviri satırları yeniler ama **sayfa durumunu değiştirmez**.
- **Yok say**: terimi bu kitap ve dil için rapordan çıkarır (`term_ignores` tablosu). Panelin
  altından geri alınabilir.

```bash
uv run rosetta consistency kitap.pdf                         # rapor (AI yok)
uv run rosetta consistency kitap.pdf --accept "leader=lider" # sözlüğe ekle (AI yok)
uv run rosetta consistency kitap.pdf --ignore "figure"
uv run rosetta translate kitap.pdf --pages 41-44 --force     # CLI'da yeniden çeviri (tahmin + onay)
```
