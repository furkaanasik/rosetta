#!/usr/bin/env sh
# Development stand-in for the PyInstaller sidecar: runs the engine from the repo with uv.
# scripts/prepare-dev-sidecar.sh copies this to rosetta-engine-<target-triple>.
HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE_DIR="${ROSETTA_ENGINE_DIR:-$HERE/../../../engine}"
exec uv --directory "$ENGINE_DIR" run --quiet rosetta "$@"
