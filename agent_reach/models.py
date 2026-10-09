"""Pydantic V2 data contracts shared by every Agent Reach stage."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_ids(v: Any) -> list[int]:
    """Accept ints, numeric strings, '#12', '[12]' -- LLMs are inconsistent."""
    out: list[int] = []
    if v is None:
        return out
    if not isinstance(v, (list, tuple, set)):
        v = [v]
    for x in v:
        try:
            out.append(int(str(x).strip().lstrip("#[").rstrip("]")))
        except ValueError:
            continue
    return out


class CategoryEnum(str, Enum):
    SPORTS = "Sports"
    ENTERTAINMENT = "Entertainment"
    TECH = "Tech"
    NEWS = "News"
    INTERNET_CULTURE = "Internet Culture"
    SCIENCE_AI = "Science & AI"
    #: the Local section of rc18 (Oct 9, 2026, removed in rc19): kept only so editions saved with it still load.
    #: Nothing assigns it any more, and the labelling model is never offered it.
    LOCAL = "Local"

    @classmethod
    def values(cls) -> list[str]:
        return [c.value for c in cls]

    @classmethod
    def model_values(cls) -> list[str]:
        """The categories the labelling model may choose (Local is historical only)."""
        return [c.value for c in cls if c is not cls.LOCAL]


class SourceName(str, Enum):
    X_TRENDS24 = "x_trends24"
    REDDIT = "reddit"
    TIKTOK = "tiktok"
    GOOGLE_TRENDS = "google_trends"
    GOOGLE_NEWS = "google_news"
    WIKIPEDIA = "wikipedia"
    ARXIV = "arxiv"
    HACKERNEWS = "hackernews"
    GITHUB = "github"
    PRODUCTHUNT = "producthunt"
    NEWS_RSS = "news_rss"
    YOUTUBE = "youtube"
    MASTODON = "mastodon"
    BLUESKY = "bluesky"


class RawTrendItem(BaseModel):
    """A single raw signal as produced by an ingester."""

    model_config = ConfigDict(use_enum_values=False)

    title: str = Field(min_length=1, max_length=1000)
    source: SourceName
    category_hint: CategoryEnum | None = None
    raw_score: float | None = None
    url: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)
    comment_count: int | None = None
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def _ensure_tz(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)

    @property
    def content_hash(self) -> str:
        basis = f"{self.source.value}|{self.title.strip().lower()}|{self.url or ''}"
        return hashlib.sha1(basis.encode("utf-8", "ignore")).hexdigest()


class CleanedTrendItem(RawTrendItem):
    """A raw item that survived heuristic filtering, enriched for clustering."""

    item_id: int
    normalized_title: str
    heuristic_score: float = Field(ge=0.0, le=1.0)
    duplicate_count: int = Field(default=1, ge=1)
    observations: list[RawTrendItem] = Field(default_factory=list)
    merged_urls: list[str] = Field(default_factory=list)
    inferred_category: CategoryEnum | None = None
    # --- Stage 2b enrichment (page title, meta description, lead paragraphs)
    context: str | None = None
    context_source: str | None = None  # "page" | "wikipedia_api" | "feed" | None

    @property
    def raw_weight(self) -> int:
        """How many raw ingested items this cleaned item stands for (itself + merged duplicates)."""
        return max(1, self.duplicate_count)


class VelocityWindow(BaseModel):
    window_hours: float
    baseline_rate: float | None = None
    current_rate: float
    growth: float | None = None


class MacroCluster(BaseModel):
    cluster_id: str
    entity_id: str = ""
    event_id: str = ""
    publisher_hosts: list[str] = Field(default_factory=list)
    momentum_uncertain: bool = False
    momentum_note: str = ""
    headline: str
    category: CategoryEnum
    relevance_score: int = Field(ge=1, le=10)
    velocity_score: float = Field(ge=0.0, le=100.0)
    summary: str
    primary_entities: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    raw_item_count: int = Field(ge=1)
    created_at: datetime = Field(default_factory=utcnow)
    # Enrichment (populated by clusterer/scorer)
    sources: list[str] = Field(default_factory=list)
    llm_relevance: int | None = None
    momentum: str = "STEADY"
    velocity_basis: str = "cold_start"
    velocity_windows: list[VelocityWindow] = Field(default_factory=list)
    combined_score: float = 0.0
    member_item_ids: list[int] = Field(default_factory=list)

    @staticmethod
    def make_id(headline: str, entities: list[str]) -> str:
        keys = sorted({e.strip().lower() for e in entities if e.strip()}) or [headline.strip().lower()]
        return hashlib.sha1("|".join(keys).encode("utf-8", "ignore")).hexdigest()[:12]


#: A stated publication time may run ahead of the retrieval clock by this much (publisher clock skew)
#: and is then clamped to the retrieval time; anything later is not a trustworthy publication time.
PUBLISHED_FUTURE_TOLERANCE = timedelta(minutes=15)


class FeedStat(BaseModel):
    """One feed inside a multi-feed source (a news_rss publisher feed, a YouTube channel, a Google News section)."""

    name: str
    url: str
    category: str | None = None
    ok: bool
    item_count: int = 0
    error: str | None = None


class SourceStat(BaseModel):
    source: str
    ok: bool
    item_count: int
    latency_ms: int
    error: str | None = None
    feeds: list[FeedStat] = Field(default_factory=list)  # per-feed health for multi-feed sources


#: Stage that owns each discard reason, used to group the ledger in reports.
DISCARD_STAGES: dict[str, str] = {
    # stage 2 - heuristic cleaner (reasons come from TrendCleaner)
    "reddit_low_signal_subreddit": "clean", "reddit_low_engagement": "clean", "reddit_unverified_metrics": "clean",
    "hn_low_points": "clean", "github_low_stars": "clean", "generic_hashtag": "clean",
    "too_short_or_non_ascii": "clean", "personal_anecdote": "clean", "meme_or_photo": "clean", "pet_post": "clean",
    "box_score_or_betting": "clean", "no_signal_tokens": "clean", "promotional": "clean", "video_clip": "clean",
    # stage 2 - candidate budget
    "not_selected_budget": "select",
    # stage 3 - clustering
    "density_noise": "cluster", "unsupported_grouping": "cluster", "insufficient_data": "cluster",
    "low_relevance": "cluster", "weak_singleton": "cluster",
}


class PipelineAccounting(BaseModel):
    """Item ledger in RAW-item units. Invariant: ingested == sum(discarded) + clustered.

    A cleaned item that absorbed duplicates counts as ``duplicate_count`` raw items, so
    de-duplication is never a discard: the duplicates travel with their representative and
    are counted wherever it ends up (a cluster or a discard bucket).
    """

    ingested: int = Field(ge=0)
    passed_filters: int = Field(ge=0, description="raw items represented by cleaned (kept) items")
    clustering_candidates: int = Field(ge=0, description="raw items represented by items sent to clustering")
    clustered: int = Field(ge=0, description="sum of raw_item_count over reported macro-clusters")
    discarded: dict[str, int] = Field(default_factory=dict)
    duplicates_folded: int = Field(default=0, ge=0, description="informational: raw items merged into representatives")

    @property
    def discarded_total(self) -> int:
        return sum(self.discarded.values())

    @property
    def unaccounted(self) -> int:
        return self.ingested - self.discarded_total - self.clustered

    @property
    def balanced(self) -> bool:
        return self.unaccounted == 0

    def by_stage(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for reason, n in sorted(self.discarded.items(), key=lambda kv: -kv[1]):
            if n:
                out.setdefault(DISCARD_STAGES.get(reason, "other"), {})[reason] = n
        return out

    @model_validator(mode="after")
    def _stage_consistency(self) -> "PipelineAccounting":
        if any(n < 0 for n in self.discarded.values()):
            raise ValueError("negative discard count")
        clean = sum(n for r, n in self.discarded.items() if DISCARD_STAGES.get(r) == "clean")
        select = self.discarded.get("not_selected_budget", 0)
        if self.ingested - clean != self.passed_filters:
            raise ValueError(f"stage 2 ledger broken: ingested {self.ingested} - cleaned-out {clean} != passed {self.passed_filters}")
        if self.passed_filters - select != self.clustering_candidates:
            raise ValueError(
                f"selection ledger broken: passed {self.passed_filters} - budget {select} != candidates {self.clustering_candidates}"
            )
        if not self.balanced:
            raise ValueError(f"unbalanced final ledger: delta {self.unaccounted}")
        return self


class PipelineReport(BaseModel):
    run_id: str
    execution_time: float = Field(description="Wall-clock seconds for the full run")
    ingested_count: int
    filtered_count: int = Field(description="Raw items that survived heuristic filtering (incl. folded duplicates)")
    cluster_count: int
    macro_clusters: list[MacroCluster]
    started_at: datetime = Field(default_factory=utcnow)
    llm_mode: str = "ollama"
    discarded_by_llm: int = Field(default=0, description="raw items discarded during stage 3 clustering")
    source_stats: list[SourceStat] = Field(default_factory=list)
    filter_breakdown: dict[str, int] = Field(default_factory=dict)
    accounting: PipelineAccounting | None = None
    enrichment: dict[str, int] = Field(default_factory=dict)
    schema_version: int = 3
    valid: bool = True
    effective_config: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[str] = Field(default_factory=list)
    label_calls: int = Field(default=0, description="model labelling calls (batches) made in stage 3")
    label_calls_failed: int = Field(default=0, description="labelling batches that fell back to heuristic labels")
    semantic: dict[str, Any] = Field(default_factory=dict, description="semantic-pipeline diagnostics: embedding "
                                     "model actually used, cache hits, fallbacks, identity-gate counts (rc12)")

    @model_validator(mode="after")
    def _validate_report(self) -> "PipelineReport":
        if self.valid:
            if self.accounting is None or not self.accounting.balanced:
                raise ValueError("valid report requires balanced accounting")
            if (self.cluster_count != len(self.macro_clusters)
                    or sum(c.raw_item_count for c in self.macro_clusters) != self.accounting.clustered
                    or self.ingested_count != self.accounting.ingested
                    or self.filtered_count != self.accounting.passed_filters):
                raise ValueError("report counts disagree with ledger")
        return self


# ---------------------------------------------------------------- LLM I/O
class LLMCluster(BaseModel):
    """Loose schema for what the LLM returns (validated/coerced afterwards)."""

    headline: str
    category: str
    item_ids: list[int]
    primary_entities: list[str] = Field(default_factory=list)
    summary: str = ""
    relevance_score: int = 5

    @field_validator("relevance_score", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> int:
        try:
            return max(1, min(10, int(round(float(v)))))
        except (TypeError, ValueError):
            return 5

    @field_validator("item_ids", mode="before")
    @classmethod
    def _ids(cls, v: Any) -> list[int]:
        return _coerce_ids(v)


class LLMClusterResponse(BaseModel):
    clusters: list[LLMCluster] = Field(default_factory=list)
    discarded_item_ids: list[int] = Field(default_factory=list)

    @field_validator("discarded_item_ids", mode="before")
    @classmethod
    def _ids(cls, v: Any) -> list[int]:
        return _coerce_ids(v)


class LLMMergeGroup(BaseModel):
    cluster_ids: list[int]
    headline: str = ""

    @field_validator("cluster_ids", mode="before")
    @classmethod
    def _ids(cls, v: Any) -> list[int]:
        return _coerce_ids(v)


class LLMMergeResponse(BaseModel):
    groups: list[LLMMergeGroup] = Field(default_factory=list)
