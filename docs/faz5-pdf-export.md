# Faz 5 — PDF dışa aktarma

Çevrilmiş sayfaları tek bir PDF olarak dışa aktarır. **AI çağrısı yapmaz**: yalnızca cache'teki
çevirileri kullanır; çevrilmemiş block'lar orijinal metinle basılır ve uyarı verilir.

## Komut

```bash
uv run rosetta export kitap.pdf                      # çevirisi olan tüm sayfalar, sadece Türkçe
uv run rosetta export kitap.pdf --pages 25-60 --mode bilingual --paper letter
uv run rosetta export kitap.pdf --no-toc-page -o ~/kitap.tr.pdf
```

| Seçenek | Varsayılan | Açıklama |
|---|---|---|
| `--pages` | çevirisi olan tüm sayfalar | 1 tabanlı: `25`, `25-60`, `25,30,59-61` |
| `--mode` | `tr` | `tr`: sadece Türkçe · `bilingual`: her block için EN \| TR iki sütun |
| `--lang`, `--provider`, `--model` | config | Hangi çevirinin kullanılacağı (cache anahtarı) |
| `--paper` | `a4` | `a4` \| `letter` |
| `--toc-page/--no-toc-page` | açık | Başa sayfa numaralı "İçindekiler" sayfası |
| `-o/--out` | `~/.local/share/rosetta/out/<hash>/<kitap>.tr.pdf` (`.en-tr.pdf` iki dilli) | Çıktı yolu |

Çıkış kodu 0 başarı, 1 hata (Chromium yok, çeviri yok, yazdırma hatası).

## Nasıl çalışır

1. Her sayfa `render.html_builder` ile (Faz 1'deki `tr` / `review` görünümü) üretilir; sayfaların
   `<main>` gövdeleri tek bir HTML'de birleştirilir (`export.<mod>.<dil>.html`, çıktı klasöründe).
   Metin akar (reflow); kaynak sayfa sınırları yalnızca küçük "s. 25" etiketiyle gösterilir.
2. Baskı CSS'i (`export/templates/print.css`): orijinal punto korunur (`--scale: 1`, Kural 4),
   kod blokları kırpılmaz/küçülmez, satır kaydırılır; kod, figür ve tablolar sayfa arasında
   bölünmez; başlıklar sonraki paragraftan ayrılmaz; her `h1` (bölüm) yeni sayfada başlar;
   sayfa numarası alt ortada (`@page @bottom-center`).
3. Sistemdeki Chromium ile headless yazdırılır (`--print-to-pdf`, geçici profil dizini).
   Arama sırası: `$ROSETTA_CHROMIUM` → `chromium`, `chromium-browser`, `google-chrome` →
   Playwright önbelleği (`~/.cache/ms-playwright`). Python Playwright bağımlılığı yoktur.
4. **Türkçe yer imleri / İçindekiler:** kitabın gömülü içindekiler tablosu (`doc.get_toc()`)
   dışa aktarılan sayfalardaki başlık block'larıyla eşlenir; başlığın Türkçe çevirisi başlık
   olur (çeviri yoksa orijinal). Kitapta TOC yoksa çıkarılan başlıklar kullanılır.
   Hedef sayfalar iki geçişle bulunur: ilk baskıda İçindekiler sayfasındaki `<a href="#id">`
   bağlantılarını Chromium adlandırılmış hedeflere çevirir; PyMuPDF bunlardan her başlığın
   çıktı sayfasını okur. İkinci baskı İçindekiler'i sayfa numaralarıyla basar (ya da
   `--no-toc-page` ile hiç basmaz ve sayfa kaydırması hesaba katılır). Son olarak yer imleri
   `set_toc` ile PDF'e yazılır.

## Sistem gereksinimi

Chromium (veya Chrome). Arch: `pacman -S chromium` · Debian/Ubuntu: `apt install chromium`.

## Bilinen sınırlar

- Tablolar ve figürler görsel olarak basılır (hücre çevirisi yok, Faz 1 kararı).
- Gömülü TOC'ta olup dışa aktarılan sayfalarda başlığı bulunamayan girdiler sayfa başına bağlanır
  ve orijinal başlıkla görünür.
- Çok büyük aralıklar tek HTML olarak basılır; 650 sayfa için Chromium süresi sınırı 10 dk'dır.
