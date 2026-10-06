"""Publisher feeds for the daily edition: defaults, validation and a one-feed test.

Each feed is one publisher channel (``FeedSpec``): an RSS/Atom/RDF feed, or a YouTube channel
(its public channel feed). Enabled RSS feeds become ``news_rss_feeds`` entries
(``"Category|URL|Name"``) and enabled YouTube channels become ``youtube_channels`` entries
(``"Category|CHANNEL_ID|Name"``) for the pipeline, where every feed has its own allowance,
selection floor and health line.

The defaults cover world, US, business, science, health, technology, AI, sports, culture and
internet news from about 100 organisations, plus 22 YouTube news, tech, science, sports and
entertainment channels. Feed addresses change over time: a feed that stops working only makes the
source partial (shown per feed in Details), and Settings > Publisher feeds > Test checks any feed.
Categories use the edition's fixed category set (business and health stories file under News).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator

from agent_reach.config import DEFAULT_YOUTUBE_CHANNELS
from agent_reach.ingestion.video import channel_id_from_url, youtube_feed_url
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
        if (parts.hostname or "").lower().removeprefix("www.").removeprefix("m.") == "youtube.com":
            channel = channel_id_from_url(v)
            if channel is None:
                raise ValueError("for a YouTube channel use its channel address (https://www.youtube.com/channel/UC...) "
                                 "or its feed address (https://www.youtube.com/feeds/videos.xml?channel_id=UC...); "
                                 "an @handle address cannot be read without the channel id")
            return youtube_feed_url(channel)
        return v

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        if v not in CategoryEnum.values():
            raise ValueError(f"category must be one of {', '.join(CategoryEnum.values())}")
        return v

    @property
    def channel_id(self) -> str | None:
        """The YouTube channel id when this feed is a YouTube channel, else None."""
        return channel_id_from_url(self.url)

    @property
    def kind(self) -> str:
        return "YouTube" if self.channel_id else "Feed"

    def entry(self) -> str:
        """The pipeline entry: 'Category|URL|Name' (news_rss) or 'Category|CHANNEL_ID|Name' (youtube)."""
        return f"{self.category}|{self.channel_id or self.url}|{self.name}"

    @property
    def publisher(self) -> str:
        return self.name.split(" - ")[0]


def _f(name: str, url: str, category: str = "News") -> FeedSpec:
    return FeedSpec(name=name, url=url, category=category)


#: Default publisher feeds (with ADDED_IN_V2 and ADDED_IN_V3 below). Business and health file under News.
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

#: Added in settings version 2: deeper technology, AI and science coverage (alongside Hacker News).
ADDED_IN_V2: list[FeedSpec] = [
    _f("TechCrunch", "https://techcrunch.com/feed/", "Tech"),
    _f("Wired", "https://www.wired.com/feed/rss", "Tech"),
    _f("Engadget", "https://www.engadget.com/rss.xml", "Tech"),
    _f("The Register", "https://www.theregister.com/headlines.atom", "Tech"),
    _f("The Guardian - Technology", "https://www.theguardian.com/technology/rss", "Tech"),
    _f("NPR - Technology", "https://feeds.npr.org/1019/rss.xml", "Tech"),
    _f("Lobsters", "https://lobste.rs/rss", "Tech"),
    _f("MIT Technology Review", "https://www.technologyreview.com/feed/", "Science & AI"),
    _f("The Guardian - Science", "https://www.theguardian.com/science/rss", "Science & AI"),
    _f("NPR - Science", "https://feeds.npr.org/1007/rss.xml", "Science & AI"),
]
#: Added in settings version 3: more publishers in every section, and YouTube channels.
ADDED_IN_V3: list[FeedSpec] = [
    # news and politics
    _f("New York Times - Home Page", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
    _f("Washington Post - World", "https://feeds.washingtonpost.com/rss/world"),
    _f("NBC News - Top Stories", "https://feeds.nbcnews.com/nbcnews/public/news"),
    _f("ABC News - Top Stories", "https://abcnews.go.com/abcnews/topstories"),
    _f("Fox News - Latest", "https://moxie.foxnews.com/google-publisher/latest.xml"),
    _f("Sky News - World", "https://feeds.skynews.com/feeds/rss/world.xml"),
    _f("CBS News - World", "https://www.cbsnews.com/latest/rss/world"),
    _f("Politico - Politics", "https://rss.politico.com/politics-news.xml"),
    _f("The Hill", "https://thehill.com/feed/"),
    _f("MarketWatch - Top Stories", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    # technology
    _f("ZDNET", "https://www.zdnet.com/news/rss.xml", "Tech"),
    _f("Gizmodo", "https://gizmodo.com/feed", "Tech"),
    _f("9to5Mac", "https://9to5mac.com/feed/", "Tech"),
    _f("Tom's Hardware", "https://www.tomshardware.com/feeds/all", "Tech"),
    _f("Android Authority", "https://www.androidauthority.com/feed/", "Tech"),
    # science and AI
    _f("Ars Technica - AI", "https://arstechnica.com/ai/feed/", "Science & AI"),
    _f("The Decoder", "https://the-decoder.com/feed/", "Science & AI"),
    _f("Google - AI", "https://blog.google/technology/ai/rss/", "Science & AI"),
    _f("OpenAI - News", "https://openai.com/news/rss.xml", "Science & AI"),
    _f("Hugging Face - Blog", "https://huggingface.co/blog/feed.xml", "Science & AI"),
    _f("New Scientist", "https://www.newscientist.com/feed/home/", "Science & AI"),
    _f("SpaceNews", "https://spacenews.com/feed/", "Science & AI"),
    _f("Quanta Magazine", "https://www.quantamagazine.org/feed/", "Science & AI"),
    _f("Nature", "https://www.nature.com/nature.rss", "Science & AI"),
    # sports
    _f("CBS Sports - Headlines", "https://www.cbssports.com/rss/headlines/", "Sports"),
    _f("Yahoo Sports", "https://sports.yahoo.com/rss/", "Sports"),
    _f("Sky Sports - News", "https://www.skysports.com/rss/12040", "Sports"),
    _f("The Guardian - Sport", "https://www.theguardian.com/sport/rss", "Sports"),
    # entertainment
    _f("Variety", "https://variety.com/feed/", "Entertainment"),
    _f("The Hollywood Reporter", "https://www.hollywoodreporter.com/feed/", "Entertainment"),
    _f("Deadline", "https://deadline.com/feed/", "Entertainment"),
    _f("Billboard", "https://www.billboard.com/feed/", "Entertainment"),
    _f("Rolling Stone", "https://www.rollingstone.com/feed/", "Entertainment"),
    _f("IGN", "https://feeds.feedburner.com/ign/all", "Entertainment"),
    _f("Polygon", "https://www.polygon.com/rss/index.xml", "Entertainment"),
    # internet culture
    _f("The Daily Dot", "https://www.dailydot.com/feed/", "Internet Culture"),
    _f("Mashable", "https://mashable.com/feeds/rss/all", "Internet Culture"),
    # YouTube channels (most-watched recent uploads; see agent_reach.ingestion.video)
    *[_f(name, youtube_feed_url(cid), category)
      for category, cid, name in (e.split("|") for e in DEFAULT_YOUTUBE_CHANNELS)],
]
#: Added in settings version 4: international, analysis, security, AI research, league and culture feeds.
ADDED_IN_V4: list[FeedSpec] = [
    # news and analysis
    _f("Axios", "https://api.axios.com/feed/"),
    _f("Vox", "https://www.vox.com/rss/index.xml"),
    _f("The Atlantic", "https://www.theatlantic.com/feed/all/"),
    _f("ProPublica", "https://www.propublica.org/feeds/propublica/main"),
    _f("CBC News - Top Stories", "https://www.cbc.ca/webfeed/rss/rss-topstories"),
    _f("ABC News Australia - Top Stories", "https://www.abc.net.au/news/feed/2942460/rss.xml"),
    _f("South China Morning Post - World", "https://www.scmp.com/rss/91/feed"),
    _f("The Japan Times", "https://www.japantimes.co.jp/feed/"),
    _f("Times of India - Top Stories", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
    _f("Euronews", "https://www.euronews.com/rss?format=mrss&level=theme&name=news"),
    # business
    _f("Business Insider", "https://feeds.businessinsider.com/custom/all"),
    _f("Fortune", "https://fortune.com/feed/"),
    _f("Bloomberg - Markets", "https://feeds.bloomberg.com/markets/news.rss"),
    # technology and security
    _f("Techmeme", "https://www.techmeme.com/feed.xml", "Tech"),
    _f("The Next Web", "https://thenextweb.com/feed", "Tech"),
    _f("MacRumors", "https://feeds.macrumors.com/MacRumors-All", "Tech"),
    _f("BleepingComputer", "https://www.bleepingcomputer.com/feed/", "Tech"),
    _f("Krebs on Security", "https://krebsonsecurity.com/feed/", "Tech"),
    _f("Fast Company", "https://www.fastcompany.com/latest/rss", "Tech"),
    # science and AI
    _f("Google DeepMind - Blog", "https://deepmind.google/blog/rss.xml", "Science & AI"),
    _f("Simon Willison", "https://simonwillison.net/atom/everything/", "Science & AI"),
    _f("MarkTechPost", "https://www.marktechpost.com/feed/", "Science & AI"),
    _f("Science - News", "https://www.science.org/rss/news_current.xml", "Science & AI"),
    _f("Phys.org", "https://phys.org/rss-feed/", "Science & AI"),
    _f("ScienceAlert", "https://www.sciencealert.com/feed", "Science & AI"),
    # sports
    _f("ESPN - NFL", "https://www.espn.com/espn/rss/nfl/news", "Sports"),
    _f("ESPN - NBA", "https://www.espn.com/espn/rss/nba/news", "Sports"),
    _f("ESPN - MLB", "https://www.espn.com/espn/rss/mlb/news", "Sports"),
    _f("ESPN - Soccer", "https://www.espn.com/espn/rss/soccer/news", "Sports"),
    _f("BBC Sport - Football", "https://feeds.bbci.co.uk/sport/football/rss.xml", "Sports"),
    _f("Sporting News", "https://www.sportingnews.com/us/rss", "Sports"),
    # entertainment and games
    _f("Pitchfork - News", "https://pitchfork.com/rss/news/", "Entertainment"),
    _f("Collider", "https://collider.com/feed/", "Entertainment"),
    _f("Screen Rant", "https://screenrant.com/feed/", "Entertainment"),
    _f("Kotaku", "https://kotaku.com/rss", "Entertainment"),
    _f("Eurogamer", "https://www.eurogamer.net/feed", "Entertainment"),
    # internet culture and creators
    _f("Tubefilter", "https://www.tubefilter.com/feed/", "Internet Culture"),
    _f("Social Media Today", "https://www.socialmediatoday.com/feeds/news/", "Internet Culture"),
    _f("Boing Boing", "https://boingboing.net/feed", "Internet Culture"),
]
DEFAULT_FEEDS = DEFAULT_FEEDS + ADDED_IN_V2 + ADDED_IN_V3 + ADDED_IN_V4

#: Settings version 5: feeds that failed in real use, mapped to their replacement (None = removed).
#: VentureBeat answers automated readers with HTTP 429; MIT News moved its topic feeds; Space.com's
#: feed came back empty.
REPLACED_IN_V5: dict[str, FeedSpec | None] = {
    "https://venturebeat.com/category/ai/feed/": None,
    "https://news.mit.edu/rss/topic/artificial-intelligence2": _f(
        "MIT News - Artificial Intelligence", "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml",
        "Science & AI"),
    "https://www.space.com/feeds/all": _f("SpaceNews", "https://spacenews.com/feed/", "Science & AI"),
}

#: Settings version 6: MIT News answered both of its feed addresses with errors in real use; removed.
REPLACED_IN_V6: dict[str, FeedSpec | None] = {
    "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml": None,
}

#: Settings version 7: Yahoo Finance's feed answers HTTP 404 (October 2026); Bloomberg's markets feed
#: replaces it as the business wire.
REPLACED_IN_V7: dict[str, FeedSpec | None] = {
    "https://finance.yahoo.com/news/rssindex": _f("Bloomberg - Markets", "https://feeds.bloomberg.com/markets/news.rss"),
}

#: Settings version 8: The Independent answers automated readers with HTTP 429 every time (it works only in
#: a browser); CBS News's world feed replaces it.
REPLACED_IN_V8: dict[str, FeedSpec | None] = {
    "https://www.independent.co.uk/news/world/rss": _f("CBS News - World", "https://www.cbsnews.com/latest/rss/world"),
}

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
    from agent_reach.ingestion.video import YouTubeIngester

    settings = settings or Settings()
    youtube = spec.channel_id is not None
    key = "youtube_channels" if youtube else "news_rss_feeds"
    settings = settings.model_copy(update={key: [spec.entry()], "http_max_retries": 1})
    ingester = YouTubeIngester if youtube else NewsRSSIngester

    async def run():
        import httpx

        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:  # same client as a refresh
            return await ingester(client, settings, asyncio.Semaphore(2)).run()

    try:
        items, stat = asyncio.run(run())
    except Exception as exc:  # noqa: BLE001 - a test result, never a crash
        return FeedTestResult(False, 0, f"Could not test the feed: {type(exc).__name__}: {str(exc)[:160]}")
    if stat.ok and not items and youtube and stat.feeds and stat.feeds[0].ok:
        return FeedTestResult(True, 0, f"Working, but {stat.feeds[0].error or 'no recent uploads'}.")
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
