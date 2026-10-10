"""Regression tests for the false-split heuristic paired evaluation."""
from __future__ import annotations

from agent_reach.models import CleanedTrendItem, SourceName
from agent_reach.pipeline.same_event import _different_central_actors
from scripts.evaluate_actor_heuristic import PAIRED_DATASET, _refined_different_central_actors


def _item(title: str, item_id: int = 1) -> CleanedTrendItem:
    return CleanedTrendItem(
        item_id=item_id,
        source=SourceName.NEWS_RSS,
        title=title,
        url=f"https://example.com/{item_id}",
        normalized_title=title,
        heuristic_score=0.9,
    )


def test_baseline_heuristic_on_same_event_different_wording():
    """Verify known behavior of baseline _different_central_actors on Category 1."""
    # Official title vs Personal name triggers a false split in baseline
    a = _item("Saudi Crown Prince unveils massive new terminal expansion at Riyadh airport")
    b = _item("Mohammed bin Salman announces multibillion-dollar Riyadh international airport expansion")
    assert _different_central_actors(a, b) is True  # Baseline false split confirmed


def test_refined_heuristic_eliminates_false_splits_on_same_event():
    """Refined heuristic recognizes shared entities and eliminates Category 1 false splits."""
    cat1_cases = [c for c in PAIRED_DATASET if c.category.startswith("1.")]
    for case in cat1_cases:
        a = _item(case.headline_a)
        b = _item(case.headline_b)
        assert _refined_different_central_actors(a, b) is False, f"False split on {case.pair_id}: {case.headline_a} vs {case.headline_b}"


def test_refined_heuristic_maintains_protection_against_false_merges():
    """Refined heuristic preserves protection for distinct entities."""
    # Starship vs New Glenn
    a = _item("SpaceX launches Starship mega-rocket on eighth orbital test flight from Texas")
    b = _item("Blue Origin launches New Glenn rocket on inaugural mission from Florida")
    assert _refined_different_central_actors(a, b) is True

    # Mount Etna vs Kilauea
    a = _item("Mount Etna erupts in Sicily sending ash cloud over Catania airport")
    b = _item("Kilauea volcano resumes eruption inside Hawaii Volcanoes National Park")
    assert _refined_different_central_actors(a, b) is True

    # Kamala Harris vs Donald Trump
    a = _item("Kamala Harris delivers economic policy address in Philadelphia")
    b = _item("Donald Trump speaks on tariffs and trade during Detroit rally")
    assert _refined_different_central_actors(a, b) is True
