from rosetta_engine.extract.classify import PageContext, Unit, classify, toc_key
from rosetta_engine.extract.pdf_reader import RawLine, RawSpan
from rosetta_engine.extract.stats import TypographyStats
from rosetta_engine.models import BBox, BlockType

STATS = TypographyStats(body_size=10.5, heading_sizes={25.0: 1, 19.0: 2, 16.0: 3})
SERIF = "MinionPro-Regular"


def _unit(
    *lines: str,
    font: str = SERIF,
    size: float = 10.5,
    flags: int = 4,
    x0: float = 72,
    y0: float = 100,
) -> Unit:
    raw = []
    for i, text in enumerate(lines):
        bbox: BBox = (x0, y0 + 13 * i, 432, y0 + 13 * i + 12)
        raw.append(
            RawLine(spans=(RawSpan(text, font, size, flags, bbox, (x0, bbox[3])),), bbox=bbox)
        )
    return Unit(lines=tuple(raw), bbox=(x0, y0, 432, y0 + 13 * len(lines)))


def _ctx(**kw: object) -> PageContext:
    return PageContext(height=661.5, stats=STATS, body_left=72, **kw)  # type: ignore[arg-type]


def test_code() -> None:
    u = _unit("SELECT *", "  FROM t", font="UbuntuMono-Regular", size=8.5, flags=12)
    assert classify(u, _ctx()).type == BlockType.CODE


def test_caption_next_to_figure() -> None:
    u = _unit("Figure 5-1. A leader and followers.", font="MinionPro-It", flags=6, y0=340)
    assert classify(u, _ctx(anchors=[(72, 100, 432, 330)])).type == BlockType.CAPTION


def test_caption_label_far_from_anchor_is_paragraph() -> None:
    u = _unit("Figure 5-1. A leader and followers.", y0=500)
    assert classify(u, _ctx(anchors=[(72, 100, 432, 330)])).type == BlockType.PARAGRAPH


def test_prose_mentioning_figure_is_not_caption() -> None:
    u = _unit("Figure 5-1 shows the leader.", y0=335)
    assert classify(u, _ctx(anchors=[(72, 100, 432, 330)])).type == BlockType.PARAGRAPH


def test_heading_level_from_toc() -> None:
    u = _unit(
        "CHAPTER 1",
        "Trade-Offs in Data Systems Architecture",
        font="MyriadPro-SemiboldCond",
        size=25.2,
        flags=20,
    )
    toc = {toc_key("Chapter 1. Trade-Offs in Data Systems Architecture"): 1}
    c = classify(u, _ctx(toc=toc))
    assert (c.type, c.heading_level) == (BlockType.HEADING, 1)


def test_heading_level_from_size() -> None:
    u = _unit("Materializing Timelines", font="MyriadPro-SemiboldCond", size=15.8, flags=20)
    c = classify(u, _ctx())
    assert (c.type, c.heading_level) == (BlockType.HEADING, 3)


def test_bold_short_line_is_level_4_heading() -> None:
    u = _unit(
        "From data warehouse to data lake", font="MyriadPro-SemiboldCond", size=11.6, flags=20
    )
    c = classify(u, _ctx())
    assert (c.type, c.heading_level) == (BlockType.HEADING, 4)


def test_footnote_small_and_low() -> None:
    u = _unit("1 Also called primaries.", size=8, y0=600)
    assert classify(u, _ctx()).type == BlockType.FOOTNOTE


def test_bullet_list_item() -> None:
    c = classify(_unit("• Writes go to the leader."), _ctx())
    assert (c.type, c.list_marker) == (BlockType.LIST_ITEM, "•")


def test_numbered_list_item() -> None:
    c = classify(_unit("2. Then follow the edges."), _ctx())
    assert (c.type, c.list_marker) == (BlockType.LIST_ITEM, "2.")


def test_vector_marker_list_item() -> None:
    u = _unit("First find the vertex.", x0=90, y0=391)
    c = classify(u, _ctx(markers=[(72.6, 393.0, 81.0, 401.4)]))
    assert (c.type, c.list_marker) == (BlockType.LIST_ITEM, "")


def test_epigraph_is_aside_paragraph() -> None:
    u = _unit(
        "There are no solutions; there are only trade-offs.", font="MinionPro-It", size=9, flags=6
    )
    c = classify(u, _ctx())
    assert (c.type, c.aside) == (BlockType.PARAGRAPH, True)


def test_plain_paragraph() -> None:
    c = classify(_unit("Data is central.", "It grows."), _ctx())
    assert (c.type, c.aside) == (BlockType.PARAGRAPH, False)
