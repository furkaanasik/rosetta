"""SQLite connection and migrations (``schema_migrations`` ledger + ``user_version``)."""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from datetime import UTC, datetime
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
        _set_wal(conn)
    return conn


def _set_wal(conn: sqlite3.Connection, attempts: int = 50) -> None:
    """Switching a fresh DB to WAL can report BUSY without honouring busy_timeout when
    several processes open it at once; retry briefly."""
    for i in range(attempts):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or i == attempts - 1:
                raise
            time.sleep(0.02 * (i + 1))


def _migrations() -> list[tuple[int, str, str]]:
    """(number, file name, sql) for every migration file, sorted by number."""
    found: list[tuple[int, str, str]] = []
    for entry in resources.files(_MIGRATIONS_PACKAGE).iterdir():
        m = _MIGRATION_RE.match(entry.name)
        if m:
            found.append((int(m.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    return sorted(found)


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


_LEDGER = """CREATE TABLE IF NOT EXISTS schema_migrations(
    number INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"""


def _statements(sql: str) -> list[str]:
    """Split a migration script into complete statements (no triggers in our migrations)."""
    out: list[str] = []
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                out.append(buf)
            buf = ""
    if buf.strip():
        out.append(buf)
    return out


_CREATE_RE = re.compile(r"CREATE\s+(TABLE|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.I)
_ADD_COLUMN_RE = re.compile(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)", re.I)


def _looks_applied(conn: sqlite3.Connection, sql: str) -> bool:
    """Heuristic for legacy DBs: every table/index/column the script creates already exists."""
    for kind, name in _CREATE_RE.findall(sql):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?", (kind.lower(), name)
        ).fetchone()
        if row is None:
            return False
    for table, column in _ADD_COLUMN_RE.findall(sql):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            return False
    return True


def applied_migrations(conn: sqlite3.Connection) -> set[int]:
    return {int(r[0]) for r in conn.execute("SELECT number FROM schema_migrations")}


def _ensure_ledger(conn: sqlite3.Connection) -> None:
    """Create the ledger. DBs migrated before it existed are backfilled: migrations up to
    ``user_version`` whose objects exist are recorded; a skipped out-of-order file is not."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(_LEDGER)
        empty = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0
        version = current_version(conn)
        if empty and version > 0:
            now = datetime.now(UTC).isoformat()
            conn.executemany(
                "INSERT INTO schema_migrations(number, name, applied_at) VALUES (?, ?, ?)",
                [
                    (n, name, now)
                    for n, name, sql in _migrations()
                    if n <= version and _looks_applied(conn, sql)
                ],
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every migration not recorded in ``schema_migrations``, each atomically.

    Out-of-order files (e.g. a 003 added after a DB reached 004) are still applied. Each
    migration runs under ``BEGIN IMMEDIATE`` and re-checks the ledger inside the transaction,
    so two processes migrating at once never apply the same file twice. ``user_version`` is
    kept equal to the highest applied number. Returns that number.
    """
    saved = conn.isolation_level
    conn.isolation_level = None  # explicit transactions only
    try:
        _ensure_ledger(conn)
        for number, name, sql in _migrations():
            if number in applied_migrations(conn):
                continue
            conn.execute("BEGIN IMMEDIATE")
            try:
                if number in applied_migrations(conn):  # another process won the race
                    conn.execute("ROLLBACK")
                    continue
                log.info("applying migration %s", name)
                for stmt in _statements(sql):
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_migrations(number, name, applied_at) VALUES (?, ?, ?)",
                    (number, name, datetime.now(UTC).isoformat()),
                )
                top = max(applied_migrations(conn))
                conn.execute(f"PRAGMA user_version = {top:d}")
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        return current_version(conn)
    finally:
        conn.isolation_level = saved
