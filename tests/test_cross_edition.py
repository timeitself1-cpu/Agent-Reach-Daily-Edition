"""Event identity across editions, scored on the labelled October 7 editions (tests/cross_edition.py).

The floor test keeps today's matcher from getting worse; the strict xfail is the Phase 2 target (PLAN 2.4):
when a matcher reaches it, the mark must go."""

from __future__ import annotations

import pytest

from tests.cross_edition import EDITIONS, load_gold, report


def test_the_answer_key_is_complete_and_consistent():
    gold = load_gold()
    assert len(gold.event) == 536 and len(set(gold.event.values())) == 256
    for name in EDITIONS:  # every edition has labelled stories
        assert gold.events_of(name)
    # hand-checked cases: one event across editions, and two events that shared a report
    def story(start: str) -> str:
        return next(k for k, h in gold.headline.items() if h.startswith(start))

    assert gold.same(story("Apple Is Reportedly Partnering with LG"), story("Apple and LG Reportedly Teaming up")) is True
    # a report shared by HP's leak and Microsoft's launch: related, not one event, and not scored
    assert gold.same(story("Microsoft Launches Surface Laptop Ultra"), story("Nvidia RTX Spark for $2,999.99")) is None
    assert gold.same(story("Trump Wants to Make Golf Club"), story("Trump's Retreat: From the Gulf")) is False


def test_todays_matcher_does_not_get_worse():
    """Baseline of October 8 (changes._match): consecutive editions P 0.967 R 0.954; 6 h+ apart P 0.966 R 0.752."""
    scores = report()
    near, far = scores["consecutive"], scores["6h+ apart"]
    assert near.precision >= 0.96 and near.recall >= 0.95
    assert far.precision >= 0.96 and far.recall >= 0.75


@pytest.mark.xfail(strict=True, reason="Phase 2 target: same event recognised across a day, no false continuations")
def test_events_are_recognised_hours_apart_without_false_continuations():
    far = report()["6h+ apart"]
    assert far.precision >= 0.99 and far.recall >= 0.90
