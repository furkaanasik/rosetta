from rosetta_engine.extract.text_clean import (
    Seg,
    clean_text,
    code_text,
    detect_soft_hyphen,
    inline_text,
    join_lines,
)


def test_dehyphenate_lowercase_continuation() -> None:
    assert join_lines(["replica-", "tion"]) == "replication"


def test_keep_hyphen_before_uppercase() -> None:
    assert join_lines(["client-", "Side"]) == "client-Side"


def test_keep_hyphen_after_short_fragment() -> None:
    assert join_lines(["re-", "use"]) == "re-use"


def test_unicode_soft_hyphen_book_keeps_ascii_compounds() -> None:
    lines = ["analysis-", "friendly concur‐", "rency"]
    assert join_lines(lines, soft="‐") == "analysis-friendly concurrency"


def test_detect_soft_hyphen() -> None:
    samples = [("‐", "r"), ("‐", "s"), ("-", "f"), (".", "T")]
    assert detect_soft_hyphen(samples) == "‐"
    assert detect_soft_hyphen([("-", "t")]) == "-"


def test_clean_text_ligatures_soft_hyphen_nbsp_spaces() -> None:
    assert clean_text("eﬃcient  data­base x") == "efficient database x"


def test_inline_mono_wrapped_in_backticks() -> None:
    lines = [
        [Seg("use the "), Seg("follows", mono=True), Seg(" table for")],
        [Seg("current_user", mono=True), Seg(" lookups")],
    ]
    assert inline_text(lines) == "use the `follows` table for `current_user` lookups"


def test_inline_mono_with_backtick_uses_double() -> None:
    assert inline_text([[Seg("run "), Seg("a`b", mono=True)]]) == "run ``a`b``"


def test_superscript_becomes_footnote_marker() -> None:
    assert inline_text([[Seg("data"), Seg("2", superscript=True), Seg(" here")]]) == "data[^2] here"


def test_code_text_keeps_indentation_and_reconstructs_offsets() -> None:
    lines = [(72.0, "SELECT *"), (72.0, "  FROM t"), (80.5, "WHERE x")]
    assert code_text(lines, left=72.0, char_width=4.25) == "SELECT *\n  FROM t\n  WHERE x"


def test_join_across_dehyphenates_page_break() -> None:
    from rosetta_engine.extract.text_clean import join_across

    assert join_across("distrib-", "uted systems") == "distributed systems"
    assert join_across("to be", "cloud native") == "to be cloud native"
    assert join_across("", "cloud") == "cloud"
    assert join_across("be ", "  ") == "be"


def test_join_across_unicode_soft_hyphen_keeps_ascii_compounds() -> None:
    from rosetta_engine.extract.text_clean import UNICODE_HYPHEN, join_across

    assert join_across("analysis-", "friendly data", UNICODE_HYPHEN) == "analysis-friendly data"
    assert join_across("distrib‐", "uted", UNICODE_HYPHEN) == "distributed"
