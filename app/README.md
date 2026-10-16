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
