"""YouTube: the most-watched recent uploads of configured channels.

YouTube retired its public Trending page in 2025 and its Data API needs a key, so this source reads
the public per-channel Atom feeds (``/feeds/videos.xml?channel_id=...``, no key, no login). Each
feed lists a channel's latest uploads with a view count; uploads older than
``youtube_max_age_hours`` are skipped (a 24/7 live stream or an old upload is not today's trend),
and the rest are ranked by views per hour since upload. Every channel is its own feed: its own
allowance (``youtube_items_per_channel``), its own health line, and a failing channel only makes
the source partial.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from agent_reach.ingestion.base import BaseIngester, IngestionError, parse_optional_datetime, xml_child_text, xml_local
from agent_reach.models import CategoryEnum, FeedStat, RawTrendItem, SourceName

YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml"
CHANNEL_ID_RX = re.compile(r"UC[\w-]{22}")
_HASHTAGS_TAIL_RX = re.compile(r"(?:\s+#[\w-]+)+\s*$")
_BOILERPLATE_LINE_RX = re.compile(
    r"^\W*(?:subscribe|follow|watch (?:more|the full|live)|sign up|download|get (?:the|our)|for more|read more|"
    r"listen|join|support|visit|click|shop|buy|sponsor|thanks to|chapters?|timestamps?|credits?|music:|"
    r"check out|never miss|stay up to date|turn on notifications|#|http|www\.)"
    r"|\bis your (?:daily |trusted )?source\b|\b24/7\b",
    re.IGNORECASE,
)


def youtube_feed_url(channel_id: str) -> str:
    return f"{YOUTUBE_FEED}?channel_id={channel_id}"


def channel_id_from_url(url: str) -> str | None:
    """Channel id from a channel feed URL or a /channel/UC... page URL; None for anything else."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host not in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        return None
    if parts.path.rstrip("/") == "/feeds/videos.xml":
        cid = (parse_qs(parts.query).get("channel_id") or [""])[0]
    else:
        m = re.match(r"^/channel/(UC[\w-]{22})(?:/|$)", parts.path)
        cid = m.group(1) if m else ""
    return cid if CHANNEL_ID_RX.fullmatch(cid) else None


def parse_channel_entry(entry: str) -> tuple[CategoryEnum, str, str]:
    """'Category|CHANNEL_ID|Name' -> (category, channel id, name)."""
    category, _, rest = entry.partition("|")
    cid, _, name = rest.partition("|")
    return CategoryEnum(category.strip()), cid.strip(), name.strip() or cid.strip()


def clean_video_title(title: str, channel: str) -> str:
    """Drop trailing hashtags and a trailing ' | Channel name' signature."""
    t = _HASHTAGS_TAIL_RX.sub("", " ".join(title.split()))
    head, sep, tail = t.rpartition(" | ")
    if sep and head and len(tail.split()) <= 5:
        low = tail.lower()
        if channel.lower() in low or low in channel.lower() or "news" in low or low.startswith("#"):
            t = head
    return t.strip(" |-")


def video_description(text: str | None, limit: int = 400) -> str | None:
    """First substantive lines of a video description (no links, credits or calls to subscribe)."""
    if not text:
        return None
    kept: list[str] = []
    sentences = [s for line in text.splitlines() for s in re.split(r"(?<=[.!?])\s+", " ".join(line.split()))]
    for line in sentences:  # channel slogans often share a line with the useful sentence
        if len(line) < 25 or _BOILERPLATE_LINE_RX.search(line) or "http" in line or "www." in line:
            continue
        kept.append(line)
        if sum(len(k) for k in kept) >= limit or len(kept) >= 2:
            break
    out = " ".join(kept)[:limit].strip()
    return out or None


def _attr_of(entry, local: str, attr: str) -> str | None:
    for el in entry.iter():
        if xml_local(el.tag) == local and el.get(attr) is not None:
            return el.get(attr)
    return None


def _text_of(entry, local: str) -> str | None:
    for el in entry.iter():
        if xml_local(el.tag) == local and el.text and el.text.strip():
            return el.text.strip()
    return None


class YouTubeIngester(BaseIngester):
    """Recent uploads from ``youtube_channels`` ranked by views per hour (public feeds, no API key)."""

    source = SourceName.YOUTUBE

    def item_cap(self) -> int:
        per_channel = self.settings.youtube_items_per_channel * max(1, len(self.settings.youtube_channels))
        return max(1, min(self.settings.youtube_max_total_items, per_channel))

    async def fetch(self) -> list[RawTrendItem]:
        channels = [parse_channel_entry(e) for e in self.settings.youtube_channels]
        if not channels:
            raise IngestionError("no youtube_channels configured")
        results = await asyncio.gather(*(self._channel(cat, cid, name) for cat, cid, name in channels),
                                       return_exceptions=True)
        per_channel: list[list[RawTrendItem]] = []
        failures: list[str] = []
        self.feed_stats = []
        for (cat, cid, name), res in zip(channels, results):
            url = youtube_feed_url(cid)
            if isinstance(res, BaseException):
                err = str(res)[:160] or type(res).__name__
                failures.append(f"{name}: {err[:80]}")
                self.feed_stats.append(FeedStat(name=name, url=url, category=cat.value, ok=False, error=err))
                continue
            items, note = res
            self.feed_stats.append(FeedStat(name=name, url=url, category=cat.value, ok=True, item_count=len(items),
                                            error=note))
            if items:
                per_channel.append(items)
        if len(failures) == len(channels):
            raise IngestionError("all YouTube channels failed: " + "; ".join(failures)[:250])
        if failures:
            self.warnings.append(f"{len(failures)}/{len(channels)} channels failed ({'; '.join(failures)})")
        out: list[RawTrendItem] = []
        for rank in range(max((len(c) for c in per_channel), default=0)):  # round-robin: fair under the cap
            out.extend(c[rank] for c in per_channel if rank < len(c))
        return out

    async def _channel(self, category: CategoryEnum, channel_id: str, name: str) -> tuple[list[RawTrendItem], str | None]:
        root = await self.get_xml(YOUTUBE_FEED, params={"channel_id": channel_id})
        if xml_local(root.tag) != "feed":
            raise IngestionError("not a YouTube channel feed")
        channel = name or xml_child_text(root, "title") or channel_id
        entries = [el for el in root if xml_local(el.tag) == "entry"]
        now = datetime.now(timezone.utc)
        max_age_h = self.settings.youtube_max_age_hours
        videos: list[tuple[float, dict]] = []
        for entry in entries:
            published = parse_optional_datetime(xml_child_text(entry, "published"))
            if published is None:
                continue
            age_h = (now - published).total_seconds() / 3600
            if age_h > max_age_h or age_h < -0.25:
                continue
            link = next((c.get("href") for c in entry if xml_local(c.tag) == "link" and c.get("href")), None)
            try:
                views = int(_attr_of(entry, "statistics", "views") or 0)
            except ValueError:
                views = 0
            per_hour = views / max(1.0, age_h)
            videos.append((per_hour, {"title": xml_child_text(entry, "title") or "", "link": link,
                                      "published": published, "views": views,
                                      "video_id": xml_child_text(entry, "videoId"),
                                      "description": _text_of(entry, "description")}))
        if not videos:
            note = "no uploads in the last %g hours" % max_age_h if entries else "the channel feed lists no videos"
            return [], note
        videos.sort(key=lambda v: v[0], reverse=True)
        feed_url = youtube_feed_url(channel_id)
        out: list[RawTrendItem] = []
        for rank, (per_hour, v) in enumerate(videos[: self.settings.youtube_items_per_channel], start=1):
            item = self.make_item(
                title=clean_video_title(v["title"], channel),
                raw_score=round(per_hour, 2),
                url=v["link"],
                published_at=v["published"],
                category_hint=category,
                description=video_description(v["description"]),
                metadata={"feed": feed_url, "publisher": channel, "channel_id": channel_id, "rank": rank,
                          "views": v["views"], "views_per_hour": round(per_hour, 1), "video_id": v["video_id"],
                          "is_short": "/shorts/" in (v["link"] or "")},
            )
            if item:
                out.append(item)
        return out, None
