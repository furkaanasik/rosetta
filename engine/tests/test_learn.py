"""Faz 6 core: dictionary build/lookup, vocab notebook, FSRS reviews, terms, stats."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from rosetta_engine.learn.dictionary import Dictionary, build, build_from_records, normalize
from rosetta_engine.learn.notebook import Notebook, add_terms, find_context, technical_terms
from rosetta_engine.learn.srs import CLOZE, Grade, ReviewService, cloze, stats, streak
from rosetta_engine.models import Block, BlockType, BookProfile, PageBlocks, text_hash
from rosetta_engine.store.db import connect, migrate
from rosetta_engine.store.learn_repo import ReviewRepo, VocabRepo
from rosetta_engine.store.repo import PageStatusRow, Repos, TranslationRow

RECORDS: list[dict[str, Any]] = [
    {
        "word": "replicate", "pos": "verb", "lang_code": "en",
        "senses": [{"glosses": ["To make a copy (replica) of."]}],
        "translations": [{"lang_code": "tr", "word": "replike etmek", "sense": "copy"}],
        "forms": [{"form": "replicated", "tags": ["past"]}, {"form": "replicates", "tags": []}],
    },
    {
        "word": "replicated", "pos": "verb", "lang_code": "en",
        "senses": [{"glosses": ["simple past of replicate"], "form_of": [{"word": "replicate"}]}],
    },
    {
        "word": "latency", "pos": "noun", "lang_code": "en",
        "senses": [{"glosses": ["The delay before a transfer of data begins."]}],
        "translations": [{"code": "tr", "word": "gecikme"}, {"lang_code": "de", "word": "Latenz"}],
    },
    {
        "word": "went", "pos": "noun", "lang_code": "en",
        "senses": [{"glosses": ["A path (archaic)."]}],
    },
    {
        "word": "go", "pos": "verb", "lang_code": "en",
        "senses": [{"glosses": ["To move."]}],
        "translations": [{"lang_code": "tr", "word": "gitmek"}],
        "forms": [{"form": "went", "tags": ["past"]}],
    },
    {
        "word": "consumer group", "pos": "noun", "lang_code": "en",
        "senses": [{"glosses": ["A set of consumers reading a topic together."]}],
    },
    {"word": "Paris", "pos": "name", "lang_code": "en", "senses": [{"glosses": ["A city."]}]},
    {"word": "Haus", "pos": "noun", "lang_code": "de", "senses": [{"glosses": ["house"]}]},
]  # fmt: skip

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
Learn = tuple[Notebook, VocabRepo, ReviewService]


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def dict_path(tmp_path: Path) -> Path:
    path = tmp_path / "dictionary.db"
    build_from_records(RECORDS, path)
    return path


@pytest.fixture
def dictionary(dict_path: Path) -> Iterator[Dictionary]:
    with Dictionary(dict_path) as d:
        yield d


@pytest.fixture
def repos() -> Iterator[Repos]:
    conn = connect(":memory:")
    migrate(conn)
    yield Repos.from_conn(conn)
    conn.close()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def learn(
    repos: Repos, dictionary: Dictionary, clock: Clock
) -> tuple[Notebook, VocabRepo, ReviewService]:
    vocab = VocabRepo(repos.conn, clock)
    srs = ReviewService(vocab, ReviewRepo(repos.conn, clock), clock=clock)
    return Notebook(vocab, srs, dictionary), vocab, srs


def _block(
    order: int, text: str, sentences: list[str], t: BlockType = BlockType.PARAGRAPH
) -> Block:
    return Block(
        page_no=4, order=order, type=t, bbox=(0, 0, 1, 1), font="f", size=10, bold=False,
        italic=False, text=text, sentences=sentences, text_hash=text_hash(text),
    )  # fmt: skip


PAGE = PageBlocks(
    page_no=4, width=500, height=700, has_text_layer=True,
    blocks=[
        _block(0, "replicated = 1", [], BlockType.CODE),
        _block(1, "Data is replicated. Latency matters.",
               ["Data is replicated.", "Latency matters."]),
    ],
)  # fmt: skip


# --- dictionary -------------------------------------------------------------------------------


def test_build_keeps_english_tr_and_skips_names(dictionary: Dictionary) -> None:
    meta = dictionary.meta()

    assert dictionary.available
    assert "CC BY-SA" in meta["license"]
    assert dictionary.lookup("Paris").found is False  # pos "name" skipped
    assert dictionary.lookup("Haus").found is False  # other language skipped
    assert dictionary.lookup("latency").tr == ["gecikme"]  # only Turkish translations


def test_lookup_inflected_form_finds_lemma(dictionary: Dictionary) -> None:
    r = dictionary.lookup("Replicated")

    assert r.query == "replicated"
    assert r.lemma == "replicate"
    assert r.tr == ["replike etmek"]
    assert r.definitions == ["To make a copy (replica) of."]


def test_lookup_prefers_candidate_with_turkish(dictionary: Dictionary) -> None:
    r = dictionary.lookup("went")

    assert r.lemma == "go"
    assert r.tr == ["gitmek"]
    assert dictionary.lemma_of("went") == "go"


def test_lookup_phrase_and_missing(dictionary: Dictionary) -> None:
    assert dictionary.lookup("Consumer  Group").definitions[0].startswith("A set of")
    missing = dictionary.lookup("zzzz")
    assert not missing.found
    assert missing.tr == []


def test_missing_dictionary_file_is_empty(tmp_path: Path) -> None:
    d = Dictionary(tmp_path / "none.db")
    d.close()

    assert not d.available
    assert not d.lookup("latency").found
    assert d.lemma_of("queries") == "query"  # simplemma fallback


def test_build_from_local_gzip_and_atomic_replace(tmp_path: Path) -> None:
    src = tmp_path / "dump.jsonl.gz"
    with gzip.open(src, "wt", encoding="utf-8") as f:
        for r in RECORDS[:3]:
            f.write(json.dumps(r) + "\n")
        f.write("{broken\n")
    target = tmp_path / "out" / "dictionary.db"

    stats_ = build(target, source=str(src))

    assert stats_.entries == 2  # replicate, latency (form-of entry has no own glosses)
    assert not target.with_suffix(".building").exists()
    with Dictionary(target) as d:
        assert d.lookup("replicates").lemma == "replicate"


def test_normalize() -> None:
    assert normalize("  Trade‐Offs’  x ") == "trade-offs' x"


# --- notebook + FSRS --------------------------------------------------------------------------


def test_find_context_skips_code_and_finds_sentence() -> None:
    ctx = find_context(PAGE, "replicated")

    assert ctx.sentence == "Data is replicated."
    assert ctx.block_ord == 1


def test_save_word_with_context_creates_card(
    learn: Learn,
) -> None:
    notebook, vocab, srs = learn

    saved = notebook.save("replicated", book_id=None, page=PAGE)
    again = notebook.save("replicates")

    assert saved.created
    assert saved.vocab.lemma == "replicate"
    assert saved.vocab.meaning == "replike etmek"
    assert saved.vocab.sentence == "Data is replicated."
    assert saved.vocab.page_no == 4
    assert not again.created  # same lemma
    assert len(srs.due()) == 1
    assert vocab.count() == 1


def test_mark_known_unknown_book_wide(learn: Learn) -> None:
    notebook, vocab, _ = learn
    notebook.save("latency")

    assert notebook.mark("latency", unknown=False)
    assert vocab.unknown_meanings() == {}
    assert notebook.mark("Latency", unknown=True)
    assert vocab.unknown_meanings() == {"latency": "gecikme"}
    assert not notebook.mark("nothing", unknown=False)
    assert notebook.mark("went", unknown=True)  # saves it first
    assert "go" in vocab.unknown_meanings()


def test_fsrs_review_schedules_forward(learn: Learn, clock: Clock) -> None:
    notebook, _, srs = learn
    v = notebook.save("latency").vocab

    row = srs.review(v.id, Grade.GOOD)
    row = srs.review(v.id, Grade.GOOD)

    assert row.reps == 2
    assert datetime.fromisoformat(row.due_at) > NOW
    assert srs.due() == []
    clock.now = NOW + timedelta(days=30)
    assert [r.vocab_id for r in srs.due()] == [v.id]


def test_lapse_counted_on_again_from_review_state(learn: Learn, clock: Clock) -> None:
    notebook, _, srs = learn
    v = notebook.save("latency").vocab
    srs.review(v.id, Grade.EASY)  # → Review state
    clock.now = NOW + timedelta(days=20)

    row = srs.review(v.id, Grade.AGAIN)

    assert row.lapses == 1


def test_grade_parse() -> None:
    assert Grade.parse("Good") is Grade.GOOD
    assert Grade.parse("1") is Grade.AGAIN
    assert Grade.parse("kolay") is Grade.EASY
    with pytest.raises(ValueError):
        Grade.parse("maybe")


def test_cloze() -> None:
    assert cloze("Data is Replicated.", "replicated") == f"Data is {CLOZE}."
    assert cloze("", "x") == CLOZE
    assert cloze("No match here.", "zzz").endswith(f"({CLOZE})")


def test_flashcard_back_uses_cached_sentence_translation(repos: Repos, learn: Learn) -> None:
    notebook, _, srs = learn
    book = repos.books.get_or_create("h" * 64, "Book", 10, "/b.pdf")
    repos.blocks.replace_page(book.id, PAGE, extractor_version=2)
    block = PAGE.blocks[1]
    repos.translations.put_page(
        [TranslationRow(book.id, 4, block.text_hash, "tr", "claude-cli", "sonnet",
                        "Veri çoğaltılır. Gecikme önemlidir.",
                        ["Veri çoğaltılır.", "Gecikme önemlidir."], True, 4)],
        PageStatusRow(book.id, 4, "tr", "claude-cli", "sonnet", "done"),
    )  # fmt: skip
    v = notebook.save("latency", book_id=book.id, page=PAGE).vocab

    card = srs.flashcard(v.id)

    assert card.front == f"{CLOZE} matters."
    assert card.back_word == "latency"
    assert card.back_meaning == "gecikme"
    assert card.back_sentence_tr == "Gecikme önemlidir."


def test_flashcard_without_translation(learn: Learn) -> None:
    notebook, _, srs = learn
    v = notebook.save("latency", sentence="Latency matters.").vocab

    assert srs.flashcard(v.id).back_sentence_tr is None


# --- stats + terms ----------------------------------------------------------------------------


def test_streak() -> None:
    days = ["2026-10-16", "2026-10-15", "2026-10-14", "2026-10-11"]

    assert streak(days, "2026-10-16") == 3
    assert streak(days[1:], "2026-10-16") == 2  # nothing today yet: count from yesterday
    assert streak([], "2026-10-16") == 0


def test_stats(learn: Learn, repos: Repos, clock: Clock) -> None:
    notebook, vocab, srs = learn
    a = notebook.save("latency").vocab
    notebook.save("go", unknown=False)
    srs.review(a.id, Grade.EASY)

    s = stats(vocab, ReviewRepo(repos.conn, clock), clock)

    assert s.total_words == 2
    assert s.unknown_words == 1
    assert s.reviewed_today == 1
    assert s.due_today == 1  # "go" is new and due now; "latency" moved days ahead
    assert s.streak_days == 1
    assert s.mature_words == 0


def test_technical_terms_and_add_all(repos: Repos, dictionary: Dictionary, learn: Learn) -> None:
    notebook, vocab, _ = learn
    book = repos.books.get_or_create("h" * 64, "Book", 10, "/b.pdf")
    repos.blocks.replace_page(book.id, PAGE, extractor_version=2)
    profile = BookProfile(glossary={"latency": "gecikme süresi", "replicated": "çoğaltılmış"})

    terms = technical_terms(profile, dictionary, vocab)
    saved = add_terms(notebook, vocab, book.id, terms)

    assert [t.term for t in terms] == ["latency", "replicated"]
    assert terms[0].dictionary_tr == ["gecikme"]
    assert terms[0].glossary_tr == "gecikme süresi"
    assert all(s.created for s in saved)
    lat = vocab.by_lemma("latency")
    assert lat is not None
    assert lat.meaning == "gecikme süresi"
    assert lat.sentence == "Latency matters."
    assert lat.page_no == 4
    assert technical_terms(profile, dictionary, vocab)[0].saved


def test_vocab_query_filters(learn: Learn, clock: Clock) -> None:
    notebook, vocab, _ = learn
    notebook.save("latency")
    clock.now = NOW + timedelta(days=2)
    notebook.save("go", sentence="We go home.")

    assert [v.lemma for v in vocab.query()] == ["go", "latency"]
    assert [v.lemma for v in vocab.query(search="home")] == ["go"]
    assert [v.lemma for v in vocab.query(since="2026-10-17")] == ["go"]
    assert vocab.query(book_id=99) == []


def test_meaning_falls_back_to_book_glossary(learn: Learn) -> None:
    notebook, _, _ = learn

    polled = notebook.save("Polling", glossary={"polling": "yoklama"})
    by_dict = notebook.save("latency", glossary={"latency": "IGNORED"})
    none = notebook.save("zzz", glossary={})

    assert polled.vocab.meaning == "yoklama"
    assert by_dict.vocab.meaning == "gecikme"  # dictionary wins when it has Turkish
    assert none.vocab.meaning == ""
