"""User preferences for the daily app (settings.json in the data directory).

Preferences are mapped onto the pipeline ``Settings`` by :func:`build_settings`. The daily
product uses daily momentum windows (24h / 48h / 7d, +/-25% tolerance) instead of the CLI's
1h / 6h / 24h, and keeps at least 10 days of SQLite history so the 7-day window can find a
baseline regardless of the edition retention setting.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from agent_reach.daily.feeds import FeedSpec, default_feeds, feeds_from_entries
from agent_reach.daily.fsutil import atomic_write_json, read_json
from agent_reach.daily.paths import DataPaths
from agent_reach.daily.timeutil import parse_hhmm

log = logging.getLogger(__name__)

#: General-interest defaults. Tech-only feeds (GitHub, Product Hunt, arXiv) are available but
#: off, so the number of enabled tech feeds cannot by itself dominate the edition.
DAILY_DEFAULT_SOURCES = ["google_news", "news_rss", "google_trends", "wikipedia", "reddit", "x_trends24", "hackernews"]
TECH_SOURCES = frozenset({"hackernews", "github", "producthunt", "arxiv"})
GENERAL_NEWS_SOURCES = frozenset({"google_news", "news_rss"})
SOURCE_NOTES = {
    "google_news": "Google News top stories (RSS)",
    "news_rss": "Publisher feeds (the list below)",
    "google_trends": "Google Trends daily searches (RSS)",
    "wikipedia": "Wikipedia most-read articles (Wikimedia API)",
    "reddit": "Reddit top posts (often rate-limited or blocked)",
    "x_trends24": "X trends via trends24.in (scrape; may break)",
    "tiktok": "TikTok Creative Center (usually bot-gated)",
    "hackernews": "Hacker News front page (tech)",
    "github": "GitHub Trending (tech)",
    "producthunt": "Product Hunt launches (tech)",
    "arxiv": "arXiv AI/ML papers (research)",
}
DAILY_VELOCITY_WINDOWS = [24.0, 48.0, 168.0]
DAILY_VELOCITY_WEIGHTS = [0.5, 0.3, 0.2]
DAILY_VELOCITY_TOLERANCE = 0.25
MIN_DB_RETENTION_DAYS = 10


class DailyPrefs(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    prefs_version: int = 1
    enabled_sources: list[str] = Field(default_factory=lambda: list(DAILY_DEFAULT_SOURCES))
    feeds: list[FeedSpec] = Field(default_factory=default_feeds)  # one entry per publisher feed
    geo: str = "US"
    contact_email: str = ""

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    embed_model: str = "nomic-embed-text"
    require_llm: bool = True  # no edition from heuristic labels unless the user explicitly allows it
    why_it_matters: bool = True
    start_ollama_if_down: bool = True

    schedule_mode: Literal["elapsed", "fixed_central"] = "elapsed"
    refresh_interval_hours: float = Field(default=24.0, ge=1.0, le=168.0)
    fixed_time_central: str = "07:00"
    refresh_on_launch: bool = True
    retry_base_minutes: float = Field(default=30.0, ge=1.0, le=720.0)
    retry_max_hours: float = Field(default=6.0, ge=0.25, le=48.0)
    max_run_minutes: float = Field(default=90.0, ge=5.0, le=360.0)

    retention_days: int = Field(default=30, ge=1, le=3650)
    max_stories: int = Field(default=15, ge=3, le=50)
    max_per_category: int = Field(default=5, ge=1, le=50)
    max_tech_only_share: float = Field(default=0.34, ge=0.0, le=1.0)
    min_useful_stories: int = Field(default=3, ge=1, le=50)
    max_story_age_hours: float = Field(default=48.0, ge=6.0, le=336.0)  # older publication times are not "today"
    # processing budget: articles grouped and labelled per refresh (more = broader but slower on CPU)
    max_items_for_llm: int = Field(default=150, ge=40, le=400)
    items_per_feed: int = Field(default=10, ge=3, le=30)

    appearance: Literal["system", "light", "dark"] = "system"

    @model_validator(mode="before")
    @classmethod
    def _migrate_feeds(cls, data: Any) -> Any:
        """Settings written before per-feed control stored 'Category|URL' strings."""
        if isinstance(data, dict) and "feeds" not in data and isinstance(data.get("news_rss_feeds"), list):
            data = dict(data)
            try:
                data["feeds"] = feeds_from_entries([str(e) for e in data.pop("news_rss_feeds")])
            except (ValueError, TypeError):
                data["feeds"] = default_feeds()
        return data

    @field_validator("feeds")
    @classmethod
    def _unique_feeds(cls, v: list[FeedSpec]) -> list[FeedSpec]:
        seen: set[str] = set()
        out = []
        for f in v:
            if f.url.lower() not in seen:
                seen.add(f.url.lower())
                out.append(f)
        return out

    def enabled_feeds(self) -> list[FeedSpec]:
        return [f for f in self.feeds if f.enabled]
    min_ok_sources: int = Field(default=2, ge=1, le=20)

    @field_validator("enabled_sources")
    @classmethod
    def _sources(cls, v: list[str]) -> list[str]:
        from agent_reach.ingestion import INGESTER_REGISTRY

        unknown = [s for s in v if s not in INGESTER_REGISTRY]
        if unknown:
            raise ValueError(f"unknown sources: {unknown}")
        if not v:
            raise ValueError("at least one source must be enabled")
        return list(dict.fromkeys(v))

    @field_validator("fixed_time_central")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        t = parse_hhmm(v)
        return f"{t.hour:02d}:{t.minute:02d}"

    @field_validator("ollama_host")
    @classmethod
    def _host(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("ollama_host must start with http:// or https://")
        return v


def load_prefs(paths: DataPaths) -> tuple[DailyPrefs, str | None]:
    """Load preferences; never fails. Returns (prefs, warning for the UI or None).

    A corrupt file is kept as ``settings.json.corrupt-<time>``. Invalid individual values are
    reset to defaults while the remaining valid values are kept.
    """
    path = paths.settings
    if not path.exists():
        return DailyPrefs(), None
    try:
        raw = read_json(path)
        if not isinstance(raw, dict):
            raise ValueError("settings file is not a JSON object")
    except (OSError, ValueError) as exc:
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        try:
            path.replace(backup)
        except OSError:
            pass
        log.warning("settings unreadable (%s); defaults in use, original kept as %s", exc, backup.name)
        return DailyPrefs(), f"Settings file was unreadable and has been reset (kept a copy as {backup.name})."
    try:
        return DailyPrefs.model_validate(raw), None
    except ValidationError as exc:
        bad = sorted({str(e["loc"][0]) for e in exc.errors() if e.get("loc")})
        cleaned = {k: v for k, v in raw.items() if k not in bad}
        try:
            prefs = DailyPrefs.model_validate(cleaned)
        except ValidationError:
            prefs = DailyPrefs()
        return prefs, f"Some settings were invalid and were reset to defaults: {', '.join(bad)}."


def save_prefs(paths: DataPaths, prefs: DailyPrefs) -> None:
    atomic_write_json(paths.settings, prefs.model_dump(mode="json"))


def build_settings(prefs: DailyPrefs, paths: DataPaths, **overrides: Any):
    """Pipeline Settings for a daily refresh (explicit values override env and .env)."""
    from agent_reach.config import Settings

    values: dict[str, Any] = dict(
        db_path=paths.db,
        retention_days=max(prefs.retention_days, MIN_DB_RETENTION_DAYS),
        enabled_sources=list(prefs.enabled_sources),
        news_rss_feeds=[f.entry() for f in prefs.enabled_feeds()],
        news_rss_items_per_feed=prefs.items_per_feed,
        max_items_for_llm=prefs.max_items_for_llm,
        geo=prefs.geo,
        ollama_host=prefs.ollama_host,
        ollama_model=prefs.ollama_model,
        embed_model=prefs.embed_model,
        velocity_windows_hours=list(DAILY_VELOCITY_WINDOWS),
        velocity_window_weights=list(DAILY_VELOCITY_WEIGHTS),
        velocity_window_tolerance=DAILY_VELOCITY_TOLERANCE,
    )
    if prefs.contact_email.strip():
        values["contact_email"] = prefs.contact_email.strip()
    values.update(overrides)
    return Settings(**values)


#: Settings keys that do not change what a run measures (mirrors the scorer's comparability rule).
_NON_COMPARABLE = {"db_path", "report_top_n", "report_width", "retention_days"}


def config_fingerprint(effective_config: dict[str, Any]) -> str:
    """Stable short hash of the effective pipeline configuration of a run."""
    comparable = {k: v for k, v in effective_config.items() if k not in _NON_COMPARABLE}
    blob = json.dumps(comparable, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]
