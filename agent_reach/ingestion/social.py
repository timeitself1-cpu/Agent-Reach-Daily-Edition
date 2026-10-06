"""Social & viral ingesters: X (via Trends24), Reddit (JSON with RSS fallback), TikTok Creative Center,
Mastodon trending links and Bluesky trending topics (public APIs, no account)."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup

from agent_reach.ingestion.base import (
    BaseIngester,
    IngestionError,
    epoch_to_utc,
    parse_count,
    parse_optional_datetime,
    xml_child_text,
    xml_local,
)
from agent_reach.ingestion.news import _URL_PREFIX_RX
from agent_reach.models import CategoryEnum, FeedStat, RawTrendItem, SourceName

SUBREDDIT_CATEGORY: dict[str, CategoryEnum] = {
    "news": CategoryEnum.NEWS,
    "worldnews": CategoryEnum.NEWS,
    "politics": CategoryEnum.NEWS,
    "technology": CategoryEnum.TECH,
    "programming": CategoryEnum.TECH,
    "gadgets": CategoryEnum.TECH,
    "apple": CategoryEnum.TECH,
    "android": CategoryEnum.TECH,
    "science": CategoryEnum.SCIENCE_AI,
    "space": CategoryEnum.SCIENCE_AI,
    "machinelearning": CategoryEnum.SCIENCE_AI,
    "artificial": CategoryEnum.SCIENCE_AI,
    "localllama": CategoryEnum.SCIENCE_AI,
    "openai": CategoryEnum.SCIENCE_AI,
    "sports": CategoryEnum.SPORTS,
    "nfl": CategoryEnum.SPORTS,
    "nba": CategoryEnum.SPORTS,
    "soccer": CategoryEnum.SPORTS,
    "baseball": CategoryEnum.SPORTS,
    "hockey": CategoryEnum.SPORTS,
    "cfb": CategoryEnum.SPORTS,
    "formula1": CategoryEnum.SPORTS,
    "movies": CategoryEnum.ENTERTAINMENT,
    "television": CategoryEnum.ENTERTAINMENT,
    "music": CategoryEnum.ENTERTAINMENT,
    "entertainment": CategoryEnum.ENTERTAINMENT,
    "gaming": CategoryEnum.ENTERTAINMENT,
    "popculturechat": CategoryEnum.ENTERTAINMENT,
    "memes": CategoryEnum.INTERNET_CULTURE,
    "outoftheloop": CategoryEnum.INTERNET_CULTURE,
    "interestingasfuck": CategoryEnum.INTERNET_CULTURE,
    "damnthatsinteresting": CategoryEnum.INTERNET_CULTURE,
}


# =====================================================================  X / Trends24
class XTrends24Ingester(BaseIngester):
    """Scrapes the most recent hourly trend card from trends24.in."""

    source = SourceName.X_TRENDS24

    async def fetch(self) -> list[RawTrendItem]:
        region = self.settings.trends24_region.strip("/")
        url = f"https://trends24.in/{region}/"
        html = await self.get_text(url)
        soup = BeautifulSoup(html, "html.parser")

        # Layout A (current): <div class="list-container"> ... <ol class="trend-card__list"><li>...
        lists = soup.select("ol.trend-card__list")
        entries: list[tuple[str, float | None]] = []
        if lists:
            for li in lists[0].find_all("li"):
                a = li.select_one("a.trend-link") or li.find("a")
                if not a:
                    continue
                name = a.get_text(" ", strip=True)
                count_el = li.select_one(".tweet-count")
                count = None
                if count_el is not None:
                    count = parse_count(count_el.get("data-count") or count_el.get_text(strip=True))
                entries.append((name, count))
        # Layout B (fallback): any search links to X/Twitter
        if not entries:
            seen: set[str] = set()
            for a in soup.select('a[href*="twitter.com/search"], a[href*="x.com/search"]'):
                name = a.get_text(" ", strip=True)
                if name and name.lower() not in seen:
                    seen.add(name.lower())
                    entries.append((name, None))
        if not entries:
            raise IngestionError("trends24 markup not recognised (no trend lists found)")

        n = len(entries)
        now = datetime.now(timezone.utc)
        items: list[RawTrendItem] = []
        for rank, (name, count) in enumerate(entries, start=1):
            # rank-based score when volume is missing: #1 -> n, last -> 1
            score = count if count is not None else float(n - rank + 1)
            item = self.make_item(
                title=name,
                raw_score=score,
                url=f"https://x.com/search?q={quote(name)}",
                timestamp=now,
                metadata={"rank": rank, "tweet_volume": count},
            )
            if item:
                items.append(item)
        return items


# =====================================================================  Reddit
def _group_by_cause(errors: list[str]) -> list[str]:
    """'r/news: HTTP 429', 'r/worldnews: HTTP 429' -> 'r/news, r/worldnews: HTTP 429' (fits the health note)."""
    by_cause: dict[str, list[str]] = {}
    for err in errors:
        name, sep, cause = err.partition(": ")
        if sep and name.startswith("r/"):
            by_cause.setdefault(cause, []).append(name)
        else:
            by_cause.setdefault(err, [])
    return [f"{', '.join(names)}: {cause}" if names else cause for cause, names in by_cause.items()]


class RedditIngester(BaseIngester):
    """Top posts of the day per subreddit.

    Resilience model (Reddit blocks and rate-limits unauthenticated clients, hardest from
    data-centre IPs such as CI runners):

    * every request uses the fixed browser headers, a ``reddit_timeout_s`` (5 s) timeout and
      exponential-backoff retries on 403/429/5xx/timeouts (``reddit_max_retries``), honouring
      ``Retry-After``;
    * ALL Reddit requests are paced at least ``reddit_request_spacing_s`` (2 s) apart;
    * JSON listings carry score/comment counts; after the first definitive JSON 403/429 the
      remaining subreddits go straight to RSS (circuit breaker);
    * a ``reddit_budget_s`` wall-clock budget stops starting new subreddits, so Reddit can
      never stall the ingestion stage. Failures return what was collected, never raise.
    """

    source = SourceName.REDDIT
    use_bot_user_agent = False
    rotate_user_agent = False  # always send DEFAULT_HEADERS verbatim

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._json_blocked = False
        self.min_request_interval_s = self.settings.reddit_request_spacing_s

    async def fetch(self) -> list[RawTrendItem]:
        subs = self.settings.reddit_subreddits
        per_sub = max(5, self.settings.max_items_per_source // max(1, len(subs)))
        started = time.monotonic()
        items: list[RawTrendItem] = []
        errors: list[str] = []
        skipped = 0
        for sub in subs:  # sequential by design: pacing makes parallelism pointless and riskier
            if time.monotonic() - started > self.settings.reddit_budget_s:
                skipped += 1
                continue
            got, err = await self._fetch_sub(sub, per_sub)
            items.extend(got)
            if err:
                # 'r/news' already names the listing: keep the URL out so the cause fits the health note
                errors.append(_URL_PREFIX_RX.sub("", err))
        errors = _group_by_cause(errors)
        if skipped:
            errors.append(f"{skipped} subreddit(s) skipped: {self.settings.reddit_budget_s:.0f}s budget exhausted")
        if not items and errors:
            raise IngestionError("; ".join(errors)[:300])
        if errors:
            self.log.info("%d issue(s): %s", len(errors), "; ".join(errors)[:240])
            self.warnings.extend(errors)
        # verified (JSON) items first by score, then RSS items by rank
        items.sort(
            key=lambda it: (
                bool(it.metadata.get("metrics_verified")),
                it.raw_score or 0.0,
                -int(it.metadata.get("rank") or 999),
            ),
            reverse=True,
        )
        return items

    async def _fetch_sub(self, sub: str, per_sub: int) -> tuple[list[RawTrendItem], str | None]:
        if not self._json_blocked:
            try:
                return await self._fetch_json(sub, per_sub), None
            except IngestionError as exc:
                if any(code in str(exc) for code in ("403", "429", "Blocked")):
                    self._json_blocked = True
                    self.log.info("JSON blocked (%s); remaining subreddits use RSS", str(exc)[:100])
                    code = "429 rate limit" if "429" in str(exc) else "403 blocked"
                    self.warnings.append(f"JSON listings refused ({code}); used RSS without engagement counts")
        try:
            return await self._fetch_rss(sub, per_sub), None
        except IngestionError as exc:
            return [], f"r/{sub}: {str(exc)[:120]}"

    async def _fetch_json(self, sub: str, limit: int) -> list[RawTrendItem]:
        data = await self.get_json(
            f"https://www.reddit.com/r/{sub}/top.json",
            params={"t": "day", "limit": min(100, limit * 2), "raw_json": 1},
            timeout=self.settings.reddit_timeout_s,
            max_retries=min(1, self.settings.reddit_max_retries),  # one retry, then RSS is cheaper
            retry_statuses={403},
        )
        children = (data or {}).get("data", {}).get("children", [])
        hint = SUBREDDIT_CATEGORY.get(sub.lower())
        out: list[RawTrendItem] = []
        for child in children:
            d: dict[str, Any] = child.get("data", {})
            if d.get("stickied") or d.get("over_18") or d.get("promoted"):
                continue
            subreddit = str(d.get("subreddit", sub))
            item = self.make_item(
                title=d.get("title", ""),
                raw_score=float(d.get("score") or 0),
                comment_count=int(d.get("num_comments") or 0),
                url=f"https://www.reddit.com{d.get('permalink', '')}",
                published_at=epoch_to_utc(d.get("created_utc")),
                category_hint=SUBREDDIT_CATEGORY.get(subreddit.lower(), hint),
                description=(d.get("selftext") or "")[:500] or None,
                metadata={
                    "subreddit": subreddit,
                    "metrics_verified": True,
                    "is_self": bool(d.get("is_self")),
                    "post_hint": d.get("post_hint"),
                    "link_flair": d.get("link_flair_text"),
                    "external_url": d.get("url_overridden_by_dest"),
                },
            )
            if item:
                out.append(item)
            if len(out) >= limit:
                break
        return out

    async def _fetch_rss(self, sub: str, limit: int) -> list[RawTrendItem]:
        root = await self.get_xml(
            f"https://www.reddit.com/r/{sub}/top/.rss",
            params={"t": "day", "limit": limit},
            timeout=self.settings.reddit_timeout_s,
            max_retries=self.settings.reddit_max_retries,
            retry_statuses={403},
        )
        hint = SUBREDDIT_CATEGORY.get(sub.lower())
        out: list[RawTrendItem] = []
        entries = [el for el in root.iter() if xml_local(el.tag) == "entry"]
        for rank, entry in enumerate(entries[:limit], start=1):
            link = next((c.get("href") for c in entry if xml_local(c.tag) == "link"), None)
            category = next((c.get("term") for c in entry if xml_local(c.tag) == "category"), sub)
            item = self.make_item(
                title=xml_child_text(entry, "title") or "",
                raw_score=None,
                url=link,
                published_at=parse_optional_datetime(xml_child_text(entry, "updated") or xml_child_text(entry, "published")),
                category_hint=SUBREDDIT_CATEGORY.get(str(category).lower(), hint),
                metadata={"subreddit": category, "metrics_verified": False, "rank": rank},
            )
            if item:
                out.append(item)
        return out


# =====================================================================  TikTok
_ESCAPED_HASHTAG_RX = re.compile(r'\\?"hashtag_?[nN]ame\\?"\s*:\s*\\?"([^"\\]{2,80})')


class TikTokCreativeCenterIngester(BaseIngester):
    """Trending hashtags from TikTok Creative Center.

    The public page embeds its initial data either in ``__NEXT_DATA__`` (pages router) or in escaped
    JSON chunks (``self.__next_f.push``, app router); both are read, then the rendered '# name' cards.
    A page that loads without hashtag data is tried once more without the country/period parameters
    (a blocked or failing request is not repeated beyond its retries). TikTok often blocks
    data-centre and automated clients; the source then fails on its own and the edition is built
    from the rest.
    """

    source = SourceName.TIKTOK
    PAGE = "https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.min_request_interval_s = self.settings.tiktok_request_spacing_s

    async def fetch(self) -> list[RawTrendItem]:
        records: list[dict[str, Any]] = []
        errors: list[str] = []
        for params in ({"countryCode": self.settings.geo, "period": 7}, None):
            try:
                # 5 s timeout, backoff retries on 403/429/5xx, attempts paced 2 s apart
                html = await self.get_text(self.PAGE, params=params, timeout=self.settings.tiktok_timeout_s,
                                           max_retries=self.settings.tiktok_max_retries, retry_statuses={403})
            except IngestionError as exc:  # blocked or down: asking again with other parameters would not help
                errors.append(str(exc)[:160])
                break
            records = self.records_from_html(html)
            if records:
                break
            errors.append("no hashtag data in the page (likely bot-gated)")
        if not records:
            raise IngestionError("TikTok Creative Center returned no hashtag data: " + "; ".join(errors)[:240])

        seen: set[str] = set()
        items: list[RawTrendItem] = []
        n = len(records)
        for rank, rec in enumerate(records, start=1):
            name = str(rec.get("hashtagName") or rec.get("hashtag_name") or "").strip().lstrip("#")
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            views = rec.get("videoViews") or rec.get("video_views") or rec.get("publishCnt") or rec.get("publish_cnt")
            try:
                score = float(views) if views is not None else float(n - rank + 1)
            except (TypeError, ValueError):
                score = float(n - rank + 1)
            industry = rec.get("industryInfo") or rec.get("industry_info") or {}
            item = self.make_item(
                title=f"#{name}",
                raw_score=score,
                url=f"https://www.tiktok.com/tag/{quote(name)}",
                category_hint=CategoryEnum.INTERNET_CULTURE,
                metadata={
                    "rank": rec.get("rank", rank),
                    "industry": industry.get("value") if isinstance(industry, dict) else None,
                    "is_promoted": bool(rec.get("isPromoted") or rec.get("is_promoted")),
                },
            )
            if item and not item.metadata.get("is_promoted"):
                items.append(item)
        return items

    @classmethod
    def records_from_html(cls, html: str) -> list[dict[str, Any]]:
        """Hashtag records from any of the page's data shapes (empty when none is present)."""
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script and script.string:
            try:
                records = list(cls._walk(json.loads(script.string)))
            except json.JSONDecodeError:
                records = []
            if records:
                return records
        names = list(dict.fromkeys(m.group(1).strip() for m in _ESCAPED_HASHTAG_RX.finditer(html)))
        if names:
            return [{"hashtagName": name} for name in names]
        return [{"hashtagName": str(span).strip().lstrip("# ").strip()}
                for span in soup.find_all(string=re.compile(r"^#\s?\w{2,}"))]

    @classmethod
    def _walk(cls, node: Any):
        if isinstance(node, dict):
            if "hashtagName" in node or "hashtag_name" in node:
                yield node
                return
            for v in node.values():
                yield from cls._walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from cls._walk(v)


# =====================================================================  Mastodon
def _history_accounts(history: Any, days: int = 2) -> int:
    """People who shared a link over the last ``days`` days (Mastodon history rows, newest first)."""
    total = 0
    for row in (history or [])[:days]:
        try:
            total += int((row or {}).get("accounts") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
    return total


class MastodonTrendsIngester(BaseIngester):
    """News links trending on Mastodon servers (``/api/v1/trends/links``, public, no account).

    Each link is a publisher's article that many people are sharing; the score is how many accounts
    shared it over the last two days. Every server is its own feed with its own health line.
    """

    source = SourceName.MASTODON
    use_bot_user_agent = True

    async def fetch(self) -> list[RawTrendItem]:
        instances = self.settings.mastodon_instances
        if not instances:
            raise IngestionError("no mastodon_instances configured")
        items: list[RawTrendItem] = []
        failures: list[str] = []
        self.feed_stats = []
        seen: set[str] = set()
        for host in instances:
            url = f"https://{host}/api/v1/trends/links"
            try:
                data = await self.get_json(url, params={"limit": 20}, timeout=self.settings.social_timeout_s,
                                           max_retries=1)
            except IngestionError as exc:
                failures.append(f"{host}: {str(exc)[:80]}")
                self.feed_stats.append(FeedStat(name=host, url=url, ok=False, error=str(exc)[:160]))
                continue
            got = 0
            for rank, card in enumerate(data if isinstance(data, list) else [], start=1):
                link = str((card or {}).get("url") or "")
                if not link or link in seen:
                    continue
                seen.add(link)
                item = self.make_item(
                    title=str(card.get("title") or "").strip(),
                    raw_score=float(_history_accounts(card.get("history"))),
                    url=link,
                    published_at=parse_optional_datetime(card.get("published_at")),
                    description=(str(card.get("description") or "").strip()[:500] or None),
                    metadata={"publisher": (str(card.get("provider_name") or "").strip() or None), "rank": rank,
                              "instance": host, "feed": url, "accounts_2d": _history_accounts(card.get("history"))},
                )
                if item:
                    items.append(item)
                    got += 1
            self.feed_stats.append(FeedStat(name=host, url=url, ok=True, item_count=got))
        if len(failures) == len(instances):
            raise IngestionError("; ".join(failures)[:300])
        if failures:
            self.warnings.append(f"{len(failures)}/{len(instances)} servers failed ({'; '.join(failures)})")
        items.sort(key=lambda it: it.raw_score or 0.0, reverse=True)
        return items


# =====================================================================  Bluesky
BLUESKY_CATEGORY: dict[str, CategoryEnum] = {
    "sports": CategoryEnum.SPORTS, "politics": CategoryEnum.NEWS, "news": CategoryEnum.NEWS,
    "pop-culture": CategoryEnum.ENTERTAINMENT, "video-games": CategoryEnum.ENTERTAINMENT,
    "entertainment": CategoryEnum.ENTERTAINMENT, "music": CategoryEnum.ENTERTAINMENT,
    "tech": CategoryEnum.TECH, "technology": CategoryEnum.TECH, "science": CategoryEnum.SCIENCE_AI,
}


class BlueskyTrendsIngester(BaseIngester):
    """Trending topics on Bluesky (public AppView API, no account).

    ``app.bsky.unspecced.getTrends`` carries post counts and a category; the older
    ``getTrendingTopics`` is the fallback. Topics are attention signals, like X trends.
    """

    source = SourceName.BLUESKY
    use_bot_user_agent = True
    API = "https://public.api.bsky.app/xrpc/"

    async def fetch(self) -> list[RawTrendItem]:
        errors: list[str] = []
        for method, key in (("app.bsky.unspecced.getTrends", "trends"),
                            ("app.bsky.unspecced.getTrendingTopics", "topics")):
            try:
                data = await self.get_json(self.API + method, params={"limit": 25},
                                           timeout=self.settings.social_timeout_s, max_retries=1)
            except IngestionError as exc:
                errors.append(str(exc)[:140])
                continue
            rows = (data or {}).get(key) if isinstance(data, dict) else None
            if rows:
                return self._items(rows)
            errors.append(f"{method}: no topics")
        raise IngestionError("Bluesky trends unavailable: " + "; ".join(errors)[:260])

    def _items(self, rows: list[dict[str, Any]]) -> list[RawTrendItem]:
        n = len(rows)
        out: list[RawTrendItem] = []
        for rank, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            name = str(row.get("displayName") or row.get("topic") or "").strip()
            link = str(row.get("link") or "")
            try:
                posts = int(row.get("postCount")) if row.get("postCount") is not None else None
            except (TypeError, ValueError):
                posts = None
            item = self.make_item(
                title=name,
                raw_score=float(posts) if posts is not None else float(n - rank + 1),
                url=f"https://bsky.app{link}" if link.startswith("/") else (link or None),
                category_hint=BLUESKY_CATEGORY.get(str(row.get("category") or "").lower()),
                description=(str(row.get("description") or "").strip() or None),
                metadata={"rank": rank, "post_count": posts, "status": row.get("status"),
                          "category": row.get("category")},
            )
            if item:
                out.append(item)
        return out
