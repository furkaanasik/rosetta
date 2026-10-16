"""`rosetta lookup|vocab|review|terms|stats|learn-html|dict` — tmp data dir, fixture dictionary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from rosetta_engine import cli, config
from rosetta_engine.commands import learn as learn_cmd
from rosetta_engine.extract.pdf_reader import file_hash
from rosetta_engine.learn.dictionary import build_from_records
from rosetta_engine.models import BookProfile
from rosetta_engine.store.db import connect, migrate
from rosetta_engine.store.repo import Repos

runner = CliRunner()

RECORDS: list[dict[str, Any]] = [
    {
        "word": "replication", "pos": "noun", "lang_code": "en",
        "senses": [{"glosses": ["The process of copying data."]}],
        "translations": [{"lang_code": "tr", "word": "replikasyon"}],
    },
    {
        "word": "leader", "pos": "noun", "lang_code": "en",
        "senses": [{"glosses": ["One who leads."]}],
        "translations": [{"lang_code": "tr", "word": "lider"}],
        "forms": [{"form": "leaders", "tags": ["plural"]}],
    },
    {
        "word": "follower", "pos": "noun", "lang_code": "en",
        "senses": [{"glosses": ["One who follows."]}],
        "translations": [{"lang_code": "tr", "word": "takipçi"}],
    },
]  # fmt: skip


@pytest.fixture(autouse=True)
def data_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(learn_cmd, "_stdin_is_tty", lambda: False)
    build_from_records(RECORDS, tmp_path / "data" / "dictionary.db")
    return tmp_path


def _run(*args: str, input: str | None = None) -> Any:
    result = runner.invoke(cli.app, list(args), input=input)
    return result


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_lookup_found_and_missing() -> None:
    ok = _run("lookup", "Leaders")
    missing = _run("lookup", "zzzz")

    assert ok.exit_code == 0, ok.output
    assert "leader" in ok.output and "lider" in ok.output
    assert missing.exit_code == 1


def test_lookup_without_dictionary_warns(data_dirs: Path) -> None:
    (data_dirs / "data" / "dictionary.db").unlink()

    result = _run("lookup", "leader")

    assert result.exit_code == 1
    assert "dict build" in _flat(result.output)


def test_vocab_add_with_book_page_and_list(book_pdf: Path) -> None:
    added = _run("vocab", "add", "leaders", "--book", str(book_pdf), "--page", "1")
    again = _run("vocab", "add", "leader")
    listed = _run("vocab", "list", "--book", str(book_pdf))
    searched = _run("vocab", "list", "--search", "nomatch")

    assert added.exit_code == 0, added.output
    assert "leader" in added.output and "eklendi" in added.output
    assert "zaten defterde" in again.output
    assert listed.exit_code == 0, listed.output
    assert "lider" in listed.output and "1 kelime" in listed.output
    assert "0 kelime" in searched.output


def test_vocab_add_page_requires_book() -> None:
    result = _run("vocab", "add", "leader", "--page", "2")

    assert result.exit_code != 0


def test_vocab_add_page_out_of_range(book_pdf: Path) -> None:
    result = _run("vocab", "add", "leader", "--book", str(book_pdf), "--page", "99")

    assert result.exit_code != 0


def test_vocab_list_unknown_book_is_error(book_pdf: Path) -> None:
    result = _run("vocab", "list", "--book", str(book_pdf))

    assert result.exit_code != 0


def test_mark_and_learn_html_rubies_unknown_word(book_pdf: Path) -> None:
    _run("vocab", "add", "leader", "--known")
    _run("vocab", "add", "follower")

    known = _run("vocab", "mark", "follower", "--known")
    unknown = _run("vocab", "mark", "Leaders", "--unknown")
    missing = _run("vocab", "mark", "nothing", "--known")
    html_run = _run("learn-html", str(book_pdf), "--pages", "1")

    assert known.exit_code == 0 and unknown.exit_code == 0
    assert missing.exit_code == 1
    assert html_run.exit_code == 0, html_run.output
    out = config.data_dir() / "out" / file_hash(book_pdf)[:12] / "p001.learn.html"
    html = out.read_text()
    assert "<rt>lider</rt>" in html
    assert "<rt>takipçi</rt>" not in html


def test_review_non_tty_lists_due_cards_and_stats() -> None:
    _run("vocab", "add", "leader")

    review = _run("review")
    stats = _run("stats")

    assert review.exit_code == 0, review.output
    assert "leader" in review.output and "1 kart" in review.output
    assert "kelime: 1" in stats.output


def test_review_interactive_grades_card(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(learn_cmd, "_stdin_is_tty", lambda: True)
    _run("vocab", "add", "leader", "--sentence", "The leader writes.")

    result = _run("review", input="\nmaybe\ngood\n")
    after = _run("review")

    assert result.exit_code == 0, result.output
    assert "The _____ writes." in result.output
    assert "unknown rating" in result.output
    assert "sonraki:" in result.output
    assert "sırası gelen kart yok" in after.output


def test_review_nothing_due() -> None:
    assert "sırası gelen kart yok" in _run("review").output


def test_terms_from_profile_and_add_all(book_pdf: Path) -> None:
    _run("extract", str(book_pdf), "--pages", "1")
    conn = connect(config.db_path())
    migrate(conn)
    repos = Repos.from_conn(conn)
    book = repos.books.get_by_hash(file_hash(book_pdf))
    assert book is not None
    repos.profiles.put(
        book.id, BookProfile(glossary={"replication": "replikasyon", "leader": "lider"})
    )
    conn.close()

    listed = _run("terms", str(book_pdf))
    added = _run("terms", str(book_pdf), "--add-all")
    vocab = _run("vocab", "list")

    assert listed.exit_code == 0, listed.output
    assert "replication" in listed.output
    assert "2 terim deftere eklendi" in added.output
    assert "2 kelime" in vocab.output


def test_terms_without_profile(book_pdf: Path) -> None:
    assert _run("terms", str(book_pdf)).exit_code == 1


def test_dict_info_and_build_from_local_file(data_dirs: Path) -> None:
    src = data_dirs / "dump.jsonl"
    src.write_text("\n".join(json.dumps(r) for r in RECORDS[:1]) + "\n")

    built = _run("dict", "build", "--source", str(src))
    info = _run("dict", "info")

    assert built.exit_code == 0, built.output
    assert "1 madde" in built.output
    assert "CC BY-SA" in info.output


def test_dict_info_missing(data_dirs: Path) -> None:
    (data_dirs / "data" / "dictionary.db").unlink()

    assert _run("dict", "info").exit_code == 1
