import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rosetta_engine.models import Block, BlockType, BookProfile, PageBlocks, text_hash
from rosetta_engine.store import db
from rosetta_engine.store.repo import (
    CacheKey,
    PageStatusRow,
    Repos,
    TranslationRow,
    UsageRow,
)

LANG, PROVIDER, MODEL = "tr", "claude-cli", "haiku"


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    c = db.connect(":memory:")
    db.migrate(c)
    yield c
    c.close()


@pytest.fixture
def repos(conn: sqlite3.Connection) -> Repos:
    return Repos.from_conn(conn, clock=lambda: datetime(2026, 10, 16, 12, 0, tzinfo=UTC))


@pytest.fixture
def book_id(repos: Repos) -> int:
    return repos.books.get_or_create("h" * 64, "DDIA", 673, "/books/ddia.pdf").id


def _row(book_id: int, page_no: int, h: str, text: str = "Merhaba.") -> TranslationRow:
    return TranslationRow(
        book_id=book_id,
        page_no=page_no,
        text_hash=h,
        lang=LANG,
        provider=PROVIDER,
        model=MODEL,
        text=text,
        sentences=[text],
        sentence_aligned=True,
        prompt_version=1,
    )


def _status(book_id: int, page_no: int) -> PageStatusRow:
    return PageStatusRow(book_id, page_no, LANG, PROVIDER, MODEL, "done")


def _block(order: int, t: BlockType, text: str, **kw: object) -> Block:
    return Block.model_validate(
        {
            "page_no": 3,
            "order": order,
            "type": t,
            "bbox": (72.0, 100.0 + order, 432.0, 120.0 + order),
            "font": "MinionPro-Regular",
            "size": 10.5,
            "bold": False,
            "italic": False,
            "text": text,
            "text_hash": text_hash(text),
            **kw,
        }
    )


def test_migration_is_idempotent(conn: sqlite3.Connection) -> None:
    latest = max(number for number, *_ in db._migrations())
    assert latest >= 3
    assert db.migrate(conn) == latest
    assert db.current_version(conn) == latest
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"books", "pages", "blocks", "translations", "page_status", "usage"} <= tables


def test_file_db_uses_wal(tmp_path: Path) -> None:
    c = db.connect(tmp_path / "r.db")
    db.migrate(c)

    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    c.close()


def test_same_hash_different_path_is_same_book(repos: Repos, book_id: int) -> None:
    again = repos.books.get_or_create("h" * 64, "DDIA", 673, "/elsewhere/ddia.pdf")

    assert again.id == book_id
    assert again.file_path == "/elsewhere/ddia.pdf"
    assert repos.books.get_by_hash("nope") is None


def test_book_meta_roundtrip(repos: Repos, book_id: int) -> None:
    repos.books.set_meta(book_id, '{"body_size": 10.5}', '["# | chapter"]')

    assert repos.books.get_meta(book_id) == ('{"body_size": 10.5}', '["# | chapter"]')


def test_replace_page_roundtrip(repos: Repos, book_id: int) -> None:
    page = PageBlocks(
        page_no=3,
        width=504.0,
        height=661.5,
        has_text_layer=True,
        continues_on_next_page=True,
        blocks=[
            _block(0, BlockType.HEADING, "Replication", heading_level=2, bold=True, family="sans"),
            _block(1, BlockType.PARAGRAPH, "Hi. Bye.", sentences=["Hi.", "Bye."], aside=True),
            _block(2, BlockType.LIST_ITEM, "one", list_marker=""),
            _block(3, BlockType.CODE, "  x = 1\n  y = 2", family="mono"),
        ],
    )

    repos.blocks.replace_page(book_id, page, extractor_version=1)
    got = repos.blocks.get_page(book_id, 3)

    assert got == page
    assert repos.blocks.page_version(book_id, 3) == 1
    assert repos.blocks.page_version(book_id, 4) is None
    assert repos.blocks.get_page(book_id, 4) is None


def test_replace_page_replaces_old_blocks(repos: Repos, book_id: int) -> None:
    old = PageBlocks(
        page_no=3, width=1, height=1, has_text_layer=True,
        blocks=[_block(0, BlockType.PARAGRAPH, "a"), _block(1, BlockType.PARAGRAPH, "b")],
    )  # fmt: skip
    new = old.model_copy(update={"blocks": [_block(0, BlockType.PARAGRAPH, "c")]})

    repos.blocks.replace_page(book_id, old, 1)
    repos.blocks.replace_page(book_id, new, 2)

    got = repos.blocks.get_page(book_id, 3)
    assert got is not None
    assert [b.text for b in got.blocks] == ["c"]
    assert repos.blocks.page_version(book_id, 3) == 2


def test_second_put_does_not_overwrite(repos: Repos, book_id: int) -> None:
    repos.translations.put_page([_row(book_id, 3, "aaa", "ilk")], _status(book_id, 3))
    repos.translations.put_page([_row(book_id, 3, "aaa", "ikinci")], _status(book_id, 3))

    got = repos.translations.for_page(book_id, 3, LANG, PROVIDER, MODEL)

    assert got["aaa"].text == "ilk"


def test_put_page_overwrite_replaces_rows(repos: Repos, book_id: int) -> None:
    repos.translations.put_page([_row(book_id, 3, "aaa", "eski")], _status(book_id, 3))
    repos.translations.put_page(
        [_row(book_id, 3, "aaa", "yeni")], _status(book_id, 3), overwrite=True
    )

    got = repos.translations.for_page(book_id, 3, LANG, PROVIDER, MODEL)

    assert got["aaa"].text == "yeni"
    assert got["aaa"].sentences == ["yeni"]


def test_put_rows_caches_without_status(repos: Repos, book_id: int) -> None:
    repos.translations.put_rows([_row(book_id, 4, "aaa", "A")])
    repos.translations.put_rows([_row(book_id, 4, "aaa", "B")])

    got = repos.translations.for_page(book_id, 4, LANG, PROVIDER, MODEL)

    assert got["aaa"].text == "A"  # never overwrites by default
    assert repos.page_status.get(book_id, 4, LANG, PROVIDER, MODEL) is None
    repos.translations.put_rows([_row(book_id, 4, "aaa", "C")], overwrite=True)
    assert repos.translations.for_page(book_id, 4, LANG, PROVIDER, MODEL)["aaa"].text == "C"


def test_get_many_maps_keys(repos: Repos, book_id: int) -> None:
    repos.translations.put_page(
        [_row(book_id, 3, "aaa", "A"), _row(book_id, 3, "bbb", "B")], _status(book_id, 3)
    )
    k_a = CacheKey(3, "aaa", LANG, PROVIDER, MODEL)
    k_b = CacheKey(3, "bbb", LANG, PROVIDER, MODEL)
    k_missing = CacheKey(3, "ccc", LANG, PROVIDER, MODEL)
    k_other_model = CacheKey(3, "aaa", LANG, PROVIDER, "sonnet")

    got = repos.translations.get_many(book_id, [k_a, k_b, k_missing, k_other_model])

    assert set(got) == {k_a, k_b}
    assert got[k_a].text == "A"
    assert got[k_b].sentences == ["B"]
    assert got[k_b].sentence_aligned is True


def test_failed_put_leaves_no_half_page(repos: Repos, book_id: int) -> None:
    bad = TranslationRow(
        book_id=book_id, page_no=3, text_hash="bbb", lang=LANG, provider=PROVIDER,
        model=MODEL, text=None,  # type: ignore[arg-type]  # violates NOT NULL
        sentences=[], sentence_aligned=True, prompt_version=1,
    )  # fmt: skip

    with pytest.raises(sqlite3.IntegrityError):
        repos.translations.put_page([_row(book_id, 3, "aaa"), bad], _status(book_id, 3))

    assert repos.translations.for_page(book_id, 3, LANG, PROVIDER, MODEL) == {}
    assert repos.page_status.get(book_id, 3, LANG, PROVIDER, MODEL) is None


def test_page_status_upsert(repos: Repos, book_id: int) -> None:
    repos.page_status.set(PageStatusRow(book_id, 5, LANG, PROVIDER, MODEL, "failed", "bad json"))
    repos.page_status.set(_status(book_id, 5))

    got = repos.page_status.get(book_id, 5, LANG, PROVIDER, MODEL)

    assert got == PageStatusRow(book_id, 5, LANG, PROVIDER, MODEL, "done", None)


def test_usage_totals_and_recent_ok(repos: Repos, book_id: int) -> None:
    repos.usage.add(UsageRow(book_id, PROVIDER, MODEL, "translate", 100, 200, 0.01, True,
                             est_input_tokens=90, est_output_tokens=180))  # fmt: skip
    repos.usage.add(UsageRow(book_id, PROVIDER, MODEL, "translate", 50, 0, 0.0, False,
                             est_input_tokens=40, est_output_tokens=60))  # fmt: skip
    repos.usage.add(UsageRow(None, PROVIDER, MODEL, "translate", 10, 20, 0.002, True))
    repos.usage.add(UsageRow(book_id, PROVIDER, MODEL, "translate", 300, 400, 0.03, True,
                             est_input_tokens=280, est_output_tokens=420))  # fmt: skip

    total = repos.usage.total()
    per_book = repos.usage.total(book_id)

    assert total.calls == 4
    assert total.input_tokens == 460
    assert per_book.calls == 3
    assert per_book.output_tokens == 600
    assert per_book.cost_usd == pytest.approx(0.04)
    assert repos.usage.recent_ok(PROVIDER, MODEL) == [(280, 300, 420, 400), (90, 100, 180, 200)]
    assert repos.usage.recent_ok(PROVIDER, MODEL, limit=1) == [(280, 300, 420, 400)]
    assert repos.usage.total(999).calls == 0


def test_profile_roundtrip(repos: Repos, book_id: int) -> None:
    assert repos.profiles.get(book_id) is None
    profile = BookProfile(genre="tech", glossary={"replication": "replikasyon"})

    repos.profiles.put(book_id, profile)
    repos.profiles.put(book_id, profile.model_copy(update={"tone": "formal"}))

    got = repos.profiles.get(book_id)
    assert got is not None
    assert got.glossary == {"replication": "replikasyon"}
    assert got.tone == "formal"


def test_excluded_rows_do_not_calibrate(conn: sqlite3.Connection) -> None:
    from datetime import UTC, datetime

    times = iter(datetime(2026, 10, 16, h, tzinfo=UTC) for h in (9, 10, 12, 13))
    repos = Repos.from_conn(conn, clock=lambda: next(times))
    bid = repos.books.get_or_create("h" * 64, "T", 10, "/x.pdf").id
    repos.usage.add(UsageRow(bid, PROVIDER, MODEL, "translate", 100, 2000, 0.1, True,
                             est_input_tokens=100, est_output_tokens=200))  # fmt: skip
    repos.usage.add(UsageRow(bid, PROVIDER, MODEL, "translate", 100, 210, 0.01, True,
                             est_input_tokens=100, est_output_tokens=200))  # fmt: skip

    excluded = repos.usage.exclude_from_calibration("2026-10-16T11:30:00+00:00")

    assert excluded == 1
    assert repos.usage.recent_ok(PROVIDER, MODEL) == [(100, 100, 200, 210)]
    assert repos.usage.total(bid).calls == 2  # still counted in usage totals


def test_out_of_order_migration_is_applied_on_legacy_db(tmp_path: Path) -> None:
    # A DB that reached 004 before 003 existed: no ledger, user_version 4, no jobs table.
    c = sqlite3.connect(tmp_path / "legacy.db")
    for number, _, sql in db._migrations():
        if number in (1, 2, 4):
            c.executescript(sql)
    c.execute("PRAGMA user_version = 4")
    c.commit()
    c.close()
    conn = db.connect(tmp_path / "legacy.db")

    version = db.migrate(conn)

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "jobs" in tables
    assert version == max(n for n, *_ in db._migrations())
    assert db.applied_migrations(conn) == {n for n, *_ in db._migrations()}
    conn.close()


def test_missing_ledger_entry_is_applied(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "r.db")
    db.migrate(conn)
    conn.execute("DROP TABLE explanations")
    conn.execute("DELETE FROM schema_migrations WHERE number = 5")
    conn.commit()

    db.migrate(conn)

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "explanations" in tables
    conn.close()


def test_concurrent_first_migrate_is_safe(tmp_path: Path) -> None:
    import threading

    path = tmp_path / "race.db"
    errors: list[BaseException] = []
    results: list[int] = []

    def run() -> None:
        try:
            c = db.connect(path)
            results.append(db.migrate(c))
            c.close()
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert errors == []
    latest = max(n for n, *_ in db._migrations())
    assert results == [latest] * 4
    c = db.connect(path)
    rows = c.execute("SELECT number, COUNT(*) FROM schema_migrations GROUP BY number").fetchall()
    assert all(count == 1 for _, count in rows)
    c.close()
