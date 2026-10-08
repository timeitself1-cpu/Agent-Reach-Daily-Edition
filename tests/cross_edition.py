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
@dataclass
class MatchScore:
    pairs: int = 0
    continuing: int = 0  # stories of the later edition whose event was in the earlier one
    correct: int = 0  # matched to a story of the same event
    wrong: int = 0  # matched to a story of a different (not related) event: a false continuation
    missed: int = 0  # continuing, but reported as new (or matched wrongly)
    new_right: int = 0  # really new, reported as new
    top_kept: int = 0  # earlier edition's Top Stories whose event is anywhere in the later edition
    top_total: int = 0
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
                f"wrong {self.wrong:3d}  missed {self.missed:3d}  precision {self.precision:.3f}  "
                f"recall {self.recall:.3f}  top stories still listed {self.top_kept}/{self.top_total}")


def baseline_matcher(previous: DailyEdition, current: DailyEdition) -> dict[int, int | None]:
    """{current rank: matched previous rank or None}, exactly as ``changes.compare_editions`` pairs stories."""
    from agent_reach.daily.changes import _match

    remaining = list(previous.stories)
    matched: list = []
    out: dict[int, int | None] = {}
    for story in current.stories:
        old = _match(story, remaining, matched)
        if old is not None and old in remaining:
            remaining.remove(old)
            matched.append(old)
        out[story.rank] = old.rank if old is not None else None
    return out


def score_pair(gold: Gold, a: str, b: str, matcher=baseline_matcher, into: MatchScore | None = None) -> MatchScore:
    score = into or MatchScore()
    score.pairs += 1
    prev, cur = edition(a), edition(b)
    earlier = gold.events_of(a)
    pairs = matcher(prev, cur)
    for story in cur.stories:
        key = f"{short(b)}#{story.rank}"
        event = gold.event.get(key)
        if event is None:
            continue
        continuing = event in earlier
        got = pairs.get(story.rank)
        verdict = gold.same(key, f"{short(a)}#{got}") if got is not None else None
        score.continuing += continuing
        if got is not None and verdict is True:
            score.correct += 1
        elif got is not None and verdict is False:
            score.wrong += 1
            score.wrong_examples.append((short(a), short(b), gold.headline.get(f"{short(a)}#{got}"), story.headline))
        if continuing and not (got is not None and verdict is True):
            if not (got is not None and verdict is None):  # matched to a related event: not scored
                score.missed += 1
                score.missed_examples.append((short(a), short(b), story.headline))
        if not continuing and got is None:
            score.new_right += 1
    later = gold.events_of(b)
    for r in prev.top_ranks:
        event = gold.event.get(f"{short(a)}#{r}")
        if event is not None:
            score.top_total += 1
            score.top_kept += event in later
    return score


def hours_apart(a: str, b: str) -> float:
    ta: datetime = edition(a).generation_started_utc
    tb: datetime = edition(b).generation_started_utc
    return abs((tb - ta).total_seconds()) / 3600


def report(matcher=baseline_matcher) -> dict[str, MatchScore]:
    gold = load_gold()
    consecutive, far = MatchScore(), MatchScore()
    for a, b in zip(EDITIONS, EDITIONS[1:]):
        score_pair(gold, a, b, matcher, consecutive)
    for i, a in enumerate(EDITIONS):
        for b in EDITIONS[i + 1:]:
            if hours_apart(a, b) >= FAR_HOURS:
                score_pair(gold, a, b, matcher, far)
    return {"consecutive": consecutive, f"{FAR_HOURS:g}h+ apart": far}


def main() -> None:
    gold = load_gold()
    multi = Counter(gold.event.values())
    print(f"answer key: {len(gold.event)} stories, {len(multi)} events, "
          f"{sum(1 for e in multi if len({k.split('#')[0] for k, v in gold.event.items() if v == e}) > 1)} "
          f"in more than one edition, {len(gold.related)} related pairs")
    for label, s in report().items():
        print(f"{label:>14}: {s.line()}")
        for ex in s.wrong_examples[:8]:
            print(f"   wrong   {ex[0]} -> {ex[1]}: {ex[2]!r} continued as {ex[3]!r}")
        for ex in s.missed_examples[:8]:
            print(f"   missed  {ex[0]} -> {ex[1]}: {ex[2]!r}")


if __name__ == "__main__":
    main()
