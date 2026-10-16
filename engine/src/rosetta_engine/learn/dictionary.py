"""Offline EN→TR dictionary: build from Wiktionary (kaikki.org extract), look up with lemmas.

The dictionary is a separate SQLite file (``data_dir()/dictionary.db``) so it can be rebuilt or
shipped independently of the user's book database. Data: English Wiktionary via kaikki.org
(CC BY-SA 4.0 / GFDL) — attribution is stored in the ``meta`` table and shown in the docs.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import sqlite3
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, cast

import simplemma

from rosetta_engine import config

log = logging.getLogger(__name__)

DICTIONARY_FILE = "dictionary.db"
KAIKKI_URL = "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl.gz"
SOURCE_LICENSE = (
    "English Wiktionary via kaikki.org (wiktextract); text available under CC BY-SA 4.0 "
    "and GFDL. https://kaikki.org/ · https://en.wiktionary.org/"
)
TARGET_LANG = "tr"
MAX_GLOSSES = 4  # per entry; keeps the file small while covering the main senses
# Articles, determiners, pronouns, prepositions and conjunctions: always their own lemma.
FUNCTION_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "some",
        "any",
        "each",
        "every",
        "no",
        "all",
        "both",
        "either",
        "neither",
        "i",
        "me",
        "my",
        "mine",
        "you",
        "your",
        "yours",
        "he",
        "him",
        "his",
        "she",
        "her",
        "hers",
        "it",
        "its",
        "we",
        "us",
        "our",
        "ours",
        "they",
        "them",
        "their",
        "theirs",
        "who",
        "whom",
        "whose",
        "which",
        "what",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "into",
        "onto",
        "upon",
        "about",
        "over",
        "under",
        "after",
        "before",
        "between",
        "through",
        "during",
        "without",
        "within",
        "and",
        "or",
        "but",
        "nor",
        "so",
        "yet",
        "if",
        "than",
        "then",
        "as",
        "because",
        "while",
        "although",
        "though",
    ]
)
# Auxiliary verb forms whose spelling is also a rare noun ("are" = unit of area).
AUXILIARY_LEMMAS = {
    **dict.fromkeys(("am", "is", "are", "was", "were", "been", "being"), "be"),
    **dict.fromkeys(("has", "had", "having"), "have"),
    **dict.fromkeys(("does", "did", "done", "doing"), "do"),
}
SKIP_POS = frozenset({"name", "character", "symbol", "punct", "romanization"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY, lemma TEXT NOT NULL, pos TEXT NOT NULL,
  definitions TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS translations(lemma TEXT NOT NULL, pos TEXT NOT NULL, tr TEXT NOT NULL,
  sense TEXT NOT NULL DEFAULT '', UNIQUE(lemma, pos, tr));
CREATE TABLE IF NOT EXISTS forms(form TEXT NOT NULL, lemma TEXT NOT NULL, UNIQUE(form, lemma));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
_INDEXES = """
CREATE INDEX IF NOT EXISTS ix_entries_lemma ON entries(lemma);
CREATE INDEX IF NOT EXISTS ix_translations_lemma ON translations(lemma);
CREATE INDEX IF NOT EXISTS ix_forms_form ON forms(form);
"""
_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")


def dictionary_path() -> Path:
    return config.data_dir() / DICTIONARY_FILE


def normalize(text: str) -> str:
    """Lowercase, unify apostrophes/dashes, collapse whitespace."""
    text = text.replace("’", "'").replace("‐", "-").replace("‑", "-")
    return " ".join(text.lower().split())


# --- build ----------------------------------------------------------------------------------


@dataclass
class BuildStats:
    lines: int = 0
    entries: int = 0
    translations: int = 0
    forms: int = 0
    skipped: int = 0
    extra: dict[str, str] = field(default_factory=dict)


def _glosses(record: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for sense in record.get("senses", []):
        if sense.get("form_of") or sense.get("alt_of"):
            continue
        for g in sense.get("glosses", [])[-1:]:  # the most specific gloss of the sense
            if g and g not in out:
                out.append(g)
        if len(out) >= MAX_GLOSSES:
            break
    return out


def _translations(record: dict[str, Any]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    items = list(record.get("translations", []))
    for sense in record.get("senses", []):
        items.extend(sense.get("translations", []))
    for t in items:
        if (t.get("lang_code") or t.get("code")) != TARGET_LANG:
            continue
        word = (t.get("word") or "").strip()
        if word and (word, t.get("sense") or "") not in found:
            found.append((word, t.get("sense") or ""))
    return found


def _form_links(record: dict[str, Any], lemma: str) -> Iterator[tuple[str, str]]:
    """(inflected form, lemma) pairs: from ``forms`` and from form-of senses."""
    for f in record.get("forms", []):
        form = normalize(f.get("form") or "")
        tags = set(f.get("tags", []))
        if form and form != lemma and not tags & {"table-tags", "inflection-template"}:
            yield form, lemma
    for sense in record.get("senses", []):
        for target in sense.get("form_of", []):
            base = normalize(target.get("word") or "")
            if base and base != lemma:
                yield lemma, base


def build_from_records(
    records: Iterable[dict[str, Any]],
    target: Path,
    *,
    meta: dict[str, str] | None = None,
    progress: Callable[[BuildStats], None] | None = None,
) -> BuildStats:
    """Write a fresh dictionary to ``target`` (atomically, via a temp file)."""
    tmp = target.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(tmp))
    stats = BuildStats()
    try:
        conn.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + _SCHEMA)
        for record in records:
            stats.lines += 1
            if record.get("lang_code") != "en" or record.get("pos") in SKIP_POS:
                stats.skipped += 1
                continue
            lemma = normalize(record.get("word") or "")
            if not lemma:
                stats.skipped += 1
                continue
            pos = str(record.get("pos") or "")
            glosses = _glosses(record)
            trs = _translations(record)
            for form, base in _form_links(record, lemma):
                conn.execute("INSERT OR IGNORE INTO forms VALUES (?, ?)", (form, base))
                stats.forms += 1
            if not glosses and not trs:
                continue
            conn.execute(
                "INSERT INTO entries(lemma, pos, definitions) VALUES (?, ?, ?)",
                (lemma, pos, json.dumps(glosses, ensure_ascii=False)),
            )
            stats.entries += 1
            for word, sense in trs:
                conn.execute(
                    "INSERT OR IGNORE INTO translations VALUES (?, ?, ?, ?)",
                    (lemma, pos, word, sense),
                )
                stats.translations += 1
            if progress is not None and stats.lines % 100_000 == 0:
                progress(stats)
        info = {
            "source": KAIKKI_URL,
            "license": SOURCE_LICENSE,
            "built_at": datetime.now(UTC).isoformat(),
            "entries": str(stats.entries),
            "translations": str(stats.translations),
            **(meta or {}),
        }
        conn.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", list(info.items()))
        conn.executescript(_INDEXES)
        conn.commit()
    finally:
        conn.close()
    tmp.replace(target)
    return stats


def iter_jsonl(stream: IO[bytes]) -> Iterator[dict[str, Any]]:
    for raw in stream:
        line = raw.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            log.warning("skipping malformed dictionary line")


def build(
    target: Path | None = None,
    *,
    source: str = KAIKKI_URL,
    progress: Callable[[BuildStats], None] | None = None,
) -> BuildStats:
    """Stream the (gzipped) JSONL from a URL or local path; the raw dump is never stored."""
    target = target or dictionary_path()
    meta: dict[str, str] = {"source": source}
    if re.match(r"^https?://", source):
        req = urllib.request.Request(source, headers={"User-Agent": "rosetta-dictionary-builder"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            meta["last_modified"] = resp.headers.get("Last-Modified", "")
            stream = cast(
                IO[bytes], gzip.GzipFile(fileobj=resp) if source.endswith(".gz") else resp
            )
            return build_from_records(iter_jsonl(stream), target, meta=meta, progress=progress)
    path = Path(source)
    with cast(IO[bytes], gzip.open(path) if path.suffix == ".gz" else path.open("rb")) as f:
        return build_from_records(iter_jsonl(f), target, meta=meta, progress=progress)


# --- lookup ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class LookupResult:
    query: str
    lemma: str
    tr: list[str]
    definitions: list[str]

    @property
    def found(self) -> bool:
        return bool(self.tr or self.definitions)


def lemmatize(word: str) -> str:
    return normalize(str(simplemma.lemmatize(normalize(word), lang="en")))


def words(text: str) -> list[str]:
    return _WORD.findall(text)


class Dictionary:
    """Read-only lookups. A missing dictionary file behaves as an empty dictionary."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or dictionary_path()
        self._conn: sqlite3.Connection | None = None
        if self.path.is_file():
            self._conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)

    @property
    def available(self) -> bool:
        return self._conn is not None

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Dictionary:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def meta(self) -> dict[str, str]:
        if self._conn is None:
            return {}
        return dict(self._conn.execute("SELECT key, value FROM meta").fetchall())

    def _raw(self, lemma: str) -> tuple[list[str], list[str]]:
        assert self._conn is not None
        tr = [
            r[0]
            for r in self._conn.execute(
                "SELECT DISTINCT tr FROM translations WHERE lemma = ? ORDER BY rowid", (lemma,)
            )
        ]
        defs: list[str] = []
        for (blob,) in self._conn.execute(
            "SELECT definitions FROM entries WHERE lemma = ? ORDER BY id", (lemma,)
        ):
            for d in json.loads(blob):
                if d not in defs:
                    defs.append(d)
        return tr, defs

    def _bases(self, form: str) -> list[str]:
        assert self._conn is not None
        return [r[0] for r in self._conn.execute("SELECT lemma FROM forms WHERE form = ?", (form,))]

    def lookup(self, text: str) -> LookupResult:
        """Candidates: exact (phrase), inflection table, simplemma lemma.

        The first candidate with a Turkish equivalent wins (so ``went`` → ``go`` rather than the
        archaic noun ``went``); otherwise the first one with an English definition.
        """
        query = normalize(text)
        if self._conn is None or not query:
            return LookupResult(query=query, lemma=query, tr=[], definitions=[])
        if query in AUXILIARY_LEMMAS:
            lemma = AUXILIARY_LEMMAS[query]
            tr, defs = self._raw(lemma)
            return LookupResult(query=query, lemma=lemma, tr=tr, definitions=defs)
        if query in FUNCTION_WORDS:
            # Closed-class words are their own lemma; the inflection table has archaic links
            # (e.g. "the" listed as a form of "they") that would otherwise win.
            tr, defs = self._raw(query)
            return LookupResult(query=query, lemma=query, tr=tr, definitions=defs)
        candidates = [query, *self._bases(query)]
        if " " not in query:
            candidates.append(lemmatize(query))
        else:
            candidates.append(" ".join(lemmatize(w) for w in query.split()))
        first_defined: LookupResult | None = None
        for lemma in dict.fromkeys(candidates):
            tr, defs = self._raw(lemma)
            if tr:
                return LookupResult(query=query, lemma=lemma, tr=tr, definitions=defs)
            if defs and first_defined is None:
                first_defined = LookupResult(query=query, lemma=lemma, tr=[], definitions=defs)
        return first_defined or LookupResult(
            query=query, lemma=candidates[-1], tr=[], definitions=[]
        )

    def lemma_of(self, word: str) -> str:
        """Best lemma for a word, used to key vocabulary book-wide (same ranking as lookup)."""
        q = normalize(word)
        if self._conn is not None:
            r = self.lookup(q)
            if r.found:
                return r.lemma
        return lemmatize(q)
