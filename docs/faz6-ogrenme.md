# Faz 6 — İngilizce öğrenme çekirdeği (AI'sız)

Bu fazdaki her şey lokal ve bedavadır; hiçbir komut AI çağrısı yapmaz.

## Offline sözlük

| | |
|---|---|
| Dosya | `~/.local/share/rosetta/dictionary.db` (`ROSETTA_DATA_DIR` ile değişir), kitap veritabanından ayrı |
| Kaynak | İngilizce Wiktionary, [kaikki.org](https://kaikki.org/) (wiktextract) İngilizce çıkarımı: `kaikki.org-dictionary-English.jsonl.gz` (~520 MB) |
| Kurulum | `uv run rosetta dict build` — dosya akış halinde indirilir ve süzülür, ham döküm diske yazılmaz |
| Ölçüm (2026-10-16) | ~180 sn, **662 319** İngilizce madde, **46 788** Türkçe karşılık, 1,39 M çekim bağlantısı, **157 MB** |
| Bilgi | `uv run rosetta dict info` (kaynak, lisans, oluşturulma tarihi) |

Tablolar: `entries(lemma, pos, definitions)` (her madde için en fazla 4 İngilizce tanım),
`translations(lemma, pos, tr, sense)` (sadece `lang_code = "tr"`), `forms(form, lemma)`
(çekimli hal → kök; `replicated → replicate`), `meta` (kaynak, lisans, tarih). Özel isimler
(`pos = name`) ve sembol/karakter maddeleri alınmaz.

### Lisans ve atıf (zorunlu)

Wiktionary metni **CC BY-SA 4.0** ve **GFDL** ile lisanslıdır. Bu nedenle:

- `dictionary.db` repoya **eklenmez**, kullanıcı makinesinde `rosetta dict build` ile üretilir.
- Sözlükten gösterilen içerikte kaynak belirtilmelidir: "Kaynak: Wiktionary (kaikki.org),
  CC BY-SA 4.0". Atıf metni `meta.license` alanında tutulur; arayüz (Faz 3) bunu sözlük
  panelinde göstermelidir.
- Sözlük dağıtılırsa (ör. paketle birlikte) CC BY-SA "aynı lisansla paylaş" şartı geçerlidir.

Lemmatization: [simplemma](https://github.com/adbar/simplemma) (MIT) — sözlükte bulunamayan
kelimeler için yedek.

## Kelimeye tıkla → anlam

`rosetta lookup WORD` — sıra: tam eşleşme (ifade olabilir: `consumer group`), çekim tablosu,
simplemma kökü. Türkçe karşılığı olan aday önce gelir (`went → go`, arkaik isim `went` değil).

## Kelime defteri

- Bir kelime defterde **lemma** ile tek kayıttır; ilk bağlam (cümle, kitap, sayfa, block
  `ord` ve `text_hash`) saklanır.
- `rosetta vocab add WORD [--book PDF --page N] [--sentence "…"] [--meaning "…"] [--known]` —
  anlam sırası: `--meaning` → sözlükteki Türkçe → kitap profilinin sözlüğü (ör. polling → yoklama);
  `--page` verilirse cümle sayfadan otomatik bulunur (kod/görsel block'lar atlanır).
- `rosetta vocab list [--book PDF] [--search X] [--since YYYY-MM-DD]`
- `rosetta vocab mark WORD --unknown|--known` — kitabın tamamında etkili.

## Flashcard (FSRS)

`fsrs` 6.x (`Scheduler(enable_fuzzing=False)`); kayıtla birlikte kart oluşur (hemen sırası gelir).

- Ön yüz: kitaptaki cümle, kelime boşluklu (`_____`).
- Arka yüz: kelime + anlam + cümlenin Türkçesi (cache'te herhangi bir sağlayıcı/model ile
  çevrilmişse; cümle eşleşmesi `sentence_aligned` ise cümle, değilse paragraf).
- `rosetta review [-n 20]` — Again / Hard / Good / Easy (1–4, "tekrar/zor/iyi/kolay" de olur).
  Terminal dışında sırası gelen kartları listeler. "Biliyorum" işaretli kelimeler tekrar
  kuyruğuna girmez (yeniden "bilmiyorum" denirse kart kaldığı yerden döner).
- Boş kelime kaydedilmez; aynı lemma eşzamanlı eklenirse tek satır kalır (`ON CONFLICT`).
  Aramada `%` ve `_` harfiyen aranır.

Tablolar (`004_learning.sql`): `vocab`, `reviews` (FSRS kart durumu + `card_json`),
`review_log`.

## Öğrenme görünümü (4. mod)

`rosetta learn-html PDF --pages 41-44` → `pNNN.learn.html`: orijinal İngilizce metin aynı
reflow düzeninde; her kelime tıklanabilir (`data-w` kelime, `data-l` lemma; tıklama
`rosetta:word` olayı yayar — Faz 3 arayüzü sözlük panelini bununla açar); "bilmiyorum"
işaretli lemmaların üstünde `<ruby>` ile Türkçe karşılık görünür. Kod block'ları ve satır
içi kod kelime kelime işlenmez. Tüm metin önce escape edilir (`learn_markup`).

Cümle eşleme: EN|TR (`review.html`) görünümünde cümlenin üstüne gelmek karşılığını
vurgular, **tıklamak** eşleşmeyi sabitler (`data-s` cümle indeksleri, ek maliyet yok).

## Teknik terim listesi

`rosetta terms PDF [--add-all]` — kitap profilindeki sözlük (Faz 2) + offline sözlük bilgisi;
`--add-all` profildeki Türkçe karşılığı anlam olarak kullanarak deftere ekler, bağlam cümlesini
kitabın extract edilmiş sayfalarından bulur.

## İstatistik

`rosetta stats` — toplam kelime (bilinmeyen), öğrenilmiş (FSRS stability ≥ 21 gün), bugün
sırası gelen, bugün çalışılan, seri (bugün ya da dün biten ardışık çalışma günleri; UTC).
