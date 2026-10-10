"""Canonical publisher URLs for Google News links (ingestion/google_urls.py), Phase 3 of the October 10, 2026 content
fixes: the source list showed 'Google News redirect' because the redirect page was never turned into the publisher's
address. Offline: mock transports with the shapes of Google's pages; whether Google's live endpoint still answers this
way can only be seen on the user's PC (see docs/PLAN.md)."""
from __future__ import annotations

import asyncio
import base64
import json
from urllib.parse import parse_qs

import httpx
import pytest

from agent_reach.config import Settings
from agent_reach.ingestion import google_urls as G
from agent_reach.ingestion.google_urls import GoogleNewsResolver, article_token, decode_legacy_token
from tests.daily_fakes import RealAsyncClient

PUBLISHER = "https://www.example-paper.com/world/2026/10/10/ferry-strike"


def legacy_token(url: str) -> str:
    body = url.encode()
    raw = b"\x08\x13\x22" + bytes([len(body)]) + body + b"\xd2\x01\x00"
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def new_token() -> str:
    body = b"AU_yqLPzRecordNotAUrl"
    return base64.urlsafe_b64encode(b"\x08\x13\x22" + bytes([len(body)]) + body + b"\xd2\x01\x00").decode().rstrip("=")


def article_page(sig="SIG123", ts="1760000000") -> str:
    return f'<html><body><c-wiz><div jscontroller="x" data-n-a-sg="{sig}" data-n-a-ts="{ts}"></div></c-wiz></body></html>'


def batch_answer(url: str) -> str:
    inner = json.dumps(["garturlres", url, 1])
    return ")]}'\n\n" + json.dumps([["wrb.fr", "Fbv4je", inner, None, None, None, "generic"]]) + "\n\n"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    async def dns(host, port):
        return '93.184.216.34'
    monkeypatch.setattr('agent_reach.pipeline.enricher._resolve_public', dns)


def run(coro):
    return asyncio.run(coro)


def resolver(tmp_path, **kw):
    return GoogleNewsResolver(Settings(db_path=tmp_path / 'history.db', **kw))


async def resolve_with(r, url, handler):
    async with RealAsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await r.resolve(url, client, asyncio.Semaphore(4))


def test_a_legacy_token_is_read_offline_without_any_request(tmp_path):
    url = f"https://news.google.com/rss/articles/{legacy_token(PUBLISHER)}?oc=5"
    assert article_token(url) == legacy_token(PUBLISHER) and decode_legacy_token(article_token(url)) == PUBLISHER
    assert decode_legacy_token(new_token()) is None and decode_legacy_token("not base64!!") is None
    hit = []
    assert run(resolve_with(resolver(tmp_path), url, lambda req: hit.append(req) or httpx.Response(500))) == PUBLISHER
    assert hit == []


def test_a_token_that_decodes_to_google_or_a_private_address_is_refused():
    assert decode_legacy_token(legacy_token("https://news.google.com/articles/x")) is None
    assert decode_legacy_token(legacy_token("http://127.0.0.1/admin")) is None


def test_the_page_data_call_resolves_a_new_style_token(tmp_path):
    token = new_token()
    url = f"https://news.google.com/rss/articles/{token}?oc=5"
    seen = {}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, text=article_page(), headers={"content-type": "text/html"})
        seen["body"] = parse_qs(req.content.decode())["f.req"][0]
        return httpx.Response(200, text=batch_answer(PUBLISHER))

    assert run(resolve_with(resolver(tmp_path), url, handler)) == PUBLISHER
    assert token in seen["body"] and "SIG123" in seen["body"] and "1760000000" in seen["body"]
    assert G.parse_batch_response(batch_answer("https://news.google.com/x")) is None
    assert G.parse_batch_response("garbage") is None


def test_a_transient_failure_is_retried_and_then_succeeds(tmp_path, monkeypatch):
    async def fast(_):
        return None
    monkeypatch.setattr(G.asyncio, "sleep", fast)
    posts = []

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, text=article_page(), headers={"content-type": "text/html"})
        posts.append(1)
        return httpx.Response(503) if len(posts) == 1 else httpx.Response(200, text=batch_answer(PUBLISHER))

    url = f"https://news.google.com/rss/articles/{new_token()}"
    assert run(resolve_with(resolver(tmp_path), url, handler)) == PUBLISHER and len(posts) == 2


def test_retries_are_limited_and_a_transient_failure_is_not_remembered(tmp_path, monkeypatch):
    async def fast(_):
        return None
    monkeypatch.setattr(G.asyncio, "sleep", fast)
    posts = []

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, text=article_page(), headers={"content-type": "text/html"})
        posts.append(1)
        return httpx.Response(503)

    r = resolver(tmp_path, google_news_resolve_retries=2)
    url = f"https://news.google.com/rss/articles/{new_token()}"
    assert run(resolve_with(r, url, handler)) is None
    assert len(posts) == 3  # one attempt and two retries, no more
    assert url not in r.cache  # a network hiccup must not hide the link for an hour


def test_a_final_failure_is_remembered_so_the_next_run_does_not_ask_again(tmp_path):
    def handler(req):  # a page without the data the call needs, and no redirect: nothing to try
        return httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"})

    r = resolver(tmp_path)
    url = f"https://news.google.com/rss/articles/{new_token()}"
    assert run(resolve_with(r, url, handler)) is None
    assert r.cache[url]["url"] is None
    assert GoogleNewsResolver(Settings(db_path=tmp_path / 'history.db')).cache[url]["url"] is None


def test_the_plain_redirect_still_works_as_the_last_step(tmp_path):
    def handler(req):
        if req.headers['host'] == 'news.google.com':
            return httpx.Response(302, headers={'location': PUBLISHER})
        return httpx.Response(200, text='<html><title>Publisher</title></html>', headers={"content-type": "text/html"})

    assert run(resolve_with(resolver(tmp_path), "https://news.google.com/rss/articles/CBMiplain", handler)) == PUBLISHER


def test_concurrency_is_capped(tmp_path):
    live, peak = 0, 0

    async def go():
        async def handler(req):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.02)
            live -= 1
            return httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"})

        class Async(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                return await handler(request)

        r = resolver(tmp_path, google_news_resolve_concurrency=2)
        async with RealAsyncClient(transport=Async()) as client:
            sem = asyncio.Semaphore(16)
            urls = [f"https://news.google.com/rss/articles/{legacy_token('http://x')}{i}" for i in range(8)]
            await asyncio.gather(*(r.resolve(u, client, sem) for u in urls))

    run(go())
    assert 0 < peak <= 2, peak


def test_after_the_run_budget_the_rest_stay_unresolved_without_a_request(tmp_path):
    r = resolver(tmp_path, google_news_resolve_budget_s=5.0)
    r.started = G.time.monotonic() - 60
    hit = []

    async def go():
        r.slots = asyncio.Semaphore(4)
        r.started = G.time.monotonic() - 60
        return await resolve_with(r, f"https://news.google.com/rss/articles/{new_token()}",
                                  lambda req: hit.append(1) or httpx.Response(200, text="<html></html>"))

    assert run(go()) is None and hit == []


def test_a_non_google_link_is_returned_unchanged(tmp_path):
    assert run(resolve_with(resolver(tmp_path), PUBLISHER, lambda req: httpx.Response(500))) == PUBLISHER


# --------------------------------------------------------------------------------- ingestion, edition, website
def _items(tmp_path, monkeypatch):
    from agent_reach.ingestion.search import GoogleNewsIngester

    good = f"https://news.google.com/rss/articles/{legacy_token(PUBLISHER)}?oc=5"
    bad = "https://news.google.com/rss/articles/CBMibroken?oc=5"
    rss = ('<?xml version="1.0"?><rss><channel>'
           f'<item><title>Ferry strike halts island service - Example Paper</title><link>{good}</link>'
           '<pubDate>Sat, 10 Oct 2026 06:00:00 GMT</pubDate><source url="https://www.example-paper.com">Example Paper</source></item>'
           f'<item><title>Council votes to close two schools - Other Paper</title><link>{bad}</link>'
           '<pubDate>Sat, 10 Oct 2026 06:10:00 GMT</pubDate><source url="https://other.test">Other Paper</source></item>'
           '</channel></rss>')

    def handler(req):
        if req.url.path.startswith("/rss") and "articles" not in req.url.path:
            return httpx.Response(200, text=rss, headers={"content-type": "application/rss+xml"})
        return httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"})

    async def go():
        async with RealAsyncClient(transport=httpx.MockTransport(handler)) as client:
            ing = GoogleNewsIngester(client, Settings(db_path=tmp_path / 'h.db', http_max_retries=0), asyncio.Semaphore(4))
            return await ing._read("https://news.google.com/rss?hl=en-US", __import__("agent_reach.models", fromlist=["x"]).CategoryEnum.NEWS, None, 10)

    return run(go()), good, bad


def test_ingestion_stores_the_canonical_url_and_keeps_the_raw_one(tmp_path, monkeypatch):
    items, good, bad = _items(tmp_path, monkeypatch)
    by = {i.title: i for i in items}
    resolved = by["Ferry strike halts island service"]
    assert resolved.url == PUBLISHER and resolved.metadata["source_url_raw"] == good
    assert "url_unresolved" not in resolved.metadata and "via" not in resolved.metadata
    unresolved = by["Council votes to close two schools"]
    assert unresolved.url == bad and unresolved.metadata["source_url_raw"] == bad
    assert unresolved.metadata["url_unresolved"] is True and unresolved.metadata["via"] == "Google News"


def test_edition_and_website_label_only_what_really_failed(tmp_path):
    from agent_reach.daily import publish as P
    from agent_reach.daily.edition import EvidenceLink, is_google_news_url
    from tests.daily_fakes import make_edition, make_story

    raw = f"https://news.google.com/rss/articles/{legacy_token(PUBLISHER)}"
    stuck = "https://news.google.com/rss/articles/CBMibroken"
    story = make_story(1, items=2)
    story.evidence = [
        EvidenceLink(item_id=1, source="google_news", source_name="Google News", title="Ferry strike", url=PUBLISHER,
                     publisher="Example Paper", url_raw=raw),
        EvidenceLink(item_id=2, source="google_news", source_name="Google News", title="Schools close", url=stuck,
                     publisher="Other Paper", url_raw=stuck, url_unresolved=True),
    ]
    ed = make_edition([story])
    public = P.public_edition(ed)
    srcs = {s["title"]: s for s in public["stories"][0]["sources"]}
    assert srcs["Ferry strike"]["url"] == PUBLISHER and srcs["Ferry strike"]["source_url_raw"] == raw
    assert "news.google.com" not in srcs["Ferry strike"]["url"]  # ('via' names the feed it came through, not a redirect)
    assert srcs["Schools close"]["via"] == "Google News" and "source_url_raw" not in srcs["Schools close"]
    page = P.edition_page(public).decode()
    assert page.count("Google News redirect") == 1
    assert is_google_news_url(stuck) and not is_google_news_url(PUBLISHER)
    from agent_reach.daily.edition import count_unresolved  # what assemble_edition stores on the edition
    assert count_unresolved([story]) == 1
    ed.unresolved_source_urls = count_unresolved(ed.stories)
    assert P.public_edition(ed)["unresolved_source_urls"] == 1
