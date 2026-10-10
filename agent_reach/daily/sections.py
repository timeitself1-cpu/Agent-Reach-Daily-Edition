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


def section_target(category: str) -> str:
    """Map a retired category to its current merge target; never change stored source categories."""
    rows = load_sections()["sections"]
    row = next((s for s in rows if s["id"] == category), {})
    target = row.get("merged_into")
    return next((s["id"] for s in rows if target and
                 (s["id"] == target or s.get("path", "").strip("/") == target)), category)


def section_groups(public: dict, minimum: int | None = None) -> list[dict]:
    """Current render groups, including old editions with separate retired sections.

    Count unique valid stories once; keep source categories, edition JSON and feed membership intact.
    """
    if minimum is None:
        from agent_reach.config import Settings
        minimum = public.get("min_section_stories", Settings().min_section_stories)
    stories = {s["id"]: s for s in public["stories"]}
    buckets, seen = {}, set()
    for sec in public.get("sections") or []:
        category = section_target(sec["category"])
        ids = buckets.setdefault(category, [])
        for story_id in sec["ids"]:
            if story_id in stories and story_id not in seen:
                ids.append(story_id)
                seen.add(story_id)
    for story_id, story in stories.items():
        if story_id not in seen:
            buckets.setdefault(section_target(story["category"]), []).append(story_id)
    groups, also = [], []
    for category in dict.fromkeys([*section_ids(), *buckets]):
        ids = buckets.get(category, [])
        if not ids:
            continue
        if len(ids) < minimum:
            also.extend(ids)
        else:
            groups.append({"category": category, "ids": ids})
    if also:
        groups.append({"category": "Also today", "ids": also})
    return groups
