"""Build the offline EN→TR dictionary (``rosetta dict build`` does the same).

Usage: uv run python scripts/build_dictionary.py [SOURCE_URL_OR_PATH] [TARGET_DB]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from rosetta_engine.learn.dictionary import KAIKKI_URL, BuildStats, build, dictionary_path


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else KAIKKI_URL
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else dictionary_path()
    started = time.monotonic()

    def progress(s: BuildStats) -> None:
        print(f"{s.lines:>9} lines · {s.entries} entries · {s.translations} tr", flush=True)

    stats = build(target, source=source, progress=progress)
    took = time.monotonic() - started
    size = target.stat().st_size / 1e6
    print(f"done in {took:.0f}s: {stats.entries} entries, {stats.translations} translations,")
    print(f"{stats.forms} form links, {size:.1f} MB → {target}")


if __name__ == "__main__":
    main()
