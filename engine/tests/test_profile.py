import json
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from typer.testing import CliRunner

from rosetta_engine import cli, config
from rosetta_engine.commands import profile as profile_cmd
from rosetta_engine.config import Settings
from rosetta_engine.errors import ProviderError, UsageLimitError
from rosetta_engine.extract.extractor import TocEntry
from rosetta_engine.models import BookProfile
from rosetta_engine.profile.profiler import (
    InvalidProfileError,
    Profiler,
    build_user_message,
    parse_profile,
    select_pages,
    start_page,
)
from rosetta_engine.store.db import connect, migrate
from rosetta_engine.store.repo import Repos
from rosetta_engine.translate.claude_cli import Completion
from rosetta_engine.translate.fake import FakeTranslator
from rosetta_engine.translate.service import PageTranslationService

runner = CliRunner()

GOOD = {
    "tur": "yazılım / dağıtık sistemler",
    "ton": "teknik ama akıcı",
    "hedef_dil": "tr",
    "cevrilmeyecek": ["Kafka", "PostgreSQL"],
    "sozluk": {"replication": "replikasyon", "leader": "lider"},
    "kod_dili": ["SQL"],
}
PARA = (
    "Replication means keeping a copy of the same data on multiple machines that are "
    "connected via a network. The leader accepts writes and the followers apply them. "
)


def _dense_book(path: Path, pages: int = 8) -> Path:
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page()
        title = "Preface" if n == 0 else f"Chapter {n}. Replication"
        page.insert_text((50, 60), title, fontname="tibo", fontsize=18)
        page.insert_textbox(pymupdf.Rect(50, 80, 545, 790), PARA * 9, fontname="tiro", fontsize=10)
    doc.set_toc(
        [[1, "Preface", 1], *[[1, f"Chapter {n}. Replication", n + 1] for n in range(1, pages)]]
    )
    doc.save(path)
    return path


class FakeComplete:
    def __init__(self, answers: list[Any]) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, system: str, message: str, **kw: Any) -> Completion:
        self.calls.append({"system": system, "message": message, **kw})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return Completion(
            text=text, structured=None, input_tokens=900, output_tokens=300, cost_usd=0.01
        )


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(profile_cmd, "_which", lambda _name: "/usr/bin/claude")
    return tmp_path


@pytest.fixture
def ctx(tmp_path: Path) -> Any:
    pdf = _dense_book(tmp_path / "book.pdf")
    conn = connect(":memory:")
    migrate(conn)
    repos = Repos.from_conn(conn)
    settings = Settings()
    service = PageTranslationService(FakeTranslator(), repos, settings)
    book, doc, meta = service.open_book(pdf)

    def load(pages: Any) -> Any:
        return service.ensure_pages(book, doc, meta, pages)

    yield repos, settings, book, meta, load
    doc.close()
    conn.close()


def test_start_page_skips_front_matter(ctx: Any) -> None:
    _, _, _, meta, _ = ctx

    assert start_page(meta) == 1  # "Preface" on page 1 is skipped


def test_start_page_without_toc_skips_five_percent(ctx: Any) -> None:
    _, _, _, meta, _ = ctx

    assert start_page(meta.model_copy(update={"toc": [], "page_count": 200})) == 10


def test_start_page_all_front_matter_falls_back(ctx: Any) -> None:
    _, _, _, meta, _ = ctx
    toc = [TocEntry(level=1, title="Contents", page=1), TocEntry(level=1, title="Preface", page=2)]

    assert start_page(meta.model_copy(update={"toc": toc})) == 0


def test_select_pages_meaningful_and_capped(ctx: Any) -> None:
    _, _, _, meta, load = ctx

    samples = select_pages(meta, load)

    assert min(samples) == 1
    assert 1 <= len(samples) <= 5
    assert all("Replication means" in t for t in samples.values())


def test_user_message_sections() -> None:
    msg = build_user_message("DDIA", "Chapter 1\n  Section", {4: "text p5", 2: "text p3"})

    assert msg.startswith("TITLE: DDIA")
    assert "TABLE OF CONTENTS:\nChapter 1" in msg
    assert msg.index("SAMPLE PAGE 3:") < msg.index("SAMPLE PAGE 5:")


def test_parse_profile_turkish_keys_and_fences() -> None:
    p = parse_profile("```json\n" + json.dumps(GOOD) + "\n```", "tr")

    assert p.genre == "yazılım / dağıtık sistemler"
    assert p.glossary == {"replication": "replikasyon", "leader": "lider"}
    assert p.do_not_translate == ["Kafka", "PostgreSQL"]
    assert p.code_languages == ["SQL"]


def test_parse_profile_forces_target_lang_and_drops_junk() -> None:
    raw = {
        **GOOD,
        "hedef_dil": "de",
        "sozluk": {"a": "b", "": "x", "c": 3},
        "cevrilmeyecek": ["K", 1],
    }

    p = parse_profile(raw, "tr")

    assert p.target_lang == "tr"
    assert p.glossary == {"a": "b"}
    assert p.do_not_translate == ["K"]


@pytest.mark.parametrize("raw", ["no json here", "{broken", "[1, 2]", '{"sozluk": [1]}'])
def test_parse_profile_rejects(raw: str) -> None:
    with pytest.raises(InvalidProfileError):
        parse_profile(raw, "tr")


def test_plan_does_not_call_model(ctx: Any) -> None:
    repos, settings, book, meta, load = ctx
    fake = FakeComplete([])

    plan = Profiler(repos, settings, complete_fn=fake).plan(book, meta, load, "tr")

    assert fake.calls == []
    assert plan.estimate.calls == 1
    assert plan.estimate.input_tokens > 0
    assert "Turkish" in plan.system_prompt
    assert "SAMPLE PAGE 2:" in plan.user_message


def test_run_stores_profile_and_usage(ctx: Any) -> None:
    repos, settings, book, meta, load = ctx
    fake = FakeComplete([GOOD])
    profiler = Profiler(repos, settings, complete_fn=fake)

    profile = profiler.run(profiler.plan(book, meta, load, "tr"))

    assert repos.profiles.get(book.id) == profile
    assert fake.calls[0]["json_schema"] is None
    rows = repos.conn.execute("SELECT operation, ok, calibrate, input_tokens FROM usage").fetchall()
    assert [tuple(r) for r in rows] == [("profile", 1, 0, 900)]


def test_run_retries_strict_once_on_invalid(ctx: Any) -> None:
    repos, settings, book, meta, load = ctx
    fake = FakeComplete(["not json", GOOD])
    profiler = Profiler(repos, settings, complete_fn=fake)

    profiler.run(profiler.plan(book, meta, load, "tr"))

    assert len(fake.calls) == 2
    assert fake.calls[1]["json_schema"] is not None
    assert repos.usage.total(book.id).calls == 2


def test_run_invalid_twice_saves_nothing(ctx: Any) -> None:
    repos, settings, book, meta, load = ctx
    profiler = Profiler(repos, settings, complete_fn=FakeComplete(["x", "y"]))

    with pytest.raises(InvalidProfileError):
        profiler.run(profiler.plan(book, meta, load, "tr"))

    assert repos.profiles.get(book.id) is None
    oks = repos.conn.execute("SELECT ok FROM usage").fetchall()
    assert [r[0] for r in oks] == [0, 0]


def test_run_provider_error_records_spent_usage(ctx: Any) -> None:
    repos, settings, book, meta, load = ctx
    err = UsageLimitError("limit", input_tokens=5, output_tokens=2, cost_usd=0.001)
    profiler = Profiler(repos, settings, complete_fn=FakeComplete([err]))

    with pytest.raises(ProviderError):
        profiler.run(profiler.plan(book, meta, load, "tr"))

    assert repos.usage.total(book.id).input_tokens == 5
    assert repos.profiles.get(book.id) is None


# --- CLI -------------------------------------------------------------------------------


def _install(monkeypatch: pytest.MonkeyPatch, answers: list[Any]) -> FakeComplete:
    fake = FakeComplete(answers)
    monkeypatch.setattr(profile_cmd, "_complete_fn", fake)
    return fake


def _stored(pdf: Path) -> BookProfile | None:
    from rosetta_engine.extract.pdf_reader import file_hash

    conn = connect(config.db_path())
    try:
        repos = Repos.from_conn(conn)
        book = repos.books.get_by_hash(file_hash(pdf))
        return None if book is None else repos.profiles.get(book.id)
    finally:
        conn.close()


def test_cli_analyze_declined_makes_no_call(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _dense_book(env / "b.pdf")
    fake = _install(monkeypatch, [GOOD])

    result = runner.invoke(cli.app, ["profile", "analyze", str(pdf)], input="n\n")

    assert result.exit_code == cli.EXIT_CANCELLED
    assert fake.calls == []
    assert _stored(pdf) is None


def test_cli_analyze_non_tty_without_yes_refuses(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _dense_book(env / "b.pdf")
    fake = _install(monkeypatch, [GOOD])
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)

    result = runner.invoke(cli.app, ["profile", "analyze", str(pdf)], input="y\n")

    assert result.exit_code == cli.EXIT_CANCELLED
    assert fake.calls == []


def test_cli_analyze_confirmed_saves(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _dense_book(env / "b.pdf")
    fake = _install(monkeypatch, [GOOD])

    result = runner.invoke(cli.app, ["profile", "analyze", str(pdf)], input="y\n")

    assert result.exit_code == 0, result.output
    assert len(fake.calls) == 1
    stored = _stored(pdf)
    assert stored is not None and stored.glossary["replication"] == "replikasyon"


def test_cli_analyze_usage_limit_exit(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _dense_book(env / "b.pdf")
    _install(monkeypatch, [UsageLimitError("limit reached")])

    result = runner.invoke(cli.app, ["profile", "analyze", str(pdf), "--yes"])

    assert result.exit_code == cli.EXIT_USAGE_LIMIT


def test_cli_analyze_missing_claude(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _dense_book(env / "b.pdf")
    fake = _install(monkeypatch, [GOOD])
    monkeypatch.setattr(profile_cmd, "_which", lambda _name: None)

    result = runner.invoke(cli.app, ["profile", "analyze", str(pdf), "--yes"])

    assert result.exit_code == 1
    assert fake.calls == []


def test_cli_set_show_export_import(env: Path) -> None:
    pdf = _dense_book(env / "b.pdf")

    r1 = runner.invoke(
        cli.app,
        ["profile", "set", str(pdf), "--term", "replication=replikasyon", "--term", "leader=lider",
         "--dnt", "Kafka", "--tur", "teknik"],
    )  # fmt: skip
    r2 = runner.invoke(cli.app, ["profile", "set", str(pdf), "--remove-term", "leader"])
    out = env / "p.json"
    r3 = runner.invoke(cli.app, ["profile", "export", str(pdf), str(out)])
    exported = json.loads(out.read_text())
    exported["sozluk"]["follower"] = "takipçi"
    out.write_text(json.dumps(exported, ensure_ascii=False))
    r4 = runner.invoke(cli.app, ["profile", "import", str(pdf), str(out)])
    r5 = runner.invoke(cli.app, ["profile", "show", str(pdf)])

    assert [r.exit_code for r in (r1, r2, r3, r4, r5)] == [0, 0, 0, 0, 0]
    assert exported["cevrilmeyecek"] == ["Kafka"]
    assert exported["tur"] == "teknik"
    stored = _stored(pdf)
    assert stored is not None
    assert stored.glossary == {"replication": "replikasyon", "follower": "takipçi"}
    assert "takipçi" in r5.output


def test_cli_set_rejects_bad_term(env: Path) -> None:
    pdf = _dense_book(env / "b.pdf")

    result = runner.invoke(cli.app, ["profile", "set", str(pdf), "--term", "noequals"])

    assert result.exit_code == 1


def test_cli_import_rejects_invalid_file(env: Path) -> None:
    pdf = _dense_book(env / "b.pdf")
    bad = env / "bad.json"
    bad.write_text('{"sozluk": [1, 2]}')

    result = runner.invoke(cli.app, ["profile", "import", str(pdf), str(bad)])

    assert result.exit_code == 1


def test_cli_show_without_profile(env: Path) -> None:
    pdf = _dense_book(env / "b.pdf")

    result = runner.invoke(cli.app, ["profile", "show", str(pdf)])

    assert result.exit_code == 1


def test_translate_uses_db_profile_by_default(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _dense_book(env / "b.pdf", pages=3)
    fake = FakeTranslator()
    monkeypatch.setattr(cli, "_translator", lambda provider, model, settings: fake)
    runner.invoke(cli.app, ["profile", "set", str(pdf), "--term", "replication=replikasyon"])

    result = runner.invoke(cli.app, ["translate", str(pdf), "--pages", "2", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Profil: DB (1 terim)" in result.output
    assert fake.calls[0][0].profile.glossary == {"replication": "replikasyon"}


def test_estimate_reports_no_profile(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _dense_book(env / "b.pdf", pages=3)
    monkeypatch.setattr(cli, "_translator", lambda provider, model, settings: FakeTranslator())

    result = runner.invoke(cli.app, ["estimate", str(pdf), "--pages", "2"])

    assert result.exit_code == 0, result.output
    assert "Profil: yok" in result.output


def test_profile_change_keeps_cache(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _dense_book(env / "b.pdf", pages=3)
    fake = FakeTranslator()
    monkeypatch.setattr(cli, "_translator", lambda provider, model, settings: fake)
    runner.invoke(cli.app, ["translate", str(pdf), "--pages", "2", "--yes"])
    calls = len(fake.calls)

    runner.invoke(cli.app, ["profile", "set", str(pdf), "--term", "leader=lider"])
    second = runner.invoke(cli.app, ["translate", str(pdf), "--pages", "2", "--yes"])

    assert second.exit_code == 0
    assert len(fake.calls) == calls  # decision 4: profile change never invalidates cache
