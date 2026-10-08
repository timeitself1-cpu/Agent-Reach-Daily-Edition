"""Event identity ACROSS editions: a labelled answer key and the churn report (PLAN Phase 2, step 2.1).

The answer key covers the twelve real editions of October 7, 2026 (05:05 to 23:34 UTC, rc11 to rc12d):
which stories of different editions report the same real-world event. It is built, not typed, so it can
be audited (``tests/fixtures/real/cross_edition_gold.json`` holds only the rules):

1. Every report already has a gold event inside its own edition (``event_corpus.load_edition``, which
   applies the per-edition splits of ``event_gold.json``). A story's event is the event of most of its
   reports.
2. Two editions' events are the same when they share a report (same article URL or same normalized
   title). Roundups and bare hashtags are 'unassigned' and link nothing.
3. Hand-checked rules on top: ``force`` gives the stories whose headline starts with one of the prefixes
   their own event (a shared report had joined two different events: HP's RTX Spark leak and Microsoft's
   Surface launch), ``join`` joins events that share no report but are one occurrence (Apple + LG
   smart-home devices, worded differently by two outlets), ``related`` marks different occurrences of one
   ongoing topic (France's stun-grenade halt and the school-funding protests): matching them is not
   scored either way.

Same event = the same real-world occurrence, including follow-up coverage of it (experts' concerns about
OpenAI's math proofs); a new occurrence in an ongoing topic (a government reacts with a ban, a new
lawsuit, another day's protest) is ``related``.

``python -m tests.cross_edition`` prints the churn report: for consecutive editions and for editions six or
more hours apart, how well the app's current matcher (``changes._match`` as used by ``compare_editions``)
finds the previous story of the same event, and how many Top Stories survive into the next edition.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

from agent_reach.daily.edition import DailyEdition
from agent_reach.pipeline.cleaner import dedupe_key
from tests.event_corpus import FIXTURES, load_edition

#: in time order (generation start, UTC)
EDITIONS = ("2026-10-07-selftest-r1.json", "2026-10-07-selftest-r2.json", "2026-10-07-selftest2-r1.json",
            "2026-10-07-selftest2-r2.json", "2026-10-07-rc12-r1.json", "2026-10-07-rc12-r2.json",
            "2026-10-07-rc12c-r1.json", "2026-10-07-rc12c-r2.json", "2026-10-07-rc12d-r1.json",
            "2026-10-07-rc12d-r2.json", "2026-10-07-rc12d2-r1.json", "2026-10-07-rc12d2-r2.json")
GOLD_FILE = FIXTURES / "cross_edition_gold.json"
FAR_HOURS = 6.0


def short(name: str) -> str:
    return name.removeprefix("2026-10-07-").removesuffix(".json")


@lru_cache(maxsize=None)
def edition(name: str) -> DailyEdition:
    return DailyEdition.model_validate(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


@dataclass
class Gold:
    event: dict[str, str]  # "selftest-r1#4" -> event id
    related: set[frozenset[str]] = field(default_factory=set)
    headline: dict[str, str] = field(default_factory=dict)

    def same(self, a: str, b: str) -> bool | None:
        """True: one event; False: different events; None: related (not scored) or unlabelled."""
        ea, eb = self.event.get(a), self.event.get(b)
        if ea is None or eb is None:
            return None
        if ea == eb:
            return True
        return None if frozenset((ea, eb)) in self.related else False

    def events_of(self, name: str) -> set[str]:
        key = short(name) + "#"
        return {e for k, e in self.event.items() if k.startswith(key)}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]


@lru_cache(maxsize=1)
def load_gold() -> Gold:
    rules = json.loads(GOLD_FILE.read_text(encoding="utf-8"))
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b) -> None:
        parent[find(a)] = find(b)

    story_event: dict[str, tuple] = {}
    headline: dict[str, str] = {}
    by_report: dict[str, set] = defaultdict(set)
    first_id = 1
    for name in EDITIONS:
        heads = {f"{name}#{s.rank}": s.headline for s in edition(name).stories}
        per_story: dict[str, Counter] = defaultdict(Counter)
        for c in load_edition(name, first_id):
            if c.gold is None:
                continue
            local = (name, c.gold)
            find(local)
            per_story[c.recorded][local] += 1
            for url in c.item.merged_urls or ([c.item.url] if c.item.url else []):
                by_report["u:" + url.split("#")[0]].add(local)
            by_report["t:" + dedupe_key(c.item.normalized_title)].add(local)
        first_id += 10_000
        for rec, counts in per_story.items():
            key = f"{short(name)}#{rec.split('#')[1]}"
            story_event[key] = counts.most_common(1)[0][0]
            headline[key] = heads[rec]
    for locals_ in by_report.values():
        locals_ = sorted(locals_)
        for other in locals_[1:]:
            union(locals_[0], other)

    def prefixed(prefixes) -> list[str]:
        return [k for k, h in headline.items() if any(h.startswith(p) for p in prefixes)]

    forced: dict[str, str] = {}
    for event_id, prefixes in rules["force"].items():
        keys = prefixed(prefixes)
        assert keys, f"cross_edition_gold.json: no story starts with {prefixes}"
        for k in keys:
            forced[k] = event_id
    roots = {k: (forced[k] if k in forced else find(story_event[k])) for k in story_event}
    for prefixes in rules["join"]:
        keys = prefixed(prefixes)
        assert len({roots[k] for k in keys}) >= 2, f"cross_edition_gold.json: join {prefixes} joins nothing"
        target = roots[keys[0]]
        for k in keys:
            old = roots[k]
            for j, r in roots.items():
                if r == old:
                    roots[j] = target
    # readable ids: a forced id, or the slug of the earliest headline of the event
    names: dict = {}
    for k in story_event:  # dict order = time order
        names.setdefault(roots[k], roots[k] if isinstance(roots[k], str) else _slug(headline[k]))
    events = {k: names[roots[k]] for k in story_event}
    related = set()
    for a, b in rules["related"]:
        ea = {events[k] for k in prefixed([a])}
        eb = {events[k] for k in prefixed([b])}
        assert ea and eb, f"cross_edition_gold.json: related {a!r} / {b!r} names no story"
        related |= {frozenset((x, y)) for x in ea for y in eb if x != y}
    return Gold(events, related, headline)


# ---------------------------------------------------------------------------------------------------- scoring
# Three independent measurements (the user, Oct 8: "separate event-matching accuracy from top-story selection
# and publishing churn"):
#   matching    is the matcher right about which earlier story continues? (depends on the matcher only)
#   carry-over  how many of the earlier edition's events are in the later edition at all (the answer key only:
#               the pipeline's collection and selection, whatever the matcher does)
#   top stories how many of the earlier Top Stories are again Top Stories, or still listed (selection only)
@dataclass
class MatchScore:
    pairs: int = 0
    continuing: int = 0  # stories of the later edition whose event was in the earlier one
    correct: int = 0  # matched to a story of the same event
    wrong: int = 0  # matched to a story of a different (not related) event: a false continuation
    missed: int = 0  # continuing, but reported as new (or matched wrongly)
    new_right: int = 0  # really new, reported as new
    wrong_examples: list = field(default_factory=list)
    missed_examples: list = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.correct / max(1, self.correct + self.wrong)

    @property
    def recall(self) -> float:
        return self.correct / max(1, self.continuing)

    def line(self) -> str:
        return (f"{self.pairs:3d} pairs  continuing {self.continuing:4d}  matched right {self.correct:4d}  "
                f"wrong {self.wrong:3d}  missed {self.missed:3d}  precision {self.precision:.3f}  recall {self.recall:.3f}")


@dataclass
class ChurnScore:
    pairs: int = 0
    events_before: int = 0
    events_kept: int = 0  # earlier events present anywhere in the later edition
    top_before: int = 0
    top_still_top: int = 0
    top_still_listed: int = 0

    def line(self) -> str:
        return (f"{self.pairs:3d} pairs  events carried over {self.events_kept}/{self.events_before} "
                f"({self.events_kept / max(1, self.events_before):.0%})  top stories again top "
                f"{self.top_still_top}/{self.top_before} ({self.top_still_top / max(1, self.top_before):.0%}), still listed "
                f"{self.top_still_listed}/{self.top_before} ({self.top_still_listed / max(1, self.top_before):.0%})")


def explain_baseline(story, candidates: list, matched: list) -> tuple[object | None, str]:
    """``changes._match`` with the rule that decided (same order, same result)."""
    from agent_reach.daily.changes import _urls
    from agent_reach.daily.edition import same_entities, same_topic

    for other in candidates:
        if other.story_id == story.story_id:
            return other, "same story_id"
    urls = _urls(story)
    best = max(((len(urls & _urls(o)), -k, o) for k, o in enumerate([*candidates, *matched])), default=None,
               key=lambda t: t[:2])
    if best is not None and best[0] > 0:
        return best[2], f"{best[0]} shared article URL(s)"
    for other in candidates:
        if same_entities(story, other):
            return other, "same entity set"
    for other in candidates:
        if same_topic(story, other):
            return other, "same topic words"
    return None, ""


def baseline_matcher(previous: DailyEdition, current: DailyEdition) -> dict[int, tuple[int | None, str]]:
    """{current rank: (matched previous rank or None, why)}, exactly as ``changes.compare_editions`` pairs stories."""
    remaining = list(previous.stories)
    matched: list = []
    out: dict[int, tuple[int | None, str]] = {}
    for story in current.stories:
        old, why = explain_baseline(story, remaining, matched)
        if old is not None and old in remaining:
            remaining.remove(old)
            matched.append(old)
        out[story.rank] = (old.rank if old is not None else None, why)
    return out


@lru_cache(maxsize=1)
def registry_assignments() -> dict[tuple[str, int], tuple[str, str]]:
    """Every story of the twelve editions run through ``daily/registry`` in time order, as the app would:
    {(edition, rank): (event id, why)}."""
    from agent_reach.daily.registry import Registry, apply_edition

    reg = Registry()
    out = {}
    for name in EDITIONS:
        for d in apply_edition(reg, edition(name)):
            out[(name, d.rank)] = (d.event_id, f"{d.tier}: {d.reason}")
    return out


def registry_matcher(previous: DailyEdition, current: DailyEdition) -> dict[int, tuple[int | None, str]]:
    """{current rank: (earlier rank of the same registry event or None, why)}."""
    names = {edition(n).generation_started_utc: n for n in EDITIONS}
    a, b = names[previous.generation_started_utc], names[current.generation_started_utc]
    ids = registry_assignments()
    earlier: dict[str, int] = {}
    for s in sorted(previous.stories, key=lambda s: s.rank):
        earlier.setdefault(ids[(a, s.rank)][0], s.rank)
    return {s.rank: (earlier.get(ids[(b, s.rank)][0]), ids[(b, s.rank)][1]) for s in current.stories}


def _shared_evidence(a, b) -> tuple[int, int]:
    from agent_reach.daily.changes import _urls

    titles = lambda s: {dedupe_key(e.title) for e in s.evidence}  # noqa: E731
    return len(_urls(a) & _urls(b)), len(titles(a) & titles(b))


def miss_cause(gold: Gold, a: str, b: str, story) -> str:
    """Why a continuing story was not found: what it still shares with its earlier story of the same event."""
    prev = edition(a)
    same = [o for o in prev.stories if gold.same(f"{short(a)}#{o.rank}", f"{short(b)}#{story.rank}") is True]
    if not same:
        return "no earlier story"
    urls, titles = max(_shared_evidence(story, o) for o in same)
    names = max(len({n.lower() for n in story.entities} & {n.lower() for n in o.entities}) for o in same)
    if urls or titles:
        return "shares reports, but the earlier story was taken by another"
    if names:
        return f"no shared report; {names} shared key name(s)"
    return "no shared report and no shared key name"


def score_pair(gold: Gold, a: str, b: str, matcher=baseline_matcher, match: MatchScore | None = None,
               churn: ChurnScore | None = None) -> tuple[MatchScore, ChurnScore]:
    match = match if match is not None else MatchScore()
    churn = churn if churn is not None else ChurnScore()
    match.pairs += 1
    churn.pairs += 1
    prev, cur = edition(a), edition(b)
    earlier = gold.events_of(a)
    pairs = matcher(prev, cur)
    for story in cur.stories:
        key = f"{short(b)}#{story.rank}"
        event = gold.event.get(key)
        if event is None:
            continue
        continuing = event in earlier
        got, why = pairs.get(story.rank, (None, ""))
        verdict = gold.same(key, f"{short(a)}#{got}") if got is not None else None
        match.continuing += continuing
        if got is not None and verdict is True:
            match.correct += 1
        elif got is not None and verdict is False:
            match.wrong += 1
            match.wrong_examples.append((short(a), short(b), gold.headline.get(f"{short(a)}#{got}"), story.headline, why))
        if continuing and not (got is not None and verdict is True):
            if not (got is not None and verdict is None):  # matched to a related event: not scored
                match.missed += 1
                match.missed_examples.append((short(a), short(b), story.headline, miss_cause(gold, a, b, story)))
        if not continuing and got is None:
            match.new_right += 1
    later = gold.events_of(b)
    later_top = {gold.event.get(f"{short(b)}#{r}") for r in cur.top_ranks}
    churn.events_before += len(earlier)
    churn.events_kept += len(earlier & later)
    for r in prev.top_ranks:
        event = gold.event.get(f"{short(a)}#{r}")
        if event is not None:
            churn.top_before += 1
            churn.top_still_top += event in later_top
            churn.top_still_listed += event in later
    return match, churn


def hours_apart(a: str, b: str) -> float:
    ta: datetime = edition(a).generation_started_utc
    tb: datetime = edition(b).generation_started_utc
    return abs((tb - ta).total_seconds()) / 3600


#: Thresholds of a new matcher are chosen on pairs whose later edition is one of the first eight (05:05 to
#: 18:49 UTC); pairs ending in the four evening editions (21:34 to 23:34) are held out. The events overlap (one
#: day of news): this is a held-out set of STORIES, not of events. A multi-day held-out set replaces it (PLAN 2.1b).
HELD_OUT_FROM = 8


def edition_pairs(split: str = "all") -> dict[str, list[tuple[str, str]]]:
    idx = {n: i for i, n in enumerate(EDITIONS)}
    keep = {"all": lambda b: True, "dev": lambda b: idx[b] < HELD_OUT_FROM,
            "held-out": lambda b: idx[b] >= HELD_OUT_FROM}[split]
    near = [(a, b) for a, b in zip(EDITIONS, EDITIONS[1:]) if keep(b)]
    far = [(a, b) for i, a in enumerate(EDITIONS) for b in EDITIONS[i + 1:]
           if hours_apart(a, b) >= FAR_HOURS and keep(b)]
    return {"consecutive": near, f"{FAR_HOURS:g}h+ apart": far}


def report(matcher=baseline_matcher, split: str = "all") -> dict[str, MatchScore]:
    """Matching scores per group of edition pairs."""
    gold = load_gold()
    out = {}
    for label, pairs in edition_pairs(split).items():
        m = MatchScore()
        for a, b in pairs:
            score_pair(gold, a, b, matcher, m)
        out[label] = m
    return out


def churn_report() -> dict[str, ChurnScore]:
    """Carry-over and Top Stories per group of edition pairs: the answer key only, independent of any matcher."""
    gold = load_gold()
    out = {}
    for label, pairs in edition_pairs().items():
        c = ChurnScore()
        for a, b in pairs:
            score_pair(gold, a, b, baseline_matcher, churn=c)
        out[label] = c
    return out


def main() -> None:
    gold = load_gold()
    multi = Counter(gold.event.values())
    spread = sum(1 for e in multi if len({k.split('#')[0] for k, v in gold.event.items() if v == e}) > 1)
    print(f"answer key: {len(gold.event)} stories, {len(multi)} events, {spread} in more than one edition, "
          f"{len(gold.related)} related pairs\n")
    for title, matcher in (("today's matcher, changes._match", baseline_matcher),
                           ("event registry, daily/registry.py", registry_matcher)):
        for split in ("dev", "held-out"):
            print(f"MATCHING: {title} [{split}]")
            for label, s in report(matcher, split).items():
                print(f"{label:>14}: {s.line()}")
                print("      false continuations by rule: " + ", ".join(
                    f"{why.split(':')[0]} {n}" for why, n in Counter(ex[4] for ex in s.wrong_examples).most_common()))
                print("      misses by cause: " + ", ".join(
                    f"{why} {n}" for why, n in Counter(ex[3] for ex in s.missed_examples).most_common()))
    print("\nCARRY-OVER AND TOP STORIES (answer key only, independent of the matcher)")
    for label, c in churn_report().items():
        print(f"{label:>14}: {c.line()}")


if __name__ == "__main__":
    main()
