"""Conservative provenance and event identity helpers; no model-generated membership."""
from __future__ import annotations

import hashlib
from datetime import timezone
from urllib.parse import urlsplit

from agent_reach.models import CleanedTrendItem, RawTrendItem


def observations(item: CleanedTrendItem) -> list[RawTrendItem]:
    return item.observations or [item]


def platforms(items: list[CleanedTrendItem]) -> list[str]:
    return sorted({o.source.value for it in items for o in observations(it)})


def publishers(items: list[CleanedTrendItem]) -> list[str]:
    """Known publisher hosts, not aggregators or an estimate of editorial independence.

    Syndication is collapsed when the ingester provides an origin URL. Unknown origins
    earn no publisher bonus; distinct hosts remain a proxy, not verified independence.
    """
    hosts = set()
    aggregators = {"news.google.com", "trends.google.com", "reddit.com", "x.com",
                   "twitter.com", "tiktok.com", "news.ycombinator.com", "trends24.in"}
    for it in items:
        for o in observations(it):
            url = o.metadata.get("original_url") or o.metadata.get("publisher_url") or o.url
            try:
                host = (urlsplit(str(url or "")).hostname or "").lower().removeprefix("www.")
            except ValueError:
                continue
            if host and "." in host and not any(host == a or host.endswith("." + a) for a in aggregators):
                hosts.add(host)
    return sorted(hosts)


def event_id(items: list[CleanedTrendItem]) -> str:
    """Evidence fingerprint; cross-run continuation requires evidence matching, not ID equality."""
    keys = sorted({f"{it.normalized_title.casefold()}|{it.timestamp.astimezone(timezone.utc):%Y-%m-%d}" for it in items})
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()[:20]
