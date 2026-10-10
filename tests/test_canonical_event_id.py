"""Unit and regression tests for stable_event_id and canonical_event_id."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_reach.daily.edition import DailyEdition, EvidenceLink, Story
from agent_reach.daily.event_registry import EventRegistry
from agent_reach.models import CategoryEnum, CleanedTrendItem, SourceName
from agent_reach.pipeline.evidence import (
    canonical_event_id,
    stable_event_id,
)

FIXTURES_REAL = Path(__file__).parent / "fixtures" / "real"
WEBSITE_EDITIONS = Path(__file__).parent.parent / "website" / "editions"


def _make_cleaned_item(
    item_id: int,
    title: str,
    ts: datetime | None = None,
    meta: dict | None = None,
) -> CleanedTrendItem:
    if ts is None:
        ts = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    return CleanedTrendItem(
        item_id=item_id,
        source=SourceName.NEWS_RSS,
        title=title,
        url=f"https://example.com/item/{item_id}",
        timestamp=ts,
        normalized_title=title,
        heuristic_score=0.9,
        metadata=meta or {},
    )


def _make_evidence_link(
    item_id: int,
    title: str,
    ts: datetime | None = None,
) -> EvidenceLink:
    if ts is None:
        ts = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    return EvidenceLink(
        item_id=item_id,
        source="news_rss",
        source_name="Reuters",
        title=title,
        url=f"https://example.com/item/{item_id}",
        published_at_utc=ts,
    )


# ----------------------------------------------------------------------
# 1. Normal identity path tests
# ----------------------------------------------------------------------
def test_stable_event_id_with_cleaned_items():
    """Verify CleanedTrendItem objects do not raise AttributeError ('CleanedTrendItem' object has no attribute 'lower')."""
    item = _make_cleaned_item(
        1,
        "Nobel Prize in Chemistry awarded to David Baker",
        meta={"location": "Stockholm"},
    )
    eid = stable_event_id([item])
    assert eid.startswith("evt_")
    assert len(eid) == 16  # 'evt_' + 12 hex chars

    # Calling canonical_event_id with the item list produces the exact same ID
    assert canonical_event_id([item]) == eid


def test_stable_event_id_evidence_growth_preserves_id():
    """Adding an additional source to an existing event should preserve its stable ID."""
    t = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
    item1 = _make_cleaned_item(1, "Nobel Prize in Chemistry awarded to David Baker", ts=t)
    item2 = _make_cleaned_item(2, "David Baker wins Nobel Prize", ts=t)

    id_one = stable_event_id([item1])
    id_both = stable_event_id([item1, item2])
    assert id_one == id_both


def test_stable_event_id_with_evidence_links():
    """Verify EvidenceLink instances (from Story.evidence) compute valid stable IDs."""
    t = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    ev1 = _make_evidence_link(1, "Nobel Prize in Chemistry awarded to David Baker", ts=t)
    ev2 = _make_evidence_link(2, "Baker wins Nobel Prize", ts=t)

    eid = stable_event_id([ev1, ev2])
    assert eid.startswith("evt_")

    # Item with same title and date produces identical stable event ID
    item = _make_cleaned_item(1, "Nobel Prize in Chemistry awarded to David Baker", ts=t)
    assert stable_event_id([item]) == eid


# ----------------------------------------------------------------------
# 2. Priority and object dispatch in canonical_event_id
# ----------------------------------------------------------------------
def test_canonical_event_id_prefers_entity_id():
    """When an entity_id is available on a Story or dict, it takes precedence."""
    story = Story(
        rank=1,
        story_id="s123456789012",
        entity_id="entity_abc123456",
        headline="Sample Story Headline",
        category=CategoryEnum.NEWS,
        sentences=["First sentence."],
        momentum="STEADY",
        velocity_basis="cold_start",
        relevance_score=10,
        velocity_score=80.0,
        combined_score=90.0,
        platforms=["news_rss"],
        raw_item_count=1,
        member_item_ids=[1],
        evidence=[_make_evidence_link(1, "Sample Evidence Title")],
    )
    assert canonical_event_id(story) == "evt_entity_abc12"

    d = {"entity_id": "entity_xyz987654", "headline": "Dict headline"}
    assert canonical_event_id(d) == "evt_entity_xyz98"


def test_canonical_event_id_prefers_existing_event_id():
    """Dict with already computed event_id returns that event_id."""
    d = {"event_id": "evt_existing1234", "headline": "Some headline"}
    assert canonical_event_id(d) == "evt_existing1234"


def test_canonical_event_id_story_uses_evidence():
    """Story with empty entity_id computes stable ID from its evidence links."""
    ev = _make_evidence_link(1, "Nobel Prize in Chemistry awarded to David Baker")
    story = Story(
        rank=1,
        story_id="s123456789012",
        entity_id="",
        headline="Baker Wins Nobel Prize in Chemistry",
        category=CategoryEnum.NEWS,
        sentences=["David Baker won the Nobel Prize."],
        momentum="STEADY",
        velocity_basis="cold_start",
        relevance_score=10,
        velocity_score=80.0,
        combined_score=90.0,
        platforms=["news_rss"],
        raw_item_count=1,
        member_item_ids=[1],
        evidence=[ev],
    )
    eid = canonical_event_id(story)
    assert eid.startswith("evt_")
    assert eid == stable_event_id([ev])


# ----------------------------------------------------------------------
# 3. Fallback scenarios
# ----------------------------------------------------------------------
def test_canonical_event_id_headline_fallback_for_dict():
    """Dict without event_id, entity_id, or sources falls back to headline hash."""
    headline = "SpaceX Falcon 9 Launches Starlink Satellites"
    expected = "evt_" + hashlib.sha256(f"{headline.casefold()}|fallback".encode()).hexdigest()[:12]
    actual = canonical_event_id({"headline": headline})
    assert actual == expected


def test_canonical_event_id_headline_fallback_for_object_without_evidence():
    """Object without entity_id or evidence items falls back to headline hash."""
    class DummyStory:
        headline = "Breaking news: test headline"

    expected = "evt_" + hashlib.sha256(b"breaking news: test headline|fallback").hexdigest()[:12]
    assert canonical_event_id(DummyStory()) == expected


def test_canonical_event_id_handles_none_and_empty():
    """None and empty inputs return valid fallback IDs without raising errors."""
    assert canonical_event_id(None).startswith("evt_")
    assert stable_event_id([]).startswith("evt_")
    assert stable_event_id([]) == "evt_" + hashlib.sha256(b"empty").hexdigest()[:12]


# ----------------------------------------------------------------------
# 4. Cross-edition verification on real edition fixtures
# ----------------------------------------------------------------------
def test_cross_edition_continuity_on_real_fixtures(tmp_path):
    """Test real editions in tests/fixtures/real/ with EventRegistry."""
    path1 = FIXTURES_REAL / "2026-10-07-rc12d-r2.json"
    path2 = FIXTURES_REAL / "2026-10-07-rc12d2-r2.json"
    if not (path1.exists() and path2.exists()):
        pytest.skip("Real edition fixtures not found")

    ed1 = DailyEdition.model_validate(json.loads(path1.read_text(encoding="utf-8")))
    ed2 = DailyEdition.model_validate(json.loads(path2.read_text(encoding="utf-8")))

    registry = EventRegistry(tmp_path / "registry")

    # Record first edition
    ed1_records = {}
    for s in ed1.stories:
        eid = canonical_event_id(s)
        assert eid.startswith("evt_")
        rec = registry.update_from_story(s, "2026-10-07", revision=1)
        assert rec.event_id == eid
        assert rec.current_headline == s.headline
        ed1_records[s.headline] = eid

    # Record second edition
    for s in ed2.stories:
        eid = canonical_event_id(s)
        assert eid.startswith("evt_")
        rec = registry.update_from_story(s, "2026-10-07", revision=2)
        assert rec.event_id == eid


def test_published_website_editions_continuity():
    """Validate canonical_event_id against published editions in website/editions/."""
    dates = ["2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10"]
    loaded = 0
    total_stories = 0

    for d in dates:
        p = WEBSITE_EDITIONS / f"{d}.json"
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        stories = data.get("stories", [])
        loaded += 1
        for story in stories:
            total_stories += 1
            eid = canonical_event_id(story)
            assert eid.startswith("evt_")
            assert len(eid) == 16

    assert loaded >= 3, "At least 3 published editions should be present"
    assert total_stories >= 50, "Should test across at least 50 real stories"
