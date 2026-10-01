"""Abstract async ingester with retry, backoff, header randomisation and safe failure."""

from __future__ import annotations

import abc
import asyncio
import logging
import random
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any

import httpx

from agent_reach.config import Settings
from agent_reach.models import PUBLISHED_FUTURE_TOLERANCE, FeedStat, RawTrendItem, SourceName, SourceStat

log = logging.getLogger(__name__)

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

BROWSER_USER_AGENTS: tuple[str, ...] = (
    DEFAULT_HEADERS["User-Agent"],
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0",
)
ACCEPT_LANGUAGES: tuple[str, ...] = ("en-US,en;q=0.9", "en-US,en;q=0.8", "en-GB,en;q=0.9,en-US;q=0.8")
RETRYABLE_STATUS: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504, 522, 524})


class IngestionError(Exception):
    """Raised inside an ingester when a source cannot be fetched after all retries."""


def xml_local(tag: str) -> str:
    """Strip an XML namespace: '{ns}title' -> 'title'."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def xml_child_text(el: ET.Element, name: str) -> str | None:
    for child in el:
        if xml_local(child.tag) == name:
            return (child.text or "").strip() or None
    return None


def parse_datetime(value: str | None) -> datetime:
    """Parse RFC-822 or ISO-8601 timestamps; fall back to now (UTC)."""
    return parse_optional_datetime(value) or datetime.now(timezone.utc)


#: Earlier than this is a parsing accident or a placeholder date, not a news publication time.
EARLIEST_PLAUSIBLE_PUBLICATION = datetime(1995, 1, 1, tzinfo=timezone.utc)
_DATE_ONLY_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FOUR_DIGIT_YEAR_RX = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def parse_optional_datetime(value: str | None) -> datetime | None:
    """Parse RFC-822 or ISO-8601 timestamps to an aware UTC datetime; None when absent or unusable.

    Never substitutes 'now'. Offsets and zone names (GMT, EDT, +05:30, Z) are normalised to UTC; a
    zone-less ISO time is read as UTC (RSS/Atom require a zone, so this only affects broken feeds).
    Rejected: unparseable text, a date without a time (it would invent a time of day), and values
    whose stated 4-digit year was rewritten by the RFC-822 two-digit-year rule (0001 -> 2001).
    """
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if not value or _DATE_ONLY_RX.match(value):
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, OverflowError):
            return None
    if dt is None:
        return None
    years = _FOUR_DIGIT_YEAR_RX.findall(value)
    if years and dt.year != int(years[0]):
        return None
    try:
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def epoch_to_utc(value: Any) -> datetime | None:
    """Unix seconds -> aware UTC datetime; None for missing, zero, non-numeric or out-of-range values."""
    try:
        seconds = float(value)
        if not seconds or seconds != seconds:  # 0 / NaN
            return None
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def validate_publication_time(published: datetime, retrieved: datetime) -> tuple[datetime | None, str | None]:
    """Check a stated publication time against the retrieval time. Returns (usable value, note).

    * naive -> treated as UTC; any offset -> normalised to UTC
    * before 1995 -> rejected ("implausibly old")
    * after retrieval by more than PUBLISHED_FUTURE_TOLERANCE -> rejected ("in the future")
    * after retrieval within the tolerance -> clamped to the retrieval time ("clock skew")
    A rejected time is never shown as a publication time; the item keeps its retrieval time.
    """
    published = (published if published.tzinfo else published.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    if published < EARLIEST_PLAUSIBLE_PUBLICATION:
        return None, "implausibly old"
    if published > retrieved + PUBLISHED_FUTURE_TOLERANCE:
        return None, "in the future"
    if published > retrieved:
        return retrieved, "clock skew (clamped to retrieval time)"
    return published, None


def parse_count(text: str | None) -> float | None:
    """'12.3K' -> 12300, '1,204' -> 1204, '200+' -> 200, '2M' -> 2_000_000."""
    if not text:
        return None
    t = text.strip().upper().replace(",", "").replace("+", "")
    mult = 1.0
    if t.endswith("K"):
        mult, t = 1e3, t[:-1]
    elif t.endswith("M"):
        mult, t = 1e6, t[:-1]
    elif t.endswith("B"):
        mult, t = 1e9, t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        digits = "".join(ch for ch in t if ch.isdigit() or ch == ".")
        try:
            return float(digits) * mult if digits else None
        except ValueError:
            return None


class BaseIngester(abc.ABC):
    """Base class for every source.

    Subclasses implement :meth:`fetch`. Callers use :meth:`run`, which never raises:
    it returns ``(items, SourceStat)`` and converts every failure into an empty list.
    """

    source: SourceName
    #: APIs like Wikimedia and ArXiv ask for an honest, descriptive UA instead of a browser UA.
    use_bot_user_agent: bool = False
    #: Rotate among browser UAs per request. Off = always send DEFAULT_HEADERS' UA verbatim.
    rotate_user_agent: bool = True
    #: Minimum gap between consecutive requests of this ingester (pacing for rate-limited hosts).
    min_request_interval_s: float = 0.0

    def __init__(self, client: httpx.AsyncClient, settings: Settings, semaphore: asyncio.Semaphore) -> None:
        self.client = client
        self.settings = settings
        self.semaphore = semaphore
        self.log = logging.getLogger(f"agent_reach.ingest.{self.source.value}")
        self._pace_lock = asyncio.Lock()
        self._last_request_at = 0.0
        #: Partial-coverage notes (e.g. one feed of several failed). Reported on a successful SourceStat.
        self.warnings: list[str] = []
        #: Per-feed health for multi-feed sources (news_rss); empty for single-endpoint sources.
        self.feed_stats: list[FeedStat] = []

    def item_cap(self) -> int:
        """How many items this source may contribute to one run (multi-feed sources scale it)."""
        return self.settings.max_items_per_source

    async def _pace(self) -> None:
        """Serialise request starts so they are at least ``min_request_interval_s`` apart."""
        if self.min_request_interval_s <= 0:
            return
        async with self._pace_lock:
            wait = self._last_request_at + self.min_request_interval_s - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    # ------------------------------------------------------------ headers
    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(DEFAULT_HEADERS)
        if self.use_bot_user_agent:
            headers["User-Agent"] = (
                f"AgentReach/2.0 (trend-intelligence research bot; contact: {self.settings.contact_email}) httpx"
            )
        elif self.rotate_user_agent:
            headers["User-Agent"] = random.choice(BROWSER_USER_AGENTS)
            headers["Accept-Language"] = random.choice(ACCEPT_LANGUAGES)
        headers["Cache-Control"] = "no-cache"
        if extra:
            headers.update(extra)
        return headers

    # -------------------------------------------------------------- HTTP
    async def request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_statuses: frozenset[int] | set[int] | None = None,
    ) -> httpx.Response:
        """HTTP request with exponential backoff + full jitter; honours Retry-After.

        ``timeout`` / ``max_retries`` override the global settings for fail-fast endpoints.
        ``retry_statuses`` extends the retryable set (e.g. 403 for hosts that block in bursts).
        Every attempt is paced by ``min_request_interval_s``.
        """
        retryable = RETRYABLE_STATUS | frozenset(retry_statuses or ())
        retries = self.settings.http_max_retries if max_retries is None else max(0, max_retries)
        attempts = retries + 1
        per_call_timeout = self.settings.http_timeout_s if timeout is None else timeout
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                await self._pace()
                async with self.semaphore:
                    resp = await self.client.request(
                        method,
                        url,
                        params=params,
                        headers=self._headers(headers),
                        timeout=per_call_timeout,
                        follow_redirects=True,
                    )
                if resp.status_code in retryable:
                    raise httpx.HTTPStatusError(
                        f"retryable status {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = exc.response.status_code
                if status not in retryable or attempt == attempts:
                    break
                delay = self._retry_after(exc.response) or self._backoff(attempt)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt == attempts:
                    break
                delay = self._backoff(attempt)
            self.log.info("retry %d/%d for %s in %.1fs (%s)", attempt, attempts - 1, url.split("?")[0], delay, str(last_exc)[:80])
            await asyncio.sleep(delay)
        raise IngestionError(f"{url}: {type(last_exc).__name__}: {last_exc}") from last_exc

    async def get_json(self, url: str, **kw: Any) -> Any:
        resp = await self.request(url, headers={"Accept": "application/json", **(kw.pop("headers", None) or {})}, **kw)
        try:
            return resp.json()
        except ValueError as exc:
            raise IngestionError(f"{url}: invalid JSON ({exc})") from exc

    async def get_text(self, url: str, **kw: Any) -> str:
        resp = await self.request(url, **kw)
        return resp.text

    async def get_xml(self, url: str, **kw: Any) -> ET.Element:
        resp = await self.request(url, **kw)
        try:
            return ET.fromstring(resp.content)
        except ET.ParseError as exc:
            raise IngestionError(f"{url}: invalid XML ({exc})") from exc

    def _backoff(self, attempt: int) -> float:
        cap = min(self.settings.http_backoff_max_s, self.settings.http_backoff_base_s * (2 ** (attempt - 1)))
        return random.uniform(cap / 2, cap)

    def _retry_after(self, resp: httpx.Response) -> float | None:
        raw = resp.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return min(float(raw), self.settings.http_backoff_max_s)
        except ValueError:
            try:
                dt = parsedate_to_datetime(raw)
                return max(0.0, min((dt - datetime.now(timezone.utc)).total_seconds(), self.settings.http_backoff_max_s))
            except (TypeError, ValueError):
                return None

    # ------------------------------------------------------------ public
    @abc.abstractmethod
    async def fetch(self) -> list[RawTrendItem]:
        """Fetch and parse the source. May raise; :meth:`run` handles it."""

    async def run(self) -> tuple[list[RawTrendItem], SourceStat]:
        started = time.perf_counter()
        try:
            items = await self.fetch()
            items = items[: self.item_cap()]
            stat = SourceStat(
                source=self.source.value,
                ok=True,
                item_count=len(items),
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=("partial: " + "; ".join(self.warnings))[:300] if self.warnings else None,
                feeds=self._final_feed_stats(items),
            )
            self.log.info("fetched %d items in %d ms", len(items), stat.latency_ms)
            return items, stat
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - an ingester must never crash the pipeline
            msg = f"{type(exc).__name__}: {exc}"[:300]
            self.log.warning("source failed, returning no items: %s", msg)
            return [], SourceStat(
                source=self.source.value,
                ok=False,
                item_count=0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=msg,
                feeds=self._final_feed_stats([]),
            )

    # ------------------------------------------------------------ helpers
    def _final_feed_stats(self, kept: list[RawTrendItem]) -> list[FeedStat]:
        """Per-feed counts of the items actually kept after the source cap."""
        if not self.feed_stats:
            return []
        kept_per_feed: dict[str, int] = {}
        for it in kept:
            feed = str(it.metadata.get("feed") or "")
            kept_per_feed[feed] = kept_per_feed.get(feed, 0) + 1
        return [fs.model_copy(update={"item_count": kept_per_feed.get(fs.url, 0)}) for fs in self.feed_stats]

    def make_item(self, *, published_at: datetime | None = None, **kwargs: Any) -> RawTrendItem | None:
        """Build an item, silently skipping ones that fail validation (e.g. empty title).

        ``published_at`` is the source's own publication time, only when the source states one.
        It is recorded as ``metadata['published_at']``; ``metadata['retrieved_at']`` is always the
        fetch time. ``timestamp`` (used for event coherence) defaults to the publication time.
        Items without ``published_at`` have no verified publication time.
        """
        try:
            title = (kwargs.get("title") or "").strip()
            if not title:
                return None
            kwargs["title"] = title[:1000]
            metadata = dict(kwargs.pop("metadata", None) or {})
            retrieved = datetime.now(timezone.utc)
            metadata["retrieved_at"] = retrieved.isoformat()
            if published_at is not None:
                published_at, note = validate_publication_time(published_at, retrieved)
                if note:
                    metadata["published_at_note"] = note
                if published_at is not None:
                    metadata["published_at"] = published_at.isoformat()
                    kwargs.setdefault("timestamp", published_at)
            return RawTrendItem(source=self.source, metadata=metadata, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self.log.debug("skipping malformed item: %s", exc)
            return None
