"""Term consistency analysis (local, no AI) on synthetic sentence pairs."""

from __future__ import annotations

import time

from rosetta_engine.models import BookProfile
from rosetta_engine.quality.terms import (
    ENGLISH_LEFT,
    SentencePair,
    analyze,
    candidate_terms,
    sentence_pairs,
    tr_fold,
)
from rosetta_engine.store.repo import PairRow


def _pairs(*items: tuple[str, str]) -> list[SentencePair]:
    return [SentencePair(n // 3, n % 3, f"h{n}", en, tr) for n, (en, tr) in enumerate(items)]


REPLICATION = [
    ("Replication keeps copies of data.", "Çoğaltma verinin kopyalarını tutar."),
    ("We discuss replication in depth.", "Çoğaltmanın ayrıntılarını tartışıyoruz."),
    ("Replication helps availability.", "Çoğaltmayı erişilebilirlik için kullanırız."),
    ("Synchronous replication is slow.", "Eşzamanlı çoğaltma yavaştır."),
    ("Replication lag is a problem.", "Çoğaltma gecikmesi bir sorundur."),
    ("Leaderless replication is popular.", "Liderli olmayan replikasyon popülerdir."),
    ("Replication across regions is hard.", "Bölgeler arası replikasyonu zordur."),
    ("Async replication loses writes.", "Asenkron replikasyon yazmaları kaybeder."),
]


def test_tr_fold_handles_dotted_and_dotless_i() -> None:
    assert tr_fold("İndeks") == tr_fold("indeks") == "indeks"
    assert tr_fold("IŞIK") == "ışık"


def test_suffixed_forms_are_one_variant() -> None:
    (issue,) = [i for i in analyze(_pairs(*REPLICATION), BookProfile()) if i.term == "replication"]

    assert issue.source == "mined" and issue.preferred is None
    counts = {v.label: v.count for v in issue.variants}
    assert counts == {"çoğaltma": 5, "replikasyon": 3}
    assert issue.affected == []
    assert all(len(v.examples) <= 3 for v in issue.variants)


def test_single_rendering_is_not_an_issue() -> None:
    pairs = _pairs(*[(en, "Çoğaltma burada da kullanılır.") for en, _ in REPLICATION])
    assert [i for i in analyze(pairs, BookProfile()) if i.term == "replication"] == []


def test_glossary_mismatch_lists_affected() -> None:
    pairs = _pairs(
        ("The leader accepts writes.", "Lider yazmaları kabul eder."),
        ("A new leader is elected.", "Yeni bir lider seçilir."),
        ("The leader may fail.", "Liderin çökmesi mümkündür."),
        ("Followers copy the leader.", "Takipçiler önderi kopyalar."),
        ("The leader sends a log.", "Önder bir günlük gönderir."),
    )
    profile = BookProfile(glossary={"leader": "lider"})

    (issue,) = [i for i in analyze(pairs, profile) if i.term == "leader"]

    assert issue.source == "glossary" and issue.preferred == "lider"
    assert [o.text_hash for o in issue.affected] == ["h3", "h4"]


def test_glossary_term_fully_consistent_is_silent() -> None:
    pairs = _pairs(
        ("The leader accepts writes.", "Lider yazmaları kabul eder."),
        ("The leader may fail.", "Liderin çökmesi mümkündür."),
    )
    assert analyze(pairs, BookProfile(glossary={"leader": "lider"})) == []


def test_english_left_is_its_own_variant() -> None:
    pairs = _pairs(
        *REPLICATION[:5],
        ("Replication is everywhere.", "Replication her yerde."),
        ("Replication matters.", "Replication önemlidir."),
        ("Replication is a must.", "Replication şarttır."),
    )
    (issue,) = [i for i in analyze(pairs, BookProfile()) if i.term == "replication"]
    labels = {v.label: v.count for v in issue.variants}
    assert labels[ENGLISH_LEFT] == 3 and labels["çoğaltma"] == 5


def test_whole_word_match_set_is_not_dataset() -> None:
    pairs = _pairs(
        ("Each dataset is big.", "Her veri kümesi büyüktür."),
        ("A dataset changes.", "Bir veri kümesi değişir."),
    )
    profile = BookProfile(glossary={"set": "küme"})
    assert analyze(pairs, profile) == []
    assert "set" not in candidate_terms(pairs, BookProfile())


def test_ignored_and_do_not_translate_terms_are_skipped() -> None:
    pairs = _pairs(*REPLICATION)
    assert not [
        i for i in analyze(pairs, BookProfile(), {"replication"}) if i.term == "replication"
    ]
    profile = BookProfile(do_not_translate=["Replication"])
    assert not [i for i in analyze(pairs, profile) if i.term == "replication"]


def test_candidates_mined_from_frequent_phrases() -> None:
    pairs = _pairs(*REPLICATION)
    terms = candidate_terms(pairs, BookProfile(glossary={"quorum": "yeter sayı"}))
    assert terms[0] == "quorum"  # glossary first, always
    assert "replication" in terms
    assert "the" not in terms and "is" not in terms  # stopwords never start/end a phrase


def test_spacing_variants_merge() -> None:
    pairs = _pairs(
        ("The database is fast.", "Veritabanı hızlıdır."),
        ("A database stores rows.", "Veritabanı satırları saklar."),
        ("Every database has an index.", "Her veritabanının bir dizini vardır."),
        ("The database crashed.", "Veri tabanı çöktü."),
        ("This database scales.", "Bu veri tabanı ölçeklenir."),
    )
    issues = [i for i in analyze(pairs, BookProfile()) if i.term == "database"]
    assert issues == []  # one variant after merging "veri tabanı" ~ "veritabanı"


def _row(page: int, ord_: int, h: str, en: list[str], tr: list[str], **kw: object) -> PairRow:
    base: dict[str, object] = {
        "page_no": page,
        "block_ord": ord_,
        "block_type": "paragraph",
        "text_hash": h,
        "en_text": " ".join(en),
        "en_sentences": en,
        "tr_text": " ".join(tr),
        "tr_sentences": tr,
        "sentence_aligned": True,
        "unit_hash": None,
        "unit_role": None,
    }
    return PairRow(**(base | kw))  # type: ignore[arg-type]


def test_sentence_pairs_aligned_misaligned_and_joined() -> None:
    rows = [
        _row(0, 1, "a", ["One.", "Two."], ["Bir.", "İki."]),
        _row(0, 2, "b", ["Three.", "Four."], ["Üç ve dört."], sentence_aligned=False),
        _row(
            0,
            3,
            "h",
            ["It is old.", "It was built to be"],
            ["Eski.", "Bulut için yapıldı."],
            unit_hash="u",
            unit_role="head",
        ),
        _row(
            1, 0, "t", ["cloud native.", "It works."], ["Çalışır."], unit_hash="u", unit_role="tail"
        ),
    ]
    pairs = sentence_pairs(rows)

    assert [(p.en, p.tr) for p in pairs] == [
        ("One.", "Bir."),
        ("Two.", "İki."),
        ("Three. Four.", "Üç ve dört."),
        ("It is old.", "Eski."),
        ("It was built to be cloud native.", "Bulut için yapıldı."),
        ("It works.", "Çalışır."),
    ]
    assert {p.text_hash for p in pairs[3:]} == {"h"}  # located at the head


def test_analysis_is_fast_enough() -> None:
    base = [(en, tr) for en, tr in REPLICATION] * 1250  # 10k sentence pairs
    pairs = _pairs(*base)
    start = time.perf_counter()
    analyze(pairs, BookProfile(glossary={"replication": "çoğaltma"}))
    assert time.perf_counter() - start < 5


def test_phrase_repeating_a_shorter_term_is_dropped() -> None:
    pairs = _pairs(*[(f"Replication means {en}", tr) for en, tr in REPLICATION])
    terms = [i.term for i in analyze(pairs, BookProfile())]
    assert "replication" in terms
    assert "replication means" not in terms


def test_discovered_term_needs_enough_evidence() -> None:
    few = _pairs(*REPLICATION[:4], *REPLICATION[5:8])  # 7 distinct sentences
    assert [i for i in analyze(few, BookProfile()) if i.term == "replication"] == []
    # A glossary term is checked whatever the count.
    (issue,) = analyze(few, BookProfile(glossary={"replication": "çoğaltma"}))
    assert issue.source == "glossary" and len(issue.affected) == 3


def test_modifier_and_softened_forms_merge() -> None:
    pairs = _pairs(
        ("The provider bills monthly.", "Sağlayıcı aylık fatura keser."),
        ("Pick a provider carefully.", "Sağlayıcıyı dikkatle seçin."),
        ("Each provider differs.", "Her sağlayıcı farklıdır."),
        ("A provider may fail.", "Sağlayıcının çökmesi olasıdır."),
        ("The cloud provider scales.", "Bulut sağlayıcısı ölçeklenir."),
        ("Your provider charges more.", "Bulut sağlayıcınız daha pahalıdır."),
        ("Ask the provider first.", "Önce sağlayıcıya sorun."),
        ("No provider is perfect.", "Hiçbir sağlayıcı kusursuz değildir."),
    )
    assert [i for i in analyze(pairs, BookProfile()) if i.term == "provider"] == []


def test_same_word_rules() -> None:
    from rosetta_engine.quality.terms import _same_word

    assert _same_word("yükü", "yüke")  # short root, vowel case endings
    assert _same_word("örnek", "örneğin")  # k → ğ softening
    assert _same_word("veri tabanı", "veritabanı")
    assert _same_word("bulut sağlayıcısı", "sağlayıcı")
    assert not _same_word("sayı", "sayfa")
    assert not _same_word("kayıt", "kayıp")
    assert not _same_word("çoğaltma", "replikasyon")
