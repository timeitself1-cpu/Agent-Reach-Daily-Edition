"""The public sample of an edition (``--export-sample``): what a website may show from a real edition."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_reach.daily.edition import DailyEdition
from agent_reach.daily.sample import SampleError, edition_sample

REAL = Path(__file__).parent / "fixtures" / "real" / "2026-10-07-rc12d-r1.json"


def _edition() -> DailyEdition:
    return DailyEdition.model_validate_json(REAL.read_text(encoding="utf-8"))


def test_sample_links_to_publishers_but_republishes_none_of_their_text():
    edition = _edition()
    sample = edition_sample(edition)
    text = json.dumps(sample)
    assert [s["rank"] for s in sample["stories"]] == edition.top_ranks[:5]
    excerpts = [ev.excerpt for s in edition.stories for ev in s.evidence if ev.excerpt]
    # no article text: a summary sentence may state a fact in the source's words ('Henri B. Kagan and Kenso Soai
    # won the Nobel Prize in chemistry'), never a passage of it
    assert excerpts and not any(e[:150] in text for e in excerpts if len(e) >= 150)
    assert "excerpt" not in text
    first = sample["stories"][0]
    assert first["headline"] == edition.stories[0].headline and first["summary"] == edition.stories[0].sentences
    assert all(src["url"] is None or src["url"].startswith(("http://", "https://")) for s in sample["stories"]
               for src in s["sources"])
    urls = [src["url"] for src in first["sources"] if src["url"]]
    assert len(urls) == len(set(urls))  # one entry per link
    assert sample["edition_date"] == "2026-10-07" and sample["models"]["grouping"] == "nomic-embed-text"


def test_sample_takes_the_chosen_stories_in_that_order():
    sample = edition_sample(_edition(), [9, 1, 3])
    assert [s["rank"] for s in sample["stories"]] == [9, 1, 3]
    assert isinstance(sample["stories"][0]["category"], str)
    with pytest.raises(SampleError, match="no story number 99"):
        edition_sample(_edition(), [1, 99])


def test_sample_drops_links_that_are_not_web_pages():
    edition = _edition()
    edition.stories[0].evidence[0].url = "javascript:alert(1)"
    sources = edition_sample(edition, [1])["stories"][0]["sources"]
    assert "javascript" not in json.dumps(sources)


def test_demo_edition_is_never_a_sample():
    edition = _edition().model_copy(update={"demo": True})
    with pytest.raises(SampleError, match="demo"):
        edition_sample(edition)
