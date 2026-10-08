"""The labelled event corpus: real October 7 editions turned back into clustering input, with gold events.

Every report a real edition published becomes a ``CleanedTrendItem`` again (title, source, publisher, link,
publication time, excerpt as page context; observations of one item stay one item). ``gold`` is the event
the report belongs to (``tests/fixtures/real/event_gold.json``), ``recorded`` is the story the rc11 pipeline
(nomic-embed-text + HDBSCAN + LinkIndex) actually put it in. Comparing a grouping with ``gold`` gives
pairwise precision / recall / F1 and the raw number of false merges, the error that matters most here:
two different events presented as one story with "Strong evidence".

Only reports that reached an edition are in the corpus (the editions do not record the noise items), so
recall is measured on published stories only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from agent_reach.models import CleanedTrendItem, RawTrendItem, SourceName
from agent_reach.pipeline.cleaner import dedupe_key, normalize_text

FIXTURES = Path(__file__).parent / "fixtures" / "real"
#: Editions the rc11 pipeline published (nomic-embed-text + HDBSCAN + single-link) ...
RC11_EDITIONS = ("2026-10-07-selftest-r1.json", "2026-10-07-selftest-r2.json", "2026-10-07-selftest2-r1.json",
                 "2026-10-07-selftest2-r2.json", "2026-10-07-0935-export.json")
#: ... and the first two rc12 editions from the user's PC (nomic-embed-text + identity gate, 12:13 and 12:23):
#: the Paxton leak with three Iran-war reports, Belgian protests in France's stun-grenade story, AI agents
#: hacking South Korea's banks with OpenAI's agents at Wikipedia.
RC12_EDITIONS = ("2026-10-07-rc12-r1.json", "2026-10-07-rc12-r2.json")
#: ... and the rc12c editions (13:41 and 13:50, rc12b gate on nomic-embed-text): two "retreats" (Trump's forces
#: pulling back, his golf club), two obituaries, three polls, Kimmel's monologue in the Trump Accounts story.
RC12C_EDITIONS = ("2026-10-07-rc12c-r1.json", "2026-10-07-rc12c-r2.json")
#: ... and the rc12d editions (16:35 and 16:43, rc12d gate on nomic-embed-text): the golf club still with the
#: forces' retreat, a Gaza child's illness in the October 7 anniversary, Texas's next execution in Christa Pike's.
RC12D_EDITIONS = ("2026-10-07-rc12d-r1.json", "2026-10-07-rc12d-r2.json",
                  # 18:26 and 18:34, rc12d again: a Pitt State profile in NASA's Artemis II data story ('NASA' + 'lunar')
                  "2026-10-07-rc12d2-r1.json", "2026-10-07-rc12d2-r2.json")
EDITIONS = RC11_EDITIONS + RC12_EDITIONS + RC12C_EDITIONS + RC12D_EDITIONS
_SOURCE_BY_NAME = {"News feeds": SourceName.NEWS_RSS, "Google News": SourceName.GOOGLE_NEWS,
                   "Google Trends": SourceName.GOOGLE_TRENDS, "Hacker News": SourceName.HACKERNEWS,
                   "YouTube": SourceName.YOUTUBE, "X (trends24)": SourceName.X_TRENDS24, "Bluesky": SourceName.BLUESKY,
                   "Mastodon": SourceName.MASTODON, "Wikipedia": SourceName.WIKIPEDIA, "Reddit": SourceName.REDDIT}


@dataclass
class CorpusItem:
    item: CleanedTrendItem
    gold: str | None  # None: covers several stories (roundup, bare hashtag); belongs to no event
    recorded: str  # the published story it was in
    edition: str

    @property
    def title(self) -> str:
        return self.item.normalized_title


def _when(ev: dict) -> datetime:
    raw = ev.get("published_at_utc") or ev.get("retrieved_at_utc") or "2026-10-07T12:00:00Z"
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


def _raw(ev: dict) -> RawTrendItem:
    source = SourceName(ev["source"]) if ev.get("source") else _SOURCE_BY_NAME.get(ev.get("source_name", ""), SourceName.NEWS_RSS)
    metadata = {"publisher": ev.get("publisher") or "", "published_at": ev.get("published_at_utc")}
    if source is SourceName.GOOGLE_TRENDS and ev.get("excerpt"):
        # a trend's excerpt is its news headlines joined by ' | ' (ingestion/search.py): give them back, as a
        # real run has them ('cam jurgens' is the concussion-protocol trend, not the Ravens trade article)
        metadata["news_titles"] = [t.strip() for t in ev["excerpt"].split(" | ") if t.strip()][:3]
    return RawTrendItem(title=ev["title"], source=source, url=ev.get("url"), timestamp=_when(ev),
                        description=ev.get("excerpt"), metadata=metadata)


def _stories(name: str) -> list[dict]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    out = []
    for s in data["stories"]:
        out.append({"key": f"{name}#{s.get('rank', s.get('card'))}", "headline": s["headline"],
                    "summary": " ".join(s.get("sentences") or [s.get("summary", "")]), "evidence": s["evidence"]})
    return out


def load_gold() -> dict:
    return json.loads((FIXTURES / "event_gold.json").read_text(encoding="utf-8"))["editions"]


def load_edition(name: str, first_id: int = 1) -> list[CorpusItem]:
    gold = load_gold().get(name, {})
    splits: dict[str, dict[str, str]] = gold.get("split", {})
    unassigned = gold.get("unassigned", [])
    same = {b: a for a, b in gold.get("same_event", [])}
    out: list[CorpusItem] = []
    next_id = first_id
    for story in _stories(name):
        moves = next((m for start, m in splits.items() if story["headline"].startswith(start)), {})
        event = story["headline"]
        for b, a in same.items():
            if story["headline"].startswith(b):
                event = next(s["headline"] for s in _stories(name) if s["headline"].startswith(a))
        groups: dict[str, list[dict]] = {}
        for ev in story["evidence"]:
            key = str(ev["item_id"]) if ev.get("item_id") is not None else dedupe_key(ev["title"])
            groups.setdefault(key, []).append(ev)
        for evs in groups.values():
            first = evs[0]
            raws = [_raw(e) for e in evs]
            context = next((e["excerpt"] for e in evs if e.get("excerpt")), None)
            item = CleanedTrendItem(**raws[0].model_dump(), item_id=next_id, normalized_title=normalize_text(first["title"]),
                                    heuristic_score=0.5, duplicate_count=len(evs), observations=raws,
                                    merged_urls=[e["url"] for e in evs if e.get("url")], context=context,
                                    context_source="page" if context else None)
            next_id += 1
            label: str | None = next((ev_id for start, ev_id in moves.items() if first["title"].startswith(start)), None)
            label = label or event
            if any(first["title"].startswith(u) for u in unassigned):
                label = None
            out.append(CorpusItem(item=item, gold=label, recorded=story["key"], edition=name))
    return out


def related_pairs(name: str) -> set[frozenset[str]]:
    """Gold events that are different occurrences of one ongoing topic (merging them is not scored)."""
    gold = load_gold().get(name, {})
    heads = [s["headline"] for s in _stories(name)]
    out = set()
    for a, b in gold.get("related", []):
        a = next((h for h in heads if h.startswith(a)), a)
        b = next((h for h in heads if h.startswith(b)), b)
        out.add(frozenset((a, b)))
    return out


def recorded_groups(corpus: list[CorpusItem]) -> list[list[int]]:
    by: dict[str, list[int]] = {}
    for c in corpus:
        by.setdefault(c.recorded, []).append(c.item.item_id)
    return list(by.values())


@dataclass
class PairScore:
    true_pairs: int
    predicted_pairs: int
    correct_pairs: int
    false_merges: list[tuple[str, str]]  # report titles wrongly put in one story
    missed_merges: list[tuple[str, str]]
    mixed_stories: int  # stories that contain more than one gold event (or an unassigned report)
    stories: int

    @property
    def precision(self) -> float:
        return self.correct_pairs / self.predicted_pairs if self.predicted_pairs else 1.0

    @property
    def recall(self) -> float:
        return self.correct_pairs / self.true_pairs if self.true_pairs else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def as_dict(self) -> dict:
        return {"precision": round(self.precision, 3), "recall": round(self.recall, 3), "f1": round(self.f1, 3),
                "false_merges": len(self.false_merges), "missed_merges": len(self.missed_merges),
                "mixed_stories": self.mixed_stories, "multi_report_stories": self.stories,
                "true_pairs": self.true_pairs, "predicted_pairs": self.predicted_pairs}


def score(corpus: list[CorpusItem], groups: list[list[int]], related: set[frozenset[str]] | None = None) -> PairScore:
    """Pairwise scores of ``groups`` (lists of item ids; items not in any group are singletons)."""
    related = related or set()
    by_id = {c.item.item_id: c for c in corpus}
    where: dict[int, int] = {}
    for g, ids in enumerate(groups):
        for i in ids:
            where[i] = g
    true_pairs = predicted = correct = 0
    false_m: list[tuple[str, str]] = []
    missed: list[tuple[str, str]] = []
    for a, b in combinations(sorted(by_id), 2):
        ca, cb = by_id[a], by_id[b]
        same_gold = ca.gold is not None and ca.gold == cb.gold
        together = a in where and where.get(a) == where.get(b)
        if not same_gold and ca.gold and cb.gold and frozenset((ca.gold, cb.gold)) in related:
            continue
        true_pairs += same_gold
        predicted += together
        correct += same_gold and together
        if together and not same_gold:
            false_m.append((ca.title, cb.title))
        if same_gold and not together:
            missed.append((ca.title, cb.title))
    mixed = 0
    multi = 0
    for ids in groups:
        if len(ids) < 2:
            continue
        multi += 1
        golds = {by_id[i].gold for i in ids}
        rel = len(golds) == 2 and None not in golds and frozenset(golds) in related
        if (len(golds) > 1 or None in golds) and not rel:
            mixed += 1
    return PairScore(true_pairs, predicted, correct, false_m, missed, mixed, multi)
