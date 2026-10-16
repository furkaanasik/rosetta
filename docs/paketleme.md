# Paketleme (Linux: .AppImage + .deb)

Rosetta iki parçadan oluşur: Tauri masaüstü uygulaması (`app/`) ve Python motoru (`engine/`).
Motor PyInstaller ile **tek dosyalık bir sidecar** (`rosetta-engine`) olarak paketlenir ve
Tauri bundle'ına gömülür; uygulama açılışta `rosetta-engine serve --port 0 --token <rastgele>`
çalıştırır ve stdout'taki tek JSON satırından port/token'ı okur.

## Gerekenler

- Rust (`rustup`, kullanıcı dizinine): `~/.cargo/bin` PATH'te olmalı (script'ler kendisi ekler).
- Node.js + npm, `uv`.
- Sistem kütüphaneleri:
  - Arch: `webkit2gtk-4.1 base-devel curl wget file openssl librsvg` (tepsi kullanılmadığı için `libappindicator-gtk3` gerekmez)
  - Debian/Ubuntu: `libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev librsvg2-dev`
- İnternet (yalnızca ilk AppImage derlemesinde): Tauri `linuxdeploy`, `AppRun` ve
  `linuxdeploy-plugin-appimage` araçlarını indirir (`~/.cache/tauri`).

## Komutlar

```bash
packaging/build-sidecar.sh          # sadece motor → packaging/dist/rosetta-engine
packaging/build-app.sh              # motor + uygulama → .AppImage ve .deb
BUNDLES=deb packaging/build-app.sh  # sadece .deb
```

`build-sidecar.sh`, ikiliyi `app/src-tauri/binaries/rosetta-engine-<target-triple>` olarak
kopyalar (gitignore'da). Bu, geliştirme sarmalayıcısının (`app/scripts/prepare-dev-sidecar.sh`)
yerine geçer; `npx tauri dev` ile tekrar kaynak koddan çalışmak için o script'i yeniden çalıştırın.

## Çıktılar (2026-10-16 ölçümü)

| Dosya | Boyut |
|---|---|
| `packaging/dist/rosetta-engine` (PyInstaller onefile) | 64 MB |
| `app/src-tauri/target/release/bundle/appimage/Rosetta_0.1.0_amd64.AppImage` | 163 MB |
| `app/src-tauri/target/release/bundle/deb/Rosetta_0.1.0_amd64.deb` | 68 MB |

Süreler: sidecar ~33 sn; tam derleme (sidecar + frontend + Rust release + iki bundle) ~2 dk 50 sn
(12 çekirdek). Sidecar `--help` açılışı ~0.9 sn (onefile her açılışta kendini /tmp'ye açar).

## İçerik

- `.deb`: `usr/bin/rosetta`, `usr/bin/rosetta-engine`, simgeler, `Rosetta.desktop`,
  `usr/share/doc/rosetta/copyright` (AGPL-3.0). Bağımlılık: `libwebkit2gtk-4.1-0, libgtk-3-0`.
- Masaüstü girdisi: `Categories=Education;Office;Viewer;`, `MimeType=application/pdf;`
  ("Birlikte aç → Rosetta"), `Exec=rosetta %f`.
- PyInstaller spec (`packaging/rosetta-engine.spec`): `rosetta_engine` paket verisi
  (migration SQL'leri, Jinja şablonları, CSS), tüm alt modüller (`commands/*` eklentileri
  `pkgutil` ile bulunduğundan `collect_submodules` şart), `pymupdf`, `simplemma` (dil verisi),
  `fsrs`, `uvicorn`/`fastapi`.

Sözlük (`dictionary.db`, ~157 MB, CC BY-SA) pakete **girmez**; kullanıcı makinesinde
`rosetta-engine dict build` ile üretilir (bkz. docs/faz6-ogrenme.md).

## Doğrulama (yapılan)

- Sidecar ikilisi: `--help` (tüm komutlar), `extract --debug`, `translate --provider fake --yes`,
  `serve --port 0` → JSON satırı, `GET /api/health` 200 (token'lı) / 401 (token'sız),
  `POST /api/books/open` 200. Hiçbir AI çağrısı yapılmadı.
- `.deb` içeriği `ar x` + `tar -t` ile, AppImage içeriği `Rosetta.AppDir` üzerinden kontrol edildi;
  sidecar iki pakette de var ve AppDir'deki kopya çalışıyor.

## Bilinen sorunlar

- GUI başsız (headless) test edilmedi: makinede `xvfb-run`/`Xvfb` yok. Uygulamanın gerçek açılışı
  elle denenmeli: `./Rosetta_0.1.0_amd64.AppImage`.
- AppImage FUSE ister; FUSE yoksa `APPIMAGE_EXTRACT_AND_RUN=1 ./Rosetta_0.1.0_amd64.AppImage`
  (build script derleme araçları için bunu zaten ayarlar).
- AppImage WebKitGTK'yı sistemden kullanır (Tauri varsayılanı); hedef sistemde
  `webkit2gtk-4.1` kurulu olmalı.
- `.desktop` dosyası `%f` ile PDF yolu verir; uygulamanın açılışta bu argümanı okuyup kitabı
  açması frontend/Rust tarafında ayrıca bağlanmalı.
- onefile sidecar her başlatmada ~0.9 sn açılma maliyeti taşır; gerekirse `onedir` moduna geçilebilir.
