"""YouTube channels, Google News sections, TikTok page shapes and the settings v3 upgrade (offline)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from agent_reach.config import DEFAULT_GOOGLE_NEWS_SECTIONS, Settings
from agent_reach.daily.feeds import ADDED_IN_V3, ADDED_IN_V4, FeedSpec, check_feed
from agent_reach.daily.prefs import PREFS_VERSION, DailyPrefs, build_settings, load_prefs
from agent_reach.ingestion import INGESTER_REGISTRY
from agent_reach.ingestion.search import GoogleNewsIngester
from agent_reach.ingestion.social import TikTokCreativeCenterIngester
from agent_reach.ingestion.video import (
    YouTubeIngester,
    channel_id_from_url,
    clean_video_title,
    video_description,
    youtube_feed_url,
)
from agent_reach.models import CategoryEnum, CleanedTrendItem, SourceName
from agent_reach.pipeline.cleaner import TrendCleaner
from tests.daily_fakes import RealAsyncClient

CH_A = "UCaaaaaaaaaaaaaaaaaaaaaa"
CH_B = "UCbbbbbbbbbbbbbbbbbbbbbb"
CH_C = "UCcccccccccccccccccccccc"


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _video(vid: str, title: str, hours_ago: float, views: int, desc: str = "") -> str:
    return (f"<entry><id>yt:video:{vid}</id><yt:videoId>{vid}</yt:videoId><title>{title}</title>"
            f'<link rel="alternate" href="https://www.youtube.com/watch?v={vid}"/>'
            f"<published>{_iso(hours_ago)}</published><updated>{_iso(0.1)}</updated>"
            f"<media:group><media:title>{title}</media:title><media:description>{desc}</media:description>"
            f'<media:community><media:starRating count="10" average="5.00"/><media:statistics views="{views}"/>'
            f"</media:community></media:group></entry>")


def _channel_feed(title: str, entries: list[str]) -> bytes:
    return ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
            'xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">'
            f"<title>{title}</title>{''.join(entries)}</feed>").encode()


CHANNEL_FEEDS = {
    CH_A: _channel_feed("Wire One", [
        _video("a1", "Ferry strike halts island service | Wire One", 2, 1000,
               "Ferry workers began a 48-hour strike over pay on Tuesday.\nSubscribe to our channel: https://x.test\n"
               "Follow us on social media for more news updates and coverage"),
        _video("a2", "Quake damages roads near Port Calder #news #shorts", 10, 50_000),  # 5,000 views/hour
        _video("a3", "Old interview from last month", 24 * 30, 9_000_000),  # too old: not today's trend
        _video("a4", "Summit agrees methane pledge", 5, 2_000),
    ]),
    CH_C: _channel_feed("Quiet Channel", [_video("c1", "An upload from two weeks ago", 24 * 14, 100)]),
}


def _yt_handler(req: httpx.Request) -> httpx.Response:
    cid = req.url.params.get("channel_id")
    if cid in CHANNEL_FEEDS:
        return httpx.Response(200, content=CHANNEL_FEEDS[cid])
    return httpx.Response(404)


def _run(ingester_cls, settings, handler):
    async def go():
        async with RealAsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ingester_cls(client, settings, asyncio.Semaphore(4)).run()

    return asyncio.run(go())


# ------------------------------------------------------------------ YouTube
def test_youtube_ranks_recent_uploads_by_views_per_hour_with_per_channel_health():
    settings = Settings(youtube_channels=[f"News|{CH_A}|Wire One", f"Tech|{CH_B}|Missing Channel",
                                          f"Sports|{CH_C}|Quiet Channel"],
                        youtube_items_per_channel=2, http_max_retries=0)
    items, stat = _run(YouTubeIngester, settings, _yt_handler)
    assert stat.ok and stat.error.startswith("partial: 1/3 channels failed")
    assert [it.title for it in items] == ["Quake damages roads near Port Calder", "Ferry strike halts island service"]
    top = items[0]
    assert top.source is SourceName.YOUTUBE and top.category_hint is CategoryEnum.NEWS
    assert top.metadata["publisher"] == "Wire One" and top.metadata["feed"] == youtube_feed_url(CH_A)
    assert top.metadata["views"] == 50_000 and top.raw_score == pytest.approx(5000, rel=0.01)
    assert top.metadata["published_at"] and top.url == "https://www.youtube.com/watch?v=a2"
    assert items[1].description == "Ferry workers began a 48-hour strike over pay on Tuesday."  # no links/calls to action
    health = {f.name: f for f in stat.feeds}
    assert health["Wire One"].ok and health["Wire One"].item_count == 2
    assert not health["Missing Channel"].ok and "404" in health["Missing Channel"].error
    assert health["Quiet Channel"].ok and health["Quiet Channel"].item_count == 0
    assert "no uploads" in health["Quiet Channel"].error


def test_youtube_all_channels_failing_is_a_clean_source_failure():
    settings = Settings(youtube_channels=[f"Tech|{CH_B}|Missing"], http_max_retries=0)
    items, stat = _run(YouTubeIngester, settings, _yt_handler)
    assert not stat.ok and items == [] and "all YouTube channels failed" in stat.error


def test_youtube_helpers():
    assert channel_id_from_url(f"https://www.youtube.com/channel/{CH_A}") == CH_A
    assert channel_id_from_url(youtube_feed_url(CH_A)) == CH_A
    assert channel_id_from_url("https://www.youtube.com/@SomeHandle") is None
    assert channel_id_from_url("https://example.test/channel/" + CH_A) is None
    assert clean_video_title("Big Story: what we know | BBC News", "BBC News") == "Big Story: what we know"
    assert clean_video_title("Phone review #tech #shorts", "Someone") == "Phone review"
    assert clean_video_title("Cats | Dogs | Birds explained", "Someone") == "Cats | Dogs | Birds explained"
    assert video_description("Subscribe now!\nhttp://x.test\n") is None
    assert "youtube" in INGESTER_REGISTRY
    with pytest.raises(ValueError):
        Settings(youtube_channels=["News|not-a-channel|X"])


def test_youtube_feed_specs_and_check_feed(monkeypatch):
    spec = FeedSpec(name="Wire One", url=f"https://www.youtube.com/channel/{CH_A}", category="News")
    assert spec.url == youtube_feed_url(CH_A) and spec.kind == "YouTube" and spec.entry() == f"News|{CH_A}|Wire One"
    with pytest.raises(ValueError, match="channel id"):
        FeedSpec(name="X", url="https://www.youtube.com/@SomeHandle")

    class Client(RealAsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(_yt_handler)
            super().__init__(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    ok = check_feed(spec)
    assert ok.ok and ok.items == 3 and ok.message.startswith("Working: 3 articles")
    quiet = check_feed(FeedSpec(name="Quiet", url=youtube_feed_url(CH_C)))
    assert quiet.ok and quiet.items == 0 and "no uploads" in quiet.message


def test_each_youtube_channel_gets_a_floor_in_the_processing_budget():
    def item(i, source, score, feed=None):
        md = {"feed": feed} if feed else {}
        return CleanedTrendItem(title=f"Story {i}", source=source, item_id=i, normalized_title=f"Story {i}",
                                heuristic_score=score, metadata=md)

    items = [item(i, SourceName.NEWS_RSS, 0.9) for i in range(1, 16)]
    items += [item(20, SourceName.YOUTUBE, 0.3, "yt-a"), item(21, SourceName.YOUTUBE, 0.2, "yt-a"),
              item(22, SourceName.YOUTUBE, 0.25, "yt-b")]
    s = Settings(max_items_for_llm=10, min_items_per_source_for_llm=0, min_items_per_feed_for_llm=0,
                 min_items_per_channel_feed_for_llm=1)
    chosen = {it.item_id for it in TrendCleaner(s).select_for_llm(items)}
    assert {20, 22} <= chosen and 21 not in chosen and len(chosen) == 10


# ------------------------------------------------------------------ Google News sections
def _gn_item(title: str, pub: str, i: int) -> str:
    return (f"<item><title>{title} - {pub}</title><link>https://news.google.com/rss/articles/{i}</link>"
            f'<source url="https://{pub.lower()}.test">{pub}</source></item>')


def test_google_news_sections_have_their_own_feeds_and_categories():
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        path = req.url.path
        if path == "/rss":
            body = _gn_item("Ferry strike halts service", "WireOne", 1) + _gn_item("Quake hits Calder", "DailyTwo", 2)
        elif path.endswith("/topic/TECHNOLOGY"):
            body = _gn_item("Nimbus phone adds satellite texting", "GadgetDesk", 3)
        elif path == "/rss/search":
            assert "when:1d" in req.url.params["q"]
            body = _gn_item("Corvid Labs opens its model", "AIWire", 4)
        else:
            return httpx.Response(503)
        return httpx.Response(200, content=f'<?xml version="1.0"?><rss><channel>{body}</channel></rss>'.encode())

    settings = Settings(google_news_sections=["Tech|TECHNOLOGY|GN Tech", "Science & AI|artificial intelligence|GN AI",
                                              "Sports|SPORTS|GN Sports"], http_max_retries=0)
    items, stat = _run(GoogleNewsIngester, settings, handler)
    assert stat.ok and stat.error.startswith("partial: 1/4 sections failed")
    by_title = {it.title: it for it in items}
    assert by_title["Nimbus phone adds satellite texting"].category_hint is CategoryEnum.TECH
    assert by_title["Corvid Labs opens its model"].category_hint is CategoryEnum.SCIENCE_AI
    assert by_title["Corvid Labs opens its model"].metadata["publisher"] == "AIWire"
    assert by_title["Nimbus phone adds satellite texting"].raw_score == 1.0  # each section's lead story ranks alike
    assert by_title["Ferry strike halts service"].metadata["top_stories"]  # keeps the source-wide budget floor
    names = {f.name: f for f in stat.feeds}
    assert names["GN Tech"].ok and not names["GN Sports"].ok and names["Google News - Top stories"].item_count == 2
    with pytest.raises(ValueError):
        Settings(google_news_sections=["Business|WORLD|X"])


def test_google_news_without_sections_is_unchanged():
    def handler(req):
        return httpx.Response(200, content=f'<?xml version="1.0"?><rss><channel>{_gn_item("A story", "Pub", 1)}'
                                           f"</channel></rss>".encode())

    items, stat = _run(GoogleNewsIngester, Settings(), handler)
    assert stat.ok and stat.feeds == [] and [it.title for it in items] == ["A story"]


# ------------------------------------------------------------------ TikTok
def test_tiktok_reads_app_router_pages_and_retries_without_parameters_only_when_empty():
    calls: list[str] = []
    escaped = '<script>self.__next_f.push([1,"{\\"hashtag_name\\":\\"WorldSeries\\",\\"video_views\\":5}"])</script>'

    def handler(req):
        calls.append(str(req.url))
        if req.url.params.get("countryCode"):
            return httpx.Response(200, text="<html><body>Loading...</body></html>")
        return httpx.Response(200, text=f"<html>{escaped}</html>")

    s = Settings(tiktok_request_spacing_s=0.0)
    items, stat = _run(TikTokCreativeCenterIngester, s, handler)
    assert stat.ok and [it.title for it in items] == ["#WorldSeries"] and len(calls) == 2
    assert items[0].category_hint is CategoryEnum.INTERNET_CULTURE


# ------------------------------------------------------------------ settings v3
def test_version_2_settings_gain_new_sources_once(daily_paths):
    old = DailyPrefs().model_dump(mode="json")
    old.update(prefs_version=2, max_items_for_llm=200,
               enabled_sources=["google_news", "news_rss", "google_trends", "wikipedia", "reddit", "x_trends24",
                                "hackernews"],
               feeds=[{"name": "Local Paper", "url": "https://local.test/rss", "category": "News"}])
    daily_paths.settings.write_text(json.dumps(old))
    prefs, warning = load_prefs(daily_paths)
    assert warning is None and prefs.prefs_version == PREFS_VERSION == 6
    assert {"youtube", "mastodon", "bluesky"} <= set(prefs.enabled_sources) and prefs.max_items_for_llm == 260
    assert "tiktok" not in prefs.enabled_sources  # switched on in v3, off again from v5 (TikTok blocks readers)
    assert prefs.feeds[0].name == "Local Paper" and len(prefs.feeds) == 1 + len(ADDED_IN_V3) + len(ADDED_IN_V4)

    # a version-3 file is taken as it is: a source the user turned off stays off
    current = prefs.model_dump(mode="json")
    current["enabled_sources"] = ["google_news", "news_rss"]
    current["max_items_for_llm"] = 200
    daily_paths.settings.write_text(json.dumps(current))
    again, _ = load_prefs(daily_paths)
    assert again.enabled_sources == ["google_news", "news_rss"] and again.max_items_for_llm == 200


def test_daily_settings_read_google_news_sections_and_skip_youtube_without_channels(daily_paths):
    prefs = DailyPrefs()
    s = build_settings(prefs, daily_paths)
    assert s.google_news_sections == list(DEFAULT_GOOGLE_NEWS_SECTIONS) and "youtube" in s.enabled_sources
    assert s.youtube_channels and s.min_items_per_channel_feed_for_llm == 1
    no_channels = prefs.model_copy(update={"feeds": [f for f in prefs.feeds if f.kind != "YouTube"]})
    s2 = build_settings(no_channels, daily_paths)
    assert "youtube" not in s2.enabled_sources and s2.youtube_channels == []


# ------------------------------------------------------------------ Mastodon, Bluesky, Wikipedia "In the news"
def test_mastodon_trending_links_are_publisher_articles_scored_by_sharers():
    from agent_reach.ingestion.social import MastodonTrendsIngester

    def card(title, url, provider, accounts):
        return {"title": title, "url": url, "provider_name": provider, "description": f"{title} in detail.",
                "history": [{"day": "1", "accounts": str(accounts), "uses": "9"}, {"day": "0", "accounts": "5"}]}

    def handler(req):
        if req.url.host == "mastodon.social":
            assert req.url.path == "/api/v1/trends/links"
            return httpx.Response(200, json=[card("Ferry strike halts islands", "https://wire-one.test/a", "Wire One", 40),
                                             card("Quake hits Calder", "https://daily-two.test/b", "Daily Two", 90)])
        return httpx.Response(503)

    settings = Settings(mastodon_instances=["mastodon.social", "down.example"], http_backoff_base_s=0.01)
    items, stat = _run(MastodonTrendsIngester, settings, handler)
    assert stat.ok and stat.error.startswith("partial: 1/2 servers failed")
    assert [it.title for it in items] == ["Quake hits Calder", "Ferry strike halts islands"]  # most shared first
    assert items[0].raw_score == 95 and items[0].metadata["publisher"] == "Daily Two"
    assert items[0].source is SourceName.MASTODON and items[0].url == "https://daily-two.test/b"
    with pytest.raises(ValueError):
        Settings(mastodon_instances=["not a host"])


def test_bluesky_trends_with_fallback_to_trending_topics():
    from agent_reach.ingestion.social import BlueskyTrendsIngester

    calls: list[str] = []

    def handler(req):
        calls.append(req.url.path)
        if req.url.path.endswith("getTrends"):
            return httpx.Response(404)
        return httpx.Response(200, json={"topics": [{"topic": "worldseries", "displayName": "World Series",
                                                      "link": "/profile/trending.bsky.app/feed/1"}]})

    items, stat = _run(BlueskyTrendsIngester, Settings(http_backoff_base_s=0.01), handler)
    assert stat.ok and [it.title for it in items] == ["World Series"] and len(calls) == 2
    assert items[0].url == "https://bsky.app/profile/trending.bsky.app/feed/1"

    def handler2(req):
        return httpx.Response(200, json={"trends": [{"topic": "f1", "displayName": "Singapore Grand Prix",
                                                      "link": "/x", "postCount": 3200, "category": "sports"}]})

    items, _ = _run(BlueskyTrendsIngester, Settings(), handler2)
    assert items[0].raw_score == 3200 and items[0].category_hint is CategoryEnum.SPORTS


def test_wikipedia_in_the_news_comes_first_and_never_fails_the_source():
    from agent_reach.ingestion.search import WikipediaPageviewsIngester

    def views(req):
        return httpx.Response(200, json={"items": [{"articles": [{"article": "Jordan_Love", "views": 300000},
                                                                  {"article": "Lizzie_Borden", "views": 100000}]}]})

    def handler(req):
        if req.url.host == "wikimedia.org":
            return views(req)
        story = ('<!--Oct 5--><a href="./Hurricane_Mira">Hurricane Mira</a> (<i>pictured</i>) makes landfall '
                 'in <a href="./Norvale">Norvale</a>.')
        return httpx.Response(200, json={"news": [{"story": story, "links": [
            {"title": "Hurricane_Mira", "extract": "Hurricane Mira is a tropical cyclone.",
             "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Hurricane_Mira"}}}]}]})

    items, stat = _run(WikipediaPageviewsIngester, Settings(wikipedia_in_the_news=True), handler)
    assert stat.ok and stat.error is None
    assert items[0].title == "Hurricane Mira makes landfall in Norvale."
    assert items[0].metadata["in_the_news"] and items[0].url == "https://en.wikipedia.org/wiki/Hurricane_Mira"
    assert [it.title for it in items[1:]] == ["Jordan Love", "Lizzie Borden"]

    def no_news(req):
        return views(req) if req.url.host == "wikimedia.org" else httpx.Response(503)

    items, stat = _run(WikipediaPageviewsIngester, Settings(wikipedia_in_the_news=True, http_max_retries=0), no_news)
    assert stat.ok and stat.error.startswith("partial: 'In the news' unavailable") and len(items) == 2


def test_budget_floors_go_round_robin_and_leave_room_for_the_best():
    def item(i, score, feed):
        return CleanedTrendItem(title=f"Story {i}", source=SourceName.NEWS_RSS, item_id=i, normalized_title=f"S {i}",
                                heuristic_score=score, metadata={"feed": feed})

    items = [item(i, 0.99 - i / 1000, "big") for i in range(1, 31)]  # one prolific, strong feed
    items += [item(100 + k, 0.30, f"small-{k}") for k in range(20)]  # twenty feeds with one weak item each
    s = Settings(max_items_for_llm=20, min_items_per_source_for_llm=0, min_items_per_feed_for_llm=2)
    chosen = TrendCleaner(s).select_for_llm(items)
    ids = {it.item_id for it in chosen}
    assert len(chosen) == 20 and 1 in ids  # the strongest item always gets in
    small = sum(1 for i in ids if i >= 100)
    assert 0 < small <= 15  # floors never take more than 75% of the budget


def test_exported_headlines_link_to_the_main_article_safely():
    from agent_reach.daily.edition import EvidenceLink
    from agent_reach.daily.render_html import render_edition_html
    from tests.daily_fakes import make_edition, make_story

    s = make_story(headline="Linked Story")
    s.evidence.insert(0, EvidenceLink(item_id=2, source="bluesky", source_name="Bluesky", title="Topic",
                                      url="https://bsky.app/profile/x"))
    bad = make_story(headline="Unsafe Only")
    bad.evidence[0].url = "javascript:alert(1)"
    page = render_edition_html(make_edition([s, bad, make_story(headline="Third")]))
    assert '<a class="hl" href="https://wire-one.test/linked-story"' in page  # the article, not the social topic
    assert "javascript:" not in page and "<h3>2. Unsafe Only</h3>" in page
