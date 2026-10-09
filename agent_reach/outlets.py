"""Publisher identity and readable names, using the already installed offline public suffix list."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from tld import get_fld

ALIASES = {
    "ap": "AP News", "apnews": "AP News", "associatedpress": "AP News",
    "reuters": "Reuters", "cnbc": "CNBC", "nasa": "NASA", "twitter": "X", "x": "X",
    "nytimes": "The New York Times", "newyorktimes": "The New York Times",
    "thenewyorktimes": "The New York Times", "bbc": "BBC News", "bbcnews": "BBC News",
    "pbs": "PBS NewsHour", "pbsnewshour": "PBS NewsHour", "dw": "DW", "wired": "Wired",
    "tomshardware": "Tom's Hardware", "github": "GitHub", "guardian": "The Guardian",
    "theguardian": "The Guardian", "washingtonpost": "The Washington Post",
    "thewashingtonpost": "The Washington Post",
    # Reviewed newsroom aliases, not parent-company ownership groups.
    "nbcdfw": "NBC DFW", "nbc5dallasfortworth": "NBC DFW",
    "aljazeera": "Al Jazeera", "aljazeeraenglish": "Al Jazeera",
}
AGGREGATORS = {"google.com", "youtube.com", "youtu.be", "news.google.com", "news.ycombinator.com"}


def registrable_domain(url: str | None) -> str:
    try:
        host = (urlsplit(url or "").hostname or "").lower().removeprefix("www.")
        return get_fld("https://" + host, fail_silently=True) or host
    except (ValueError, TypeError):
        return ""


def _key(name: str) -> str:
    name = re.sub(r"\s*\([^)]*\)$", "", name.lower().strip().removeprefix("www."))
    name = re.sub(r"\.(?:co|com|org|net)\.[a-z]{2}$|\.[a-z]{2,}$", "", name)
    return re.sub(r"[^a-z0-9]", "", name)


def outlet_name(publisher: str | None, url: str | None = None) -> str:
    readable = re.sub(r"\s+[-–—|:]\s+.*$", "", publisher or "").strip()
    readable = re.sub(r"\s*\([^)]*\)$", "", readable).strip()
    key = _key(readable)
    if key in ALIASES:
        return ALIASES[key]
    domain = registrable_domain(url)
    if domain and domain not in AGGREGATORS and not domain.endswith('.test'):
        if _key(domain) in ALIASES:
            return ALIASES[_key(domain)]
    return readable or ALIASES.get(_key(domain), domain)


def outlet_key(publisher: str | None, url: str | None = None) -> str | None:
    name = outlet_name(publisher, url)
    key = _key(name)
    domain = registrable_domain(url)
    if key in ALIASES or name in ALIASES.values() or not domain or domain in AGGREGATORS or domain.endswith('.test'):
        return _key(ALIASES.get(key, name)) or None
    return _key(domain) or key or None
