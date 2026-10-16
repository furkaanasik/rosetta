# Rosetta — masaüstü uygulaması (Tauri 2 + React + PDF.js)

```bash
npm install
npm run dev            # tarayıcıda, sahte motorla (MockEngineApi)
npm test               # Vitest
npm run lint && npm run typecheck
sh scripts/prepare-dev-sidecar.sh     # geliştirme sidecar'ı (uv ile repo'daki motoru çalıştırır)
PATH="$HOME/.cargo/bin:$PATH" npm run tauri dev
```

- Motor bağlantısı: Tauri, `binaries/rosetta-engine` sidecar'ını `serve --port 0 --token …` ile başlatır ve
  stdout'taki ilk JSON satırından port/token'ı okur. Geliştirmede `ROSETTA_ENGINE_URL`/`ROSETTA_ENGINE_TOKEN`
  ile elle başlatılmış bir motora bağlanılabilir. Uç noktalar: [API_CONTRACT.md](API_CONTRACT.md).
- Görünüm modları: Orijinal, Split (paragraf bazlı senkron kaydırma), Sadece Çeviri, Öğrenme.
- AI işlemleri iki adımlıdır: tahmin → maliyet penceresi → "Onayla". Onaysız çağrı yoktur.
- Motorun ürettiği HTML ayrıca temizlenir (script/olay öznitelikleri atılır) ve sıkı bir CSP altında gösterilir.

## Uçtan uca testler (Playwright)

```bash
npm run e2e         # sentetik test kitabı + gerçek motor, sahte AI
npm run e2e:ddia    # DDIA kitabında görsel kontrol (kullanıcı verisinin KOPYASI üzerinde)
```

`e2e/run.mjs` geçici bir veri klasöründe motoru `rosetta serve --dev-fake-ai` ile başlatır, Vite'ı
`VITE_ENGINE_URL`/`VITE_ENGINE_TOKEN` ile açar ve Playwright'ı sistem Chromium'uyla çalıştırır
(`CHROMIUM_PATH` ile değiştirilebilir). Ekran görüntüleri `e2e/screenshots/` altına yazılır.

- `--dev-fake-ai` gizli bir geliştirme bayrağıdır: çeviri, profil ve "Bunu açıkla" sahte yanıt verir;
  `provider = "fake"` dışındaki sağlayıcılar bu modda yalnızca okunur (çeviri reddedilir). Motorun
  PATH'inden `claude` ayrıca çıkarılır. Paketli uygulama motoru sabit argümanlarla başlatır, bayrak
  orada hiç kullanılmaz.
- `--dev-fake-delay` (sn) çağrıları yavaşlatır, böylece bir iş arayüzden duraklatılabilir. Test
  kitabının 3. sayfasındaki `ROSETTA_E2E_FAIL_ONCE` işareti bir kez sağlayıcı hatası üretir
  ("sadece hatalıları tekrar dene" akışı).
- `e2e:ddia` gerçek veriyi (rosetta.db, out/) geçici klasöre kopyalar; asıl veri hiç değişmez.
