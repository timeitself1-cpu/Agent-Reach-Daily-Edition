"""Website publishing: put each validated edition on the Agent Reach website (opt-in, off by default).

The website (getagentreach.dev) is a static site served by Cloudflare from the ``main`` branch of its GitHub
repository; every push to ``main`` is deployed. Publishing therefore means one commit to that repository,
made through GitHub's REST API with an access key the user pastes once. The PC only makes outgoing HTTPS
requests to api.github.com: nothing listens for connections and nothing about the PC is uploaded.

What goes up for one edition (``site_files``):

* ``editions/YYYY-MM-DD.json``  the public edition (``public_edition``): headlines, the app's own validated
  summaries, categories, coverage strength, New/Updated labels, and for each source its outlet, headline, link
  and stated publication time; and the sources the edition read (``public_sources``: each kind of source, each
  feed by name and website, with report counts; the website's Sources page, asked for on Oct 9, 2026). Never:
  publisher excerpts, feed addresses, error texts, the run log, settings, model diagnostics, file paths or anything
  else about this computer (``assert_public`` refuses text that looks like a local path).
* ``daily/YYYY-MM-DD/index.html``  the permanent page of that date (``edition_page``); ``/daily/`` and the
  home page show the newest date.
* ``editions/index.json``  the archive list, rewritten from what is already on the site plus this edition.
* ``feed.xml`` (RSS, one item per edition) and ``sitemap.xml``, both rebuilt from that archive list
  (``index_files``), so they always agree with it, also after a withdrawal.
* ``search/YYYY-MM.json``  the archive search data of that month (``search_files``): per story only what the
  search page shows (date, headline, category, a short summary, outlets, coverage level). One small file per
  month keeps search fast however long the archive gets: the page loads the newest months first, and the
  browser revalidates old months instead of downloading them again.

Safety:

* All files change in ONE commit, and the branch moves only by fast-forward: a failed upload changes nothing
  on the site (the previous edition stays live), and two publishers cannot overwrite each other.
* Idempotent: the files are a pure function of the edition, so a retry finds them already there and makes
  no commit (no duplicate editions). One file per date: a later revision of the day replaces the earlier one.
* A demo edition, an edition the site already has in a newer revision, and a date the user withdrew (until a
  newer revision exists) are never published.
* ``withdraw`` takes a date off the site; ``hide_story`` removes one story from the public copy and republishes;
  later revisions of that date leave it out too, recognised by its reports (its id can change).

Local files (``%LOCALAPPDATA%\\AgentReachDaily\\publish``): ``publish.json`` (settings, hidden stories, withdrawn
dates), ``status.json`` (last attempt and last success), ``access-key.dat`` (the access key, encrypted with
Windows DPAPI for this Windows user; a 0600 file elsewhere), ``publish.lock``.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import os
import re
import sys
from email.utils import format_datetime
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape

from pydantic import BaseModel, Field

from agent_reach.daily import __version__
from agent_reach.daily.edition import (DailyEdition, SourceHealth, Story, category_sections, newest_published, primary_url,
                                      safe_url, top_stories)
from agent_reach.daily.fsutil import FileUnavailable, atomic_write_bytes, atomic_write_json, read_json, unlink_with_retry
from agent_reach.daily.lock import LockBusy, RefreshLock
from agent_reach.daily.paths import DataPaths
from agent_reach.daily.registry import evidence_keys
from agent_reach.daily.strength import reporting_groups, strength_of
from agent_reach.daily.timeutil import format_central, format_long_date, utcnow
from agent_reach.outlets import outlet_name
from agent_reach.ingestion.google_urls import is_google_news

log = logging.getLogger(__name__)

SITE_URL = "https://getagentreach.dev"
SITE_REPO = "timeitself1-cpu/Agent-Reach-Website"
SITE_BRANCH = "main"
GITHUB_API = "https://api.github.com"
PUBLIC_SCHEMA = "agent_reach.public_edition"
PUBLIC_SCHEMA_VERSION = 1
INDEX_SCHEMA = "agent_reach.public_index"
INDEX_PATH = "editions/index.json"
FEED_PATH = "feed.xml"
SITEMAP_PATH = "sitemap.xml"
FEED_ITEMS = 30
SEARCH_SCHEMA = "agent_reach.search_month"
SEARCH_SUMMARY_CHARS = 280
SEARCH_OUTLETS = 5
# Page shells that exist on the site whatever is published (sitemap.xml lists them).
STATIC_PAGES = ("", "daily/", "latest/", "world/", "technology/", "science/", "sports/", "entertainment/",
                "internet-culture/", "archive/", "about/", "sources/", "corrections/")
#: Environment variable that overrides the stored access key (CI, a portable install).
TOKEN_ENV = "AGENT_REACH_PUBLISH_TOKEN"
HTTP_TIMEOUT_S = 30.0
COMMIT_ATTEMPTS = 3
#: The scheduled check runs every hour; a failed automatic publication is tried again at most this often
#: (a little under an hour, so a check that runs a minute early is not skipped).
CATCH_UP_MINUTES = 55
#: GitHub states a fine-grained key's expiry on every API answer; the window warns this many days ahead.
EXPIRY_HEADER = "github-authentication-token-expiration"
KEY_WARN_DAYS = 7

State = Literal["never", "publishing", "published", "unchanged", "failed", "withdrawn", "skipped"]


class PublishError(Exception):
    """Publishing did not happen (plain-English message). The website is unchanged."""


class Conflict(PublishError):
    """The site branch moved while this commit was being made: re-read and try again."""


class Hopeless(PublishError):
    """A failure that trying again cannot fix: the key was refused, it lacks access, or the site already has a
    newer revision. The hourly retry waits for a new key or a new edition (audit round 2, N5)."""


def edition_json_path(d: str) -> str:
    return f"editions/{d}.json"


def edition_page_path(d: str) -> str:
    return f"daily/{d}/index.html"


def search_path(month: str) -> str:
    return f"search/{month}.json"


# ====================================================================== settings and status (local files)
class PublishSettings(BaseModel):
    enabled: bool = False  # publish automatically after every successful refresh
    site_url: str = SITE_URL
    repo: str = SITE_REPO
    branch: str = SITE_BRANCH
    hidden_stories: dict[str, list[str]] = Field(default_factory=dict)  # date -> story ids kept off the site
    # date -> story id -> that story's reports (each: its article link and normalized title keys). A story id is a
    # fingerprint of the reports and changes when a later revision adds or loses one, so the reports are what keep
    # a removed story off the site (rc15; settings from rc13/rc14 have ids only)
    hidden_reports: dict[str, dict[str, list[list[str]]]] = Field(default_factory=dict)
    withdrawn: dict[str, int] = Field(default_factory=dict)  # date -> newest revision the user took down


class PublishStatus(BaseModel):
    state: State = "never"
    message: str = ""
    attempt_utc: datetime | None = None
    success_utc: datetime | None = None  # last time the site received an edition
    edition_date: str | None = None  # the edition the site has from this PC
    revision: int | None = None
    stories: int | None = None
    commit: str | None = None
    failed_action: Literal["publish", "withdraw"] | None = None  # what the last failure was trying to do
    blocked_on: str | None = None  # 'date#revision' that failed hopelessly: not retried until a new key or edition
    key_expires_utc: datetime | None = None  # as GitHub stated it on the last call (None: no expiry, or unknown)


def _dir(paths: DataPaths) -> Path:
    return paths.root / "publish"


def settings_file(paths: DataPaths) -> Path:
    return _dir(paths) / "publish.json"


def status_file(paths: DataPaths) -> Path:
    return _dir(paths) / "status.json"


def key_file(paths: DataPaths) -> Path:
    return _dir(paths) / "access-key.dat"


def load_settings(paths: DataPaths) -> PublishSettings:
    try:
        return PublishSettings.model_validate(read_json(settings_file(paths)))
    except FileNotFoundError:
        return PublishSettings()
    except (OSError, ValueError) as exc:  # damaged or held file: publishing stays off rather than guessing
        log.warning("publish settings unreadable (%s); using defaults", type(exc).__name__)
        return PublishSettings()


def save_settings(paths: DataPaths, settings: PublishSettings) -> None:
    atomic_write_json(settings_file(paths), settings.model_dump(mode="json"))


def load_status(paths: DataPaths) -> PublishStatus:
    try:
        return PublishStatus.model_validate(read_json(status_file(paths)))
    except (OSError, ValueError):
        return PublishStatus()


def _record(paths: DataPaths, **changes) -> PublishStatus:
    status = load_status(paths).model_copy(update=changes)
    try:
        atomic_write_json(status_file(paths), status.model_dump(mode="json"))
    except OSError:
        log.exception("could not record the publishing status")
    return status


# ====================================================================== the access key (never in the repo)
def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows DPAPI for the current user: only this Windows account on this PC can decrypt the key."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buf = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    blob_in = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    blob_out = Blob()
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):  # UI_FORBIDDEN
        raise OSError(f"Windows could not {'protect' if protect else 'read'} the access key "
                      f"(error {ctypes.get_last_error()}).")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def save_token(paths: DataPaths, token: str) -> None:
    token = token.strip()
    if not token or any(c.isspace() for c in token):
        raise PublishError("That does not look like an access key (it is empty or contains spaces).")
    raw = token.encode("utf-8")
    data = b"DPAPI1\n" + _dpapi(raw, True) if sys.platform == "win32" else b"PLAIN1\n" + raw
    atomic_write_bytes(key_file(paths), data)
    if sys.platform != "win32":
        os.chmod(key_file(paths), 0o600)
    _record(paths, key_expires_utc=None, blocked_on=None)  # a new key: expiry read on its first call; retries resume


def load_token(paths: DataPaths) -> str | None:
    env = os.environ.get(TOKEN_ENV, "").strip()
    if env:
        return env
    try:
        data = key_file(paths).read_bytes()
    except FileNotFoundError:
        return None
    head, _, body = data.partition(b"\n")
    if head == b"DPAPI1" and sys.platform == "win32":
        return _dpapi(body, False).decode("utf-8")
    if head == b"PLAIN1":
        return body.decode("utf-8").strip() or None
    raise PublishError("The saved access key cannot be read on this computer. Paste it again in Website publishing.")


def forget_token(paths: DataPaths) -> None:
    unlink_with_retry(key_file(paths))
    _record(paths, key_expires_utc=None)


def parse_expiry(value: str | None) -> datetime | None:
    """GitHub's ``github-authentication-token-expiration`` header ('2026-11-07 12:00:00 UTC'), or None."""
    text = (value or "").strip().replace(" UTC", " +0000")
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(text, fmt).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def key_warning(expires: datetime | None, now: datetime | None = None) -> str:
    """Plain-English warning when the access key expires within ``KEY_WARN_DAYS`` (or has expired)."""
    if expires is None:
        return ""
    now = now or utcnow()
    day = format_long_date(expires.date())
    if expires <= now:
        return (f"Your access key expired on {day}. Publishing stops until you make a new one on github.com and "
                "paste it in Website publishing.")
    if (expires - now).total_seconds() <= KEY_WARN_DAYS * 86400:
        return (f"Your access key expires on {day}. Make a new one on github.com before then and paste it in "
                "Website publishing (the steps are the same as the first time).")
    return ""


def has_token(paths: DataPaths) -> bool:
    return bool(os.environ.get(TOKEN_ENV, "").strip()) or key_file(paths).exists()


# ====================================================================== the public edition
#: Text that looks like something on this computer: a Windows or home-folder path, the data folder.
_LOCAL_RX = re.compile(r"\b[A-Za-z]:\\|\\\\[\w.$-]+\\|\\Users\\|/home/\w|/Users/\w|AppData|LOCALAPPDATA|"
                       r"AgentReachDaily|file:/", re.IGNORECASE)


def _text_values(obj, key: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _text_values(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _text_values(v, key)
    elif isinstance(obj, str) and key != "url":  # links were checked by safe_url (absolute http/https only)
        yield obj


def looks_local(obj) -> bool:
    """Does any text in ``obj`` look like a path on this PC?"""
    return any(_LOCAL_RX.search(text) for text in _text_values(obj))


def assert_public(obj) -> None:
    """Refuse to publish text that looks like a path on this PC (defence in depth: no field should carry one)."""
    if looks_local(obj):
        raise PublishError("The edition contains text that looks like a file path on this computer, so it was "
                           "not published. Please report this.")


def _utc(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


#: A feed's section after the outlet's name: 'CNBC - Top News' -> 'CNBC' (as strength.origin does).
_SECTION_RX = re.compile(r"\s+[-\u2013\u2014|:]\s+.*$")


def _outlet(name: str) -> str:
    return _SECTION_RX.sub("", name.strip()) or name.strip()


def _public_story(s: Story, edition: DailyEdition, change: str, top_rank: int | None) -> dict:
    from agent_reach.pipeline.summary_checks import verified_story
    headline, summary = verified_story(s)
    strength = strength_of(s, edition.generation_completed_utc)
    sources, seen = [], set()
    for ev, identity in zip(s.evidence, reporting_groups(s.evidence)):
        url = safe_url(ev.url)
        key = url or ev.title
        if key in seen:
            continue
        seen.add(key)
        sources.append({"outlet": outlet_name(ev.publisher, ev.url) or _outlet(ev.source_name),
                        "via": "Google News" if is_google_news(url) else ev.source_name, "title": ev.title,
                        "url": url, "published_utc": _utc(ev.published_at_utc), **identity})
    labels = [label for label in s.labels if label in ("Hot", "Rising")]
    # The cited report supporting the displayed headline, or the internal evidence view when its
    # destination cannot be resolved. Background and attention signals never supply this link.
    link = primary_url(s, headline)
    return {"id": s.story_id[:12], "rank": s.rank, "top_rank": top_rank, "category": s.category.value,
            "headline": headline, "url": link if any(x["url"] == link for x in sources) else None,
            "summary": summary, "why_it_matters": s.why_it_matters,
            "change": change, "labels": labels, "newest_published_utc": _utc(newest_published(s)),
            "coverage": {"level": strength.level, "points": strength.points, "independent_reports": strength.independent_reports,
                         "publishers": list(strength.publishers), "repeats": strength.duplicates_collapsed,
                         "source_links": sum(bool(x['url']) for x in sources),
                         "linked_outlets": len({x['outlet_id'] for x in sources if x['kind'] != 'signal' and x['outlet_id']}),
                         "linked_reporting_origins": len({x['reporting_origin'] for x in sources if x['reporting_origin']}),
                         "signals": strength.trend_signals, "channels": strength.channels},
            "sources": sources}


def removed_reports(story: Story) -> list[list[str]]:
    """What identifies a removed story in later revisions: one entry per report (its link and title keys)."""
    return sorted(sorted(keys) for keys in evidence_keys(story))


def is_removed(story: Story, hidden_ids: set[str], hidden_reports: dict[str, list[list[str]]] | None = None) -> bool:
    """Is this story one the user took off the website, by id or as the same story in a later revision?

    The same story = more than half of ITS reports were in a removed story, or more than half of the removed
    story's reports are in it. Either way round: a story that grew from 2 to 6 reports, or the corrected half of
    a mixed story the user removed, stays off the site. Removing too much is the safe side of a correction.
    On October 7 a same-day revision brought back 28 of 144 continuing stories when only ids were kept."""
    if story.story_id[:12] in hidden_ids:
        return True
    if not hidden_reports:
        return False
    mine = evidence_keys(story)
    if not mine:
        return False
    my_keys = set().union(*mine)
    for reports in hidden_reports.values():
        gone = [set(r) for r in reports if r]
        if not gone:
            continue
        gone_keys = set().union(*gone)
        if 2 * sum(bool(r & gone_keys) for r in mine) > len(mine) or 2 * sum(bool(r & my_keys) for r in gone) > len(gone):
            return True
    return False


#: What each kind of source is, for the website's Sources page (plain English; the window has its own notes).
PUBLIC_SOURCE_NOTES = {
    "google_news": "Google News top stories and one Google News section per category.",
    "news_rss": "News publishers' own RSS feeds, listed below by name.",
    "youtube": "New videos from the YouTube channels of news organisations, listed below.",
    "google_trends": "What people in the US are searching for on Google today.",
    "wikipedia": "Wikipedia's most-read articles and its 'In the news' list.",
    "mastodon": "News links people are sharing on Mastodon (mastodon.social).",
    "bluesky": "Topics trending on Bluesky.",
    "reddit": "Top posts of news communities on Reddit (often rate-limited).",
    "x_trends24": "Trending topics on X, as listed by trends24.in.",
    "tiktok": "Trending TikTok hashtags.",
    "hackernews": "The Hacker News front page (technology).",
    "github": "GitHub's trending repositories (technology).",
    "producthunt": "New products on Product Hunt (technology).",
    "arxiv": "New AI and machine-learning papers on arXiv (research).",
}


def public_sources(health: list[SourceHealth]) -> list[dict]:
    """The sources an edition read, for the website's Sources page: each kind of source with how many reports it
    gave and how many the edition cites, and each feed by name and website. Never a feed's full address (a
    private feed's address can carry a key) or its error text."""
    out = []
    for h in health:
        feeds = []
        for f in h.feeds:
            site = (urlsplit(f.url).hostname or "").removeprefix("www.") if f.url.startswith(("http://", "https://")) else ""
            feeds.append({"name": f.name, "site": site, "category": f.category, "status": f.status,
                          "reports": f.collected, "cited": f.used})
        out.append({"type": h.source, "name": h.name, "about": PUBLIC_SOURCE_NOTES.get(h.source, ""),
                    "status": h.status, "reports": h.item_count, "cited": h.used, "feeds": feeds})
    return out


def public_edition(edition: DailyEdition, hidden: list[str] | None = None,
                   hidden_reports: dict[str, list[list[str]]] | None = None, left_out: list[int] | None = None) -> dict:
    """The public copy of an edition (deterministic: the same edition always gives the same bytes).

    A story whose text looks like a path on this PC is left out (its rank goes into ``left_out``) instead of
    stopping the whole edition: one headline about "AppData" used to keep the day off the site (audit F10)."""
    if edition.demo:
        raise PublishError("This is the demo edition (made-up stories); it is never published.")
    hidden_ids = {h[:12] for h in hidden or []}
    hidden_ids |= {s.story_id[:12] for s in edition.stories if is_removed(s, hidden_ids, hidden_reports)}
    local = [s for s in edition.stories
             if s.story_id[:12] not in hidden_ids and
             (looks_local([s.headline, *s.sentences]) or looks_local(_public_story(s, edition, "", None)))]
    hidden_ids |= {s.story_id[:12] for s in local}
    if left_out is not None:
        left_out.extend(s.rank for s in local)
    stories = [s for s in edition.stories if s.story_id[:12] not in hidden_ids]
    if not stories:
        raise PublishError("Every story of this edition was removed from the website; nothing to publish.")
    changes = edition.changes
    change_of = {}
    if changes is not None:
        change_of.update({c.story_id: "updated" for c in changes.updated})
        change_of.update({c.story_id: "new" for c in changes.new})
    top = [s for s in top_stories(edition) if s.story_id[:12] not in hidden_ids]
    top_rank = {s.story_id: i for i, s in enumerate(top, 1)}
    kept = {s.story_id for s in stories}
    public = {
        "schema": PUBLIC_SCHEMA, "schema_version": PUBLIC_SCHEMA_VERSION,
        "app": f"Agent Reach Daily {__version__}",
        "edition_date": edition.edition_date.isoformat(), "revision": edition.revision,
        "timezone": edition.timezone, "generated_utc": _utc(edition.generation_completed_utc),
        "models": {"summaries": edition.model.llm_model, "grouping": edition.model.embed_model_used or None},
        "summaries": edition.model.summaries,
        "reports_read": edition.accounting.ingested,
        "sources_answered": edition.coverage.sources_ok, "sources_tried": edition.coverage.sources_attempted,
        "sources": public_sources(edition.source_health),
        "compared_with": ({"edition_date": changes.compared_edition_date, "revision": changes.compared_revision}
                          if changes is not None else None),
        "top": [s.story_id[:12] for s in top],
        "sections": [{"category": cat, "ids": [s.story_id[:12] for s in group if s.story_id in kept]}
                     for cat, group in category_sections(edition)],
        "stories": [_public_story(s, edition, change_of.get(s.story_id, ""), top_rank.get(s.story_id))
                    for s in stories],
    }
    public["sections"] = [sec for sec in public["sections"] if sec["ids"]]
    if changes is not None:
        public['changes'] = {
            'compared_with': public['compared_with'],
            'new': [c.story_id[:12] for c in changes.new if c.story_id in kept],
            'updated': [c.story_id[:12] for c in changes.updated if c.story_id in kept],
            'fading': [c.story_id[:12] for c in changes.signals_down if c.story_id in kept],
            'dropped': [{'headline': c.headline, 'category': getattr(c, 'category', '')}
                        for c in changes.gone if c.story_id[:12] not in hidden_ids],
        }
    assert_public(public)
    return public


def _dumps(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def edition_page(public: dict, site_url: str = SITE_URL) -> bytes:
    """A complete, escaped edition before any website build or browser JavaScript runs."""
    d = public["edition_date"]
    day = format_long_date(date.fromisoformat(d))
    by_id = {s["id"]: s for s in public["stories"]}
    lead = by_id.get(public["top"][0]) if public["top"] else public["stories"][0]
    title = html.escape(f"Agent Reach Daily: {day}")
    desc = html.escape(f"{lead['headline']}, and {len(public['stories']) - 1} more stories from the {day} edition.",
                       quote=True)
    url = html.escape(f"{site_url.rstrip('/')}/daily/{d}/", quote=True)
    articles = []
    for story in sorted(public["stories"], key=lambda s: s["rank"]):
        headline = html.escape(story["headline"])
        link = safe_url(story.get("url"))
        if link:
            headline = f'<a href="{html.escape(link, quote=True)}">{headline}</a>'
        paragraphs = "".join(f"<p>{html.escape(p)}</p>" for p in story["summary"])
        why = story.get("why_it_matters")
        if why:
            paragraphs += f'<p class="why"><b>Why it matters: </b>{html.escape(why)}</p>'
        sources = []
        for source in story["sources"]:
            label = html.escape(source["title"])
            link = safe_url(source.get("url"))
            if link:
                label = f'<a href="{html.escape(link, quote=True)}" rel="noopener noreferrer">{label}</a>'
            when = html.escape(source.get("published_utc") or "Time not stated")
            outlet = html.escape(source["outlet"])
            kind = html.escape(source["kind"])
            via = ' · Google News redirect' if is_google_news(link) else ''
            sources.append(f"<li>{label}<small>{outlet} · {when} · {kind}{via}</small></li>")
        anchor = html.escape(story["id"], quote=True)
        category = html.escape(story["category"])
        articles.append(
            f'<article class="card" id="story-{anchor}"><span class="kicker">{category}</span>'
            f'<h2 class="hl">{headline}</h2><div class="story-body">{paragraphs}</div>'
            f'<details class="src"><summary>Sources ({len(sources)})</summary><ul>{"".join(sources)}</ul></details>'
            '</article>'
        )
    content = (
        '<header class="wrap page-head"><nav aria-label="Edition navigation">'
        '<a href="/daily/">Latest edition</a> · <a href="/archive/">Browse the archive</a></nav>'
        f'<h1>{title}</h1><p>{len(articles)} stories · Update {int(public["revision"])} · '
        f'Generated <time datetime="{html.escape(public["generated_utc"], quote=True)}">'
        f'{html.escape(public["generated_utc"])}</time></p>'
        '<p>AI-generated summaries from public reporting. Read the sources to check the reporting.</p></header>'
        f'<main id="main" class="wrap"><div class="compact">{"".join(articles)}</div></main>'
    )
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
        f"<title>{title}</title>\n<meta name=\"description\" content=\"{desc}\">\n"
        f"<link rel=\"canonical\" href=\"{url}\">\n"
        f"<meta property=\"og:title\" content=\"{title}\"><meta property=\"og:description\" content=\"{desc}\">"
        f"<meta property=\"og:type\" content=\"article\"><meta property=\"og:url\" content=\"{url}\">\n"
        "<meta name=\"theme-color\" content=\"#121417\">\n"
        "<link rel=\"icon\" href=\"/assets/icon.svg\" type=\"image/svg+xml\">\n"
        "<link rel=\"alternate\" type=\"application/rss+xml\" title=\"Agent Reach Daily\" href=\"/feed.xml\">\n"
        "<link rel=\"stylesheet\" href=\"/assets/site.css\"><script src=\"/assets/site.js\" defer></script>\n"
        "</head>\n"
        f"<body data-page=\"edition\" data-date=\"{d}\">\n<div id=\"app\">\n"
        f"{content}\n"
        "</div>\n</body>\n</html>\n"
    ).encode("utf-8")


def index_entry(public: dict) -> dict:
    by_id = {s["id"]: s for s in public["stories"]}
    lead = by_id.get(public["top"][0]) if public["top"] else public["stories"][0]
    return {"date": public["edition_date"], "revision": public["revision"], "generated_utc": public["generated_utc"],
            "stories": len(public["stories"]), "lead": lead["headline"],
            "headlines": [by_id[i]["headline"] for i in public["top"][1:4] if i in by_id],
            "sections": {sec["category"]: len(sec["ids"]) for sec in public["sections"]}}


def merge_index(current: dict | None, entry: dict | None = None, remove: str | None = None) -> dict:
    """The archive list with ``entry`` added (or replacing its date) and/or ``remove`` taken out, newest first."""
    editions = [e for e in (current or {}).get("editions", []) if isinstance(e, dict) and isinstance(e.get("date"), str)]
    editions = [e for e in editions if e["date"] not in {remove, entry and entry["date"]}]
    if entry is not None:
        editions.append(entry)
    editions.sort(key=lambda e: e["date"], reverse=True)
    return {"schema": INDEX_SCHEMA, "schema_version": 1, "latest": editions[0]["date"] if editions else None,
            "editions": editions}


def _parse_utc(value) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def feed_xml(index: dict, site_url: str = SITE_URL) -> bytes:
    """RSS 2.0, one item per edition (newest first). A later revision of a day keeps the item's link and guid,
    so feed readers update it instead of showing the day twice. Built from the archive list only: no clock, so
    the same list always gives the same bytes (a retry commits nothing)."""
    base = site_url.rstrip("/")
    entries = [e for e in index.get("editions", []) if isinstance(e.get("date"), str)][:FEED_ITEMS]
    stamps = [t for t in (_parse_utc(e.get("generated_utc")) for e in entries) if t]
    items = []
    for e in entries:
        try:
            day = format_long_date(date.fromisoformat(e["date"]))
        except ValueError:
            continue
        link = f"{base}/daily/{e['date']}/"
        heads = [str(e.get("lead") or "")] + [str(x) for x in e.get("headlines") or []]
        desc = (f"Top stories: {'; '.join(h for h in heads if h)}. "
                f"{e.get('stories', 0)} stories in this edition, summarized by a local AI model; read the sources.")
        stamp = _parse_utc(e.get("generated_utc"))
        items.append(
            "<item>"
            f"<title>{xml_escape(f'{day}: {heads[0]}')}</title>"
            f"<link>{xml_escape(link)}</link><guid isPermaLink=\"true\">{xml_escape(link)}</guid>"
            + (f"<pubDate>{format_datetime(stamp, usegmt=True)}</pubDate>" if stamp else "")
            + f"<description>{xml_escape(desc)}</description></item>\n")
    built = f"<lastBuildDate>{format_datetime(max(stamps), usegmt=True)}</lastBuildDate>" if stamps else ""
    return (
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<rss version=\"2.0\" xmlns:atom=\"http://www.w3.org/2005/Atom\"><channel>\n"
        f"<title>Agent Reach Daily</title><link>{xml_escape(base)}/</link>"
        f"<atom:link href=\"{xml_escape(base)}/{FEED_PATH}\" rel=\"self\" type=\"application/rss+xml\"/>"
        "<description>The day's news from public reporting: each event as one story, summarized by a local AI "
        "model, with its sources. Summaries can be wrong; coverage strength is not a fact check.</description>"
        f"<language>en</language>{built}\n" + "".join(items) + "</channel></rss>\n"
    ).encode("utf-8")


def sitemap_xml(index: dict, site_url: str = SITE_URL) -> bytes:
    """The page shells plus one permanent page per published date."""
    base = site_url.rstrip("/")
    urls = [f"<url><loc>{xml_escape(f'{base}/{p}')}</loc></url>" for p in STATIC_PAGES]
    for e in index.get("editions", []):
        if not isinstance(e.get("date"), str):
            continue
        stamp = _parse_utc(e.get("generated_utc"))
        mod = f"<lastmod>{stamp.date().isoformat()}</lastmod>" if stamp else ""
        loc = xml_escape(f"{base}/daily/{e['date']}/")
        urls.append(f"<url><loc>{loc}</loc>{mod}</url>")
    return ("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
            + "\n".join(urls) + "\n</urlset>\n").encode("utf-8")


def index_files(index: dict, site_url: str = SITE_URL) -> dict[str, bytes]:
    """Everything derived from the archive list; committed together with it."""
    return {FEED_PATH: feed_xml(index, site_url), SITEMAP_PATH: sitemap_xml(index, site_url), INDEX_PATH: _dumps(index)}


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return cut + "\u2026"


def search_entries(public: dict) -> list[dict]:
    """The searchable part of each story of a public edition, in edition order."""
    out = []
    for s in sorted(public["stories"], key=lambda x: x["rank"]):
        names: list[str] = []
        for kind in ("report", "repeat", "signal"):
            for src in s["sources"]:
                if src["kind"] == kind and src["outlet"] not in names:
                    names.append(src["outlet"])
        out.append({"d": public["edition_date"], "id": s["id"], "r": s["rank"], "t": s["top_rank"],
                    "c": s["category"], "h": s["headline"], "s": _clip(" ".join(s["summary"]), SEARCH_SUMMARY_CHARS),
                    "o": names[:SEARCH_OUTLETS], "l": s["coverage"]["level"], "coverage": s["coverage"]})
        if s.get("url"):
            out[-1]["u"] = s["url"]
    return out


def search_files(t: "Target", index: dict, d: str, entries: list[dict] | None) -> dict[str, bytes | None]:
    """The search file of ``d``'s month with that date's stories replaced by ``entries`` (None: removed).

    Dates of that month that are in the archive but missing from the file (a file damaged or never written, e.g.
    editions published before search existed) are filled in from their edition files on the site, so the
    search data repairs itself on the next publication. Stories of dates no longer in the archive are dropped."""
    month = d[:7]
    path = search_path(month)
    raw = t.read(path)
    current = _read_json(t, path) if raw is not None else None
    dates = {e["date"] for e in index.get("editions", []) if str(e.get("date", "")).startswith(month)}
    kept = []
    if current and current.get("schema") == SEARCH_SCHEMA and isinstance(current.get("stories"), list):
        kept = [x for x in current["stories"] if isinstance(x, dict) and x.get("d") in dates and x.get("d") != d]
    have = {x["d"] for x in kept}
    for other in sorted(dates - have - {d}):
        pub = _read_json(t, edition_json_path(other))
        if pub and isinstance(pub.get("stories"), list):
            kept += search_entries(pub)
    stories = kept + list(entries or [])
    if not stories:
        return {path: None} if raw is not None else {}
    stories.sort(key=lambda x: (x["d"], -x["r"]), reverse=True)
    return {path: _dumps({"schema": SEARCH_SCHEMA, "schema_version": 1, "month": month, "stories": stories})}


# ====================================================================== targets
class Target:
    """Where the site lives. ``begin`` pins a version, ``read`` reads at it, ``commit`` applies all changes at once."""

    description = ""

    def begin(self) -> None: ...

    def check(self) -> str:
        """Can the site be read? (raises PublishError when not)"""
        self.begin()
        return ""

    def read(self, path: str) -> bytes | None:
        raise NotImplementedError

    def commit(self, changes: dict[str, bytes | None], message: str) -> str:
        raise NotImplementedError

    def close(self) -> None: ...


class FolderTarget(Target):
    """A local copy of the website (preview, tests). The archive list is written last, so the site never lists a
    date whose files are not there yet."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.description = str(self.root)

    def _path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents:
            raise PublishError(f"Refusing to write outside the website folder: {rel}")
        return p

    def read(self, path: str) -> bytes | None:
        try:
            return self._path(path).read_bytes()
        except FileNotFoundError:
            return None

    def commit(self, changes: dict[str, bytes | None], message: str) -> str:
        for rel in sorted(changes, key=lambda r: r == INDEX_PATH):
            data, p = changes[rel], self._path(rel)
            if data is None:
                unlink_with_retry(p)
                try:
                    p.parent.rmdir()
                except OSError:
                    pass
            else:
                atomic_write_bytes(p, data)
                os.chmod(p, 0o644)  # a web page, not a private file
        return "folder"


class GitHubTarget(Target):
    """The website's GitHub repository. One commit per publication; the branch only moves by fast-forward."""

    def __init__(self, repo: str, branch: str, token: str, client=None) -> None:
        import httpx

        self.repo, self.branch = repo, branch
        self.description = f"github.com/{repo} ({branch})"
        self.own_client = client is None  # a client made here is closed here
        self.client = client or httpx.Client(timeout=HTTP_TIMEOUT_S, follow_redirects=True)
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": f"AgentReachDaily/{__version__}"}
        self.head: str | None = None
        self.tree: str | None = None
        self.key_expires: datetime | None = None  # from GitHub's answers (fine-grained keys expire)
        self._files: dict[str, bytes | None] = {}  # what was read at the pinned version (each file read once)

    def _call(self, method: str, path: str, *, ok=(200, 201), allow=(), **kw):
        import httpx

        url = f"{GITHUB_API}/repos/{self.repo}{path}"
        try:
            r = self.client.request(method, url, headers={**self.headers, **kw.pop("headers", {})}, **kw)
        except httpx.HTTPError as exc:
            raise PublishError(f"Could not reach GitHub ({type(exc).__name__}). Is this PC online?") from exc
        self.key_expires = parse_expiry(r.headers.get(EXPIRY_HEADER)) or self.key_expires
        if r.status_code in ok or r.status_code in allow:
            return r
        if r.status_code == 401:
            raise Hopeless("GitHub did not accept the access key (it may have expired or been revoked). "
                               "Paste a new one in Website publishing.")
        if r.status_code in (403, 404):
            raise Hopeless(f"The access key cannot {'read' if method == 'GET' else 'write to'} {self.repo}. "
                               "It needs access to that repository with 'Contents: Read and write'.")
        if r.status_code == 409 or (r.status_code == 422 and path.startswith("/git/refs")):
            raise Conflict("The website changed while publishing.")
        raise PublishError(f"GitHub answered {r.status_code} to {method} {path.split('?')[0]}.")

    def begin(self) -> None:
        ref = self._call("GET", f"/git/ref/heads/{self.branch}").json()
        self.head = ref["object"]["sha"]
        self.tree = self._call("GET", f"/git/commits/{self.head}").json()["tree"]["sha"]
        self._files = {}

    def close(self) -> None:
        if self.own_client:
            self.client.close()

    def check(self) -> str:
        """Read access to the repository and branch (the write permission shows on the first publication)."""
        self.begin()
        return self.head or ""

    def read(self, path: str) -> bytes | None:
        """The file at the pinned version; each file is fetched once per version (the plan and the comparison of
        what changed both read the index and the search month: audit F11)."""
        if path not in self._files:
            self._files[path] = self._fetch(path)
        return self._files[path]

    def _fetch(self, path: str) -> bytes | None:
        r = self._call("GET", f"/contents/{path}?ref={self.head}", allow=(404,))
        if r.status_code == 404:
            return None
        body = r.json()
        if isinstance(body, dict) and body.get("encoding") == "base64" and body.get("content") is not None:
            return base64.b64decode(body["content"])
        if isinstance(body, dict) and body.get("sha"):  # larger than 1 MB: read the blob
            blob = self._call("GET", f"/git/blobs/{body['sha']}").json()
            return base64.b64decode(blob["content"])
        raise PublishError(f"Unexpected answer from GitHub for {path}.")

    def commit(self, changes: dict[str, bytes | None], message: str) -> str:
        tree = []
        for path, data in sorted(changes.items()):
            if data is None:
                tree.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            else:
                blob = self._call("POST", "/git/blobs", json={"content": base64.b64encode(data).decode("ascii"),
                                                                "encoding": "base64"}).json()
                tree.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        new_tree = self._call("POST", "/git/trees", json={"base_tree": self.tree, "tree": tree}).json()["sha"]
        commit = self._call("POST", "/git/commits", json={"message": message, "tree": new_tree,
                                                          "parents": [self.head]}).json()["sha"]
        self._call("PATCH", f"/git/refs/heads/{self.branch}", json={"sha": commit, "force": False})
        return commit


def github_target(paths: DataPaths, settings: PublishSettings | None = None, client=None) -> GitHubTarget:
    settings = settings or load_settings(paths)
    token = load_token(paths)
    if not token:
        raise PublishError("No access key is saved yet. Open Website publishing and paste one (one-time setup).")
    return GitHubTarget(settings.repo, settings.branch, token, client=client)


# ====================================================================== publish / withdraw
@dataclass
class PublishResult:
    state: State
    message: str
    commit: str | None = None
    changed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.state in ("published", "unchanged", "withdrawn", "skipped")


def _read_json(target: Target, path: str) -> dict | None:
    data = target.read(path)
    if data is None:
        return None
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None  # a damaged file on the site is replaced, never trusted
    return obj if isinstance(obj, dict) else None


def site_files(edition: DailyEdition, settings: PublishSettings, current_index: dict | None,
               left_out: list[int] | None = None) -> tuple[dict, dict]:
    """(public edition, {path: bytes}) for one edition."""
    d = edition.edition_date.isoformat()
    public = public_edition(edition, settings.hidden_stories.get(d), settings.hidden_reports.get(d), left_out)
    files = {edition_json_path(d): _dumps(public), edition_page_path(d): edition_page(public, settings.site_url),
             **index_files(merge_index(current_index, index_entry(public)), settings.site_url)}
    return public, files


def _with_target(target: Target, plan, message: str) -> tuple[str | None, list[str]]:
    """Run ``plan(target) -> {path: bytes | None}`` against a pinned version and commit only what differs;
    a branch that moved meanwhile is re-read (fast-forward only, never overwritten)."""
    for attempt in range(COMMIT_ATTEMPTS):
        target.begin()
        wanted = plan(target)
        changes = {p: data for p, data in wanted.items() if target.read(p) != data}
        if not changes:
            return None, []
        try:
            return target.commit(changes, message), sorted(changes)
        except Conflict:
            if attempt == COMMIT_ATTEMPTS - 1:
                raise
            log.info("site branch moved during publishing; retrying")
    raise PublishError("The website kept changing while publishing.")  # not reached


def publish_edition(paths: DataPaths, edition: DailyEdition, target: Target | None = None, *,
                    settings: PublishSettings | None = None, automatic: bool = False) -> PublishResult:
    """Publish one edition. Never raises: problems are returned and recorded; the site keeps what it had."""
    settings = settings or load_settings(paths)
    d = edition.edition_date.isoformat()
    label = f"{format_long_date(edition.edition_date)}" + (f" (revision {edition.revision})" if edition.revision > 1 else "")
    if automatic and settings.withdrawn.get(d, 0) >= edition.revision:
        return PublishResult("skipped", f"Not published: you took the {label} edition off the website.")
    lock = RefreshLock(_dir(paths) / "publish.lock")
    try:
        _dir(paths).mkdir(parents=True, exist_ok=True)
        lock.acquire()
    except LockBusy:
        return PublishResult("skipped", "Another publication is already running.")
    except OSError as exc:
        return PublishResult("failed", f"Publication failed: the publishing folder is not writable ({exc}).")
    try:
        _record(paths, state="publishing", message=f"Publishing the {label} edition", attempt_utc=utcnow())
        again = " The app tries again at its next hourly check." if automatic and settings.enabled else ""
        published: dict = {}

        def plan(t: Target) -> dict:
            current = _read_json(t, INDEX_PATH)
            on_site = next((e for e in (current or {}).get("editions", []) if e.get("date") == d), None)
            if on_site and int(on_site.get("revision") or 0) > edition.revision:
                raise Hopeless(f"The website already has a newer revision ({on_site['revision']}) of the {label} "
                                   "edition; nothing was changed.")
            left_out: list[int] = []
            public, files = site_files(edition, settings, current, left_out)
            published["public"], published["left_out"] = public, left_out
            files.update(search_files(t, merge_index(current, index_entry(public)), d, search_entries(public)))
            return files

        own = target is None
        try:
            target = target or github_target(paths, settings)
            try:
                commit, changed = _with_target(target, plan, f"Publish the {d} edition (revision {edition.revision})")
            finally:
                _note_key(paths, target)
                if own:
                    target.close()
        except Hopeless as exc:
            msg = f"Publication failed: {exc} The website still shows the previous edition."
            _record(paths, state="failed", message=msg, failed_action="publish", blocked_on=f"{d}#{edition.revision}")
            return PublishResult("failed", msg)
        except PublishError as exc:
            msg = f"Publication failed: {exc} The website still shows the previous edition.{again}"
            _record(paths, state="failed", message=msg, failed_action="publish", blocked_on=None)
            return PublishResult("failed", msg)
        except Exception as exc:  # noqa: BLE001 - a bug here must never break a refresh
            log.exception("publishing failed unexpectedly")
            msg = (f"Publication failed ({type(exc).__name__}). The website still shows the previous edition. "
                   f"Details are in the refresh log.{again}")
            _record(paths, state="failed", message=msg, failed_action="publish")
            return PublishResult("failed", msg)
        if d in settings.withdrawn:
            settings = load_settings(paths)
            if settings.withdrawn.pop(d, None) is not None:
                save_settings(paths, settings)
        stories = len(published["public"]["stories"])
        now = utcnow()
        if commit is None:
            msg = f"The website already has the {label} edition ({stories} stories)."
            _record(paths, state="unchanged", message=msg, success_utc=load_status(paths).success_utc or now,
                    failed_action=None, blocked_on=None,
                    edition_date=d, revision=edition.revision, stories=stories)
            return PublishResult("unchanged", msg)
        msg = (f"Published successfully: the {label} edition ({stories} stories) at {format_central(now)}. "
               "The website shows it within a few minutes.")
        if published["left_out"]:
            msg += (f" Left out: story {', '.join(str(r) for r in published['left_out'])}, because its text looks like "
                    "a file path on this computer. Please report this.")
        _record(paths, state="published", message=msg, success_utc=now, edition_date=d, revision=edition.revision,
                failed_action=None, blocked_on=None,
                stories=stories, commit=commit)
        log.info("published %s r%d to %s: %s", d, edition.revision, target.description, ", ".join(changed))
        return PublishResult("published", msg, commit, changed)
    finally:
        lock.release()


def withdraw(paths: DataPaths, d: str, target: Target | None = None) -> PublishResult:
    """Take one date's edition off the website (the archive and /daily/ then show the next newest date)."""
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise ValueError(d)
        date.fromisoformat(d)  # the date names the files to delete: never anything else (audit F13)
    except ValueError:
        return PublishResult("failed", f"'{d}' is not a date (YYYY-MM-DD); nothing was changed.")
    settings = load_settings(paths)
    lock = RefreshLock(_dir(paths) / "publish.lock")
    try:
        _dir(paths).mkdir(parents=True, exist_ok=True)
        lock.acquire()
    except LockBusy:
        return PublishResult("skipped", "Another publication is running; try again in a minute.")
    try:
        def plan(t: Target) -> dict:
            index = merge_index(_read_json(t, INDEX_PATH), remove=d)
            files: dict[str, bytes | None] = dict(index_files(index, settings.site_url))
            files.update(search_files(t, index, d, None))
            for p in (edition_json_path(d), edition_page_path(d)):
                if t.read(p) is not None:
                    files[p] = None
            return files

        try:
            own = target is None
            target = target or github_target(paths, settings)
            try:
                on_site = _read_json_at(target, d)
                commit, _ = _with_target(target, plan, f"Withdraw the {d} edition")
            finally:
                _note_key(paths, target)
                if own:
                    target.close()
        except PublishError as exc:
            msg = f"Could not take the edition off the website: {exc}"
            _record(paths, state="failed", message=msg, attempt_utc=utcnow(), failed_action="withdraw")
            return PublishResult("failed", msg)
        settings = load_settings(paths)
        settings.withdrawn[d] = max(int(on_site or 0), settings.withdrawn.get(d, 0), 1)
        save_settings(paths, settings)
        day = format_long_date(date.fromisoformat(d))
        msg = (f"The {day} edition was taken off the website." if commit else
               f"The website did not have the {day} edition.")
        _record(paths, state="withdrawn", message=msg, attempt_utc=utcnow(), failed_action=None)
        return PublishResult("withdrawn", msg, commit)
    finally:
        lock.release()


def _note_key(paths: DataPaths, target: Target) -> None:
    """Record the key's expiry as GitHub stated it (a folder target states none)."""
    expires = getattr(target, "key_expires", None)
    if expires is not None:
        _record(paths, key_expires_utc=expires)


def check_connection(paths: DataPaths) -> str:
    """The window's 'Test connection': read access to the site's branch (raises PublishError); notes the expiry."""
    target = github_target(paths)
    try:
        return target.check()
    finally:
        _note_key(paths, target)
        target.close()


def connected_message(paths: DataPaths) -> str:
    """What the window says after a successful connection test. A failure recorded before the test stays visible:
    on the PC (Oct 8) the window said "Connected" under a red "Publication failed" with no reason given."""
    msg = (f"Connected: the key can read {load_settings(paths).repo}. Write access is confirmed by the first "
           "publication.")
    status = load_status(paths)
    if status.state == "failed" and status.message:
        msg += (f" The red line above is the last attempt, made before this test: {status.message} "
                "Click Publish latest edition to try again.")
    return msg


def _read_json_at(target: Target, d: str) -> int | None:
    """Revision of date ``d`` on the site, if any."""
    target.begin()
    current = _read_json(target, INDEX_PATH) or {}
    entry = next((e for e in current.get("editions", []) if e.get("date") == d), None)
    return int(entry.get("revision") or 0) if entry else None


def hide_story(paths: DataPaths, edition: DailyEdition, story_id: str, target: Target | None = None) -> PublishResult:
    """Remove one story from the public copy of this edition and republish it (a correction). Later revisions of
    the same date leave it out too, recognised by its reports (``is_removed``)."""
    settings = load_settings(paths)
    d = edition.edition_date.isoformat()
    hidden = settings.hidden_stories.setdefault(d, [])
    if story_id[:12] not in hidden:
        hidden.append(story_id[:12])
    story = next((s for s in edition.stories if s.story_id[:12] == story_id[:12]), None)
    if story is not None:
        settings.hidden_reports.setdefault(d, {})[story_id[:12]] = removed_reports(story)
    save_settings(paths, settings)
    return publish_edition(paths, edition, target, settings=settings)


def publish_latest(paths: DataPaths, target: Target | None = None, *, automatic: bool = False) -> PublishResult:
    from agent_reach.daily.store import EditionStore

    edition = EditionStore(paths).load_latest().edition
    if edition is None:
        return PublishResult("failed", "There is no edition to publish yet. Refresh first.")
    return publish_edition(paths, edition, target, automatic=automatic)


def publish_after_refresh(paths: DataPaths, edition: DailyEdition) -> PublishResult | None:
    """The refresh worker's hook: None when automatic publishing is off; never raises."""
    try:
        settings = load_settings(paths)
        if not settings.enabled:
            return None
        if not has_token(paths):
            msg = "Publication failed: no access key is saved. The website still shows the previous edition."
            _record(paths, state="failed", message=msg, attempt_utc=utcnow(), failed_action="publish")
            return PublishResult("failed", msg)
        result = publish_edition(paths, edition, settings=settings, automatic=True)
        warning = key_warning(load_status(paths).key_expires_utc)
        if warning:
            result.message = f"{result.message} {warning}"
        return result
    except (OSError, FileUnavailable) as exc:
        log.exception("publishing could not start")
        return PublishResult("failed", f"Publication failed ({type(exc).__name__}); the website was not changed.")


def catch_up(paths: DataPaths, now: datetime | None = None) -> PublishResult | None:
    """The hourly scheduled check, when no refresh is due: publish the latest edition if automatic publishing is
    on and the website did not get it (the last publication failed, was interrupted, or never ran).

    Before rc15 a failed upload waited for the next refresh, 24 hours later by default (audit F2, Oct 8). Tried at
    most once per ``CATCH_UP_MINUTES``; a withdrawn date stays withdrawn; a failed withdrawal is not turned into a
    publication. None when there is nothing to do (no network call). Never raises."""
    try:
        settings = load_settings(paths)
        if not settings.enabled or not has_token(paths):
            return None
        status = load_status(paths)
        if status.state == "failed" and status.failed_action == "withdraw":
            return None  # the user's withdrawal failed: the window says so; republishing would undo their intent
        now = now or utcnow()
        if status.attempt_utc is not None and (now - status.attempt_utc).total_seconds() < CATCH_UP_MINUTES * 60:
            return None
        from agent_reach.daily.store import EditionStore

        edition = EditionStore(paths).load_latest().edition
        if edition is None or edition.demo:
            return None
        d = edition.edition_date.isoformat()
        if settings.withdrawn.get(d, 0) >= edition.revision:
            return None
        if status.state == "failed" and status.blocked_on == f"{d}#{edition.revision}":
            return None  # a refused key or a newer revision on the site: retrying the same edition cannot help
        sent = status.state in ("published", "unchanged") and status.edition_date is not None
        if sent and (status.edition_date, status.revision or 0) >= (d, edition.revision):
            return None  # the website has this edition (or a newer one) from this PC
        log.info("website catch-up: publishing the %s edition (revision %d); last publication: %s", d,
                 edition.revision, status.state)
        return publish_edition(paths, edition, settings=settings, automatic=True)
    except Exception as exc:  # noqa: BLE001 - the scheduled check must end quietly whatever happens here
        log.exception("website catch-up failed")
        return PublishResult("failed", f"Publication failed ({type(exc).__name__}); the website was not changed.")


# ====================================================================== what the window shows
def live_edition(site_url: str = SITE_URL, client=None) -> tuple[str | None, int | None]:
    """(date, revision) of the newest edition the live website serves, or (None, None) if it cannot be read."""
    import httpx

    try:
        c = client or httpx.Client(timeout=10.0, follow_redirects=True)
        r = c.get(f"{site_url.rstrip('/')}/{INDEX_PATH}", params={"t": int(utcnow().timestamp())},
                  headers={"Cache-Control": "no-cache", "User-Agent": f"AgentReachDaily/{__version__}"})
        if client is None:
            c.close()
        body = r.json() if r.status_code == 200 else {}
        latest = body.get("latest")
        entry = next((e for e in body.get("editions", []) if e.get("date") == latest), {})
        return latest, entry.get("revision")
    except Exception:  # noqa: BLE001 - offline, blocked or not JSON: unknown
        return None, None


def status_lines(paths: DataPaths) -> dict:
    """Plain-English publishing state for the window: headline, detail, colour key."""
    settings, status = load_settings(paths), load_status(paths)
    connected = has_token(paths)
    if status.state == "publishing":
        head, kind = "Publishing", "refreshing"
    elif status.state == "failed":
        head, kind = "Publication failed: previous edition preserved", "failed"
    elif status.state in ("published", "unchanged") and status.edition_date:
        head, kind = "Published successfully", "current"
    elif status.state == "withdrawn":
        head, kind = "Edition taken off the website", "stale"
    elif connected:
        head, kind = "Ready to publish", "empty"
    else:
        head, kind = "Not set up: paste an access key below (one time)", "empty"
    last = "Nothing published from this PC yet."
    if status.edition_date and status.success_utc:
        day = format_long_date(date.fromisoformat(status.edition_date))
        rev = f" (revision {status.revision})" if status.revision and status.revision > 1 else ""
        last = f"{day}{rev}, {status.stories or 0} stories, sent {format_central(status.success_utc)}"
    return {"headline": head, "kind": kind, "message": status.message, "last_published": last,
            "automatic": settings.enabled, "connected": connected, "site_url": settings.site_url,
            "repo": settings.repo, "branch": settings.branch,
            "key_warning": key_warning(status.key_expires_utc) if connected else ""}
