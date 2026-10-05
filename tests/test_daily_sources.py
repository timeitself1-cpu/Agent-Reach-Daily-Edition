"""Daily app: broad publisher coverage, fair per-feed limits, per-feed health and appearance."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from agent_reach.config import Settings
from agent_reach.daily import app as A
from agent_reach.daily.edition import SourceHealth, health_summary, source_health
from agent_reach.daily.feeds import DEFAULT_FEEDS, LEGACY_DEFAULT_ENTRIES, FeedSpec, check_feed, default_feeds
from agent_reach.daily.prefs import DailyPrefs, build_settings, load_prefs, save_prefs
from agent_reach.ingestion.news import NewsRSSIngester, parse_feed_entry
from agent_reach.ingestion.social import RedditIngester
from agent_reach.models import CategoryEnum, CleanedTrendItem, SourceName
from agent_reach.pipeline.cleaner import TrendCleaner
from tests.daily_fakes import RealAsyncClient, make_edition, make_story

ORGS = {"BBC News": "BBC", "BBC Sport": "BBC"}


# ------------------------------------------------------------------ coverage defaults
def test_default_feeds_are_broad_and_valid():
    feeds = default_feeds()
    orgs = {ORGS.get(f.publisher, f.publisher) for f in feeds}
    assert 30 <= len(feeds) <= 45 and len(orgs) >= 20
    assert len({f.url for f in feeds}) == len(feeds) and len({f.name for f in feeds}) == len(feeds)
    assert all(f.url.startswith("https://") and f.enabled for f in feeds)
    assert {f.category for f in feeds} >= {"News", "Sports", "Entertainment", "Science & AI", "Tech"}
    names = " ".join(f.name for f in feeds)
    for wanted in ("PBS", "Le Monde", "NASA", "ScienceDaily", "Business", "Health"):
        assert wanted in names
    assert sum(f.category == "Tech" for f in feeds) >= 8 and sum(f.category == "Science & AI" for f in feeds) >= 6
    assert sum(f.category == "News" for f in feeds) >= 12  # general news is still the largest group


def test_untouched_old_settings_upgrade_and_custom_feeds_are_kept(daily_paths):
    daily_paths.settings.write_text(json.dumps({"news_rss_feeds": LEGACY_DEFAULT_ENTRIES, "max_stories": 9}))
    prefs, warning = load_prefs(daily_paths)
    assert warning is None and len(prefs.feeds) == len(DEFAULT_FEEDS) and prefs.max_stories == 9
    daily_paths.settings.write_text(json.dumps({"news_rss_feeds": ["Sports|https://club.test/rss|Club News"]}))
    prefs, _ = load_prefs(daily_paths)
    assert [(f.name, f.url, f.category) for f in prefs.feeds] == [("Club News", "https://club.test/rss", "Sports")]


def test_feed_settings_round_trip_and_only_enabled_feeds_are_collected(daily_paths):
    feeds = default_feeds()
    feeds[0].enabled = False
    feeds.append(FeedSpec(name="Local Paper - Metro", url="https://local.test/metro.xml", category="News"))
    feeds.append(FeedSpec(name="Duplicate", url=feeds[1].url.upper().replace("HTTPS", "https")))  # same feed
    save_prefs(daily_paths, DailyPrefs(feeds=feeds, items_per_feed=12, max_items_for_llm=200))
    prefs, _ = load_prefs(daily_paths)
    assert len(prefs.feeds) == len(DEFAULT_FEEDS) + 1 and not prefs.feeds[0].enabled
    s = build_settings(prefs, daily_paths)
    assert len(s.news_rss_feeds) == len(DEFAULT_FEEDS)  # one off, one added
    assert "News|https://local.test/metro.xml|Local Paper - Metro" in s.news_rss_feeds
    assert s.news_rss_items_per_feed == 12 and s.max_items_for_llm == 200
    assert parse_feed_entry("News|https://local.test/metro.xml|Local Paper - Metro") == (
        CategoryEnum.NEWS, "https://local.test/metro.xml", "Local Paper - Metro")


@pytest.mark.parametrize("bad", [dict(name="", url="https://x.test/rss"), dict(name="X", url="ftp://x.test/rss"),
                                 dict(name="X", url="https://x.test/rss", category="Business"),
                                 dict(name="X", url="https://x.test/a b")])
def test_invalid_feeds_are_rejected(bad):
    with pytest.raises(ValueError):
        FeedSpec(**bad)


def test_pipeline_settings_accept_named_feeds_and_reject_bad_ones():
    Settings(news_rss_feeds=["News|https://a.test/rss|A Paper", "Sports|https://b.test/rss"])
    with pytest.raises(ValueError):
        Settings(news_rss_feeds=["Business|https://a.test/rss|A Paper"])


# ------------------------------------------------------------------ fair intake
def _feed_xml(n: int, tag: str) -> bytes:
    pub = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = "".join(f"<item><title>{tag} story number {i} about {tag} events</title>"
                    f"<link>https://{tag}.test/{i}</link><pubDate>{pub}</pubDate></item>" for i in range(n))
    return f'<?xml version="1.0"?><rss><channel><title>{tag} feed</title>{items}</channel></rss>'.encode()


def _run_news(settings, handler):
    async def go():
        async with RealAsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await NewsRSSIngester(client, settings, asyncio.Semaphore(4)).run()

    return asyncio.run(go())


def test_every_feed_gets_its_own_allowance_not_a_shared_40():
    feeds = [f"News|https://feeds.test/f{i}.xml|Paper {i}" for i in range(26)]
    settings = Settings(news_rss_feeds=feeds, news_rss_items_per_feed=10, max_items_per_source=40)

    def handler(req):
        if req.url.path == "/f3.xml":
            return httpx.Response(503)
        return httpx.Response(200, content=_feed_xml(15, req.url.path.strip("/").removesuffix(".xml")))

    items, stat = _run_news(settings, handler)
    assert stat.ok and len(items) == 25 * 10  # not truncated to max_items_per_source
    assert len(stat.feeds) == 26
    by_name = {f.name: f for f in stat.feeds}
    assert by_name["Paper 0"].ok and by_name["Paper 0"].item_count == 10
    assert not by_name["Paper 3"].ok and "503" in by_name["Paper 3"].error
    assert stat.error.startswith("partial: 1/26 feeds failed")
    assert {it.metadata["publisher"] for it in items[:25]} == {f"Paper {i}" for i in range(26) if i != 3}  # round-robin


def test_total_intake_is_still_bounded():
    feeds = [f"News|https://feeds.test/f{i}.xml|P{i}" for i in range(30)]
    settings = Settings(news_rss_feeds=feeds, news_rss_items_per_feed=20, news_rss_max_total_items=120)
    items, stat = _run_news(settings, lambda req: httpx.Response(200, content=_feed_xml(20, "x")))
    assert len(items) == 120 and sum(f.item_count for f in stat.feeds) == 120
    assert all(f.item_count == 4 for f in stat.feeds)  # the cap is shared fairly


def _cleaned(i: int, feed: str, score: float) -> CleanedTrendItem:
    return CleanedTrendItem(item_id=i, source=SourceName.NEWS_RSS, title=f"t{i}", normalized_title=f"t{i}",
                            heuristic_score=score, metadata={"feed": feed}, timestamp=datetime.now(timezone.utc))


def test_processing_budget_keeps_a_floor_for_every_feed():
    items = [_cleaned(i, "https://big.test/rss", 0.9) for i in range(50)]
    items += [_cleaned(100 + i, "https://small.test/rss", 0.1) for i in range(5)]
    chosen = TrendCleaner(Settings(max_items_for_llm=20, min_items_per_feed_for_llm=3)).select_for_llm(items)
    assert len(chosen) == 20
    assert sum(c.metadata["feed"] == "https://small.test/rss" for c in chosen) == 3


# ------------------------------------------------------------------ honest health
def test_reddit_rate_limit_with_rss_fallback_is_partial():
    entries = "".join(f"<entry><title>Big news story {i} today</title><link href='https://www.reddit.com/r/news/{i}'/>"
                      f"<category term='news'/></entry>" for i in range(3))
    atom = f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'.encode()

    def handler(req):
        if req.url.path.endswith(".json"):
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=atom)

    settings = Settings(reddit_subreddits=["news"], reddit_max_retries=0, reddit_request_spacing_s=0.0,
                        http_backoff_base_s=0.01)

    async def go():
        async with RealAsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await RedditIngester(client, settings, asyncio.Semaphore(2)).run()

    items, stat = asyncio.run(go())
    assert stat.ok and items and "429" in stat.error
    from agent_reach.models import PipelineAccounting, PipelineReport

    acct = PipelineAccounting(ingested=0, passed_filters=0, clustering_candidates=0, clustered=0, discarded={})
    report = PipelineReport(run_id="r", timestamp=datetime.now(timezone.utc), ingested_count=0, filtered_count=0,
                            cluster_count=0, llm_mode="x", execution_time=0, macro_clusters=[],
                            source_stats=[stat], accounting=acct)
    assert [h.status for h in source_health(report)] == ["partial"]


def test_health_summary_never_calls_a_partial_source_healthy():
    health = [SourceHealth(source=f"s{i}", name=f"S{i}", status="ok") for i in range(6)]
    health.append(SourceHealth(source="reddit", name="Reddit", status="partial", error="partial: 429"))
    assert health_summary(health) == "6 healthy · 1 partial"
    health.append(SourceHealth(source="x", name="X", status="failed"))
    assert health_summary(health) == "6 healthy · 1 partial · 1 failed"


def test_feed_health_and_publishers_in_a_real_edition(daily_env):
    from agent_reach.daily.refresh import refresh
    from tests.daily_fakes import OllamaUp

    daily_env.net.down.add("arts")
    ed = refresh(daily_env.paths, trigger="manual", force=True, ollama_probe=lambda p: OllamaUp()).edition
    rss = next(h for h in ed.source_health if h.source == "news_rss")
    assert rss.status == "partial" and len(rss.feeds) == 6
    feeds = {f.name: f for f in rss.feeds}
    assert set(feeds) == {"Wire One - World", "Daily Two - US", "Sports Three", "Arts Four", "Science Five", "Tech Seven"}
    assert feeds["Arts Four"].status == "failed" and feeds["Arts Four"].collected == 0
    assert "503" in feeds["Arts Four"].error
    assert all(f.status == "ok" for name, f in feeds.items() if name != "Arts Four")
    assert sum(f.used for f in rss.feeds) == rss.used > 0
    assert all(f.used <= f.collected for f in rss.feeds)
    assert any("1 of 6 publisher feeds returned nothing" in w for w in ed.coverage.warnings)
    pubs = {r.publisher: r for r in A.publisher_breakdown(ed)}
    assert "Daily Two" in pubs and "Google News" in pubs["Daily Two"].channels  # publisher reached via an aggregator
    assert A.coverage_summary(ed) == "Sources: 2 healthy · 1 partial"


def test_publisher_breakdown_counts_stories_and_articles():
    s1, s2 = make_story(headline="One"), make_story(headline="Two")
    s1.evidence.append(s1.evidence[0].model_copy(update={"url": "https://wire-one.test/x"}))
    rows = A.publisher_breakdown(make_edition([s1, s2]))
    assert [(r.publisher, r.stories, r.articles) for r in rows] == [("Wire One", 2, 3)]


# ------------------------------------------------------------------ feed test button
def test_check_feed_reports_working_and_broken_feeds(monkeypatch):
    def handler(req):
        return httpx.Response(200, content=_feed_xml(7, "good")) if "good" in req.url.host else httpx.Response(404)

    class Client(RealAsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    ok = check_feed(FeedSpec(name="Good", url="https://good.test/rss"))
    assert ok.ok and ok.items == 7 and ok.message.startswith("Working: 7 articles") and ok.feed_title == "good feed"
    bad = check_feed(FeedSpec(name="Bad", url="https://bad.test/rss"))
    assert not bad.ok and bad.message.startswith("Not working") and "404" in bad.message


# ------------------------------------------------------------------ appearance
def test_appearance_resolution():
    assert A.resolve_appearance("dark", lambda: False) == "dark"
    assert A.resolve_appearance("light", lambda: True) == "light"
    assert A.resolve_appearance("system", lambda: True) == "dark"
    assert A.resolve_appearance("system", lambda: False) == "light"
    assert DailyPrefs().appearance == "system"
    with pytest.raises(ValueError):
        DailyPrefs(appearance="purple")


@pytest.mark.parametrize("raw,expected", [
    ("https://feeds.test/a.xml: HTTPStatusError: retryable status 503", "server error (HTTP 503)"),
    ("https://x.test/1001/rss.xml: HTTPStatusError: Client error '404 Not Found'", "not found (HTTP 404)"),
    ("partial: JSON listings refused (429 rate limit); used RSS", "rate-limited by the site (HTTP 429)"),
    ("https://a.test: ConnectError: [Errno -2] Name or service not known", "could not connect"),
    ("https://a.test: invalid XML (syntax error)", "not a readable feed"),
    ("https://a.test: ReadTimeout: ", "did not answer in time"),
])
def test_feed_problems_are_explained_in_plain_words(raw, expected):
    from agent_reach.daily.edition import friendly_error

    text = friendly_error(raw)
    assert expected in text and "https://" not in text
