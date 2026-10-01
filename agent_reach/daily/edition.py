"""DailyEdition: the versioned presentation wrapper around one valid PipelineReport.

The pipeline's ``PipelineReport`` (schema_version 3) and ``CategoryEnum`` are unchanged; this
module adds a separate, versioned document (``edition_schema_version``) that the GUI and the
HTML export both render. An edition carries:

* ``edition_date`` = Central calendar date of the refresh START (consistent across midnight)
* generation start/completion in UTC, revision history for same-date replacements
* source health, coverage indicators and warnings, configuration fingerprint, model identity
* ranked stories with their evidence: item IDs, URLs, excerpts, publication time ONLY when the
  source stated one (``published_at_utc``), and the retrieval time

Story membership comes straight from the validated clusters; nothing here regroups items.
Momentum labels are derived only from the scorer's momentum/basis: a first run is BASELINE
(no trend label), and missing history is never shown as flat growth.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_reach.daily.prefs import GENERAL_NEWS_SOURCES, TECH_SOURCES, DailyPrefs
from agent_reach.daily.timeutil import CENTRAL_TZ_NAME, central_date, parse_utc
from agent_reach.models import CategoryEnum, CleanedTrendItem, MacroCluster, PipelineReport, RawTrendItem

EDITION_SCHEMA = "agent_reach.daily_edition"
EDITION_SCHEMA_VERSION = 1
MAX_EVIDENCE_PER_STORY = 8
EXCERPT_CHARS = 320

SOURCE_NAMES = {
    "x_trends24": "X (trends24)", "reddit": "Reddit", "tiktok": "TikTok", "google_trends": "Google Trends",
    "google_news": "Google News", "wikipedia": "Wikipedia", "arxiv": "arXiv", "hackernews": "Hacker News",
    "github": "GitHub", "producthunt": "Product Hunt", "news_rss": "News feeds",
}
MOMENTUM_LABELS = {"SURGING": "Hot", "RISING": "Rising", "NEW": "New", "STEADY": "Continuing",
                   "COOLING": "Cooling", "FADING": "Fading", "UNCERTAIN": "Uncertain trend"}
#: Platforms whose items come from a named publisher (an article), not a trend list or social post.
PUBLISHER_PLATFORMS = frozenset({"news_rss", "google_news", "hackernews", "arxiv"})
#: Held-back stories (over a category or tech cap) may still fill empty slots only when this strong.
STRONG_RELEVANCE = 7
META_SENTENCE_RX = re.compile(
    r"^(?:signals were observed on .*|.* (?:is|are) carrying \d+ related signals? about .*|"
    r".* is drawing attention across trend sources\.?)$",
    re.IGNORECASE,
)
SENTENCE_SPLIT_RX = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def source_name(source: str) -> str:
    return SOURCE_NAMES.get(source, source)


# ====================================================================== schema
class EvidenceLink(BaseModel):
    item_id: int
    source: str
    source_name: str
    title: str
    url: str | None = None
    publisher: str | None = None
    excerpt: str | None = None
    context_source: str | None = None
    published_at_utc: datetime | None = Field(default=None, description="only when the source stated a publication time")
    retrieved_at_utc: datetime | None = None
    feed: str | None = None  # publisher feed URL for news_rss items


class Story(BaseModel):
    rank: int = Field(ge=1)
    story_id: str = Field(description="evidence fingerprint (event_id); can change when evidence changes")
    entity_id: str = ""
    headline: str
    category: CategoryEnum
    sentences: list[str] = Field(min_length=1, max_length=4)
    why_it_matters: str | None = None
    labels: list[str] = Field(default_factory=list)
    momentum: str
    velocity_basis: str
    momentum_note: str = ""
    relevance_score: int
    velocity_score: float
    combined_score: float
    platforms: list[str]
    publisher_hosts: list[str] = Field(default_factory=list)
    raw_item_count: int = Field(ge=1)
    member_item_ids: list[int] = Field(min_length=1)
    evidence: list[EvidenceLink] = Field(min_length=1)
    tech_only: bool = False


class FeedHealth(BaseModel):
    """One publisher feed inside a channel: did it answer, how much it gave, how much was cited."""

    name: str
    url: str
    category: str | None = None
    status: Literal["ok", "empty", "failed"]
    collected: int = 0
    used: int = 0
    error: str | None = None


class SourceHealth(BaseModel):
    source: str
    name: str
    status: Literal["ok", "partial", "empty", "failed"]
    item_count: int = 0
    latency_ms: int = 0
    error: str | None = None
    used: int = 0  # articles from this channel cited in the edition
    feeds: list[FeedHealth] = Field(default_factory=list)


class Coverage(BaseModel):
    sources_attempted: int = 0
    sources_ok: int = 0
    failed: list[str] = Field(default_factory=list)
    partial: list[str] = Field(default_factory=list)
    category_counts: dict[str, int] = Field(default_factory=dict)
    general_news_available: bool = False
    tech_only_stories: int = 0
    held_back_for_balance: int = 0
    balanced: bool = False
    warnings: list[str] = Field(default_factory=list)


class ModelInfo(BaseModel):
    llm_model: str
    embed_model: str
    pipeline_mode: str
    summaries: Literal["local_model", "extractive"]


class AccountingSummary(BaseModel):
    ingested: int
    passed_filters: int
    clustering_candidates: int
    clustered: int
    discarded_total: int
    balanced: bool


class Revision(BaseModel):
    revision: int
    run_id: str
    generation_completed_utc: datetime


class DailyEdition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    edition_schema: Literal["agent_reach.daily_edition"] = EDITION_SCHEMA
    edition_schema_version: int = EDITION_SCHEMA_VERSION
    demo: bool = False
    edition_date: date
    timezone: Literal["America/Chicago"] = CENTRAL_TZ_NAME
    revision: int = Field(default=1, ge=1)
    previous_revisions: list[Revision] = Field(default_factory=list)
    run_id: str
    trigger: str = "manual"
    generation_started_utc: datetime
    generation_completed_utc: datetime
    model: ModelInfo
    config_fingerprint: str
    pipeline_schema_version: int
    accounting: AccountingSummary
    source_health: list[SourceHealth]
    coverage: Coverage
    overview: str
    notes: list[str] = Field(default_factory=list)
    stories: list[Story]

    @model_validator(mode="after")
    def _consistency(self) -> "DailyEdition":
        if self.edition_schema_version != EDITION_SCHEMA_VERSION:
            raise ValueError(f"unsupported edition schema version {self.edition_schema_version}")
        for name in ("generation_started_utc", "generation_completed_utc"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.generation_completed_utc < self.generation_started_utc:
            raise ValueError("generation completed before it started")
        if not self.demo and central_date(self.generation_started_utc) != self.edition_date:
            raise ValueError("edition_date must be the Central date of the refresh start")
        if [s.rank for s in self.stories] != list(range(1, len(self.stories) + 1)):
            raise ValueError("story ranks must be 1..n")
        if not self.accounting.balanced:
            raise ValueError("an edition requires a balanced item ledger")
        return self


# ====================================================================== building
def tech_only(cluster: MacroCluster) -> bool:
    return bool(cluster.sources) and set(cluster.sources) <= TECH_SOURCES


def story_labels(cluster: MacroCluster) -> list[str]:
    """Trend labels only when the scorer had comparable history; BASELINE gets none."""
    if cluster.momentum_uncertain or cluster.velocity_basis == "coverage_uncertain" or cluster.momentum == "UNCERTAIN":
        return ["Uncertain trend"]
    if cluster.velocity_basis != "historical":
        return []
    label = MOMENTUM_LABELS.get(cluster.momentum)
    return [label] if label else []


def body_sentences(summary: str) -> list[str]:
    parts = [s.strip() for s in SENTENCE_SPLIT_RX.split(summary or "") if s.strip()]
    return [s for s in parts if not META_SENTENCE_RX.match(s)][:2]


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    return host.removeprefix("www.") or None


def safe_url(url: str | None) -> str | None:
    """Only absolute http(s) URLs with a host are ever rendered as links."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return url.strip()


def _clip(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") + "..."


def evidence_links(cluster: MacroCluster, items: dict[int, CleanedTrendItem]) -> list[EvidenceLink]:
    members = [items[i] for i in cluster.member_item_ids if i in items]
    members.sort(key=lambda m: m.heuristic_score, reverse=True)
    links: list[EvidenceLink] = []
    seen: set[str] = set()
    for m in members:
        observations: list[RawTrendItem] = list(m.observations) or [m]
        for k, obs in enumerate(observations):
            url = safe_url(obs.url)
            key = url or f"{obs.source.value}|{obs.title.lower()}"
            if key in seen:
                continue
            seen.add(key)
            md = obs.metadata or {}
            links.append(EvidenceLink(
                item_id=m.item_id,
                source=obs.source.value,
                source_name=source_name(obs.source.value),
                title=_clip(obs.title, 300) or obs.title[:300],
                url=url,
                publisher=(str(md.get("publisher")) if md.get("publisher") else None) or _host(url),
                excerpt=_clip(m.context, EXCERPT_CHARS) if k == 0 else None,
                context_source=m.context_source if k == 0 else None,
                published_at_utc=parse_utc(md.get("published_at")),
                retrieved_at_utc=parse_utc(md.get("retrieved_at")),
                feed=str(md["feed"]) if md.get("feed") else None,
            ))
    links.sort(key=lambda link: link.url is None)  # linked evidence first, order otherwise preserved
    return links[:MAX_EVIDENCE_PER_STORY]


def newest_published(story: Story) -> datetime | None:
    """Most recent publication time a source actually stated for this story (None if none did)."""
    times = [e.published_at_utc for e in story.evidence if e.published_at_utc is not None]
    return max(times) if times else None


def is_stale(story: Story, now: datetime, max_age_hours: float) -> bool:
    """True when every stated publication time is older than ``max_age_hours``.

    Stories without any stated publication time (trend lists, Wikipedia) are not stale by this
    rule; they are shown with "publication time not stated" instead of a fake age.
    """
    newest = newest_published(story)
    return newest is not None and (now - newest).total_seconds() > max_age_hours * 3600


def is_weak(story: Story) -> bool:
    """A single uncorroborated trend/social signal with no publisher article and modest relevance."""
    has_publisher = any(p in PUBLISHER_PLATFORMS for p in story.platforms)
    return story.raw_item_count <= 1 and not has_publisher and story.relevance_score < STRONG_RELEVANCE


def _topic_tokens(story: Story) -> set[str]:
    from agent_reach.pipeline.cleaner import dedupe_key, significant_tokens

    return significant_tokens(dedupe_key(story.headline))


def same_topic(a: Story, b: Story) -> bool:
    """Deterministic 'this is the same story again' test used to avoid repetitive editions."""
    if a.entity_id and a.entity_id == b.entity_id:
        return True
    urls_a = {e.url for e in a.evidence if e.url}
    if urls_a & {e.url for e in b.evidence if e.url}:
        return True
    ta, tb = _topic_tokens(a), _topic_tokens(b)
    shared = ta & tb
    return len(shared) >= 2 and len(shared) / max(1, min(len(ta), len(tb))) >= 0.6


@dataclass
class Selection:
    stories: list[Story]
    held_back: int = 0
    filled_from_held_back: int = 0
    dropped_unsupported: int = 0
    dropped_stale: int = 0
    dropped_weak: int = 0
    dropped_duplicate: int = 0
    notes: list[str] = field(default_factory=list)


def select_stories(stories: list[Story], prefs: DailyPrefs, *, now: datetime) -> Selection:
    """Choose a balanced edition from stories in pipeline rank order. Quality beats story count.

    1. Drop stale stories (every stated publication time older than ``max_story_age_hours``),
       weak single uncorroborated trend signals, and repeats of a story already chosen.
    2. Keep the pipeline ranking while capping each category and the tech-only share.
    3. A story held back by a cap fills an empty slot only when it is strong (relevance >= 7)
       and not tech-only. Empty slots are otherwise left empty: no filler to reach a quota.
    """
    sel = Selection(stories=[])
    candidates: list[Story] = []
    for s in stories:
        if is_stale(s, now, prefs.max_story_age_hours):
            sel.dropped_stale += 1
        elif is_weak(s):
            sel.dropped_weak += 1
        elif any(same_topic(s, c) for c in candidates):
            sel.dropped_duplicate += 1
        else:
            candidates.append(s)

    limit = prefs.max_stories
    tech_cap = limit if prefs.max_tech_only_share >= 1 else int(limit * prefs.max_tech_only_share)
    chosen: list[Story] = []
    held: list[Story] = []
    per_cat: Counter[str] = Counter()
    tech = 0
    for s in candidates:
        if len(chosen) >= limit:
            break
        if per_cat[s.category.value] >= prefs.max_per_category or (s.tech_only and tech >= tech_cap):
            held.append(s)
            continue
        chosen.append(s)
        per_cat[s.category.value] += 1
        tech += s.tech_only
    for s in held:
        if len(chosen) >= limit:
            break
        if s.relevance_score >= STRONG_RELEVANCE and not s.tech_only:
            chosen.append(s)
            sel.filled_from_held_back += 1
    order = {id(s): i for i, s in enumerate(stories)}
    chosen.sort(key=lambda s: order[id(s)])
    sel.stories = chosen
    sel.held_back = len(held) - sel.filled_from_held_back
    return sel


def build_story(rank: int, cluster: MacroCluster, items: dict[int, CleanedTrendItem]) -> Story | None:
    """None when the cluster has no factual sentence or no evidence to cite."""
    sentences = body_sentences(cluster.summary)
    evidence = evidence_links(cluster, items)
    if not sentences:
        lead = next((e.excerpt for e in evidence if e.excerpt), None)
        if lead:
            first = SENTENCE_SPLIT_RX.split(lead.split(" | ")[-1])[0].strip()
            if len(first) >= 40 and first.endswith((".", "!", "?")):
                sentences = [first]
    if not sentences or not evidence:
        return None
    return Story(
        rank=rank,
        story_id=cluster.event_id or cluster.cluster_id,
        entity_id=cluster.entity_id,
        headline=cluster.headline,
        category=cluster.category,
        sentences=sentences,
        labels=story_labels(cluster),
        momentum=cluster.momentum,
        velocity_basis=cluster.velocity_basis,
        momentum_note=cluster.momentum_note,
        relevance_score=cluster.relevance_score,
        velocity_score=cluster.velocity_score,
        combined_score=cluster.combined_score,
        platforms=list(cluster.sources),
        publisher_hosts=list(cluster.publisher_hosts),
        raw_item_count=cluster.raw_item_count,
        member_item_ids=list(cluster.member_item_ids),
        evidence=evidence,
        tech_only=tech_only(cluster),
    )


HEALTH_WORDS = {"ok": "healthy", "partial": "partial", "empty": "empty", "failed": "failed"}
_STATUS_RX = re.compile(r"(?<![\d./])([45]\d\d)(?![\d./])")
_URL_RX = re.compile(r"https?://\S+")


def friendly_error(error: str | None) -> str:
    """Short plain-language reason for a source or feed problem (the raw text stays in the data)."""
    if not error:
        return ""
    text = _URL_RX.sub("", error.removeprefix("partial: "))
    m = _STATUS_RX.search(text)
    code = int(m.group(1)) if m else None
    if code == 429:
        return "rate-limited by the site (HTTP 429)"
    if code in (401, 403):
        return f"blocked by the site (HTTP {code})"
    if code in (404, 410):
        return f"feed address not found (HTTP {code}); it may have moved"
    if code is not None and code >= 500:
        return f"the site had a server error (HTTP {code})"
    low = text.lower()
    if "invalid xml" in low or "no entries" in low:
        return "not a readable feed (no articles found)"
    if "timeout" in low or "timed out" in low:
        return "the site did not answer in time"
    if "connecterror" in low or "name or service" in low or "getaddrinfo" in low or "unreachable" in low:
        return "could not connect (offline, or the site is blocked)"
    return text.strip(" :")[:160]


def health_summary(health: list[SourceHealth]) -> str:
    """Honest one-line count, e.g. '6 healthy \u00b7 1 partial' (a channel with errors is never 'healthy')."""
    counts = Counter(h.status for h in health)
    parts = [f"{counts[k]} {HEALTH_WORDS[k]}" for k in ("ok", "partial", "empty", "failed") if counts[k]]
    return " \u00b7 ".join(parts) if parts else "no sources"


def source_health(report: PipelineReport, stories: list[Story] | None = None) -> list[SourceHealth]:
    used_by_source: Counter[str] = Counter()
    used_by_feed: Counter[str] = Counter()
    for story in stories or []:
        for e in story.evidence:
            used_by_source[e.source] += 1
            if e.feed:
                used_by_feed[e.feed] += 1
    out = []
    for s in report.source_stats:
        if not s.ok:
            status = "failed"
        elif s.error:
            status = "partial"
        elif s.item_count == 0:
            status = "empty"
        else:
            status = "ok"
        feeds = [FeedHealth(name=f.name, url=f.url, category=f.category,
                            status="failed" if not f.ok else ("ok" if f.item_count else "empty"),
                            collected=f.item_count, used=used_by_feed.get(f.url, 0), error=f.error)
                 for f in s.feeds]
        out.append(SourceHealth(source=s.source, name=source_name(s.source), status=status,
                                item_count=s.item_count, latency_ms=s.latency_ms, error=s.error,
                                used=used_by_source.get(s.source, 0), feeds=feeds))
    return out


def build_coverage(health: list[SourceHealth], stories: list[Story], selection: Selection,
                   report: PipelineReport) -> Coverage:
    ok = [h for h in health if h.status in ("ok", "partial")]
    failed = [h.name for h in health if h.status == "failed"]
    partial = [h.name for h in health if h.status in ("partial", "empty")]
    counts = Counter(s.category.value for s in stories)
    general = any(h.source in GENERAL_NEWS_SOURCES for h in ok)
    tech_n = sum(s.tech_only for s in stories)
    warnings: list[str] = []
    if failed:
        warnings.append(f"Unavailable this run: {', '.join(failed)}.")
    if partial:
        warnings.append(f"Partial or empty coverage: {', '.join(partial)}.")
    all_feeds = [f for h in health for f in h.feeds]
    bad_feeds = [f.name for f in all_feeds if f.status != "ok"]
    if bad_feeds:
        shown = ", ".join(bad_feeds[:6]) + (f" and {len(bad_feeds) - 6} more" if len(bad_feeds) > 6 else "")
        warnings.append(f"{len(bad_feeds)} of {len(all_feeds)} publisher feeds returned nothing: {shown}.")
    if not general:
        warnings.append("No general-news source responded, so this edition may over-represent social and tech trends.")
    if selection.filled_from_held_back:
        warnings.append(f"Not enough stories in other categories to balance the edition; "
                        f"{selection.filled_from_held_back} strong story(ies) beyond the per-category limit were included.")
    if stories and tech_n / len(stories) > 0.5:
        warnings.append(f"{tech_n} of {len(stories)} stories come only from tech sources.")
    if "lexical" in (report.llm_mode or ""):
        warnings.append("Embedding model unavailable: stories were grouped by shared words (less precise).")
    balanced = general and not selection.filled_from_held_back and len(counts) >= 3 and (not stories or tech_n / len(stories) <= 0.5)
    return Coverage(
        sources_attempted=len(health), sources_ok=len(ok), failed=failed, partial=partial,
        category_counts=dict(counts.most_common()), general_news_available=general,
        tech_only_stories=tech_n, held_back_for_balance=selection.held_back, balanced=balanced, warnings=warnings,
    )


def build_overview(stories: list[Story], coverage: Coverage) -> str:
    if not stories:
        return ""
    cats = ", ".join(f"{k} {v}" for k, v in coverage.category_counts.items())
    text = (f"{len(stories)} {'story' if len(stories) == 1 else 'stories'} from {coverage.sources_ok} of "
            f"{coverage.sources_attempted} sources: {cats}.")
    if coverage.failed or coverage.partial or not coverage.balanced:
        text += " Coverage is partial today (see Details)."
    return text


def assemble_edition(
    report: PipelineReport,
    selection: Selection,
    prefs: DailyPrefs,
    *,
    started: datetime,
    completed: datetime,
    trigger: str,
    config_fingerprint: str,
    revision: int = 1,
    previous_revisions: list[Revision] | None = None,
) -> DailyEdition:
    if not report.valid or report.accounting is None:
        raise ValueError("only a valid report can become an edition")
    stories = selection.stories
    for i, s in enumerate(stories, start=1):
        s.rank = i
    health = source_health(report, stories)
    coverage = build_coverage(health, stories, selection, report)
    acct = report.accounting
    notes = list(selection.notes)
    if stories and all(s.velocity_basis == "cold_start" for s in stories):
        notes.append("Baseline edition: there is no comparable earlier edition yet, so no story is labelled hot, "
                     "rising or new. Trend labels appear once a previous daily edition can be compared.")
    if selection.dropped_unsupported:
        notes.append(f"{selection.dropped_unsupported} ranked group(s) were omitted because they had no citable "
                     "factual sentence.")
    if selection.dropped_stale:
        notes.append(f"{selection.dropped_stale} story(ies) were left out because every source was published more "
                     f"than {prefs.max_story_age_hours:g} hours before this refresh.")
    if selection.dropped_duplicate:
        notes.append(f"{selection.dropped_duplicate} repeat(s) of stories already in this edition were left out.")
    if selection.dropped_weak:
        notes.append(f"{selection.dropped_weak} weak signal(s) (a single trend or social post with no article) "
                     "were left out.")
    summaries = "extractive" if report.llm_mode.startswith("heuristic") else "local_model"
    if summaries == "extractive":
        notes.append("Summaries are extractive (lead sentences from the sources) because the local model was not used.")
    return DailyEdition(
        edition_date=central_date(started),
        revision=revision,
        previous_revisions=previous_revisions or [],
        run_id=report.run_id,
        trigger=trigger,
        generation_started_utc=started.astimezone(timezone.utc),
        generation_completed_utc=completed.astimezone(timezone.utc),
        model=ModelInfo(llm_model=prefs.ollama_model, embed_model=prefs.embed_model,
                        pipeline_mode=report.llm_mode, summaries=summaries),
        config_fingerprint=config_fingerprint,
        pipeline_schema_version=report.schema_version,
        accounting=AccountingSummary(ingested=acct.ingested, passed_filters=acct.passed_filters,
                                     clustering_candidates=acct.clustering_candidates, clustered=acct.clustered,
                                     discarded_total=acct.discarded_total, balanced=acct.balanced),
        source_health=health,
        coverage=coverage,
        overview=build_overview(stories, coverage),
        notes=notes,
        stories=stories,
    )


@dataclass
class PublishDecision:
    publishable: bool
    reasons: list[str]


def evaluate_publication(edition: DailyEdition, prefs: DailyPrefs, *, allow_extractive: bool = False) -> PublishDecision:
    """Publication is stricter than ledger validity: an empty run can balance and still be useless."""
    reasons: list[str] = []
    cov = edition.coverage
    if cov.sources_ok == 0:
        reasons.append("No news source responded (offline, blocked or all feeds failed).")
    elif cov.sources_ok < prefs.min_ok_sources:
        reasons.append(f"Only {cov.sources_ok} source(s) responded; at least {prefs.min_ok_sources} are required.")
    if len(edition.stories) < prefs.min_useful_stories:
        reasons.append(f"Only {len(edition.stories)} useful story(ies) were found; at least "
                       f"{prefs.min_useful_stories} are required for a daily edition.")
    if edition.model.summaries == "extractive" and prefs.require_llm and not allow_extractive:
        reasons.append("The local model was not used, and AI summaries are required by your settings.")
    return PublishDecision(publishable=not reasons, reasons=reasons)


def all_categories() -> list[str]:
    return CategoryEnum.values()
