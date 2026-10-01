"""Publisher feeds for the daily edition: defaults, validation and a one-feed test.

Each feed is one publisher channel (``FeedSpec``). Enabled feeds become ``news_rss_feeds``
entries (``"Category|URL|Name"``) for the pipeline, where every feed has its own allowance,
selection floor and health line.

The defaults cover world, US, business, science, health, technology, sports and culture news
from 15 organisations. Feed addresses change over time: a feed that stops working only makes
the source partial (shown per feed in Details), and Settings > Sources > Test checks any feed.
Categories use the edition's fixed category set (business and health stories file under News).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator

from agent_reach.models import CategoryEnum


class FeedSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    url: str
    category: str = CategoryEnum.NEWS.value
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.replace("|", "/").split())
        if not v:
            raise ValueError("a feed needs a name")
        return v[:80]

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        parts = urlsplit(v)
        if parts.scheme not in ("http", "https") or not parts.hostname or "|" in v or " " in v:
            raise ValueError("feed address must be an http(s):// URL")
        return v

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        if v not in CategoryEnum.values():
            raise ValueError(f"category must be one of {', '.join(CategoryEnum.values())}")
        return v

    def entry(self) -> str:
        return f"{self.category}|{self.url}|{self.name}"

    @property
    def publisher(self) -> str:
        return self.name.split(" - ")[0]


def _f(name: str, url: str, category: str = "News") -> FeedSpec:
    return FeedSpec(name=name, url=url, category=category)


#: Default publisher feeds (26 feeds, 15 organisations). Business and health file under News.
DEFAULT_FEEDS: list[FeedSpec] = [
    # world and US news
    _f("BBC News - World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    _f("NPR - News", "https://feeds.npr.org/1001/rss.xml"),
    _f("NPR - World", "https://feeds.npr.org/1004/rss.xml"),
    _f("The Guardian - US", "https://www.theguardian.com/us-news/rss"),
    _f("The Guardian - World", "https://www.theguardian.com/world/rss"),
    _f("PBS News - Headlines", "https://www.pbs.org/newshour/feeds/rss/headlines"),
    _f("CBS News - Latest", "https://www.cbsnews.com/latest/rss/main"),
    _f("Al Jazeera - All", "https://www.aljazeera.com/xml/rss/all.xml"),
    _f("Le Monde - English", "https://www.lemonde.fr/en/rss/une.xml"),
    _f("France 24 - English", "https://www.france24.com/en/rss"),
    _f("DW - English", "https://rss.dw.com/rdf/rss-en-all"),
    # business
    _f("BBC News - Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    _f("NPR - Business", "https://feeds.npr.org/1006/rss.xml"),
    _f("CNBC - Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    # science and health
    _f("BBC News - Science", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "Science & AI"),
    _f("NASA - News", "https://www.nasa.gov/news-release/feed/", "Science & AI"),
    _f("ScienceDaily - Top Science", "https://www.sciencedaily.com/rss/top/science.xml", "Science & AI"),
    _f("NPR - Health", "https://feeds.npr.org/1128/rss.xml"),
    # technology (general audience)
    _f("BBC News - Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml", "Tech"),
    _f("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "Tech"),
    _f("The Verge", "https://www.theverge.com/rss/index.xml", "Tech"),
    # sports
    _f("ESPN - Top Headlines", "https://www.espn.com/espn/rss/news", "Sports"),
    _f("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml", "Sports"),
    # culture
    _f("BBC News - Entertainment & Arts", "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml", "Entertainment"),
    _f("The Guardian - Culture", "https://www.theguardian.com/culture/rss", "Entertainment"),
    _f("NPR - Arts & Life", "https://feeds.npr.org/1008/rss.xml", "Entertainment"),
]

#: The six feeds shipped before per-feed settings existed (used to migrate untouched settings).
LEGACY_DEFAULT_ENTRIES = [
    "News|https://feeds.bbci.co.uk/news/rss.xml",
    "News|https://feeds.npr.org/1001/rss.xml",
    "News|https://www.theguardian.com/us-news/rss",
    "Sports|https://www.espn.com/espn/rss/news",
    "Entertainment|https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
    "Science & AI|https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
]


def default_feeds() -> list[FeedSpec]:
    return [f.model_copy() for f in DEFAULT_FEEDS]


def feeds_from_entries(entries: list[str]) -> list[FeedSpec]:
    """Old ``news_rss_feeds`` strings -> FeedSpec list (untouched old defaults -> new defaults)."""
    if list(entries) == LEGACY_DEFAULT_ENTRIES:
        return default_feeds()
    from agent_reach.ingestion.news import parse_feed_entry

    out = []
    for e in entries:
        cat, url, name = parse_feed_entry(e)
        out.append(FeedSpec(name=name, url=url, category=cat.value))
    return out


# ====================================================================== testing a feed
@dataclass
class FeedTestResult:
    ok: bool
    items: int
    message: str
    newest_utc: datetime | None = None
    feed_title: str = ""


def check_feed(spec: FeedSpec, settings=None) -> FeedTestResult:
    """Fetch one feed now and report what the next refresh would get from it. Never raises."""
    from agent_reach.config import Settings
    from agent_reach.ingestion.news import NewsRSSIngester

    settings = settings or Settings()
    settings = settings.model_copy(update={"news_rss_feeds": [spec.entry()], "http_max_retries": 1})

    async def run():
        import httpx

        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:  # same client as a refresh
            return await NewsRSSIngester(client, settings, asyncio.Semaphore(2)).run()

    try:
        items, stat = asyncio.run(run())
    except Exception as exc:  # noqa: BLE001 - a test result, never a crash
        return FeedTestResult(False, 0, f"Could not test the feed: {type(exc).__name__}: {str(exc)[:160]}")
    if not stat.ok or not items:
        from agent_reach.daily.edition import friendly_error

        reason = (stat.feeds[0].error if stat.feeds else stat.error) or "no articles"
        return FeedTestResult(False, 0, f"Not working: {friendly_error(reason)}")
    dated = [datetime.fromisoformat(i.metadata["published_at"]) for i in items if i.metadata.get("published_at")]
    newest = max(dated) if dated else None
    when = ""
    if newest is not None:
        hours = (datetime.now(timezone.utc) - newest).total_seconds() / 3600
        when = f"; newest article {hours:.0f} h old" if hours >= 1 else "; newest article under an hour old"
        if hours > 72:
            when += " (this feed may no longer be updated)"
    else:
        when = "; articles carry no publication time"
    title = str(items[0].metadata.get("feed_title") or "")
    return FeedTestResult(True, len(items), f"Working: {len(items)} articles{when}.", newest, title)
