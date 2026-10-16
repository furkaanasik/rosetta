# Faz 8 — İsteğe bağlı sağlayıcılar: DeepL ve Ollama

Varsayılan sağlayıcı `claude-cli` olarak kalır. İki ek sağlayıcı `--provider` ile seçilir:

```bash
uv run rosetta estimate  kitap.pdf --pages 41-44 --provider deepl
uv run rosetta translate kitap.pdf --pages 41-44 --provider ollama [--model llama3.1:8b]
```

Kurallar aynıdır: önce tahmin + onay, her çeviri cache'lenir (cache anahtarı sağlayıcı ve
modeli içerir; DeepL/Ollama çevirileri Claude çevirilerinden ayrı tutulur), kod/görsel/tablo
gönderilmez.

## DeepL

- Anahtar **yalnızca ortam değişkeninden** okunur: `DEEPL_AUTH_KEY` (adı `config.toml`
  `deepl_auth_key_env` ile değiştirilebilir). Anahtar `:fx` ile bitiyorsa Free uç noktası
  (`api-free.deepl.com`), aksi halde Pro (`api.deepl.com`) kullanılır.
- **Kitap profili, sözlük ve önceki sayfa bağlamı kullanılmaz.** CLI bunu her çalıştırmada
  "Bu sağlayıcı kitap profilini/bağlamı kullanmaz" notuyla belirtir; arayüz de aynı bilgiyi
  `supports_profile = False` özelliğinden okur.
- Her cümle ayrı metin olarak gönderilir (istek başına en çok 50), bu yüzden cümle eşleme her
  zaman korunur.
- Satır içi kod (`` `…` ``) `tag_handling=xml` ile `<x id="n"/>` yer tutucularına çevrilir,
  DeepL'e hiç gitmez ve dönüşte aynen geri konur.
- Hatalar: 401/403 → kimlik doğrulama (çıkış 5); 456 karakter kotası → kullanım limiti
  (çıkış 4); 429 → 1, 2, 4 sn bekleyip 3 kez yeniden dener, sonra kullanım limiti; ağ hatası →
  sağlayıcı hatası.
- Maliyet: DeepL karakter başına ücretlendirir (Pro: 1M karakter ≈ $25). Tahmin motoru token
  tabanlı olduğundan fiyat, ~3.6 karakter/token ile token başına çevrilmiştir:
  `[pricing.deepl] in = 90.0, out = 0.0` ($/1M token). **Free anahtarda** bunu sıfırlayın:

  ```toml
  [pricing.deepl]
  in = 0.0
  out = 0.0
  ```

## Ollama

- Yerel model, ücretsiz (`[pricing.ollama]` = 0). Varsayılanlar:
  `ollama_url = "http://localhost:11434"`, `ollama_model = "qwen2.5:7b"`, `ollama_timeout_s = 600`.
- Claude ile **aynı sistem prompt'u, kullanıcı mesajı (profil + bağlam dahil) ve JSON
  doğrulaması** kullanılır. İlk deneme `format: "json"`, geçersiz yanıtta tek yeniden deneme
  tam JSON şemasıyla (structured outputs).
- Model, cache ve fiyat için `ollama/<ad>` olarak kaydedilir (ör. `ollama/qwen2.5:7b`).
- Sunucu kapalıysa ya da model indirilmemişse iş hemen durur (çıkış 7):
  `ollama serve` / `ollama pull <model>`.
- Token sayıları Ollama'nın `prompt_eval_count` / `eval_count` alanlarından okunur.

## Kod

- `translate/providers.py`: `make_translator(provider, model, settings)`, `supports_profile()`.
- `translate/deepl.py`, `translate/ollama.py`; testler `tests/test_providers.py`
  (`httpx.MockTransport`, ağ erişimi yok).
