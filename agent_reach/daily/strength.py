"""Deterministic evidence strength for a story. No model involvement and no probabilities.

The level summarises how well the collected evidence supports a story. It is computed only from
the story's evidence links and the edition's generation time, so the same evidence always gives
the same result:

* **Independent reports.** Article-like evidence is grouped by origin publisher (Google News items
  count as the publisher they point to). Repeats from one publisher count once, and syndicated
  copies (the same headline from different publishers, e.g. a wire story) count once.
* **Trend signals.** Search, social and Wikipedia evidence shows attention, not reporting: it is
  listed, but it never counts as a report, as channel diversity or as recency (rc12: a Google Trends
  phrase plus three articles from one channel read "Strong evidence").
* **Source diversity.** The number of distinct channels that carried reports.
* **Recency.** Age of the newest *stated* publication time of a report relative to the edition.
  Unknown times earn nothing and are never guessed.

Rule points: corroboration (2 reports = 2, 3 = 3, 4+ = 4) + 1 for reports from two or more channels +
1 for a report stated within 24 hours. Fewer than two independent reports is always "limited" (nothing
corroborates it); otherwise 5+ points is "strong" and the rest "moderate".
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from agent_reach.outlets import outlet_key, outlet_name

#: Channels whose items are attention signals (searches, posts, page views), not reports.
SIGNAL_SOURCES = frozenset({"google_trends", "x_trends24", "reddit", "wikipedia", "tiktok", "bluesky", "mastodon"})
_SECTION_RX = re.compile(r"\s+[-–—|:]\s+.*$")
_DEMO_RX = re.compile(r"\s*\(demo\)\s*$", re.IGNORECASE)


class EvidenceStrength(BaseModel):
    level: Literal["strong", "moderate", "limited"]
    points: int = Field(ge=0, description="rule points (see agent_reach.daily.strength), not a probability")
    independent_reports: int = 0
    publishers: list[str] = Field(default_factory=list)
    channels: int = 0
    trend_signals: int = 0
    duplicates_collapsed: int = 0
    newest_age_hours: float | None = None
    reasons: list[str] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return {"strong": "Strong evidence", "moderate": "Moderate evidence", "limited": "Limited evidence"}[self.level]


def origin(publisher: str | None, url: str | None) -> str | None:
    """Publisher organisation key: 'BBC News - World' -> 'bbc news'; else the article host."""
    return outlet_key(publisher, url)


def _title_key(title: str) -> str:
    from agent_reach.pipeline.cleaner import dedupe_key

    return dedupe_key(title)


def assess(evidence: list, reference: datetime) -> EvidenceStrength:
    """Evidence strength of one story's evidence links at ``reference`` (the edition's generation time)."""
    reference = reference.astimezone(timezone.utc)
    origins: dict[str, str] = {}  # origin key -> display name
    title_owner: dict[str, str] = {}  # headline key -> origin that reported it first
    duplicates = 0
    signals = 0
    newest: datetime | None = None
    for e in evidence:
        if e.source in SIGNAL_SOURCES:
            signals += 1
            continue
        if e.published_at_utc is not None and e.published_at_utc <= reference:
            newest = e.published_at_utc if newest is None else max(newest, e.published_at_utc)
        key = origin(e.publisher, e.url)
        if key is None:
            continue
        tkey = _title_key(e.title)
        owner = title_owner.get(tkey) if tkey else None
        if key in origins or (owner is not None and owner != key):
            duplicates += 1  # same publisher again, or a syndicated copy of a headline already counted
            continue
        origins[key] = outlet_name(e.publisher, e.url) or key
        if tkey:
            title_owner[tkey] = key
    independent = len(origins)
    channels = len({e.source for e in evidence if e.source not in SIGNAL_SOURCES})  # channels that carried reports
    age = round((reference - newest).total_seconds() / 3600, 1) if newest is not None else None

    points = {0: 0, 1: 0, 2: 2, 3: 3}.get(independent, 4)
    if channels >= 2:
        points += 1
    if age is not None and age <= 24:
        points += 1
    level = "limited" if independent < 2 else ("strong" if points >= 5 else "moderate")

    reasons = [f"{independent} independent report{'s' if independent != 1 else ''}"
               + (f" ({', '.join(sorted(origins.values())[:4])}{', ...' if independent > 4 else ''})" if origins else "")]
    if duplicates:
        reasons.append(f"{duplicates} repeat or syndicated cop{'ies' if duplicates != 1 else 'y'} counted once")
    if signals:
        reasons.append(f"{signals} trend/social signal{'s' if signals != 1 else ''} (attention, not reporting)")
    reasons.append(f"{channels} reporting channel{'s' if channels != 1 else ''}")
    if age is None:
        reasons.append("no stated publication time")
    else:
        reasons.append(f"newest report {age:.0f} h before this edition" if age >= 1 else
                       "newest report under an hour before this edition")
    if independent < 2:
        reasons.append("not corroborated by a second independent publisher")
    return EvidenceStrength(level=level, points=points, independent_reports=independent,
                            publishers=sorted(origins.values()), channels=channels, trend_signals=signals,
                            duplicates_collapsed=duplicates, newest_age_hours=age, reasons=reasons)


def strength_of(story, generated_at: datetime) -> EvidenceStrength:
    """Stored strength, or computed now for editions written before strength existed."""
    stored = story.evidence_strength
    if stored is None:
        return assess(story.evidence, generated_at)
    # Stored strength was assessed over ALL reports before the reader evidence list was capped at eight.
    # Preserve that scope while correcting aliases in pre-roadmap editions.
    publishers = sorted({outlet_name(name) for name in stored.publishers if name})
    independent = min(stored.independent_reports, len(publishers))
    points = stored.points - {0: 0, 1: 0, 2: 2, 3: 3}.get(stored.independent_reports, 4)
    points += {0: 0, 1: 0, 2: 2, 3: 3}.get(independent, 4)
    level = 'limited' if independent < 2 else ('strong' if points >= 5 else 'moderate')
    reasons = [f"{independent} independent report{'s' if independent != 1 else ''} ({', '.join(publishers)})"]
    reasons.extend(stored.reasons[1:])
    return stored.model_copy(update={'publishers': publishers, 'independent_reports': independent, 'points': points,
                                     'level': level, 'reasons': reasons,
                                     'duplicates_collapsed': stored.duplicates_collapsed + stored.independent_reports - independent})
