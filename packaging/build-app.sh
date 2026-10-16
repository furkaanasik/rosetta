#!/usr/bin/env bash
# Full desktop build: engine sidecar (PyInstaller) + Tauri bundles (.AppImage, .deb).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.cargo/bin:$PATH"
"$ROOT/packaging/build-sidecar.sh"
cd "$ROOT/app"
[ -d node_modules ] || npm ci
# linuxdeploy/appimagetool are AppImages themselves; run them without FUSE.
export APPIMAGE_EXTRACT_AND_RUN=1
npx tauri build --bundles "${BUNDLES:-appimage,deb}"
ls -lh "$ROOT/app/src-tauri/target/release/bundle/"{deb,appimage}/ 2>/dev/null || true
