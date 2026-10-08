"""Production priorities: publication-time validation, collapsible evidence in HTML, deterministic
evidence strength, and "what changed since last refresh"."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from agent_reach.config import Settings
from agent_reach.daily.changes import compare_editions
from agent_reach.daily.edition import DailyEdition, EvidenceLink
from agent_reach.daily.render_html import render_edition_html
from agent_reach.daily.store import EditionStore
from agent_reach.daily.strength import assess, strength_of
from agent_reach.ingestion.base import (
    EARLIEST_PLAUSIBLE_PUBLICATION,
    epoch_to_utc,
    parse_optional_datetime,
    validate_publication_time,
)
from agent_reach.ingestion.news import NewsRSSIngester
from agent_reach.ingestion.tech import HackerNewsIngester
from agent_reach.models import PUBLISHED_FUTURE_TOLERANCE
from tests.daily_fakes import OllamaUp, RealAsyncClient, make_edition, make_story

UTC = timezone.utc
T0 = datetime(2026, 10, 1, 12, 5, tzinfo=UTC)


# ====================================================================== 1. publication times
@pytest.mark.parametrize("raw,expected", [
    ("Thu, 01 Oct 2026 07:05:00 -0500", datetime(2026, 10, 1, 12, 5, tzinfo=UTC)),
    ("Thu, 01 Oct 2026 08:05:00 EDT", datetime(2026, 10, 1, 12, 5, tzinfo=UTC)),
    ("Thu, 01 Oct 2026 12:05:00 GMT", datetime(2026, 10, 1, 12, 5, tzinfo=UTC)),
    ("2026-10-01T17:35:00+05:30", datetime(2026, 10, 1, 12, 5, tzinfo=UTC)),
    ("2026-10-01T12:05:00Z", datetime(2026, 10, 1, 12, 5, tzinfo=UTC)),
    ("2026-10-01T12:05:00", datetime(2026, 10, 1, 12, 5, tzinfo=UTC)),  # zone-less: read as UTC
])
def test_timezones_are_normalised_to_utc(raw, expected):
    dt = parse_optional_datetime(raw)
    assert dt == expected and dt.utcoffset() == timedelta(0)


@pytest.mark.parametrize("raw", [
    None, "", "   ", "yesterday", "32 Oct 2026", "2026-13-01T00:00:00Z", "2026-10-01T25:00:00Z",
    "Thu, 01 Oct 2026 07:05:00 +9999", "2026-10-01",  # date only: would invent a time of day
    "Mon, 01 Jan 0001 00:00:00 +0000",  # RFC-822 two-digit-year rule would silently turn this into 2001
    12345,
])
def test_malformed_timestamps_are_unknown_not_guessed(raw):
    assert parse_optional_datetime(raw) is None


def test_publication_time_is_checked_against_retrieval():
    r = T0
    assert validate_publication_time(r - timedelta(hours=3), r) == (r - timedelta(hours=3), None)
    assert validate_publication_time(r + timedelta(minutes=5), r) == (r, "clock skew (clamped to retrieval time)")
    assert validate_publication_time(r + PUBLISHED_FUTURE_TOLERANCE + timedelta(seconds=1), r) == (None, "in the future")
    assert validate_publication_time(datetime(2099, 1, 1, tzinfo=UTC), r) == (None, "in the future")
    assert validate_publication_time(EARLIEST_PLAUSIBLE_PUBLICATION - timedelta(days=1), r) == (None, "implausibly old")
    naive = datetime(2026, 10, 1, 9, 0)
    assert validate_publication_time(naive, r) == (datetime(2026, 10, 1, 9, 0, tzinfo=UTC), None)


@pytest.mark.parametrize("value", [None, 0, "", "abc", float("nan"), 1e20, -1e20])
def test_bad_epoch_values_are_unknown(value):
    assert epoch_to_utc(value) is None


def _run(ingester_cls, settings, handler):
    async def go():
        async with RealAsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ingester_cls(client, settings, asyncio.Semaphore(2)).run()

    return asyncio.run(go())


def test_feed_items_with_bad_dates_keep_no_publication_time():
    future = (datetime.now(UTC) + timedelta(days=2)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    good = (datetime.now(UTC) - timedelta(hours=2)).astimezone(timezone(timedelta(hours=-5))).strftime(
        "%a, %d %b %Y %H:%M:%S %z")  # an offset that must be normalised to UTC
    xml = ('<?xml version="1.0"?><rss><channel><title>T</title>'
           f'<item><title>Future dated story</title><link>https://a.test/1</link><pubDate>{future}</pubDate></item>'
           '<item><title>Garbled date story</title><link>https://a.test/2</link><pubDate>someday soon</pubDate></item>'
           f'<item><title>Good date story</title><link>https://a.test/3</link><pubDate>{good}</pubDate></item>'
           '</channel></rss>').encode()
    items, stat = _run(NewsRSSIngester, Settings(news_rss_feeds=["News|https://a.test/rss|A"]),
                       lambda req: httpx.Response(200, content=xml))
    md = {i.title: i.metadata for i in items}
    assert stat.ok and len(items) == 3
    assert "published_at" not in md["Future dated story"] and md["Future dated story"]["published_at_note"] == "in the future"
    assert "published_at" not in md["Garbled date story"]
    published = datetime.fromisoformat(md["Good date story"]["published_at"])
    retrieved = datetime.fromisoformat(md["Good date story"]["retrieved_at"])
    assert published.utcoffset() == timedelta(0) and published < retrieved
    future_item = next(i for i in items if i.title == "Future dated story")
    assert future_item.timestamp <= datetime.now(UTC)  # coherence timestamp falls back to retrieval, not the future


def test_one_bad_epoch_does_not_fail_hacker_news():
    hits = [{"objectID": "1", "title": "Overflowing timestamp story", "url": "https://a.test/x", "points": 500,
             "num_comments": 10, "created_at_i": 10 ** 20},
            {"objectID": "2", "title": "Normal timestamp story", "url": "https://a.test/y", "points": 500,
             "num_comments": 10, "created_at_i": int(datetime.now(UTC).timestamp()) - 3600}]
    items, stat = _run(HackerNewsIngester, Settings(), lambda req: httpx.Response(200, json={"hits": hits}))
    assert stat.ok and len(items) == 2
    assert "published_at" not in items[0].metadata and "published_at" in items[1].metadata


def test_edition_drops_evidence_times_after_generation_and_normalises_zones():
    ev = EvidenceLink(item_id=1, source="news_rss", source_name="News feeds", title="t",
                      published_at_utc=datetime(2026, 10, 1, 9, 0), retrieved_at_utc=T0)
    assert ev.published_at_utc == datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    after_retrieval = EvidenceLink(item_id=1, source="news_rss", source_name="News feeds", title="t",
                                   published_at_utc=T0 + timedelta(hours=2), retrieved_at_utc=T0)
    assert after_retrieval.published_at_utc is None
    s = make_story(now=T0)
    s.evidence[0].published_at_utc = T0 + timedelta(days=30)  # set directly, as an old cached file could contain
    s.evidence[0].retrieved_at_utc = None
    ed = make_edition([s, make_story(headline="Second Story", now=T0), make_story(headline="Third Story", now=T0)])
    reloaded = DailyEdition.model_validate_json(ed.model_dump_json())
    assert reloaded.stories[0].evidence[0].published_at_utc is None  # after generation time: dropped
    assert reloaded.stories[1].evidence[0].published_at_utc == T0 - timedelta(hours=3)


def test_cached_edition_with_impossible_dates_still_loads(daily_paths):
    ed = make_edition()
    data = json.loads(ed.model_dump_json())
    data["stories"][0]["evidence"][0]["published_at_utc"] = "2099-01-01T00:00:00Z"
    data["stories"][0]["evidence"][0]["retrieved_at_utc"] = None
    (daily_paths.editions_dir / "2026-10-01.json").write_text(json.dumps(data), encoding="utf-8")
    res = EditionStore(daily_paths).load_latest()
    assert res.edition is not None and not res.corrupt
    assert res.edition.stories[0].evidence[0].published_at_utc is None
    assert "publication time not stated" in render_edition_html(res.edition)


# ====================================================================== 2. collapsible evidence (HTML)
EVIL = '<script>alert("x")</script><b onmouseover=1>'


def test_each_story_has_one_accessible_collapsible_evidence_section():
    s = make_story(headline="Evidence Story")
    s.evidence[0].title = "Title " + EVIL
    s.evidence[0].excerpt = "Excerpt " + EVIL
    page = render_edition_html(make_edition([s, make_story(headline="Second"), make_story(headline="Third")]))
    articles = re.findall(r"<article .*?</article>", page, re.S)
    assert len(articles) == 3
    for art in articles:
        assert art.count('<details class="evidence">') == 1 and art.count("<summary>") == 1
        assert re.search(r"<summary>Sources \(\d+\) &middot; (Strong|Moderate|Limited) evidence</summary>", art)
        assert art.index("<details") < art.index('<ul class="evidence">') < art.index("</details>")  # list is inside
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in page
    assert "<script" not in page.lower() and "onmouseover" not in page.replace("&lt;b onmouseover=1&gt;", "")
    assert "default-src 'none'" in page and "summary:focus-visible" in page and "prefers-color-scheme: dark" in page
    assert "<details open" not in page  # collapsed by default; native disclosure, no script needed


def test_html_says_which_model_grouped_the_stories_and_keeps_details_compact():
    """rc12: the footer names the embedding model that actually grouped the stories; a collapsed section gives a
    few plain numbers (the full pair log stays in the diagnostics folder, never in the page)."""
    from agent_reach.daily.edition import grouping_summary

    semantic = {"model_used": "nomic-embed-text", "fallback": "embeddinggemma-2:270m was not used: "
                "embeddinggemma-2:270m: model \"embeddinggemma-2:270m\" not found <b>", "roundups_in_run": 2,
                "embedding": {"dims": 768, "cache_hits": 40, "items": 260},
                "gate": {"candidate_pairs": 900, "accepted_pairs": 120, "rejected_pairs": 75,
                         "merges_blocked_conflict": 3, "merges_blocked_cohesion": 4}}
    ed = make_edition([make_story(headline="One"), make_story(headline="Two"), make_story(headline="Three")])
    ed.model.embed_model, ed.model.embed_model_used = "embeddinggemma-2:270m", "nomic-embed-text"
    ed.model.grouping = grouping_summary(semantic)
    page = render_edition_html(ed)
    assert "llama3.1:8b / nomic-embed-text" in page  # the model actually used, not the one asked for
    section = re.search(r"<details><summary>How stories were grouped</summary>.*?</details>", page, re.S).group(0)
    assert "Grouping model: nomic-embed-text (768 dimensions)" in section
    assert "900 candidate pairs, 120 accepted, 75 refused" in section and "7 merges blocked" in section
    assert "2 multi-story roundups" in section and "40 of 260 reports" in section
    assert "&lt;b&gt;" in section  # model text is escaped
    assert "shared_evidence" not in page and "<b>" not in section
    legacy = make_edition([make_story(headline="One")])  # editions before rc12: no section, the asked-for model
    assert "How stories were grouped" not in render_edition_html(legacy)


# ====================================================================== 3. evidence strength
def _ev(publisher, title, *, source="news_rss", hours=3.0, url=None):
    return EvidenceLink(item_id=1, source=source, source_name=source, title=title, publisher=publisher,
                        url=url or f"https://{(publisher or 'x').split()[0].lower()}.test/{abs(hash(title)) % 999}",
                        published_at_utc=None if hours is None else T0 - timedelta(hours=hours), retrieved_at_utc=T0)


def test_three_independent_publishers_on_two_channels_is_strong():
    ev = [_ev("Wire One - World", "Quake hits Port Calder"), _ev("Daily Two - US", "Port Calder quake damages roads"),
          _ev("Third Paper", "Roads damaged in Calder earthquake", source="google_news")]
    st = assess(ev, T0)
    assert (st.level, st.independent_reports, st.channels, st.points) == ("strong", 3, 2, 5)
    assert st.publishers == ["Daily Two", "Third Paper", "Wire One"]


def test_repeats_and_syndicated_copies_count_once():
    same_pub = [_ev("Wire One - World", f"Quake story version {i} differs") for i in range(3)]
    st = assess(same_pub, T0)
    assert st.level == "limited" and st.independent_reports == 1 and st.duplicates_collapsed == 2
    assert "not corroborated" in " ".join(st.reasons)
    wire = [_ev("Paper A", "Exact Wire Headline About The Quake"), _ev("Paper B", "Exact wire headline about the quake!")]
    st = assess(wire, T0)
    assert st.independent_reports == 1 and st.duplicates_collapsed == 1 and st.level == "limited"


def test_aggregator_items_count_as_their_publisher():
    ev = [_ev("Daily Two - US", "Ferry strike halts service"), _ev("Daily Two", "Ferry strike: islands cut off",
                                                                    source="google_news")]
    assert assess(ev, T0).independent_reports == 1


def test_trend_signals_never_corroborate():
    ev = [_ev(None, "ferry strike", source="google_trends", hours=None),
          _ev(None, "Ferry strike thread", source="reddit", hours=1)]
    st = assess(ev, T0)
    assert st.independent_reports == 0 and st.trend_signals == 2 and st.level == "limited"
    assert st.channels == 0 and st.newest_age_hours is None  # attention is neither a channel nor recency


def test_attention_never_lifts_a_story_to_strong():
    """rc12: three articles from one channel plus a Google Trends phrase and a Bluesky post read as 'Strong
    evidence' (the trend channel added the diversity point). Attention is shown, not counted."""
    reports = [_ev("Wire One", "Quake hits Port Calder", hours=30), _ev("Daily Two", "Port Calder quake damages roads", hours=30),
               _ev("Third Paper", "Roads damaged in Calder earthquake", hours=30)]
    attention = [_ev(None, "port calder quake", source="google_trends", hours=None),
                 _ev(None, "Port Calder quake post", source="bluesky", hours=1)]
    st = assess(reports + attention, T0)
    assert (st.level, st.independent_reports, st.channels, st.trend_signals) == ("moderate", 3, 1, 2)
    assert st.newest_age_hours == 30  # the fresh post is attention, not a newer report
    assert assess(reports, T0).points == st.points


def test_recency_uses_stated_times_only_and_is_deterministic():
    fresh = [_ev("Paper A", "Story one alpha", hours=2), _ev("Paper B", "Story two bravo", hours=2),
             _ev("Paper C", "Story three charlie", hours=2, source="google_news")]
    old = [e.model_copy(update={"published_at_utc": T0 - timedelta(hours=30)}) for e in fresh]
    undated = [e.model_copy(update={"published_at_utc": None}) for e in fresh]
    assert assess(fresh, T0).level == "strong" and assess(old, T0).level == "moderate"
    st = assess(undated, T0)
    assert st.newest_age_hours is None and "no stated publication time" in st.reasons
    assert assess(fresh, T0) == assess(fresh, T0)
    future = [e.model_copy(update={"published_at_utc": T0 + timedelta(hours=5)}) for e in fresh]
    assert assess(future, T0).newest_age_hours is None  # later than the edition: not usable for recency


def test_strength_is_never_a_percentage_and_old_editions_get_it_computed():
    ed = make_edition()
    for s in ed.stories:
        s.evidence_strength = None  # as in editions written before strength existed
        st = strength_of(s, ed.generation_completed_utc)
        text = " ".join(st.reasons) + st.label
        assert "%" not in text and st.level in ("strong", "moderate", "limited")


def test_real_editions_carry_strength(daily_env):
    from agent_reach.daily.refresh import refresh

    ed = refresh(daily_env.paths, trigger="manual", force=True, ollama_probe=lambda p: OllamaUp()).edition
    assert all(s.evidence_strength is not None for s in ed.stories)
    ferry = next(s for s in ed.stories if "Norvale" in s.headline).evidence_strength
    assert ferry.independent_reports >= 2 and ferry.level in ("strong", "moderate")
    assert any(s.evidence_strength.level == "limited" for s in ed.stories)  # single-publisher stories exist


# ====================================================================== 4. what changed since last refresh
def _story(headline, *, sid=None, url=None, items=2, pubs=("Wire One",), sentences=None, why=None, entity=None):
    s = make_story(headline=headline, now=T0, items=items, url=url, why=why, sentences=sentences, entity_id=entity)
    if sid:
        s.story_id = sid
    base = s.evidence[0]
    s.evidence = [base.model_copy(update={"publisher": p, "url": f"{base.url}?p={i}" if i else base.url,
                                          "title": f"{headline} as reported by {p}"})  # distinct, not syndicated
                  for i, p in enumerate(pubs)]
    s.evidence_strength = None
    return s


def test_new_updated_signal_and_gone_stories_are_identified():
    prev = make_edition([
        _story("Port Calder Earthquake Damages Roads", sid="quake-1", url="https://w.test/quake"),
        _story("Norvale Ferry Strike Halts Service", sid="ferry-1", url="https://w.test/ferry", items=3),
        _story("Oakdene Council Delays Budget Vote", sid="oak-1", url="https://w.test/oak"),
        _story("Kestrel Marathon Record Falls", sid="run-1", url="https://w.test/run", items=12),
    ], run_id="prev")
    cur = make_edition([
        _story("Port Calder Earthquake Damages Roads", sid="quake-1", url="https://w.test/quake"),  # unchanged
        _story("Norvale Ferry Strike Halts Service", sid="ferry-2", url="https://w.test/ferry", items=9,
               pubs=("Wire One", "Daily Two", "Third Paper")),  # new evidence id, same article URL
        _story("Kestrel Marathon Record Falls", sid="run-2", url="https://w.test/run-new", items=4,
               entity="ent-kestrel-marathon-record-falls"),  # matched by entity set, fewer signals
        _story("Lumen Summit Agrees Methane Pledge", sid="lumen-1", url="https://w.test/lumen"),  # new
    ], started=T0 + timedelta(hours=6), run_id="cur")
    prev.stories[3].entity_id = "ent-kestrel-marathon-record-falls"
    ch = compare_editions(prev, cur)
    assert [c.headline for c in ch.new] == ["Lumen Summit Agrees Methane Pledge"]
    assert [c.headline for c in ch.gone] == ["Oakdene Council Delays Budget Vote"]
    assert [c.headline for c in ch.updated] == ["Norvale Ferry Strike Halts Service"]
    assert "new reporting from Daily Two, Third Paper" in ch.updated[0].detail
    assert [c.headline for c in ch.signals_up] == ["Norvale Ferry Strike Halts Service"]
    assert ch.signals_up[0].detail.startswith("signals 3 → 9")
    assert [c.headline for c in ch.signals_down] == ["Kestrel Marathon Record Falls"]
    assert ch.unchanged == 1 and ch.compared_run_id == "prev"
    assert ch.summary() == "1 new, 1 updated, 1 growing, 1 fading, 1 no longer listed"


def test_a_story_split_from_an_earlier_false_merge_is_not_new():
    """rc12: an earlier edition merged two events into one card (the smart-glasses privacy probe carried WSJ's
    profile of Meta's AI-app billionaire). When the next edition shows them apart, both continue that card:
    neither is 'new', the half with fewer reports is not 'fading', and the best URL overlap wins."""
    mixed = _story("Privacy Watchdog Launches Investigation into China-Based Company", sid="mixed",
                   url="https://w.test/oaic", pubs=("Reuters", "WSJ", "ABC"), items=6)
    mixed.evidence[1] = mixed.evidence[1].model_copy(update={"url": "https://w.test/wsj-meta"})
    other = _story("Lumen Summit Agrees Methane Pledge", sid="lumen", url="https://w.test/lumen")
    other.evidence.append(mixed.evidence[0].model_copy(update={"url": "https://w.test/oaic?p=2"}))
    probe = _story("Privacy Watchdog Launches Investigation into China-Based Company", sid="probe",
                   url="https://w.test/oaic", pubs=("Reuters", "ABC"), items=4)
    probe.evidence[1] = probe.evidence[1].model_copy(update={"url": "https://w.test/oaic?p=2"})
    wsj = _story("The Mulleted, Meme-Loving Billionaire Behind Meta's Hit AI App", sid="wsj",
                 url="https://w.test/wsj-meta", pubs=("WSJ",), items=1)
    ch = compare_editions(make_edition([mixed, other], run_id="p"),
                          make_edition([probe, wsj, other.model_copy(deep=True)], run_id="c"))
    assert ch.new == [] and ch.gone == [] and ch.signals_down == []
    assert ch.unchanged == 3


def test_small_or_cosmetic_differences_are_not_reported():
    a = _story("Port Calder Earthquake Damages Roads", sid="q1", items=4,
               sentences=["A magnitude 6.8 earthquake struck near Port Calder early on Wednesday."])
    b = _story("Port Calder Earthquake Damages Roads", sid="q2", items=5,  # +1 signal: not significant
               sentences=["A magnitude 6.8 earthquake struck near Port Calder early Wednesday."])
    ch = compare_editions(make_edition([a, make_story(headline="X1"), make_story(headline="Y2")], run_id="p"),
                          make_edition([b, make_story(headline="X1"), make_story(headline="Y2")], run_id="c"))
    assert ch.total == 0 and ch.unchanged == 3 and ch.summary() == "No material changes"


def test_a_rewritten_summary_alone_is_not_an_update():
    # rc10: the model rewording the same evidence (new summary, new 'why it matters') is not news
    a = _story("Norvale Ferry Strike", sid="f1", sentences=["Workers began a strike over pay at the port."])
    b = _story("Norvale Ferry Strike", sid="f1", sentences=["Talks collapsed and the island ferry service stopped "
                                                           "entirely; officials announced emergency flights."],
               why="Island residents lose their ferry link.")
    ch = compare_editions(make_edition([a, make_story(headline="X1"), make_story(headline="Y2")], run_id="p"),
                          make_edition([b, make_story(headline="X1"), make_story(headline="Y2")], run_id="c"))
    assert ch.updated == [] and ch.unchanged == 3


def test_refresh_persists_changes_against_the_previous_edition(daily_env):
    from agent_reach.daily.refresh import refresh

    first = refresh(daily_env.paths, trigger="manual", force=True, ollama_probe=lambda p: OllamaUp()).edition
    assert first.changes is None  # nothing to compare with
    page = render_edition_html(first)
    assert "first edition: there is no earlier edition to compare with" in page.lower()
    daily_env.net.down.add("sports")  # the sports feed disappears in the next refresh
    second = refresh(daily_env.paths, trigger="manual", force=True, ollama_probe=lambda p: OllamaUp(),
                     now_fn=lambda: first.generation_completed_utc + timedelta(hours=1)).edition
    ch = EditionStore(daily_env.paths).load_latest().edition.changes
    assert ch is not None and ch == second.changes
    assert ch.compared_run_id == first.run_id and ch.compared_revision == 1 and second.revision == 2
    gone = {c.headline for c in ch.gone}
    assert not gone  # Feed failure alone does not evict yesterday's still-fresh listed stories.
    assert {s.story_id for s in first.stories if s.category.value == "Sports"} <= {s.story_id for s in second.stories}
    assert not ch.new and ch.unchanged >= 5
    page = render_edition_html(second)
    assert "<details><summary>What changed since last refresh (No material changes)</summary>" in page
    assert page.index("What changed since last refresh") > page.index('<section class="sec"')  # after the news
    assert any(s.headline in page for s in first.stories if s.category.value == "Sports")


def test_demo_edition_has_no_change_section():
    assert "What changed since last refresh" not in render_edition_html(make_edition(demo=True))
