"""Canonical publisher URLs for Google News links. A Google News RSS link is not the article: it is an address on
news.google.com that a browser turns into the publisher's page with script. Showing it as a source sends the reader
through Google and hides the outlet (October 10, 2026: sources listed as 'Google News redirect').

Resolution, cheapest first, every step bounded:

1. Offline: older links carry the publisher URL inside the token (base64), so it is read, not fetched.
2. Google's own page-data call (the same ``batchexecute`` request the news.google.com page makes for its redirect),
   for links whose token only points at a record. It needs the article page's signature and timestamp.
3. Plain redirects / canonical tags of the article page (what rc17 did).

A link that none of these resolves stays on news.google.com and keeps the label; ``unresolved`` is counted and
published. Nothing here invents a URL: the result is either a destination Google itself returned (checked to be a
public http(s) address that is not Google) or None. The raw link is always kept by the caller as ``source_url_raw``.

Limits: ``google_news_resolve_timeout_s`` per attempt, ``google_news_resolve_retries`` retries of a transient failure,
``google_news_resolve_concurrency`` requests at once, ``google_news_resolve_budget_s`` for a whole run (after that,
remaining links stay unresolved instead of slowing the refresh). Step 2 depends on an undocumented Google endpoint
and can stop working; tests use recorded response shapes, and the failure mode is the labelled, unresolved link.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from agent_reach.pipeline.enricher import ContentEnricher, _is_public_http_url

log = logging.getLogger("agent_reach.ingest.google_urls")

BATCH_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
_TOKEN_RX = re.compile(r"/(?:rss/)?(?:articles|read)/([A-Za-z0-9_-]+)")
_LEGACY_PREFIX = b"\x08\x13\x22"
_LEGACY_SUFFIX = b"\xd2\x01\x00"


def is_google_news(url: str | None) -> bool:
    try:
        return (urlsplit(url or '').hostname or '').lower() == 'news.google.com'
    except ValueError:
        return False


def article_token(url: str) -> str | None:
    match = _TOKEN_RX.search(urlsplit(url).path)
    return match.group(1) if match else None


def decode_legacy_token(token: str) -> str | None:
    """The publisher URL a legacy token carries inside itself, or None (then the token only names a record)."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (ValueError, TypeError):
        return None
    if raw.startswith(_LEGACY_PREFIX):
        raw = raw[len(_LEGACY_PREFIX):]
    if raw.endswith(_LEGACY_SUFFIX):
        raw = raw[:-len(_LEGACY_SUFFIX)]
    if not raw:
        return None
    length = raw[0]
    body = raw[2:length + 2] if length >= 0x80 else raw[1:length + 1]
    if body.startswith(b"AU_yqL"):
        return None
    try:
        url = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return url if _is_public_http_url(url) and not is_google_news(url) else None


def batch_body(token: str, signature: str, timestamp: str) -> str:
    inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None,
                                        None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                        token, int(timestamp), signature], separators=(",", ":"))
    return "f.req=" + quote(json.dumps([[["Fbv4je", inner, None, "generic"]]], separators=(",", ":")))


def parse_batch_response(text: str) -> str | None:
    """The destination in a batchexecute answer ()]}' header, then JSON chunks), or None."""
    for chunk in text.split("\n\n"):
        chunk = chunk.strip()
        if not chunk.startswith("["):
            continue
        try:
            rows = json.loads(chunk)
            for row in rows:
                if isinstance(row, list) and len(row) > 2 and row[1] == "Fbv4je" and isinstance(row[2], str):
                    payload = json.loads(row[2])
                    url = payload[1]
                    if isinstance(url, str) and _is_public_http_url(url) and not is_google_news(url):
                        return url
        except (ValueError, IndexError, TypeError):
            continue
    return None


class _Transient(Exception):
    """A failure worth another attempt (timeout, connection error, 429/5xx)."""


class GoogleNewsResolver:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.enricher = ContentEnricher(settings)
        self.path = Path(settings.db_path).with_name('google-news-urls.json')
        try:
            self.cache = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(self.cache, dict):
                self.cache = {}
        except (OSError, ValueError):
            self.cache = {}
        self.pending: dict[str, asyncio.Task] = {}
        self.slots: asyncio.Semaphore | None = None
        self.started: float | None = None
        self.stats = {"resolved": 0, "unresolved": 0, "cached": 0}

    # ------------------------------------------------------------------------------------------- public
    async def resolve(self, url, client, semaphore) -> str | None:
        if not is_google_news(url):
            return url
        cached = self.cache.get(url)
        if isinstance(cached, dict) and cached.get('until', 0) > time.time():
            self.stats["cached"] += 1
            return cached.get('url')
        if url not in self.pending:
            self.pending[url] = asyncio.create_task(self._resolve(url, client, semaphore))
        try:
            return await self.pending[url]
        finally:
            self.pending.pop(url, None)

    # ------------------------------------------------------------------------------------------ internals
    def _over_budget(self) -> bool:
        budget = float(getattr(self.settings, 'google_news_resolve_budget_s', 90.0))
        return self.started is not None and time.monotonic() - self.started > budget

    async def _resolve(self, url, client, semaphore) -> str | None:
        if self.slots is None:
            self.slots = asyncio.Semaphore(int(getattr(self.settings, 'google_news_resolve_concurrency', 4)))
            self.started = time.monotonic()
        resolved = None
        permanent = True
        async with self.slots:
            if self._over_budget():
                permanent = False  # not tried: do not remember it as a failure
            else:
                resolved, permanent = await self._with_retries(url, client, semaphore)
        self.stats["resolved" if resolved else "unresolved"] += 1
        if resolved or permanent:
            self._remember(url, resolved)
        return resolved

    async def _with_retries(self, url, client, semaphore) -> tuple[str | None, bool]:
        """(destination or None, whether the failure is final). Transient failures are retried a few times."""
        timeout = float(getattr(self.settings, 'google_news_resolve_timeout_s', 10.0))
        retries = int(getattr(self.settings, 'google_news_resolve_retries', 2))
        for attempt in range(retries + 1):
            try:
                found = await asyncio.wait_for(self._attempt(url, client, semaphore, timeout), timeout=timeout)
                return found, True
            except (_Transient, asyncio.TimeoutError, httpx.HTTPError, OSError) as exc:
                log.info("google news link not resolved (attempt %d): %s", attempt + 1, type(exc).__name__)
                if attempt == retries or self._over_budget():
                    return None, False
                await asyncio.sleep(min(2.0, 0.4 * 2 ** attempt))
            except Exception:  # a failed resolver never drops a source
                log.exception("google news resolver error")
                return None, True
        return None, False

    async def _attempt(self, url, client, semaphore, timeout) -> str | None:
        token = article_token(url)
        if token:
            offline = decode_legacy_token(token)
            if offline:
                return offline
            transient = None
            try:
                found = await self._batchexecute(token, url, client, semaphore, timeout)
                if found:
                    return found
            except (_Transient, httpx.HTTPError) as exc:
                transient = exc  # the plain redirect below may still work; if not, the failure is worth a retry
            found = await self._follow(url, client, semaphore)
            if found is None and transient is not None:
                raise _Transient(str(transient))
            return found
        return await self._follow(url, client, semaphore)

    async def _batchexecute(self, token, url, client, semaphore, timeout) -> str | None:
        page = await self.enricher._get(f"https://news.google.com/rss/articles/{token}", client, semaphore, 'text/html')
        if page is not None and not is_google_news(page.url):
            return page.url  # the article address already redirected to the publisher
        if page is None or 'html' not in page.content_type.lower():
            raise _Transient("article page unavailable")
        soup = BeautifulSoup(page.body, 'html.parser')
        node = soup.select_one('c-wiz div[data-n-a-sg][data-n-a-ts]')
        if node is None:
            return None  # a page without the data this call needs: final, not transient
        signature, stamp = str(node.get('data-n-a-sg')), str(node.get('data-n-a-ts'))
        if not stamp.isdigit():
            return None
        response = await client.post(BATCH_URL, content=batch_body(token, signature, stamp), timeout=timeout,
                                     headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        if response.status_code in (429,) or response.status_code >= 500:
            raise _Transient(f"HTTP {response.status_code}")
        if response.status_code != 200:
            return None
        return parse_batch_response(response.text)

    async def _follow(self, url, client, semaphore) -> str | None:
        page = await self.enricher._get(url, client, semaphore, 'text/html')
        if page is None:
            return None
        if not is_google_news(page.url):
            return page.url
        if 'html' not in page.content_type.lower():
            return None
        soup = BeautifulSoup(page.body, 'html.parser')
        targets = [t.get('href') for t in soup.select('link[rel="canonical"]')]
        targets += [t.get('content') for t in soup.select('meta[property="og:url"]')]
        for tag in soup.select('meta[http-equiv]'):
            if str(tag.get('http-equiv')).lower() == 'refresh':
                m = re.search(r'url\s*=\s*(.+)', str(tag.get('content')), re.I)
                if m:
                    targets.append(m.group(1).strip('"\''))
        for target in targets:
            if not target:
                continue
            destination = urljoin(page.url, str(target))
            if _is_public_http_url(destination) and not is_google_news(destination):
                # The existing safe fetch validates DNS and redirects, including Google HTML targets.
                final = await self.enricher._get(destination, client, semaphore, 'text/html')
                if final and not is_google_news(final.url):
                    return final.url
        return None

    def _remember(self, url: str, resolved: str | None) -> None:
        self.cache[url] = {'url': resolved, 'until': time.time() + (7 * 86400 if resolved else 3600)}
        self.cache = {key: value for key, value in self.cache.items()
                      if isinstance(value, dict) and value.get('until', 0) > time.time()}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps(self.cache), encoding='utf-8')
            temp.replace(self.path)
        except OSError:
            pass
