"""General-news RSS ingester: public publisher feeds configured in ``news_rss_feeds``.

Each feed entry is ``"Category|URL"`` or ``"Category|URL|Publisher name"``. Feeds are fetched
concurrently; a failing feed is reported per feed and as partial coverage on the source's health
line while the others still count. Items are interleaved by in-feed rank so the source cap never
drops a whole feed.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from agent_reach.ingestion.base import (
    BaseIngester,
    IngestionError,
    parse_optional_datetime,
    xml_child_text,
    xml_local,
)
from agent_reach.models import CategoryEnum, FeedStat, RawTrendItem, SourceName


def parse_feed_entry(entry: str) -> tuple[CategoryEnum, str, str]:
    """'Category|URL' or 'Category|URL|Publisher name' -> (category, url, name)."""
    category, _, rest = entry.partition("|")
    url, _, name = rest.partition("|")
    url = url.strip()
    return CategoryEnum(category.strip()), url, name.strip() or (urlsplit(url).hostname or url)


class NewsRSSIngester(BaseIngester):
    """Top stories from public publisher RSS/Atom/RDF feeds (``news_rss_feeds``).

    Every feed is its own publisher channel: it gets its own allowance
    (``news_rss_items_per_feed``), its own health line in ``SourceStat.feeds``, and a failing
    feed only makes the source partial. The source cap scales with the number of feeds
    (bounded by ``news_rss_max_total_items``), so adding publishers never shrinks the others.
    """

    source = SourceName.NEWS_RSS
    use_bot_user_agent = True

    def item_cap(self) -> int:
        per_feed = self.settings.news_rss_items_per_feed * max(1, len(self.settings.news_rss_feeds))
        return min(self.settings.news_rss_max_total_items, max(self.settings.max_items_per_source, per_feed))

    async def fetch(self) -> list[RawTrendItem]:
        feeds = [parse_feed_entry(e) for e in self.settings.news_rss_feeds]
        if not feeds:
            raise IngestionError("no news_rss_feeds configured")
        results = await asyncio.gather(*(self._feed(cat, url, name) for cat, url, name in feeds),
                                       return_exceptions=True)
        per_feed: list[list[RawTrendItem]] = []
        failures: list[str] = []
        self.feed_stats = []
        for (cat, url, name), res in zip(feeds, results):
            if isinstance(res, BaseException):
                err = str(res)[:160] or type(res).__name__
                failures.append(f"{name}: {err[:80]}")
                self.feed_stats.append(FeedStat(name=name, url=url, category=cat.value, ok=False, error=err))
            elif not res:
                failures.append(f"{name}: no entries")
                self.feed_stats.append(FeedStat(name=name, url=url, category=cat.value, ok=False, error="no entries"))
            else:
                per_feed.append(res)
                self.feed_stats.append(FeedStat(name=name, url=url, category=cat.value, ok=True, item_count=len(res)))
        if not per_feed:
            raise IngestionError("all news feeds failed: " + "; ".join(failures)[:250])
        if failures:
            self.warnings.append(f"{len(failures)}/{len(feeds)} feeds failed ({'; '.join(failures)})")
        out: list[RawTrendItem] = []
        for rank in range(max(len(f) for f in per_feed)):  # round-robin: a cap never drops a whole feed
            out.extend(f[rank] for f in per_feed if rank < len(f))
        return out

    async def _feed(self, category: CategoryEnum, url: str, name: str = "") -> list[RawTrendItem]:
        root = await self.get_xml(url)
        entries = [el for el in root.iter() if xml_local(el.tag) in ("item", "entry")]
        limit = self.settings.news_rss_items_per_feed
        feed_title = ""
        for el in root.iter():
            if xml_local(el.tag) in ("channel", "feed"):
                feed_title = xml_child_text(el, "title") or ""
                break
        publisher = (name or feed_title or urlsplit(url).hostname or url)[:120]
        out: list[RawTrendItem] = []
        n = min(len(entries), limit)
        for rank, entry in enumerate(entries[:limit], start=1):
            title = xml_child_text(entry, "title") or ""
            link = None
            for c in entry:
                if xml_local(c.tag) == "link":
                    link = c.get("href") or (c.text or "").strip() or link
                    if c.get("rel") in (None, "alternate"):
                        break
            raw_desc = xml_child_text(entry, "description") or xml_child_text(entry, "summary") or ""
            desc = re.sub(r"\s+", " ", BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True))[:500] if raw_desc else ""
            item = self.make_item(
                title=title,
                raw_score=float(n - rank + 1),
                url=link,
                published_at=parse_optional_datetime(
                    xml_child_text(entry, "pubDate") or xml_child_text(entry, "published")
                    or xml_child_text(entry, "updated") or xml_child_text(entry, "date")  # RDF dc:date
                ),
                category_hint=category,
                description=desc or None,
                metadata={"feed": url, "feed_title": feed_title[:120], "rank": rank, "publisher": publisher},
            )
            if item:
                out.append(item)
        return out
