"""A public sample of one edition, for a website: headlines, the app's own summaries, source names and links.

Publishers' article text (the excerpts an edition keeps as evidence) is left out: a sample republishes no one's
writing, it links to it. The story text is the validated summary the edition already shows. A demo edition is
never a sample: its stories are made up.
"""

from __future__ import annotations

from datetime import datetime

from agent_reach.daily import __version__
from agent_reach.daily.edition import DailyEdition, Story, safe_url, top_stories

SAMPLE_SCHEMA = "agent_reach.daily_sample"
SAMPLE_SCHEMA_VERSION = 1
DEFAULT_SAMPLE_STORIES = 5


class SampleError(ValueError):
    """The edition cannot be published as a sample (plain-English message)."""


def _utc(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def _story(s: Story) -> dict:
    sources, seen = [], set()
    for ev in s.evidence:
        url = safe_url(ev.url)
        key = url or ev.title
        if key in seen:
            continue
        seen.add(key)
        sources.append({"outlet": ev.publisher or ev.source_name, "via": ev.source_name, "title": ev.title,
                        "url": url, "published_utc": _utc(ev.published_at_utc)})
    strength = s.evidence_strength
    return {"rank": s.rank, "category": s.category.value, "headline": s.headline, "summary": list(s.sentences),
            "why_it_matters": s.why_it_matters,
            "independent_reports": strength.independent_reports if strength else None,
            "evidence": list(strength.reasons) if strength else [],
            "sources": sources}


def edition_sample(edition: DailyEdition, ranks: list[int] | None = None,
                   count: int = DEFAULT_SAMPLE_STORIES) -> dict:
    """The stories with these ``ranks`` (in that order), or the first ``count`` Top Stories."""
    if edition.demo:
        raise SampleError("This is the demo edition (made-up stories). Refresh first, then export a real edition.")
    by_rank = {s.rank: s for s in edition.stories}
    if ranks:
        missing = [r for r in ranks if r not in by_rank]
        if missing:
            raise SampleError(f"This edition has no story number {', '.join(map(str, missing))}.")
        chosen = [by_rank[r] for r in ranks]
    else:
        chosen = top_stories(edition)[:count]
    return {"schema": SAMPLE_SCHEMA, "schema_version": SAMPLE_SCHEMA_VERSION,
            "app": f"Agent Reach Daily {__version__}", "edition_date": edition.edition_date.isoformat(),
            "timezone": edition.timezone, "revision": edition.revision,
            "generated_utc": _utc(edition.generation_completed_utc),
            "models": {"summaries": edition.model.llm_model, "grouping": edition.model.embed_model_used},
            "stories_in_edition": len(edition.stories),
            "stories": [_story(s) for s in chosen]}
