"""The one taxonomy: section ids, labels and reading order, read from ``sections.json``.

The app (window, standalone export), the publisher and the website all use this list, so a section is
renamed or reordered in one place. Retired sections (Local, since Oct 9, 2026) still label old editions.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SECTIONS_FILE = Path(__file__).with_name("sections.json")


@lru_cache(maxsize=1)
def load_sections() -> dict:
    return json.loads(SECTIONS_FILE.read_text(encoding="utf-8"))


def section_ids(include_retired: bool = True) -> list[str]:
    return [s["id"] for s in load_sections()["sections"] if include_retired or not s.get("retired")]


def section_label(category: str) -> str:
    """What readers see for a category id ('News' -> 'World & Nation'); an unknown id is shown as it is."""
    for s in load_sections()["sections"]:
        if s["id"] == category:
            return s["label"]
    return category


def sections_bytes() -> bytes:
    """The file as published to the website (``editions/sections.json``)."""
    return (json.dumps(load_sections(), ensure_ascii=False, indent=1) + "\n").encode("utf-8")
