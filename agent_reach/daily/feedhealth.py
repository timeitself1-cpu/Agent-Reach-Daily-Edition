"""Feed doctor: remembers which feeds keep failing across refreshes.

After every refresh that ran the pipeline, each feed's result (publisher feeds, YouTube channels,
Google News sections, Mastodon servers) is recorded in ``state/feed_health.json``. A feed that has
failed in every refresh for at least ``FAILING_DAYS`` days (and at least ``FAILING_RUNS`` refreshes)
is flagged, so the reader can fix its address or turn it off. A channel whose feeds ALL failed in
one refresh is skipped for that refresh: that is an outage or a blocked connection, not a broken
feed. Only the refresh worker (lock holder) writes the file; the window reads it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_reach.daily.fsutil import atomic_write_json, read_json
from agent_reach.daily.paths import DataPaths

log = logging.getLogger(__name__)

FAILING_DAYS = 3.0
FAILING_RUNS = 2
#: A channel where fewer than this share of feeds answered had an outage (YouTube answered 1 of 22 channel
#: feeds in a real refresh on October 7): no single feed is blamed for it.
OUTAGE_OK_SHARE = 0.2


def channel_outage(feeds: list) -> bool:
    """Every feed failed, or (with 5 or more feeds) fewer than ``OUTAGE_OK_SHARE`` of them answered."""
    ok = sum(1 for f in feeds if f.ok)
    return not ok or (len(feeds) >= 5 and ok < OUTAGE_OK_SHARE * len(feeds))


class FeedRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    url: str
    source: str
    failures_in_row: int = 0
    failing_since_utc: datetime | None = None
    last_ok_utc: datetime | None = None
    last_error: str | None = None


class FeedHealthLog(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = 1
    feeds: dict[str, FeedRecord] = Field(default_factory=dict)  # by feed URL


def _path(paths: DataPaths):
    return paths.state_dir / "feed_health.json"


def load_feed_health(paths: DataPaths) -> FeedHealthLog:
    """Never fails: a missing or damaged file is an empty log."""
    try:
        return FeedHealthLog.model_validate(read_json(_path(paths)))
    except (OSError, ValueError, ValidationError):
        return FeedHealthLog()


def record_run(paths: DataPaths, source_stats: list, now: datetime) -> FeedHealthLog:
    """Fold one refresh's per-feed results into the log and save it (refresh worker only)."""
    health = load_feed_health(paths)
    for stat in source_stats:
        feeds = list(getattr(stat, "feeds", []) or [])
        if not feeds or channel_outage(feeds):
            continue  # (nearly) every feed of the channel failed at once: an outage, not a broken feed
        for f in feeds:
            rec = health.feeds.get(f.url) or FeedRecord(name=f.name, url=f.url, source=stat.source)
            rec.name, rec.source = f.name, stat.source
            if f.ok:
                rec.failures_in_row, rec.failing_since_utc, rec.last_error = 0, None, None
                rec.last_ok_utc = now
            else:
                rec.failures_in_row += 1
                rec.failing_since_utc = rec.failing_since_utc or now
                rec.last_error = (f.error or "")[:200] or None
            health.feeds[f.url] = rec
    try:
        atomic_write_json(_path(paths), health.model_dump(mode="json"))
    except OSError:
        log.warning("could not save feed health", exc_info=True)
    return health


def failing_feeds(health: FeedHealthLog, now: datetime, *, days: float = FAILING_DAYS,
                  runs: int = FAILING_RUNS) -> list[FeedRecord]:
    """Feeds that failed in every refresh for at least ``days`` days and ``runs`` refreshes."""
    out = [r for r in health.feeds.values()
           if r.failing_since_utc is not None and r.failures_in_row >= runs
           and now - r.failing_since_utc >= timedelta(days=days)]
    return sorted(out, key=lambda r: (r.failing_since_utc, r.name.lower()))
