# Faz 2 — Kitap profili

Profil, çevirinin kitap boyunca tutarlı olması içindir: hangi terim nasıl çevrilecek (sözlük),
hangi adlar hiç çevrilmeyecek, kitabın türü ve tonu. Profil DB'de kitap başına saklanır ve
`translate` / `estimate` onu **varsayılan olarak** kullanır (`--profile dosya.json` verilirse dosya
kazanır). Çıktıda hangisinin kullanıldığı yazar: `Profil: DB (n terim)`, `Profil: dosya (…)`,
`Profil: yok`.

## Komutlar

```bash
# Taslak profil çıkar: içindekiler + ilk anlamlı 5 gövde sayfası → tek AI çağrısı.
# Önce tahmin gösterir, onay ister (Kural 1/2). DDIA'da ≈ 4 200 girdi token, Sonnet ≈ $0.035 eşdeğeri.
uv run rosetta profile analyze kitap.pdf [--lang tr] [--model sonnet] [--yes]

uv run rosetta profile show kitap.pdf                    # JSON (Türkçe anahtarlar)
uv run rosetta profile export kitap.pdf profil.json      # dosyaya yaz
uv run rosetta profile import kitap.pdf profil.json      # doğrulayıp DB'ye al
uv run rosetta profile set kitap.pdf \
    --term "replication=replikasyon" --remove-term leader \
    --dnt Kafka --remove-dnt SaaS --tur "teknik kitap" --ton "akıcı"
```

Profil biçimi (gereksinim §3.2):

```json
{"tur": "yazılım / dağıtık sistemler", "ton": "teknik ama akıcı", "hedef_dil": "tr",
 "cevrilmeyecek": ["Kafka", "PostgreSQL"], "sozluk": {"replication": "replikasyon"},
 "kod_dili": ["SQL"]}
```

## Davranış

- **Girdi seçimi:** İçindekiler'deki ilk üst seviye bölüm (ön madde — Preface, Contents,
  Copyright… — atlanır) gövdenin başlangıcı sayılır; oradan itibaren en az 1 200 karakter
  çevrilebilir metin içeren en fazla 5 sayfa, toplam ~6 000 token sınırında. İçindekiler yoksa
  kitabın ilk %5'i atlanır. Taranmış (metinsiz) sayfalar atlanır.
- **Çağrı:** `claude -p` (abonelik girişi; `ANTHROPIC_*` alt süreçten çıkarılır), varsayılan model
  ve düşünme ayarı config'ten. Yanıt metindeki JSON'dan okunur; geçersizse bir kez
  `--json-schema` ile yeniden denenir, yine geçersizse hiçbir şey kaydedilmez.
- **Doğrulama:** Türkçe anahtarlar zorunlu biçim; `hedef_dil` istenen dile zorlanır; boş/tip dışı
  sözlük girdileri atılır; en fazla 120 terim.
- **Kullanım kaydı:** her çağrı `usage` tablosuna `operation="profile"` ile yazılır (başarısızlar
  da, harcanan token'larla); profil çağrıları çeviri tahmini kalibrasyonuna katılmaz.
- **Cache:** profil değişikliği mevcut çevirileri geçersiz kılmaz (karar 4). Yeni sözlüğü eski
  sayfalara uygulamak için `translate --force`.
- **Çıkış kodları:** 0 tamam, 1 hata (claude yok, geçersiz profil), 2 iptal, 4 kullanım limiti,
  5 kimlik doğrulama, 6 bütçe, 7 sağlayıcı kullanılamıyor.

## Geliştirici notu

`translate/claude_cli.complete(system_prompt, user_message, *, model, settings, json_schema,
runner, max_budget_usd) -> Completion(text, structured, input_tokens, output_tokens, cost_usd)`
tüm `claude -p` çağrılarının ortak yoludur (çeviri, profil, Faz 7 "Bunu açıkla").
