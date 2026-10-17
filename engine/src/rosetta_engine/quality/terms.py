"""Term consistency of a book's cached translations. Local statistics only, no AI.

For each candidate English term (glossary keys, plus 1-3 word phrases mined from the source
text) the sentence pairs mentioning it are collected. Turkish words are reduced to a crude stem
signature (first ``STEM_LEN`` letters, Turkish-aware lower-casing) so suffixed forms count
together ("çoğaltma", "çoğaltmanın" → "çoğal"). The signatures most associated with the term
(Dice coefficient) are its candidate renderings; each occurrence goes to the strongest one
present. Two or more renderings with a real share → a *possible* inconsistency. Glossary terms
also report occurrences that do not use the glossary's rendering.

The 5-letter stem is a heuristic ("işlem"/"işlemci" collide), hence "possible" in the UI.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Literal

from rosetta_engine.extract.text_clean import join_across
from rosetta_engine.models import BookProfile
from rosetta_engine.store.repo import PairRow
from rosetta_engine.translate.prompt import mentions

MIN_OCC = 3  # a mined phrase must occur in at least this many sentences
MAX_MINED = 300  # mined candidates kept (by frequency)
STEM_LEN = 5  # Turkish signature: first letters of a word
MIN_SHARE = 0.15  # a rendering needs this share of the term's occurrences to count
MIN_COUNT = 2  # ... and at least this many occurrences
MIN_DICE = 0.15  # weaker associations are ignored
MIN_DICE_MINED = 0.3  # a discovered term's rendering must be at least this strongly associated
MIN_MINED_SENTENCES = 8  # distinct sentences before a discovered term can be an issue
TOP_SIGNATURES = 5
MERGE_PREFIX = 5  # renderings sharing this many letters (spaces removed) are one variant
MAX_EXAMPLES = 3
LOANWORD_PREFIX = 4  # a Turkish signature this close to the English term is a loanword
ENGLISH_LEFT = "(İngilizce bırakılmış)"

_STOPWORDS_TEXT = """a an the and or but nor so yet of in on at to for from by with without
    into onto over
    under about as than then that this these those there here it its it's is are was were be
    been being am do does did done have has had having can could may might must shall should
    will would not no yes if else when while where which who whom whose what why how all any
    each every some such other another more most less least many much few very also only just
    even still both either neither one two three first second new old same own up down out off
    again further once we you they he she i me my our your their them us his her him let lets
    via per like used use using uses make makes made get gets got way ways thing things often
    usually however therefore thus because since although though whether
    need needs needed become becomes became large small big number numbers time times example
    examples run runs running work works working case cases part parts lot lots kind kinds
    good better best well able want wants take takes give gives see look looks say says mean
    means allow allows provide provides different important possible"""
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())
# Turkish function words never count as a rendering ("bu sorgu" is "sorgu").
_TR_STOPWORDS_TEXT = """ve bir bu şu o da de ile için gibi daha çok en ki ya veya ama ancak fakat
    olan olarak her hem ne mi mı değil kadar sonra önce bile yani ise diğer başka tüm bütün aynı
    çünkü"""
TR_STOPWORDS = frozenset(_TR_STOPWORDS_TEXT.split())
# Consonant softening at a suffix boundary ("örnek" → "örneği", "kitap" → "kitabı").
_VOWELS = "aeıioöuü"
_SOFTENING = str.maketrans({"ğ": "k", "b": "p", "c": "ç", "d": "t"})

_CODE = re.compile(r"``.+?``|`[^`]+`")
_EN_WORD = re.compile(r"[A-Za-z]+")
_TR_WORD = re.compile(r"[^\W\d_]+")


def tr_fold(s: str) -> str:
    """Turkish-aware lower case: "I" → "ı", "İ" → "i" (``str.lower`` maps "I" to "i")."""
    return s.replace("I", "ı").replace("İ", "i").lower()


def _stem(word: str) -> str:
    return word[:STEM_LEN]


@dataclass(frozen=True)
class Occurrence:
    page_no: int  # 0-based
    block_ord: int
    text_hash: str
    en: str
    tr: str


@dataclass(frozen=True)
class Variant:
    key: str  # signature ("çoğal", "veri taban") or ENGLISH_LEFT
    label: str  # shortest surface form seen (suffix-free when possible)
    count: int
    examples: list[Occurrence] = field(default_factory=list)


@dataclass(frozen=True)
class TermIssue:
    term: str
    source: Literal["glossary", "mined"]
    preferred: str | None
    occurrences: int
    variants: list[Variant]
    affected: list[Occurrence]  # glossary terms: occurrences not using ``preferred``


@dataclass(frozen=True)
class SentencePair:
    page_no: int
    block_ord: int
    text_hash: str
    en: str
    tr: str


@dataclass
class _Prepared:
    pair: SentencePair
    en_low: str
    tr_words: list[str]  # Turkish-folded words
    sigs: frozenset[str]  # unigram + bigram stem signatures


# --- input ---------------------------------------------------------------------------------


def _pairs_of(
    page_no: int,
    block_ord: int,
    h: str,
    en_s: list[str],
    tr_s: list[str],
    en_text: str,
    tr_text: str,
    aligned: bool,
) -> list[SentencePair]:
    if aligned and en_s and len(en_s) == len(tr_s):
        return [SentencePair(page_no, block_ord, h, e, t) for e, t in zip(en_s, tr_s, strict=True)]
    if not tr_text.strip():
        return []
    return [SentencePair(page_no, block_ord, h, en_text, tr_text)]


def sentence_pairs(rows: Sequence[PairRow]) -> list[SentencePair]:
    """EN/TR sentence pairs: aligned rows sentence by sentence, misaligned rows whole.

    The two rows of a paragraph joined across a page break are merged back into one
    paragraph (located at the head) so the sentence crossing the break pairs correctly."""
    units: dict[str, dict[str, PairRow]] = {}
    for r in rows:
        if r.unit_hash and r.unit_role in ("head", "tail"):
            units.setdefault(r.unit_hash, {})[r.unit_role] = r
    out: list[SentencePair] = []
    for r in rows:
        unit = units.get(r.unit_hash or "")
        if unit is not None and len(unit) == 2:
            if r.unit_role == "tail":
                continue
            head, tail = unit["head"], unit["tail"]
            h_en = head.en_sentences or [head.en_text]
            t_en = tail.en_sentences or [tail.en_text]
            en_s = [*h_en[:-1], join_across(h_en[-1], t_en[0]), *t_en[1:]]
            tr_s = [*head.tr_sentences, *tail.tr_sentences]
            out += _pairs_of(
                head.page_no,
                head.block_ord,
                head.text_hash,
                en_s,
                tr_s,
                join_across(head.en_text, tail.en_text),
                " ".join(s for s in (head.tr_text, tail.tr_text) if s),
                head.sentence_aligned and tail.sentence_aligned,
            )
            continue
        out += _pairs_of(
            r.page_no,
            r.block_ord,
            r.text_hash,
            r.en_sentences or [r.en_text],
            r.tr_sentences,
            r.en_text,
            r.tr_text,
            r.sentence_aligned,
        )
    return out


def _signatures(words: Sequence[str]) -> frozenset[str]:
    """Stems of content words, plus stem pairs of adjacent content words."""
    keep = [w not in TR_STOPWORDS for w in words]
    stems = [_stem(w) for w in words]
    uni = [st for st, k in zip(stems, keep, strict=True) if k]
    bi = [
        f"{a} {b}"
        for (a, b), (ka, kb) in zip(pairwise(stems), pairwise(keep), strict=True)
        if ka and kb
    ]
    return frozenset([*uni, *bi])


def _prepare(pairs: Iterable[SentencePair]) -> list[_Prepared]:
    out = []
    for p in pairs:
        words = _TR_WORD.findall(tr_fold(p.tr))
        out.append(_Prepared(p, p.en.lower(), words, _signatures(words)))
    return out


# --- candidates ----------------------------------------------------------------------------


def _en_tokens(text: str) -> list[str]:
    return [w.lower() for w in _EN_WORD.findall(_CODE.sub(" ", text))]


def _ngrams(tokens: Sequence[str]) -> set[str]:
    out: set[str] = set()
    n_tok = len(tokens)
    for i in range(n_tok):
        if tokens[i] in STOPWORDS:
            continue
        for n in (1, 2, 3):
            j = i + n
            if j > n_tok or tokens[j - 1] in STOPWORDS:
                continue
            if n == 1 and len(tokens[i]) < 4:
                continue
            out.add(" ".join(tokens[i:j]))
    return out


def _excluded(profile: BookProfile, ignored: set[str]) -> set[str]:
    return {t.lower() for t in [*profile.do_not_translate, *ignored] if t}


def candidate_terms(
    pairs: Sequence[SentencePair],
    profile: BookProfile,
    ignored: set[str] | None = None,
    *,
    min_occ: int = MIN_OCC,
    limit: int = MAX_MINED,
) -> list[str]:
    """Glossary keys (always) plus mined phrases in at least ``min_occ`` sentences."""
    skip = _excluded(profile, ignored or set())
    glossary = [k for k in profile.glossary if k and k.lower() not in skip]
    known = {k.lower() for k in glossary}
    counts: Counter[str] = Counter()
    for p in pairs:
        counts.update(_ngrams(_en_tokens(p.en)))
    mined = [
        t for t, n in counts.most_common() if n >= min_occ and t not in skip and t not in known
    ][:limit]
    return [*glossary, *mined]


# --- analysis ------------------------------------------------------------------------------


def _surface(words: Sequence[str], key: str) -> list[str]:
    """Surface forms in ``words`` whose signature is ``key`` (one or two words)."""
    parts = key.split(" ")
    n = len(parts)
    return [
        " ".join(words[i : i + n])
        for i in range(len(words) - n + 1)
        if all(_stem(words[i + k]) == parts[k] for k in range(n))
    ]


def _preferred_sig(preferred: str) -> frozenset[str]:
    words = _TR_WORD.findall(tr_fold(preferred))
    if not words:
        return frozenset()
    if len(words) <= 2:
        return frozenset({" ".join(_stem(w) for w in words)})
    return frozenset(_stem(w) for w in words)


def _uses(prep: _Prepared, preferred: str, sig: frozenset[str]) -> bool:
    if not sig:
        return True
    if sig <= prep.sigs:
        return True
    compact = "".join(_TR_WORD.findall(tr_fold(preferred)))
    return bool(compact) and compact in "".join(prep.tr_words)


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


@dataclass
class _Bucket:
    key: str
    dice: float = 1.0  # association of the (strongest merged) signature with the term
    forms: Counter[str] = field(default_factory=Counter)
    occ: list[Occurrence] = field(default_factory=list)

    def label(self) -> str:
        if self.key == ENGLISH_LEFT or not self.forms:
            return self.key
        return min(self.forms, key=lambda f: (len(f), -self.forms[f], f))


def _same_word(a: str, b: str) -> bool:
    """Spacing aside, a shared long stem ("veri tabanı" ~ "veritabanı") or one form being the
    other plus a suffix ("veri" ~ "veriler", roots shorter than the signature)."""
    wa, wb = a.split(), b.split()
    # A modifier aside: "bulut sağlayıcısı" ~ "sağlayıcı", "bunun yerine" ~ "yerine".
    if wa and wb and (len(wa) > 1 or len(wb) > 1) and _same_word(wa[-1], wb[-1]):
        return True
    a, b = (x.replace(" ", "").translate(_SOFTENING) for x in (a, b))
    short, long_ = sorted((a, b), key=len)
    common = _common_prefix(a, b)
    if common >= MERGE_PREFIX or (len(short) >= 3 and long_.startswith(short)):
        return True
    # A short root with one-vowel case endings: "yükü" ~ "yüke".
    rest = (a[common:], b[common:])
    return common >= 3 and all(len(r) <= 1 and r in _VOWELS for r in rest)


def _merge(buckets: list[_Bucket]) -> list[_Bucket]:
    """One variant for renderings of the same word (shortest forms absorb longer ones)."""
    out: list[_Bucket] = []
    for b in sorted(buckets, key=lambda b: (len(b.label()), -len(b.occ), b.key)):
        target = next(
            (
                o
                for o in out
                if b.key != ENGLISH_LEFT
                and o.key != ENGLISH_LEFT
                and _same_word(o.label(), b.label())
            ),
            None,
        )
        if target is None:
            out.append(b)
        else:
            target.forms.update(b.forms)
            target.dice = max(target.dice, b.dice)
            target.occ.extend(b.occ)
    return out


def _occurrence(p: SentencePair) -> Occurrence:
    return Occurrence(p.page_no, p.block_ord, p.text_hash, p.en, p.tr)


def analyze(
    pairs: Sequence[SentencePair],
    profile: BookProfile,
    ignored: set[str] | None = None,
    *,
    min_occ: int = MIN_OCC,
    min_share: float = MIN_SHARE,
    terms: Sequence[str] | None = None,
) -> list[TermIssue]:
    """Possible inconsistencies, glossary mismatches first, then by spread."""
    ignored = ignored or set()
    prepared = _prepare(pairs)
    # Statistics count each distinct sentence pair once: a repeated block (same text twice)
    # must not make its other words look perfectly associated with the term.
    df: Counter[str] = Counter()
    for prep in _distinct(prepared):
        df.update(prep.sigs)
    glossary_low = {k.lower(): v for k, v in profile.glossary.items() if k}
    candidates = (
        terms if terms is not None else candidate_terms(pairs, profile, ignored, min_occ=min_occ)
    )
    skip = _excluded(profile, ignored)

    issues: list[TermIssue] = []
    for term in candidates:
        low = term.lower()
        if low in skip:
            continue
        occ = [p for p in prepared if mentions(low, p.en_low)]
        if not occ:
            continue
        preferred = glossary_low.get(low)
        issue = _term_issue(term, occ, df, preferred, min_share)
        if issue is not None:
            issues.append(issue)

    issues = _drop_redundant(issues)

    def rank(i: TermIssue) -> tuple[int, int, str]:
        spread = i.occurrences - max((v.count for v in i.variants), default=0)
        return (0 if i.affected else 1, -(len(i.affected) or spread), i.term)

    return sorted(issues, key=rank)


def _drop_redundant(issues: list[TermIssue]) -> list[TermIssue]:
    """A mined phrase that only repeats a shorter reported term ("replication means" with the
    same renderings as "replication") is dropped."""

    def counts(i: TermIssue) -> list[int]:
        return [v.count for v in i.variants]

    return [
        i
        for i in issues
        if i.source == "glossary"
        or not any(
            o.term != i.term and mentions(o.term.lower(), i.term.lower()) and counts(o) == counts(i)
            for o in issues
        )
    ]


def _distinct(prepared: Iterable[_Prepared]) -> list[_Prepared]:
    seen: set[tuple[str, str]] = set()
    out = []
    for prep in prepared:
        key = (prep.pair.en, prep.pair.tr)
        if key not in seen:
            seen.add(key)
            out.append(prep)
    return out


def _loanword(sig: str, term: str) -> bool:
    """A signature that starts like the English term ("repli" ~ "replication")."""
    return _common_prefix(sig, term) >= LOANWORD_PREFIX


def _term_issue(
    term: str,
    occ: list[_Prepared],
    df: Counter[str],
    preferred: str | None,
    min_share: float,
) -> TermIssue | None:
    n = len(occ)
    distinct = _distinct(occ)
    co: Counter[str] = Counter()
    for prep in distinct:
        co.update(prep.sigs)
    dice = {s: 2 * c / (len(distinct) + df[s]) for s, c in co.items()}
    low = term.lower()

    def strength(s: str) -> tuple[float, bool, int, str]:
        # Ties: a loanword-like rendering first (one word: "replikasyon", not "replikasyon
        # ağ"); otherwise the two-word signature ("veri tabanı" over "tabanı").
        loan = _loanword(s, low)
        words = s.count(" ")
        return (-dice[s], not loan, words if loan else -words, s)

    top = [s for s in sorted(dice, key=strength) if dice[s] >= MIN_DICE][:TOP_SIGNATURES]
    buckets: dict[str, _Bucket] = {}
    for prep in occ:
        if mentions(low, tr_fold(prep.pair.tr)):
            key = ENGLISH_LEFT
        else:
            key = next((s for s in top if s in prep.sigs), "")
        if not key:
            continue  # ambiguous: not reported as a variant
        bucket = buckets.setdefault(key, _Bucket(key, dice.get(key, 1.0)))
        if key != ENGLISH_LEFT:
            bucket.forms.update(_surface(prep.tr_words, key))
        bucket.occ.append(_occurrence(prep.pair))

    merged = sorted(_merge(list(buckets.values())), key=lambda b: (-len(b.occ), b.key))
    variants = [Variant(b.key, b.label(), len(b.occ), b.occ[:MAX_EXAMPLES]) for b in merged]
    assigned = sum(v.count for v in variants)
    # A discovered term needs strongly associated renderings: weak ones are mostly context
    # words of a few sentences (small books), not a second translation of the term.
    min_dice = MIN_DICE if preferred is not None else MIN_DICE_MINED
    real = [
        b
        for b in merged
        if len(b.occ) >= MIN_COUNT
        and assigned
        and len(b.occ) / assigned >= min_share
        and (b.key == ENGLISH_LEFT or b.dice >= min_dice)
    ]

    affected: list[Occurrence] = []
    if preferred is not None:
        sig = _preferred_sig(preferred)
        affected = [_occurrence(p.pair) for p in occ if not _uses(p, preferred, sig)]

    if preferred is None and len(distinct) < MIN_MINED_SENTENCES:
        real = []  # too little evidence for a discovered term
    if len(real) < 2 and not affected:
        return None
    return TermIssue(
        term=term,
        source="glossary" if preferred is not None else "mined",
        preferred=preferred,
        occurrences=n,
        variants=variants,
        affected=affected,
    )
