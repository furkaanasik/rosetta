import json

from rosetta_engine.models import Block, BlockType, BookProfile, text_hash


def test_profile_accepts_turkish_keys() -> None:
    raw = json.dumps(
        {
            "tur": "teknik",
            "ton": "resmi",
            "hedef_dil": "tr",
            "cevrilmeyecek": ["Kafka"],
            "sozluk": {"replication": "replikasyon"},
            "kod_dili": ["java"],
        }
    )

    p = BookProfile.model_validate_json(raw)

    assert p.genre == "teknik"
    assert p.do_not_translate == ["Kafka"]
    assert p.glossary == {"replication": "replikasyon"}
    assert p.code_languages == ["java"]


def test_profile_accepts_english_keys() -> None:
    p = BookProfile.model_validate({"genre": "tech", "glossary": {"a": "b"}})

    assert p.genre == "tech"
    assert p.glossary == {"a": "b"}


def test_block_translatable() -> None:
    def mk(t: BlockType) -> Block:
        return Block(
            page_no=0, order=0, type=t, bbox=(0, 0, 1, 1), font="f", size=10,
            bold=False, italic=False, text="x", text_hash=text_hash("x"),
        )  # fmt: skip

    assert mk(BlockType.PARAGRAPH).translatable
    assert mk(BlockType.CAPTION).translatable
    assert not mk(BlockType.CODE).translatable
    assert not mk(BlockType.FURNITURE).translatable


def test_text_hash_is_16_hex() -> None:
    h = text_hash("replication")

    assert len(h) == 16
    assert h == text_hash("replication")


def test_ddia_profile_file_parses() -> None:
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "profiles" / "ddia.json"

    p = BookProfile.model_validate_json(path.read_text(encoding="utf-8"))

    assert p.glossary["vertex"] == "düğüm"
    assert p.glossary["set"] == "küme"
    assert "OLAP" in p.do_not_translate
    assert p.target_lang == "tr"
