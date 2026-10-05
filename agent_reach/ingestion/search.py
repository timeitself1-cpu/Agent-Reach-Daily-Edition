"""Search & news ingesters: Google Trends RSS, Google News RSS, Wikipedia Pageviews, ArXiv."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

from bs4 import BeautifulSoup

from agent_reach.ingestion.base import (
    BaseIngester,
    IngestionError,
    parse_count,
    parse_optional_datetime,
    xml_child_text,
    xml_local,
)
from agent_reach.models import CategoryEnum, FeedStat, RawTrendItem, SourceName


# =====================================================================  Google Trends
class GoogleTrendsIngester(BaseIngester):
    """Daily trending searches RSS (includes approx traffic + linked news headlines)."""

    source = SourceName.GOOGLE_TRENDS
    URLS = (
        "https://trends.google.com/trending/rss",
        "https://trends.google.com/trends/trendingsearches/daily/rss",  # legacy endpoint
    )

    async def fetch(self) -> list[RawTrendItem]:
        last_exc: Exception | None = None
        for url in self.URLS:
            try:
                root = await self.get_xml(url, params={"geo": self.settings.geo})
                items = self._parse(root)
                if items:
                    return items
            except IngestionError as exc:
                last_exc = exc
        raise IngestionError(f"Google Trends RSS unavailable: {last_exc}")

    def _parse(self, root) -> list[RawTrendItem]:
        out: list[RawTrendItem] = []
        for el in root.iter():
            if xml_local(el.tag) != "item":
                continue
            title = xml_child_text(el, "title") or ""
            traffic = parse_count(xml_child_text(el, "approx_traffic"))
            news_titles: list[str] = []
            news_urls: list[str] = []
            for child in el:
                if xml_local(child.tag) == "news_item":
                    t = xml_child_text(child, "news_item_title")
                    u = xml_child_text(child, "news_item_url")
                    if t:
                        news_titles.append(t)
                    if u:
                        news_urls.append(u)
            item = self.make_item(
                title=title,
                raw_score=traffic,
                url=news_urls[0] if news_urls else f"https://www.google.com/search?q={quote(title)}",
                published_at=parse_optional_datetime(xml_child_text(el, "pubDate")),
                description=" | ".join(news_titles[:3]) or None,
                metadata={"news_titles": news_titles[:3], "news_urls": news_urls[:3], "approx_traffic": traffic},
            )
            if item:
                out.append(item)
        return out


# =====================================================================  Google News
#: Google News topic sections (``/rss/headlines/section/topic/<TOPIC>``).
GOOGLE_NEWS_TOPICS = frozenset({"WORLD", "NATION", "BUSINESS", "TECHNOLOGY", "SCIENCE", "HEALTH", "SPORTS",
                                "ENTERTAINMENT"})


def parse_section_entry(entry: str) -> tuple[CategoryEnum, str, str]:
    """'Category|TOPIC or search words|Name' -> (category, topic or query, name)."""
    category, _, rest = entry.partition("|")
    key, _, name = rest.partition("|")
    key = key.strip()
    return CategoryEnum(category.strip()), key, name.strip() or f"Google News - {key.title()}"


class GoogleNewsIngester(BaseIngester):
    """Top stories RSS, plus optional per-category sections (``google_news_sections``).

    Google appends ' - Publisher' to titles; we split that off and keep the publisher. A section is a
    Google News topic (WORLD, TECHNOLOGY, SPORTS, ...) or a search limited to the last day. Each
    section is its own feed with its own allowance and health line; a failing section only makes the
    source partial. Scores are rank-based (1.0 for each section's first story), so every section's
    lead stories rank alike.
    """

    source = SourceName.GOOGLE_NEWS
    BASE = "https://news.google.com/rss"

    def item_cap(self) -> int:
        sections = len(self.settings.google_news_sections)
        base = self.settings.max_items_per_source
        return base + sections * self.settings.google_news_items_per_section if sections else base

    def _locale(self) -> dict[str, str]:
        geo = self.settings.geo.upper()
        return {"hl": f"en-{geo}", "gl": geo, "ceid": f"{geo}:en"}

    def section_url(self, key: str) -> str:
        params = self._locale()
        if key in GOOGLE_NEWS_TOPICS:
            return f"{self.BASE}/headlines/section/topic/{key}?{urlencode(params)}"
        return f"{self.BASE}/search?{urlencode({'q': f'{key} when:1d', **params})}"

    async def fetch(self) -> list[RawTrendItem]:
        top_url = f"{self.BASE}?{urlencode(self._locale())}"
        sections = [parse_section_entry(e) for e in self.settings.google_news_sections]
        if not sections:
            return await self._read(top_url, CategoryEnum.NEWS, None, self.settings.max_items_per_source)
        jobs = [("Google News - Top stories", top_url, CategoryEnum.NEWS, "", self.settings.max_items_per_source)]
        jobs += [(name, self.section_url(key), cat, name, self.settings.google_news_items_per_section)
                 for cat, key, name in sections]
        results = await asyncio.gather(*(self._read(url, cat, sec, limit) for _, url, cat, sec, limit in jobs),
                                       return_exceptions=True)
        per_section: list[list[RawTrendItem]] = []
        failures: list[str] = []
        self.feed_stats = []
        for (name, url, cat, _sec, _limit), res in zip(jobs, results):
            if isinstance(res, BaseException) or not res:
                err = (str(res)[:160] or type(res).__name__) if isinstance(res, BaseException) else "no entries"
                failures.append(f"{name}: {err[:80]}")
                self.feed_stats.append(FeedStat(name=name, url=url, category=cat.value, ok=False, error=err))
                continue
            per_section.append(res)
            self.feed_stats.append(FeedStat(name=name, url=url, category=cat.value, ok=True, item_count=len(res)))
        if not per_section:
            raise IngestionError("all Google News sections failed: " + "; ".join(failures)[:250])
        if failures:
            self.warnings.append(f"{len(failures)}/{len(jobs)} sections failed ({'; '.join(failures)})")
        out: list[RawTrendItem] = []
        for rank in range(max(len(x) for x in per_section)):  # round-robin: a cap never drops a whole section
            out.extend(x[rank] for x in per_section if rank < len(x))
        return out

    async def _read(self, url: str, category: CategoryEnum, section: str | None, limit: int) -> list[RawTrendItem]:
        root = await self.get_xml(url)
        out: list[RawTrendItem] = []
        entries = [el for el in root.iter() if xml_local(el.tag) == "item"][:limit]
        n = len(entries)
        for rank, el in enumerate(entries, start=1):
            raw_title = xml_child_text(el, "title") or ""
            publisher = xml_child_text(el, "source")
            title = raw_title
            if publisher and raw_title.endswith(f" - {publisher}"):
                title = raw_title[: -len(publisher) - 3]
            else:
                title = re.sub(r"\s+-\s+[^-]{2,60}$", "", raw_title)
            metadata = {"publisher": publisher, "rank": rank,
                        "publisher_url": next((node.get("url") for node in el if xml_local(node.tag) == "source"), None)}
            if section is not None:  # with sections, every section (top stories too) has its own health line
                metadata.update(feed=url, section=section or "Top stories")
                if not section:
                    metadata["top_stories"] = True  # keeps the source-wide floor in the processing budget
            item = self.make_item(
                title=title,
                raw_score=round(1.0 - (rank - 1) / max(1, n), 4),
                url=xml_child_text(el, "link"),
                published_at=parse_optional_datetime(xml_child_text(el, "pubDate")),
                category_hint=category,
                metadata=metadata,
            )
            if item:
                out.append(item)
        return out


# =====================================================================  Wikipedia
WIKI_EXCLUDE = re.compile(
    r"^(Main_Page|Special:|Wikipedia:|File:|Portal:|Help:|Talk:|Category:|Template:|User:|Draft:|Module:|"
    r"Deaths_in_|List_of_|Search$|Undefined$|-$|\d{4}_in_|\d{4}$)",
    re.IGNORECASE,
)


class WikipediaPageviewsIngester(BaseIngester):
    """Top viewed articles for the most recent complete UTC day, plus (optionally) the curated
    "In the news" list of the featured-content feed (``wikipedia_in_the_news``).

    "In the news" items come first so the source cap never drops them; when that list is
    unavailable the source is partial, never failed, as long as the page views answered.
    """

    source = SourceName.WIKIPEDIA
    use_bot_user_agent = True

    async def fetch(self) -> list[RawTrendItem]:
        project = self.settings.wikipedia_project
        today = datetime.now(timezone.utc).date()
        last_exc: Exception | None = None
        viewed: list[RawTrendItem] | None = None
        for days_back in (1, 2):
            day = today - timedelta(days=days_back)
            url = (
                "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
                f"{project}/all-access/{day.year:04d}/{day.month:02d}/{day.day:02d}"
            )
            try:
                data = await self.get_json(url)
            except IngestionError as exc:
                last_exc = exc
                continue
            articles = ((data or {}).get("items") or [{}])[0].get("articles", [])
            viewed = self._parse(articles, day)
            break
        news: list[RawTrendItem] = []
        if self.settings.wikipedia_in_the_news:
            try:
                news = await self._in_the_news(today, viewed or [])
            except IngestionError as exc:
                if viewed is None:
                    raise IngestionError(f"Wikipedia unavailable: {last_exc}; In the news: {exc}") from exc
                self.warnings.append(f"'In the news' unavailable ({str(exc)[:100]})")
        if viewed is None and not news:
            raise IngestionError(f"Wikipedia pageviews unavailable: {last_exc}")
        return news + (viewed or [])

    async def _in_the_news(self, today, viewed: list[RawTrendItem]) -> list[RawTrendItem]:
        """Wikipedia's curated 'In the news' stories (one sentence each, linked to the main article)."""
        lang = self.settings.wikipedia_project.split(".")[0]
        views = sorted(it.raw_score or 0.0 for it in viewed)
        median = views[len(views) // 2] if views else 1.0  # mid-pack attention: curated, not most-read
        last_exc: Exception | None = None
        for day in (today, today - timedelta(days=1)):
            url = f"https://{lang}.wikipedia.org/api/rest_v1/feed/featured/{day.year:04d}/{day.month:02d}/{day.day:02d}"
            try:
                data = await self.get_json(url)
            except IngestionError as exc:
                last_exc = exc
                continue
            out: list[RawTrendItem] = []
            for rank, story in enumerate((data or {}).get("news") or [], start=1):
                text = BeautifulSoup(str((story or {}).get("story") or ""), "html.parser").get_text()
                text = re.sub(r"\s*\(\s*(?:pictured|shown|featured)[^)]*\)", "", text)
                text = re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s+", " ", text)).strip()
                links = [link for link in (story or {}).get("links") or [] if isinstance(link, dict)]
                lead = links[0] if links else {}
                page = ((lead.get("content_urls") or {}).get("desktop") or {}).get("page")
                item = self.make_item(
                    title=text,
                    raw_score=float(median),
                    url=page or f"https://{lang}.wikipedia.org/wiki/Main_Page",
                    description=(str(lead.get("extract") or "")[:400] or None),
                    metadata={"in_the_news": True, "rank": rank, "date": day.isoformat(),
                              "articles": [str(link.get("title") or "") for link in links[:5]]},
                )
                if item:
                    out.append(item)
            if out:
                return out
            last_exc = IngestionError("no 'In the news' stories")
        raise IngestionError(str(last_exc)[:200])

    def _parse(self, articles: list[dict], day) -> list[RawTrendItem]:
        out: list[RawTrendItem] = []
        ts = datetime(day.year, day.month, day.day, 23, 59, tzinfo=timezone.utc)
        lang = self.settings.wikipedia_project.split(".")[0]
        for a in articles:
            name = str(a.get("article", ""))
            if not name or WIKI_EXCLUDE.search(name):
                continue
            item = self.make_item(
                title=name.replace("_", " "),
                raw_score=float(a.get("views") or 0),
                url=f"https://{lang}.wikipedia.org/wiki/{quote(name)}",
                timestamp=ts,
                metadata={"rank": a.get("rank"), "views": a.get("views"), "date": day.isoformat()},
            )
            if item:
                out.append(item)
            if len(out) >= self.settings.max_items_per_source:
                break
        return out


# =====================================================================  ArXiv
class ArxivIngester(BaseIngester):
    """Newest submissions in configured AI/ML categories (Atom API)."""

    source = SourceName.ARXIV
    use_bot_user_agent = True

    async def fetch(self) -> list[RawTrendItem]:
        query = " OR ".join(f"cat:{c}" for c in self.settings.arxiv_categories)
        root = await self.get_xml(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": query,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": self.settings.max_items_per_source,
            },
        )
        entries = [el for el in root if xml_local(el.tag) == "entry"]
        n = len(entries)
        out: list[RawTrendItem] = []
        for rank, entry in enumerate(entries, start=1):
            title = re.sub(r"\s+", " ", xml_child_text(entry, "title") or "")
            summary = re.sub(r"\s+", " ", xml_child_text(entry, "summary") or "")
            link = xml_child_text(entry, "id")
            for c in entry:
                if xml_local(c.tag) == "link" and c.get("rel") == "alternate":
                    link = c.get("href") or link
            categories = [c.get("term") for c in entry if xml_local(c.tag) == "category" and c.get("term")]
            authors = [xml_child_text(a, "name") for a in entry if xml_local(a.tag) == "author"]
            item = self.make_item(
                title=title,
                raw_score=float(n - rank + 1),
                url=link,
                published_at=parse_optional_datetime(xml_child_text(entry, "published")),
                category_hint=CategoryEnum.SCIENCE_AI,
                description=summary[:500] or None,
                metadata={"categories": categories, "authors": [a for a in authors if a][:5]},
            )
            if item:
                out.append(item)
        return out
