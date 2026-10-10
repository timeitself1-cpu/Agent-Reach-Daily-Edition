"""Conservative provenance and event identity helpers; no model-generated membership."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
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


def _item_title(it: Any) -> str:
    if isinstance(it, str):
        return it
    if isinstance(it, dict):
        return it.get("normalized_title") or it.get("title") or ""
    return getattr(it, "normalized_title", None) or getattr(it, "title", None) or ""


def _item_date(it: Any) -> str | None:
    if isinstance(it, dict):
        ts = it.get("timestamp") or it.get("published_at_utc") or it.get("published_utc") or it.get("retrieved_at_utc")
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.astimezone(timezone.utc).date().isoformat()
            except Exception:
                if len(ts) >= 10 and ts[4] == "-" and ts[7] == "-":
                    return ts[:10]
        elif isinstance(ts, datetime):
            return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).date().isoformat()
        return None
    ts = getattr(it, "timestamp", None) or getattr(it, "published_at_utc", None) or getattr(it, "retrieved_at_utc", None)
    if isinstance(ts, datetime):
        return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).date().isoformat()
    return None


def stable_event_id(items: list[Any]) -> str:
    """Stable event identifier for timelines: same event across editions, even as evidence grows.

    Derived from the event's core identity (actor + action + location + date), not the
    evidence set. Two editions covering the same event get the same stable ID even if
    the second edition has more sources.
    """
    from agent_reach.pipeline.same_event import _actor, title_words

    if not items:
        return "evt_" + hashlib.sha256(b"empty").hexdigest()[:12]

    rep = max(items, key=lambda it: len(_item_title(it)))
    title = _item_title(rep)
    actor = " ".join(_actor(title)) if title else ""
    actions = sorted(title_words(title) & {
        'strike', 'attack', 'bomb', 'launch', 'unveil', 'introduce', 'resign', 'quit',
        'arrest', 'detain', 'suspend', 'halt', 'pause', 'win', 'defeat', 'kill', 'die',
        'announce', 'reveal', 'release', 'confirm', 'deny', 'reject', 'approve'
    })
    try:
        found_dates = sorted(d for it in items if (d := _item_date(it)))
        date = found_dates[0] if found_dates else "unknown"
    except Exception:
        date = "unknown"
    location = ""
    meta = rep.get("metadata") if isinstance(rep, dict) else getattr(rep, "metadata", None)
    if meta and isinstance(meta, dict):
        for key in ('location', 'city', 'country', 'region'):
            if meta.get(key):
                location = str(meta[key]).lower()
                break
    key = f"{actor}|{' '.join(actions)}|{location}|{date}"
    return "evt_" + hashlib.sha256(key.encode()).hexdigest()[:12]


def canonical_event_id(story_or_items) -> str:
    """ONE canonical event ID mechanism. Used by _public_story() and EventRegistry.

    Priority:
    1. entity_id from story (stable hash of entities — survives headline/evidence changes)
    2. event_id already computed (for dict inputs)
    3. stable_event_id from evidence items (actor+action+location+date)
    4. Headline hash fallback

    Same event → same ID, regardless of which code path calls this.
    """
    if story_or_items is None:
        return "evt_" + hashlib.sha256(b"|fallback").hexdigest()[:12]

    # Dict (public story JSON)
    if isinstance(story_or_items, dict):
        if story_or_items.get("event_id"):
            return story_or_items["event_id"]
        if story_or_items.get("entity_id"):
            return "evt_" + str(story_or_items["entity_id"])[:12]
        sources = story_or_items.get("evidence") or story_or_items.get("sources")
        if sources and isinstance(sources, list):
            try:
                return stable_event_id(sources)
            except Exception:
                pass
        headline = story_or_items.get("headline", "")
        return "evt_" + hashlib.sha256(f"{headline.casefold()}|fallback".encode()).hexdigest()[:12]

    # Story object with entity_id (preferred: stable across editions)
    if hasattr(story_or_items, "entity_id") and story_or_items.entity_id:
        return "evt_" + str(story_or_items.entity_id)[:12]

    # Try items
    items = None
    headline = ""
    if isinstance(story_or_items, list):
        items = story_or_items
    elif hasattr(story_or_items, 'items') and story_or_items.items:
        items = story_or_items.items
        headline = getattr(story_or_items, 'headline', '') or ""
    elif hasattr(story_or_items, 'evidence') and story_or_items.evidence:
        # Story.evidence is list[EvidenceLink]; use evidence items for stable ID
        items = story_or_items.evidence
        headline = getattr(story_or_items, 'headline', '') or ""
    else:
        headline = getattr(story_or_items, 'headline', '') or ""

    if items:
        try:
            return stable_event_id(items)
        except Exception:
            pass

    return "evt_" + hashlib.sha256(f"{headline.casefold()}|fallback".encode()).hexdigest()[:12]
