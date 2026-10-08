"""Event registry: one stable identity per real-world event across editions and days (PLAN Phase 2.3-2.4).

A story is one edition's account of an event; its ``story_id`` changes whenever its evidence changes. The
registry keeps the EVENT: a stable id, when it was first and last seen, the reports (article URLs and titles)
and key names it was built from, and every appearance with how confidently it was matched and why.

Matching a new edition (``match_edition``) is deterministic and explainable. For each story, every event seen
in the last ``WINDOW_DAYS`` is a candidate, scored on three kinds of evidence:

* **shared reports**: the story's reports (article URL, or normalized title) already in the event. Counted as a
  share of the STORY's reports, never as a raw count: on October 7 one shared report out of six continued
  a story that a previous edition had mixed up (Cornell's Sally Yates review inside the Maine Senate debate;
  Trump's golf-club "retreat" inside the forces' retreat).
* **wording**: tf-idf cosine of headline, summary and report titles (stems of 5 letters, rare words weigh
  most). This finds the same event told by new articles hours later (Apple + LG smart home, Decisions API).
* **key names**: shared people, places, organisations. Never enough alone: OpenAI's EU watermark and its teen
  usage report share every name and are two events.

Tiers (``Decision.tier``): ``reports`` (most of the story's reports are the event's, and the wording agrees),
``wording`` (strong wording agreement plus a shared name or two rare shared words), else no match. When a
second candidate scores close to the best (``AMBIGUOUS_MARGIN``), the story is NOT matched: it opens a new event
and records the candidates (``Decision.ambiguous``). A false split is cheaper than a false merge.

The LLM is never involved (invariant 2). Nothing here changes an edition: the registry only observes.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from agent_reach.daily.edition import DailyEdition, Story
from agent_reach.pipeline.cleaner import dedupe_key, significant_tokens

REGISTRY_SCHEMA = "agent_reach.event_registry"
REGISTRY_VERSION = 1
WINDOW_DAYS = 7  # events not seen for this long are no longer candidates
KEEP_DAYS = 30  # and are dropped from the file after this long
MAX_REPORTS = 300
MAX_TOKENS = 120
MAX_APPEARANCES = 60

# thresholds (chosen on the October 7 development pairs, PLAN 2.4; see tests/cross_edition.py)
REPORTS_SHARE = 0.5  # more than this share of the story's reports already in the event
REPORTS_MIN_WORDING = 0.12  # ... and the wording must not disagree
WORDING_MIN = 0.32  # wording alone: cosine
WORDING_STRONG = 0.45  # wording alone with a shared name or rare words
RARE_IDF = 3.0  # a word in at most ~5% of the documents
AMBIGUOUS_MARGIN = 0.9  # a second candidate within 90% of the best score: do not decide


# ====================================================================== model
class Appearance(BaseModel):
    edition_date: str
    revision: int
    seen_utc: datetime
    story_id: str
    rank: int
    headline: str
    tier: str  # "new" | "reports" | "wording"
    confidence: float
    reason: str
    ambiguous_with: list[str] = Field(default_factory=list)


class Event(BaseModel):
    event_id: str
    first_seen_utc: datetime
    last_seen_utc: datetime
    headline: str
    category: str
    reports: list[str] = Field(default_factory=list)  # report keys (URL or 't:' + normalized title), newest last
    names: dict[str, int] = Field(default_factory=dict)  # key name (lowercase) -> appearances
    tokens: dict[str, float] = Field(default_factory=dict)  # stem -> weight (decays with each appearance)
    appearances: list[Appearance] = Field(default_factory=list)


class Registry(BaseModel):
    schema_: str = Field(default=REGISTRY_SCHEMA, alias="schema")
    version: int = REGISTRY_VERSION
    events: dict[str, Event] = Field(default_factory=dict)
    # run ids of the editions already applied: applying an edition twice changes nothing
    applied: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


# ====================================================================== story features
_STEM = 5


def _stems(text: str) -> list[str]:
    return [t[:_STEM] for t in significant_tokens(dedupe_key(text))]


def evidence_keys(story: Story) -> list[frozenset[str]]:
    """One entry per report: its article URL and its normalized title (either one identifies it)."""
    out: dict[frozenset[str], None] = {}
    for e in story.evidence:
        keys = {"t:" + dedupe_key(e.title)} if e.title else set()
        if e.url:
            keys.add("u:" + e.url.split("#")[0])
        if keys:
            out[frozenset(keys)] = None
    return list(out)


def report_keys(story: Story) -> set[str]:
    return set().union(*evidence_keys(story)) if story.evidence else set()


def story_tokens(story: Story) -> Counter:
    c: Counter = Counter()
    for t in _stems(story.headline):
        c[t] += 2.0
    for sentence in story.sentences:
        for t in set(_stems(sentence)):
            c[t] += 1.0
    for e in story.evidence[:12]:
        for t in set(_stems(e.title)):
            c[t] += 0.5
    return c


def story_names(story: Story) -> set[str]:
    return {n.lower().strip() for n in story.entities if n.strip()}


@dataclass
class _Doc:
    tokens: Counter
    reports: list[frozenset[str]]
    names: set[str]


def _cosine(a: dict, b: dict, idf: dict[str, float]) -> float:
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    dot = sum(a[t] * b[t] * idf.get(t, 1.0) ** 2 for t in shared)
    na = math.sqrt(sum((w * idf.get(t, 1.0)) ** 2 for t, w in a.items()))
    nb = math.sqrt(sum((w * idf.get(t, 1.0)) ** 2 for t, w in b.items()))
    return dot / (na * nb) if na and nb else 0.0


# ====================================================================== matching
@dataclass
class Decision:
    rank: int
    event_id: str | None  # None: a new event
    tier: str  # "reports" | "wording" | "new"
    confidence: float
    reason: str
    ambiguous: list[str] = field(default_factory=list)  # candidate event ids when undecided


@dataclass
class _Candidate:
    event_id: str
    tier: str
    score: float
    reason: str


def _score(doc: _Doc, ev: Event, idf: dict[str, float]) -> _Candidate | None:
    known = set(ev.reports)
    shared_n = sum(1 for keys in doc.reports if keys & known)
    share = shared_n / max(1, len(doc.reports))
    wording = _cosine(doc.tokens, ev.tokens, idf)
    names = doc.names & set(ev.names)
    # rare shared words that are not part of a shared name: what happened, not only who (Oct 7: two Eagles
    # opinion pieces, and Meta Muse's review vs its iPad launch, shared only their names)
    name_stems = {t for n in names for t in _stems(n)}
    rare = [t for t in set(doc.tokens) & set(ev.tokens) if idf.get(t, 0.0) >= RARE_IDF and t not in name_stems]
    if share > REPORTS_SHARE and wording >= REPORTS_MIN_WORDING:
        return _Candidate(ev.event_id, "reports", 1.0 + share + wording,
                          f"{shared_n} of the story's reports are this event's ({share:.0%}); wording {wording:.2f}")
    if rare and (wording >= WORDING_STRONG and (names or len(rare) >= 2)
                 or wording >= WORDING_MIN and names and len(rare) >= 2):
        why = [f"wording {wording:.2f}"]
        if names:
            why.append("shared names: " + ", ".join(sorted(names)[:3]))
        if rare:
            why.append("rare shared words: " + ", ".join(sorted(rare)[:4]))
        return _Candidate(ev.event_id, "wording", wording, "; ".join(why))
    return None


def _idf(docs: list[dict]) -> dict[str, float]:
    df: Counter = Counter()
    for d in docs:
        df.update(set(d))
    n = len(docs) + 1
    return {t: math.log(n / (c + 0.5)) for t, c in df.items()}


def candidates_for(registry: Registry, when: datetime) -> list[Event]:
    cutoff = when - timedelta(days=WINDOW_DAYS)
    return [e for e in registry.events.values() if e.last_seen_utc >= cutoff]


def match_edition(registry: Registry, edition: DailyEdition) -> list[Decision]:
    """Which registry event each story of ``edition`` continues (pure; the registry is not changed)."""
    when = edition.generation_completed_utc
    events = candidates_for(registry, when)
    docs = {s.rank: _Doc(story_tokens(s), evidence_keys(s), story_names(s)) for s in edition.stories}
    idf = _idf([d.tokens for d in docs.values()] + [e.tokens for e in events])
    proposals: list[tuple[float, int, _Candidate, list[_Candidate]]] = []
    decisions: dict[int, Decision] = {}
    for s in edition.stories:
        scored = sorted((c for c in (_score(docs[s.rank], e, idf) for e in events) if c),
                        key=lambda c: (-(c.tier == "reports"), -c.score, c.event_id))
        if not scored:
            decisions[s.rank] = Decision(s.rank, None, "new", 1.0, "no earlier event shares its reports or wording")
            continue
        best = scored[0]
        close = [c for c in scored[1:] if c.tier == best.tier and c.score >= best.score * AMBIGUOUS_MARGIN]
        if close:
            decisions[s.rank] = Decision(s.rank, None, "new", 0.5,
                                         f"undecided between {len(close) + 1} earlier events; kept apart",
                                         [best.event_id] + [c.event_id for c in close])
            continue
        proposals.append((best.score, s.rank, best, scored))
    # one story per event, best evidence first; a second story of the same edition may continue the same event
    # only on its reports (one event told twice in one edition: Messi's farewell as #15 and #37 on Oct 7)
    taken: set[str] = set()
    for _, rank, best, scored in sorted(proposals, key=lambda p: (-(p[2].tier == "reports"), -p[0], p[1])):
        choice = best if best.tier == "reports" or best.event_id not in taken else None
        if choice is None:
            decisions[rank] = Decision(rank, None, "new", 0.6,
                                       "its best match was already continued by a story with stronger evidence")
            continue
        taken.add(choice.event_id)
        confidence = 0.95 if choice.tier == "reports" else round(min(0.9, 0.5 + choice.score), 2)
        decisions[rank] = Decision(rank, choice.event_id, choice.tier, confidence, choice.reason)
    return [decisions[s.rank] for s in edition.stories]


# ====================================================================== updating
def _event_id(edition: DailyEdition, story: Story) -> str:
    digest = hashlib.sha1(f"{edition.run_id}|{story.story_id}".encode()).hexdigest()
    return f"ev-{edition.edition_date:%Y%m%d}-{digest[:8]}"


def apply_edition(registry: Registry, edition: DailyEdition,
                  decisions: list[Decision] | None = None) -> list[Decision]:
    """Record ``edition`` in the registry (in place) and return the decisions. Applying the same edition
    revision again changes nothing (a retry, or the app reading an edition it already recorded)."""
    key = edition.run_id or f"{edition.edition_date}#{edition.revision}"
    if key in registry.applied:
        return []
    if edition.demo:
        return []
    decisions = decisions if decisions is not None else match_edition(registry, edition)
    when = edition.generation_completed_utc
    by_rank = {s.rank: s for s in edition.stories}
    for d in decisions:
        s = by_rank[d.rank]
        if d.event_id is None or d.event_id not in registry.events:
            ev = Event(event_id=_event_id(edition, s), first_seen_utc=when, last_seen_utc=when,
                       headline=s.headline, category=s.category.value)
            registry.events[ev.event_id] = ev
            d.event_id = ev.event_id
        ev = registry.events[d.event_id]
        ev.last_seen_utc = max(ev.last_seen_utc, when)
        ev.headline, ev.category = s.headline, s.category.value
        ev.reports = (ev.reports + sorted(report_keys(s) - set(ev.reports)))[-MAX_REPORTS:]
        for n in story_names(s):
            ev.names[n] = ev.names.get(n, 0) + 1
        merged = {t: w * 0.7 for t, w in ev.tokens.items()}  # older wording fades, newer counts more
        for t, w in story_tokens(s).items():
            merged[t] = merged.get(t, 0.0) + w
        ev.tokens = dict(sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_TOKENS])
        ev.appearances = (ev.appearances + [Appearance(
            edition_date=edition.edition_date.isoformat(), revision=edition.revision, seen_utc=when,
            story_id=s.story_id, rank=s.rank, headline=s.headline, tier=d.tier, confidence=d.confidence,
            reason=d.reason, ambiguous_with=d.ambiguous)])[-MAX_APPEARANCES:]
    registry.applied = (registry.applied + [key])[-400:]
    cutoff = when - timedelta(days=KEEP_DAYS)
    registry.events = {k: e for k, e in registry.events.items() if e.last_seen_utc >= cutoff}
    return decisions


# ====================================================================== file
def registry_file(paths) -> Path:
    """``state/events.json`` in the data folder (``paths``: a DataPaths)."""
    return paths.state_dir / "events.json"


def load_registry(path: Path) -> Registry:
    """The saved registry, or an empty one when there is none. A damaged file raises (the caller decides)."""
    if not path.exists():
        return Registry()
    return Registry.model_validate_json(path.read_text(encoding="utf-8"))


def save_registry(path: Path, registry: Registry) -> None:
    from agent_reach.daily.fsutil import atomic_write_text

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, registry.model_dump_json(by_alias=True, indent=1))


_ID_RX = re.compile(r"^ev-\d{8}-[0-9a-f]{8}$")


def is_event_id(value: str) -> bool:
    return bool(_ID_RX.match(value))


def record_edition(paths, edition: DailyEdition) -> list[Decision] | None:
    """Record a published edition in the registry file. Called by the refresh worker (the lock holder) after
    the edition is saved; it only observes, so any problem is logged and never fails the refresh. A damaged
    registry is set aside (``events.json.damaged``) and a new one started: it is rebuilt from the next editions."""
    import logging

    from pydantic import ValidationError

    from agent_reach.daily.fsutil import FileUnavailable

    log = logging.getLogger(__name__)
    path = registry_file(paths)
    try:
        try:
            registry = load_registry(path)
        except (ValidationError, ValueError, UnicodeDecodeError):
            log.warning("event registry %s is damaged; starting a new one", path)
            path.replace(path.with_name(path.name + ".damaged"))
            registry = Registry()
        decisions = apply_edition(registry, edition)
        if decisions:
            save_registry(path, registry)
            kept = sum(d.tier != "new" for d in decisions)
            undecided = sum(bool(d.ambiguous) for d in decisions)
            log.info("event registry: %d stories, %d continue earlier events, %d undecided (kept apart); %d events",
                     len(decisions), kept, undecided, len(registry.events))
        return decisions
    except FileUnavailable:
        log.warning("event registry is open in another program; this edition is not recorded")
    except Exception:  # noqa: BLE001 - observing must never break a refresh
        log.exception("event registry could not record the edition")
    return None
