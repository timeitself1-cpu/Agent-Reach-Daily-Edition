"""What changed since the last refresh: compare a new edition with the previously persisted one.

Deterministic, evidence-based comparison (no model). Stories are matched across editions in this
order: identical story_id; a shared article URL; the same entity set (entity_id); near-identical
headline words. ``story_id`` alone is not enough because it fingerprints the evidence and changes
whenever evidence is added.

For every story of the new edition:

* **new**: no match in the previous edition;
* **updated** (materially): new independent publishers, a substantially different summary, a
  different headline, a changed category, or a newly added "why it matters";
* **signals up / down**: the story's signal count (raw items) changed by at least 50% and at least 2
  (e.g. 3 -> 9), or its independent-report count changed by 2 or more;
* otherwise **unchanged**.

Stories of the previous edition with no match are **gone** (no longer in today's selection: they
may have faded, aged out or been outranked; this is not a claim that the story ended).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from agent_reach.daily.strength import strength_of

SIGNAL_RATIO = 1.5
SIGNAL_MIN_DELTA = 2
REPORTS_MIN_DELTA = 2
SUMMARY_MIN_SIMILARITY = 0.5


class ChangeItem(BaseModel):
    kind: Literal["new", "updated", "signals_up", "signals_down", "gone"]
    headline: str
    story_id: str
    rank: int | None = None  # rank in the new edition (None for "gone")
    previous_rank: int | None = None
    detail: str = ""


class EditionChanges(BaseModel):
    compared_run_id: str
    compared_edition_date: str
    compared_revision: int = 1
    compared_generated_utc: datetime
    new: list[ChangeItem] = Field(default_factory=list)
    updated: list[ChangeItem] = Field(default_factory=list)
    signals_up: list[ChangeItem] = Field(default_factory=list)
    signals_down: list[ChangeItem] = Field(default_factory=list)
    gone: list[ChangeItem] = Field(default_factory=list)
    unchanged: int = 0

    @property
    def total(self) -> int:
        return len(self.new) + len(self.updated) + len(self.signals_up) + len(self.signals_down) + len(self.gone)

    def summary(self) -> str:
        parts = [(len(self.new), "new"), (len(self.updated), "updated"), (len(self.signals_up), "growing"),
                 (len(self.signals_down), "fading"), (len(self.gone), "no longer listed")]
        text = ", ".join(f"{n} {word}" for n, word in parts if n)
        return text or "No material changes"


def _tokens(text: str) -> set[str]:
    from agent_reach.pipeline.cleaner import dedupe_key, significant_tokens

    return significant_tokens(dedupe_key(text))


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    return len(ta & tb) / max(1, len(ta | tb))


def _match(story, candidates: list) -> object | None:
    from agent_reach.daily.edition import same_topic

    for test in (lambda o: o.story_id == story.story_id,
                 lambda o: bool({e.url for e in story.evidence if e.url} & {e.url for e in o.evidence if e.url}),
                 lambda o: bool(story.entity_id) and story.entity_id == o.entity_id,
                 lambda o: same_topic(story, o)):
        for other in candidates:
            if test(other):
                return other
    return None


def compare_editions(previous, current) -> EditionChanges:
    """Changes from ``previous`` (the last persisted edition) to ``current`` (the new one)."""
    prev_time, cur_time = previous.generation_completed_utc, current.generation_completed_utc
    changes = EditionChanges(compared_run_id=previous.run_id, compared_edition_date=previous.edition_date.isoformat(),
                             compared_revision=previous.revision, compared_generated_utc=prev_time)
    remaining = list(previous.stories)
    for story in current.stories:
        old = _match(story, remaining)
        if old is None:
            changes.new.append(ChangeItem(kind="new", headline=story.headline, story_id=story.story_id,
                                          rank=story.rank, detail="not in the previous edition"))
            continue
        remaining.remove(old)
        base = dict(headline=story.headline, story_id=story.story_id, rank=story.rank, previous_rank=old.rank)
        now_s, old_s = strength_of(story, cur_time), strength_of(old, prev_time)

        reasons: list[str] = []
        added = sorted(set(now_s.publishers) - set(old_s.publishers))
        if added:
            reasons.append(f"new reporting from {', '.join(added[:3])}{' and others' if len(added) > 3 else ''}")
        if _similarity(" ".join(story.sentences), " ".join(old.sentences)) < SUMMARY_MIN_SIMILARITY:
            reasons.append("the summary changed substantially")
        if _similarity(story.headline, old.headline) < SUMMARY_MIN_SIMILARITY:
            reasons.append(f"headline was “{old.headline}”")
        if story.category != old.category:
            reasons.append(f"category changed from {old.category.value}")
        if story.why_it_matters and not old.why_it_matters:
            reasons.append("now explains why it matters")

        a, b = old.raw_item_count, story.raw_item_count
        report_delta = now_s.independent_reports - old_s.independent_reports
        up = (b >= a * SIGNAL_RATIO and b - a >= SIGNAL_MIN_DELTA) or report_delta >= REPORTS_MIN_DELTA
        down = (a >= b * SIGNAL_RATIO and a - b >= SIGNAL_MIN_DELTA) or report_delta <= -REPORTS_MIN_DELTA
        signal_text = (f"signals {a} → {b}, independent reports "
                       f"{old_s.independent_reports} → {now_s.independent_reports}")

        if reasons:
            changes.updated.append(ChangeItem(kind="updated", detail="; ".join(reasons), **base))
        if up and not down:
            changes.signals_up.append(ChangeItem(kind="signals_up", detail=signal_text, **base))
        elif down and not up:
            changes.signals_down.append(ChangeItem(kind="signals_down", detail=signal_text, **base))
        if not reasons and not (up ^ down):
            changes.unchanged += 1
    for old in remaining:
        changes.gone.append(ChangeItem(kind="gone", headline=old.headline, story_id=old.story_id,
                                       previous_rank=old.rank, detail="not in today's selection"))
    return changes
