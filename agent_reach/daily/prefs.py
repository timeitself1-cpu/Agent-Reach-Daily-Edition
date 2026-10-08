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

from agent_reach.daily.feeds import (
    ADDED_IN_V2,
    ADDED_IN_V3,
    ADDED_IN_V4,
    REPLACED_IN_V5,
    REPLACED_IN_V6,
    REPLACED_IN_V7,
    REPLACED_IN_V8,
    FeedSpec,
    default_feeds,
    feeds_from_entries,
)
from agent_reach.daily.fsutil import FileUnavailable, atomic_write_json, read_json
from agent_reach.daily.paths import DataPaths
from agent_reach.daily.timeutil import parse_hhmm

log = logging.getLogger(__name__)

#: General-interest defaults. Tech-only feeds (GitHub, Product Hunt, arXiv) are available but
#: off, so the number of enabled tech feeds cannot by itself dominate the edition.
DAILY_DEFAULT_SOURCES = ["google_news", "news_rss", "youtube", "google_trends", "wikipedia", "reddit", "x_trends24",
                         "hackernews", "mastodon", "bluesky"]  # TikTok blocks automated readers: available, off
TECH_SOURCES = frozenset({"hackernews", "github", "producthunt", "arxiv"})
GENERAL_NEWS_SOURCES = frozenset({"google_news", "news_rss"})
SOURCE_NOTES = {
    "google_news": "Google News: top stories and one section per category (RSS)",
    "news_rss": "Publisher feeds (Publisher feeds tab)",
    "youtube": "YouTube: popular new videos",
    "google_trends": "Google Trends daily searches (RSS)",
    "wikipedia": "Wikipedia: most-read articles and 'In the news'",
    "mastodon": "Mastodon: news links people are sharing (mastodon.social)",
    "bluesky": "Bluesky trending topics",
    "reddit": "Reddit top posts (often rate-limited or blocked)",
    "x_trends24": "X trends via trends24.in (scrape; may break)",
    "tiktok": "TikTok trending hashtags (Creative Center; often blocked)",
    "hackernews": "Hacker News front page (tech)",
    "github": "GitHub Trending (tech)",
    "producthunt": "Product Hunt launches (tech)",
    "arxiv": "arXiv AI/ML papers (research)",
}
PREFS_VERSION = 9
DAILY_VELOCITY_WINDOWS = [24.0, 48.0, 168.0]
DAILY_VELOCITY_WEIGHTS = [0.5, 0.3, 0.2]
DAILY_VELOCITY_TOLERANCE = 0.25
MIN_DB_RETENTION_DAYS = 10


def _replace_feeds(feeds: list, replaced: dict) -> list:
    """Swap feeds listed in ``replaced`` (REPLACED_IN_V5, ...) for their replacement (keeping on/off), or drop them."""
    have = {str((f.get("url") if isinstance(f, dict) else getattr(f, "url", "")) or "").lower() for f in feeds}
    out = []
    for f in feeds:
        url = str((f.get("url") if isinstance(f, dict) else getattr(f, "url", "")) or "")
        if url not in replaced:
            out.append(f)
            continue
        new = replaced[url]
        if new is not None and new.url.lower() not in have:
            enabled = f.get("enabled", True) if isinstance(f, dict) else getattr(f, "enabled", True)
            out.append(new.model_copy(update={"enabled": bool(enabled)}))
    return out


class DailyPrefs(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    prefs_version: int = PREFS_VERSION
    enabled_sources: list[str] = Field(default_factory=lambda: list(DAILY_DEFAULT_SOURCES))
    feeds: list[FeedSpec] = Field(default_factory=default_feeds)  # one entry per publisher feed
    geo: str = "US"
    contact_email: str = ""

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    embed_model: str = "embeddinggemma-2:270m"
    embed_fallback_models: list[str] = Field(default_factory=lambda: ["nomic-embed-text"])
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
    # sections: Top Stories, then each category. max_stories = stories per section (top 10 overall,
    # top 10 per category); max_per_category = most stories one category may place in Top Stories.
    max_stories: int = Field(default=10, ge=3, le=30)
    max_per_category: int = Field(default=4, ge=1, le=30)
    max_tech_only_share: float = Field(default=0.34, ge=0.0, le=1.0)  # of Top Stories
    min_useful_stories: int = Field(default=3, ge=1, le=50)
    min_ok_sources: int = Field(default=2, ge=1, le=20)
    # a later refresh of the same day replaces that day's edition (and its page on the website) only when at least
    # this share of the sources and of the stories of the edition it replaces came through; 0 turns the check off
    min_share_of_same_day: float = Field(default=0.5, ge=0.0, le=1.0)
    # install new releases of the app by itself (daily/updater.py): when the window opens and at the hourly check
    auto_update: bool = True
    max_story_age_hours: float = Field(default=48.0, ge=6.0, le=336.0)  # older publication times are not "today"
    # processing budget: articles grouped and labelled per refresh (more = broader but slower on CPU)
    max_items_for_llm: int = Field(default=260, ge=40, le=400)
    items_per_feed: int = Field(default=10, ge=3, le=30)

    appearance: Literal["system", "light", "dark"] = "system"
    # topics: stories mentioning a followed topic are starred and gathered under "Following";
    # stories mentioning a muted topic are hidden (whole words, any case)
    follow_topics: list[str] = Field(default_factory=list)
    mute_topics: list[str] = Field(default_factory=list)

    # podcast: a spoken edition recorded on this PC after each successful refresh (see daily/podcast.py)
    podcast_auto: bool = True
    podcast_voice: str = ""  # an installed Windows voice; empty = the system default
    podcast_rate: int = Field(default=0, ge=-5, le=5)  # speaking speed
    podcast_stories: int = Field(default=8, ge=3, le=15)  # top stories told in full
    podcast_keep_days: int = Field(default=7, ge=1, le=60)

    @model_validator(mode="before")
    @classmethod
    def _migrate(cls, data: Any) -> Any:
        """Bring settings written by earlier versions up to date (values the user changed are kept).

        * before per-feed control: 'Category|URL' strings -> feeds;
        * version 1 -> 2: sections of 10 instead of one 15-story list, a 200-article processing
          budget instead of 150, and the technology/AI/science feeds added in version 2;
        * version 2 -> 3: more publishers in every section, YouTube channels, the YouTube and TikTok
          channels switched on, and a 260-article budget instead of 200;
        * version 3 -> 4: more publishers, and the Mastodon and Bluesky channels switched on;
        * version 4 -> 5: TikTok off (it blocks automated readers), and three feeds that failed in real
          use fixed or removed (``REPLACED_IN_V5``);
        * version 5 -> 6: the MIT News feed, which failed at both of its addresses, removed
          (``REPLACED_IN_V6``);
        * version 6 -> 7: Yahoo Finance (HTTP 404) replaced by Bloomberg's markets feed (``REPLACED_IN_V7``);
        * version 7 -> 8: The Independent's world feed (HTTP 429 for every automated reader) replaced by
          CBS News's (``REPLACED_IN_V8``);
        * version 8 -> 9: story grouping uses EmbeddingGemma 2 (``embeddinggemma-2:270m``) instead of
          nomic-embed-text, which stays as the fallback when the new model is not installed. A model the
          user chose themselves is kept.
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "feeds" not in data and isinstance(data.get("news_rss_feeds"), list):
            try:
                data["feeds"] = feeds_from_entries([str(e) for e in data.pop("news_rss_feeds")])
            except (ValueError, TypeError):
                data["feeds"] = default_feeds()
        # Every settings file this app writes records its version, so only an explicit older version
        # is migrated; values built in code (or hand-written without a version) are taken as they are.
        try:
            version = int(data.get("prefs_version", PREFS_VERSION))
        except (TypeError, ValueError):
            version = 1
        steps = [(2, (("max_stories", 15, 10), ("max_per_category", 5, 4), ("max_items_for_llm", 150, 200)), ADDED_IN_V2, ()),
                 (3, (("max_items_for_llm", 200, 260),), ADDED_IN_V3, ("youtube", "tiktok")),
                 (4, (), ADDED_IN_V4, ("mastodon", "bluesky"))]
        for target, defaults, added_feeds, added_sources in steps:
            if version >= target:
                continue
            for key, old, new in defaults:
                if data.get(key) == old:
                    data[key] = new
            if isinstance(data.get("feeds"), list):
                have = {str((f.get("url") if isinstance(f, dict) else getattr(f, "url", "")) or "").lower()
                        for f in data["feeds"]}
                data["feeds"] = list(data["feeds"]) + [f.model_copy() for f in added_feeds if f.url.lower() not in have]
            if isinstance(data.get("enabled_sources"), list):
                data["enabled_sources"] = list(data["enabled_sources"]) + [
                    x for x in added_sources if x not in data["enabled_sources"]]
        if version < 5:
            if isinstance(data.get("enabled_sources"), list):
                data["enabled_sources"] = [x for x in data["enabled_sources"] if x != "tiktok"]
            if isinstance(data.get("feeds"), list):
                data["feeds"] = _replace_feeds(data["feeds"], REPLACED_IN_V5)
        if version < 6 and isinstance(data.get("feeds"), list):
            data["feeds"] = _replace_feeds(data["feeds"], REPLACED_IN_V6)
        if version < 7 and isinstance(data.get("feeds"), list):
            data["feeds"] = _replace_feeds(data["feeds"], REPLACED_IN_V7)
        if version < 8 and isinstance(data.get("feeds"), list):
            data["feeds"] = _replace_feeds(data["feeds"], REPLACED_IN_V8)
        if version < 9 and data.get("embed_model", "nomic-embed-text") in ("nomic-embed-text", "nomic-embed-text:latest"):
            data["embed_model"] = "embeddinggemma-2:270m"
            data.setdefault("embed_fallback_models", ["nomic-embed-text"])
        data["prefs_version"] = PREFS_VERSION
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

    def enabled_rss_feeds(self) -> list[FeedSpec]:
        return [f for f in self.feeds if f.enabled and f.channel_id is None]

    def enabled_youtube_channels(self) -> list[FeedSpec]:
        return [f for f in self.feeds if f.enabled and f.channel_id is not None]

    @field_validator("follow_topics", "mute_topics")
    @classmethod
    def _topics(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for t in v:
            t = " ".join(str(t).split())[:60]
            if len(t) >= 2 and t.lower() not in {o.lower() for o in out}:
                out.append(t)
        return out[:100]

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


def load_prefs(paths: DataPaths, *, strict: bool = False) -> tuple[DailyPrefs, str | None]:
    """Load preferences. Returns (prefs, warning for the UI or None).

    A corrupt file is kept as ``settings.json.corrupt-<time>``. Invalid individual values are
    reset to defaults while the remaining valid values are kept. A file that cannot be read right now
    (another program holds it) is left exactly as it is: the window shows defaults with a warning, and
    with ``strict`` (the refresh worker) ``FileUnavailable`` is raised so no refresh runs on defaults.
    """
    path = paths.settings
    if not path.exists():
        return DailyPrefs(), None
    try:
        raw = read_json(path)
        if not isinstance(raw, dict):
            raise ValueError("settings file is not a JSON object")
    except OSError as exc:
        log.warning("settings cannot be read right now (%s); the file is left unchanged", exc)
        if strict:
            raise FileUnavailable(f"settings file cannot be read: {exc}") from exc
        return DailyPrefs(), ("Your settings could not be read just now (the file is open in another program "
                              "or not readable), so defaults are shown. The file was not changed.")
    except ValueError as exc:
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

    from agent_reach.config import DEFAULT_GOOGLE_NEWS_SECTIONS

    channels = [f.entry() for f in prefs.enabled_youtube_channels()]
    sources = [s for s in prefs.enabled_sources if s != "youtube" or channels]  # no channels on: nothing to read
    values: dict[str, Any] = dict(
        db_path=paths.db,
        retention_days=max(prefs.retention_days, MIN_DB_RETENTION_DAYS),
        enabled_sources=sources or list(prefs.enabled_sources),
        news_rss_feeds=[f.entry() for f in prefs.enabled_rss_feeds()],
        news_rss_items_per_feed=prefs.items_per_feed,
        news_rss_max_total_items=900,
        youtube_channels=channels,
        youtube_items_per_channel=3,
        google_news_sections=list(DEFAULT_GOOGLE_NEWS_SECTIONS),
        wikipedia_in_the_news=True,
        max_items_for_llm=prefs.max_items_for_llm,
        max_items_per_source=60,
        # A lone article from a real publisher is a story (most tech and science news is reported by one
        # outlet a day). Keep reasonably ranked uncorroborated items as single-item stories instead of
        # discarding them as density noise; evidence strength then shows them as "limited", and the
        # edition still drops weak single trend/social signals.
        outlier_policy="keep_top",
        singleton_keep_score=0.35,  # about the top 7 of each publisher feed (percentile within the channel)
        singleton_keep_relevance=6,
        min_items_per_feed_for_llm=2,
        min_items_per_channel_feed_for_llm=1,
        geo=prefs.geo,
        ollama_host=prefs.ollama_host,
        ollama_model=prefs.ollama_model,
        embed_model=prefs.embed_model,
        embed_fallback_models=list(prefs.embed_fallback_models),
        # developer artifact: every candidate pair of the run with the identity gate's verdict and reasons
        semantic_log_dir=paths.diagnostics_dir / "semantic" if hasattr(paths, "diagnostics_dir") else None,
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
