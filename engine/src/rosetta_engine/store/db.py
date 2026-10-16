"""SQLite connection and ``PRAGMA user_version`` migrations."""

from __future__ import annotations

import logging
import re
import sqlite3
from importlib import resources
from pathlib import Path

log = logging.getLogger(__name__)

_MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")
_MIGRATIONS_PACKAGE = "rosetta_engine.store.migrations"


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _migrations() -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for entry in resources.files(_MIGRATIONS_PACKAGE).iterdir():
        m = _MIGRATION_RE.match(entry.name)
        if m:
            found.append((int(m.group(1)), entry.read_text(encoding="utf-8")))
    return sorted(found)


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def migrate(conn: sqlite3.Connection) -> int:
    """Apply migrations newer than ``user_version``, each atomically. Returns the new version."""
    version = current_version(conn)
    for number, sql in _migrations():
        if number <= version:
            continue
        log.info("applying migration %s", number)
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            raise
        version = number
    return version
