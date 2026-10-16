#!/usr/bin/env sh
# Installs the dev sidecar wrapper under the name Tauri expects (binaries/rosetta-engine-<triple>),
# with the absolute engine path baked in (Tauri copies sidecars next to the executable at runtime).
set -eu
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE_DIR="$(cd "$APP_DIR/../engine" && pwd)"
TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
OUT="$APP_DIR/src-tauri/binaries/rosetta-engine-$TRIPLE"
sed "s|\$HERE/../../../engine|$ENGINE_DIR|" "$APP_DIR/src-tauri/binaries/dev-sidecar.sh" > "$OUT"
chmod +x "$OUT"
echo "$OUT (dev wrapper → $ENGINE_DIR)"
