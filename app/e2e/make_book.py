"""Build the synthetic E2E book (same pages as the engine's test fixtures). Run inside engine/."""

import sys

import pymupdf

sys.path.insert(0, "tests")
from conftest import build_book_page  # noqa: E402

doc = pymupdf.open()
for n in range(4):
    page = doc.new_page()
    build_book_page(page, n + 101)
    if n == 2:
        # The dev fake translator fails once on this marker: exercises "retry failed pages".
        page.insert_textbox(
            pymupdf.Rect(50, 650, 545, 700),
            "This paragraph is part of the test book. Marker ROSETTA_E2E_FAIL_ONCE here.",
            fontname="tiro",
            fontsize=10,
        )
doc.set_toc([[1, "Chapter 5. Replication", 1]])
doc.save(sys.argv[1])
