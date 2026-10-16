import re
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from rosetta_engine import cli, config
from rosetta_engine.translate.claude_cli import build_argv, child_env
from rosetta_engine.translate.fake import FakeTranslator

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    return tmp_path


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeTranslator:
    t = FakeTranslator()
    monkeypatch.setattr(cli, "_translator", lambda provider, model, settings: t)
    return t


def _flat(text: str) -> str:
    """Collapse rich's terminal line wrapping."""
    return " ".join(text.split())


def _out_dir(pdf: Path) -> Path:
    from rosetta_engine.extract.pdf_reader import file_hash

    return config.data_dir() / "out" / file_hash(pdf)[:12]


@pytest.mark.parametrize(
    ("spec", "expected"),
    [("2", [1]), ("1-3", [0, 1, 2]), ("1,3,5-6", [0, 2, 4, 5]), ("3,1-2,3", [0, 1, 2])],
)
def test_parse_pages(spec: str, expected: list[int]) -> None:
    assert cli.parse_pages(spec, 10) == expected


@pytest.mark.parametrize("spec", ["0", "11", "5-3", "a", "1-", ""])
def test_parse_pages_rejects(spec: str) -> None:
    with pytest.raises(typer.BadParameter):
        cli.parse_pages(spec, 10)


def test_format_pages() -> None:
    assert cli.format_pages([40, 41, 42, 49]) == "41-43,50"


def test_translate_declined_does_not_call_provider(book_pdf: Path, fake: FakeTranslator) -> None:
    result = runner.invoke(cli.app, ["translate", str(book_pdf), "--pages", "1"], input="n\n")

    assert result.exit_code == cli.EXIT_CANCELLED
    assert fake.calls == []


def test_translate_non_tty_without_yes_refuses(
    book_pdf: Path, fake: FakeTranslator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)

    result = runner.invoke(cli.app, ["translate", str(book_pdf), "--pages", "1"], input="y\n")

    assert result.exit_code == cli.EXIT_CANCELLED
    assert fake.calls == []


def test_translate_confirmed_writes_html_then_cache_hit(
    book_pdf: Path, fake: FakeTranslator
) -> None:
    first = runner.invoke(cli.app, ["translate", str(book_pdf), "--pages", "1-2"], input="y\n")

    assert first.exit_code == 0, first.output
    out = _out_dir(book_pdf)
    for name in ("p001.tr.html", "p001.review.html", "p002.tr.html", "index.html"):
        assert (out / name).is_file()
    assert "[TR]" in (out / "p001.tr.html").read_text()
    calls = len(fake.calls)
    assert calls > 0

    second = runner.invoke(cli.app, ["translate", str(book_pdf), "--pages", "1-2"])

    assert second.exit_code == 0, second.output
    assert "0 çağrı" in second.output
    assert len(fake.calls) == calls


def test_translate_usage_limit_exit_code(book_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t = FakeTranslator(fail_mode="limit")
    monkeypatch.setattr(cli, "_translator", lambda provider, model, settings: t)

    result = runner.invoke(cli.app, ["translate", str(book_pdf), "--pages", "1", "--yes"])

    assert result.exit_code == cli.EXIT_USAGE_LIMIT


def test_translate_auth_exit_code(book_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t = FakeTranslator(fail_mode="auth")
    monkeypatch.setattr(cli, "_translator", lambda provider, model, settings: t)

    result = runner.invoke(cli.app, ["translate", str(book_pdf), "--pages", "1", "--yes"])

    assert result.exit_code == cli.EXIT_AUTH


def test_translate_unavailable_exit_code(book_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t = FakeTranslator(fail_mode="unavailable")
    monkeypatch.setattr(cli, "_translator", lambda provider, model, settings: t)

    result = runner.invoke(cli.app, ["translate", str(book_pdf), "--pages", "1", "--yes"])

    assert result.exit_code == cli.EXIT_UNAVAILABLE
    assert "Sağlayıcı kullanılamıyor" in _flat(result.output)


def test_translate_three_consecutive_errors_exit_unavailable(
    book_pdf: Path, isolated_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = isolated_dirs / "cfg"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text("batch_max_pages = 1\n")
    t = FakeTranslator(fail_mode="error")
    monkeypatch.setattr(cli, "_translator", lambda provider, model, settings: t)

    result = runner.invoke(cli.app, ["translate", str(book_pdf), "--pages", "1-3", "--yes"])

    assert len(t.calls) == 3
    assert result.exit_code == cli.EXIT_UNAVAILABLE


def test_translate_invalid_is_partial_failure(
    book_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = FakeTranslator(fail_mode="invalid")
    monkeypatch.setattr(cli, "_translator", lambda provider, model, settings: t)

    result = runner.invoke(cli.app, ["translate", str(book_pdf), "--pages", "1", "--yes"])

    assert result.exit_code == cli.EXIT_PARTIAL
    assert len(t.calls) == 2  # original + one strict retry


def test_extract_debug_writes_html(book_pdf: Path) -> None:
    result = runner.invoke(cli.app, ["extract", str(book_pdf), "--pages", "1-3", "--debug"])

    assert result.exit_code == 0, result.output
    out = _out_dir(book_pdf)
    assert (out / "p001.debug.html").is_file()
    assert (out / "p003.debug.html").is_file()
    assert (out / "index.html").is_file()


def test_estimate_and_usage_with_fake_provider(book_pdf: Path) -> None:
    est = runner.invoke(cli.app, ["estimate", str(book_pdf), "--pages", "1", "--provider", "fake"])
    tr = runner.invoke(
        cli.app, ["translate", str(book_pdf), "--pages", "1", "--provider", "fake", "--yes"]
    )
    usage = runner.invoke(cli.app, ["usage", "--book", str(book_pdf)])

    assert est.exit_code == 0, est.output
    assert "çağrı: 1" in est.output
    assert tr.exit_code == 0, tr.output
    assert usage.exit_code == 0
    assert "çağrı: 1" in usage.output


def test_out_of_range_page_is_error(book_pdf: Path) -> None:
    result = runner.invoke(cli.app, ["extract", str(book_pdf), "--pages", "9"])

    assert result.exit_code != 0
    assert "out of range" in result.output


def test_translate_budget_exit_code(book_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    t = FakeTranslator(fail_mode="budget")
    monkeypatch.setattr(cli, "_translator", lambda provider, model, settings: t)

    result = runner.invoke(cli.app, ["translate", str(book_pdf), "--pages", "1", "--yes"])

    assert result.exit_code == cli.EXIT_BUDGET
    assert "Bütçe sınırı aşıldı" in result.output


def test_budget_option_reaches_claude_settings(
    book_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[config.Settings] = []

    def make(provider: str, model: str | None, settings: config.Settings) -> FakeTranslator:
        seen.append(settings)
        return FakeTranslator(model=model or settings.model)

    monkeypatch.setattr(cli, "_translator", make)

    result = runner.invoke(
        cli.app,
        ["estimate", str(book_pdf), "--pages", "1", "--provider", "claude-cli",
         "--max-budget-usd", "0.02"],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert seen[0].claude_max_budget_usd == 0.02


def test_budget_option_ignored_for_fake(book_pdf: Path) -> None:
    result = runner.invoke(
        cli.app,
        ["estimate", str(book_pdf), "--pages", "1", "--provider", "fake",
         "--max-budget-usd", "0.02"],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert "yalnızca claude-cli" in result.output


def _capture_settings(monkeypatch: pytest.MonkeyPatch) -> list[config.Settings]:
    seen: list[config.Settings] = []

    def make(provider: str, model: str | None, settings: config.Settings) -> FakeTranslator:
        seen.append(settings)
        return FakeTranslator(model=model or settings.model)

    monkeypatch.setattr(cli, "_translator", make)
    return seen


def test_think_medium_enables_cli_thinking(book_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_THINKING_TOKENS", raising=False)
    seen = _capture_settings(monkeypatch)

    result = runner.invoke(
        cli.app,
        ["estimate", str(book_pdf), "--pages", "1", "--provider", "claude-cli",
         "--think", "medium"],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    s = seen[0]
    argv = build_argv("haiku", "SYS", strict=False, effort=s.claude_effort)
    assert argv[argv.index("--effort") + 1] == "medium"
    assert "MAX_THINKING_TOKENS" not in child_env(max_thinking_tokens=s.claude_max_thinking_tokens)
    out = _flat(result.output)
    assert "düşünme: medium" in out
    assert "+~1 500 tok" in out


def test_think_off_forces_thinking_off(book_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(book_pdf.parent / "cfg-think"))
    (book_pdf.parent / "cfg-think").mkdir()
    (book_pdf.parent / "cfg-think" / "config.toml").write_text(
        'claude_effort = "high"\nclaude_max_thinking_tokens = 5000\n'
    )
    seen = _capture_settings(monkeypatch)

    result = runner.invoke(
        cli.app,
        ["estimate", str(book_pdf), "--pages", "1", "--provider", "claude-cli", "--think", "off"],
    )

    assert result.exit_code == 0, result.output
    s = seen[0]
    argv = build_argv("haiku", "SYS", strict=False, effort=s.claude_effort)
    assert argv[argv.index("--effort") + 1] == "low"
    assert child_env(max_thinking_tokens=s.claude_max_thinking_tokens)["MAX_THINKING_TOKENS"] == "0"
    assert "düşünme" not in result.output


def test_think_estimate_includes_extra_output(book_pdf: Path) -> None:
    def output_tokens(args: list[str]) -> int:
        result = runner.invoke(cli.app, ["estimate", str(book_pdf), "--pages", "1", *args])
        assert result.exit_code == 0, result.output
        m = re.search(r"output ≈ ([\d ]+) tok", result.output)
        assert m is not None
        return int(m.group(1).replace(" ", ""))

    off = output_tokens(["--provider", "claude-cli", "--think", "off"])
    default = output_tokens(["--provider", "claude-cli"])
    medium = output_tokens(["--provider", "claude-cli", "--think", "medium"])
    high = output_tokens(["--provider", "claude-cli", "--think", "high"])
    haiku = output_tokens(["--provider", "claude-cli", "--model", "haiku"])

    assert default == off + 1500  # sonnet is the default model
    assert medium == default
    assert high == off + 6000
    assert haiku == off + 18000


def test_default_estimate_shows_thinking_and_off_hides_it(book_pdf: Path) -> None:
    default = runner.invoke(
        cli.app, ["estimate", str(book_pdf), "--pages", "1", "--provider", "claude-cli"]
    )
    off = runner.invoke(
        cli.app,
        ["estimate", str(book_pdf), "--pages", "1", "--provider", "claude-cli", "--think", "off"],
    )

    assert "düşünme: medium, değişken: çağrı başı +~1 500 tok" in default.output
    assert "±%40" in default.output
    assert "düşünme" not in off.output


def test_fake_provider_has_no_thinking_extra(book_pdf: Path) -> None:
    result = runner.invoke(
        cli.app, ["estimate", str(book_pdf), "--pages", "1", "--provider", "fake"]
    )

    assert result.exit_code == 0, result.output
    assert "düşünme" not in result.output


def test_think_invalid_value_rejected(book_pdf: Path) -> None:
    result = runner.invoke(
        cli.app, ["estimate", str(book_pdf), "--pages", "1", "--think", "extreme"]
    )

    assert result.exit_code == 2


def test_think_ignored_for_fake(book_pdf: Path) -> None:
    result = runner.invoke(
        cli.app,
        ["estimate", str(book_pdf), "--pages", "1", "--provider", "fake", "--think", "medium"],
    )

    assert result.exit_code == 0, result.output
    assert "--think yalnızca claude-cli" in result.output
    assert "düşünme" not in result.output


def test_estimate_force_counts_cached_blocks_without_deleting(book_pdf: Path) -> None:
    tr = runner.invoke(
        cli.app, ["translate", str(book_pdf), "--pages", "1", "--provider", "fake", "--yes"]
    )
    plain = runner.invoke(
        cli.app, ["estimate", str(book_pdf), "--pages", "1", "--provider", "fake"]
    )
    forced = runner.invoke(
        cli.app, ["estimate", str(book_pdf), "--pages", "1", "--provider", "fake", "--force"]
    )
    again = runner.invoke(
        cli.app, ["estimate", str(book_pdf), "--pages", "1", "--provider", "fake"]
    )

    assert tr.exit_code == 0, tr.output
    assert "çağrı: 0" in plain.output
    assert forced.exit_code == 0, forced.output
    assert "çağrı: 1" in forced.output
    assert "çağrı: 0" in again.output  # estimate --force deleted nothing


def test_estimate_profile_adds_glossary_tokens(book_pdf: Path, tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(
        '{"sozluk": {"leader": "lider", "followers": "takipçiler", "replication": "replikasyon"},'
        ' "tur": "teknik kitap (veri sistemleri)", "ton": "açık, teknik, akıcı Türkçe"}',
        encoding="utf-8",
    )

    def input_tokens(extra: list[str]) -> int:
        result = runner.invoke(
            cli.app,
            ["estimate", str(book_pdf), "--pages", "1", "--provider", "fake", *extra],
        )
        assert result.exit_code == 0, result.output
        m = re.search(r"input ≈ ([\d ]+) tok", result.output)
        assert m is not None
        return int(m.group(1).replace(" ", ""))

    assert input_tokens(["--profile", str(profile)]) > input_tokens([])


def test_missing_claude_binary_fails_before_planning(
    book_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)

    result = runner.invoke(
        cli.app, ["translate", str(book_pdf), "--pages", "1", "--provider", "claude-cli", "--yes"]
    )

    assert result.exit_code == 1
    assert "claude CLI bulunamadı" in _flat(result.output)
    assert "Tahmin" not in result.output


def test_unknown_price_is_shown_not_zero(book_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_settings(monkeypatch)

    result = runner.invoke(
        cli.app,
        ["estimate", str(book_pdf), "--pages", "1", "--provider", "claude-cli",
         "--model", "opus-experimental"],
    )  # fmt: skip

    out = _flat(result.output)
    assert result.exit_code == 0, result.output
    assert "fiyat bilinmiyor" in out
    assert "[pricing.opus-experimental]" in out
    assert "$0.000" not in out


def test_unknown_price_with_yes_still_warns(
    book_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_settings(monkeypatch)

    result = runner.invoke(
        cli.app,
        ["translate", str(book_pdf), "--pages", "1", "--provider", "claude-cli",
         "--model", "opus-experimental", "--yes"],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert "fiyat bilinmiyor" in _flat(result.output)


def test_malformed_config_is_friendly_error(
    book_pdf: Path, isolated_dirs: Path, fake: FakeTranslator
) -> None:
    cfg = isolated_dirs / "cfg"
    cfg.mkdir()
    (cfg / "config.toml").write_text("model = \n")

    result = runner.invoke(cli.app, ["estimate", str(book_pdf), "--pages", "1"])

    assert result.exit_code == 1
    assert "geçersiz ayar dosyası" in _flat(result.output)
    assert result.exception is None or isinstance(result.exception, SystemExit)
