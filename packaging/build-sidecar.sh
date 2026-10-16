#!/usr/bin/env bash
# Builds the engine sidecar (PyInstaller onefile) and installs it where Tauri expects it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.cargo/bin:$PATH"
TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
cd "$ROOT/engine"
uv run --group dev pyinstaller --noconfirm --clean \
  --distpath "$ROOT/packaging/dist" --workpath "$ROOT/packaging/build" \
  "$ROOT/packaging/rosetta-engine.spec"
mkdir -p "$ROOT/app/src-tauri/binaries"
install -m 755 "$ROOT/packaging/dist/rosetta-engine" "$ROOT/app/src-tauri/binaries/rosetta-engine-$TRIPLE"
echo "sidecar: $ROOT/app/src-tauri/binaries/rosetta-engine-$TRIPLE"
