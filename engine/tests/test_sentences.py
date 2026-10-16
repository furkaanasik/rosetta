from rosetta_engine.extract.sentences import split_sentences


def test_abbreviation_does_not_split() -> None:
    assert split_sentences("Use e.g. Kafka. It works.") == ["Use e.g. Kafka.", "It works."]


def test_backtick_never_split() -> None:
    assert split_sentences("Call `a.b()`. Done.") == ["Call `a.b()`.", "Done."]


def test_decimals_versions_filenames() -> None:
    text = "Version v1.2 reads config.yaml in 3.5 seconds. Then it stops."
    assert split_sentences(text) == [
        "Version v1.2 reads config.yaml in 3.5 seconds.",
        "Then it stops.",
    ]


def test_initials_not_split() -> None:
    assert split_sentences("Written by A. B. Smith in 2001.") == ["Written by A. B. Smith in 2001."]


def test_citation_stays_with_previous_sentence() -> None:
    assert split_sentences("It scales. [12] Next one.") == ["It scales. [12]", "Next one."]


def test_question_exclamation_and_quotes() -> None:
    assert split_sentences("Why? Because “it works.” Fine!") == [
        "Why?",
        "Because “it works.”",
        "Fine!",
    ]


def test_caption_label_kept_with_caption() -> None:
    assert split_sentences("Figure 3-1. A schema. More text.") == [
        "Figure 3-1. A schema.",
        "More text.",
    ]


def test_empty() -> None:
    assert split_sentences("  ") == []
