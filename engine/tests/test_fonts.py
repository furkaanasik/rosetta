import pytest

from rosetta_engine.extract.fonts import (
    font_family,
    is_bold,
    is_italic,
    is_monospace,
    strip_subset,
)


@pytest.mark.parametrize("font", ["XYZABC+Consolas", "CourierNewPSMT", "UbuntuMono-Regular"])
def test_monospace_by_name(font: str) -> None:
    assert is_monospace(font, 0)


def test_monospace_by_flag() -> None:
    assert is_monospace("Minion-Regular", 8)


def test_proportional_font_is_not_mono() -> None:
    assert not is_monospace("Minion-Regular", 0)


def test_strip_subset_prefix() -> None:
    assert strip_subset("ABCDEF+Courier-Bold") == "Courier-Bold"
    assert strip_subset("Courier-Bold") == "Courier-Bold"


def test_semibold_italic() -> None:
    assert is_bold("Myriad-SemiboldIt")
    assert is_italic("Myriad-SemiboldIt")


def test_flags_bold_italic() -> None:
    assert is_bold("Whatever", 16)
    assert is_italic("Whatever", 2)
    assert not is_bold("MinionPro-Regular", 4)
    assert not is_italic("MinionPro-Regular", 4)


def test_family() -> None:
    assert font_family("MinionPro-Regular", 4) == "serif"
    assert font_family("MyriadPro-SemiboldCond", 20) == "sans"  # serif flag lies
    assert font_family("UbuntuMono-Bold", 28) == "mono"
