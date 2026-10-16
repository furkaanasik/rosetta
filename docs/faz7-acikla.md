# Faz 7 — "Bunu açıkla"

Seçili bir İngilizce cümlenin dil bilgisi yapısını, deyim/kalıplarını, anahtar kelimelerini ve
doğal Türkçe çevirisini açıklar. **AI yalnızca açık kullanıcı eylemiyle, tahmin + onaydan sonra**
çağrılır; sonuç `explanations` tablosunda cache'lenir ve aynı cümle bir daha sorulmaz.

## Kullanım

```bash
uv run rosetta explain "Replication means keeping a copy of the same data on multiple machines."
uv run rosetta explain "…" --book kitap.pdf --page 59      # sayfadaki paragraf bağlam olur
uv run rosetta explain "…" --model sonnet --yes
```

- **Cache'te varsa**: onay sorulmaz, AI çağrısı yapılmaz, sonuç hemen basılır.
- **Yoksa**: tahmin (`çağrı: 1`, token, `≈ $… liste fiyatı eşdeğeri`) → `Onaylıyor musun?`
  (varsayılan Hayır). stdin terminal değilse `--yes` gerekir.
- `--book` ile `--page` birlikte verilir; o sayfada cümleyi içeren paragraf (yoksa ilk iki
  paragraf) modele **bağlam** olarak gider (çevrilmez/açıklanmaz). Sayfa çıkarımı AI kullanmaz.

Çıkış kodları çeviriyle aynı: 0 başarı, 1 hata (geçersiz yanıt, `claude` yok), 2 iptal,
4 kullanım limiti, 5 kimlik doğrulama, 6 bütçe sınırı, 7 sağlayıcı kullanılamıyor.

## Model ve maliyet

- Varsayılan model **Haiku** (gereksinim §3.6): `config.toml` → `explain_model = "haiku"`;
  komut başına `--model` ile değiştirilebilir. Çeviri modeli (`model`) bundan bağımsızdır.
- Tahmin: sistem prompt + mesaj token'ı; çıktı ≈ 700 token + modelin düşünme payı
  (`thinking_output_tokens_per_call`). Çağrı başı bütçe sınırı (`claude_max_budget_usd`) geçerli.
- Her çağrı (başarısız olanlar dahil, harcanan token'larıyla) `usage` tablosuna
  `operation="explain"` ve `calibrate=0` ile yazılır — çeviri tahmini kalibrasyonunu etkilemez.

## Cache anahtarı

`hash = sha256(normalize(cümle) + dil + model + PROMPT_VERSION)[:32]` (boşluklar sadeleştirilir).
Bağlam anahtara girmez: aynı cümle farklı sayfada da cache'ten gelir. Prompt değişirse
`PROMPT_VERSION` artar ve yeni açıklamalar ayrı satır olur.

## Yanıt biçimi

Model yalnızca JSON döner (Türkçe anahtarlar), lokal olarak doğrulanır:

```json
{"ceviri": "…", "yapi": "…", "deyimler": [{"ifade": "…", "anlam": "…"}],
 "kelimeler": [{"kelime": "…", "anlam": "…"}], "notlar": "…"}
```

Geçersiz JSON → bir kez `--json-schema` ile katı tekrar; yine geçersizse hata, hiçbir şey
kaydedilmez. HTML/arayüz bu alanları kendisi biçimlendirir (LLM HTML üretmez).

## Kod

- `src/rosetta_engine/explain/explainer.py`: `Explainer(conn, settings, complete_fn, model)`,
  `plan()` (AI yok; cache hit → `cached`, aksi halde `estimate`), `run()` (çağrı + doğrulama +
  kayıt), `ExplanationRepo`, `render_text()`.
- `src/rosetta_engine/store/migrations/005_explanations.sql`
- `src/rosetta_engine/commands/explain.py` (`rosetta explain`)
- API eşlemesi (Faz 3): `POST /api/explain/estimate` → cache hit ise `Explanation`, değilse
  `Estimate`; `POST /api/explain {confirm_token}` → `Explainer.run(plan)`.
