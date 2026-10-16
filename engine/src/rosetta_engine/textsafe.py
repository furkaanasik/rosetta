"""Make untrusted text (model output, provider messages) safe to print in a terminal."""

from __future__ import annotations

import re

# C0 controls except tab/newline, DEL and C1 controls (includes ESC, CSI, OSC introducers).
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def strip_controls(text: str) -> str:
    """Remove terminal control characters so model text cannot move the cursor, recolour the
    terminal or set its title. Newlines and tabs are kept."""
    return _CONTROLS.sub("", text.replace("\r\n", "\n"))
