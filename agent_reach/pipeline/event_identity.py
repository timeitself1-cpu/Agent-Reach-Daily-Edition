"""Event identity: may two reports be presented as one story, and may a report join a story?

Embeddings (``pipeline/embeddings.py``) only PROPOSE candidates: each report's nearest neighbours above a
loose cosine floor. Whether two reports describe the same occurrence is decided here, pair by pair, by an
explicit gate whose every decision carries its reasons:

* REJECT, with a conflict: a multi-story roundup or live page is involved (it covers several events, so it
  is evidence for none and may bridge none); the reports are more than ``event_max_age_hours`` apart;
  they name different kinds of event (a launch vs an acquisition) or exclusive qualifiers (the physics vs
  the chemistry Nobel).
* ACCEPT: the reports share specific evidence about what happened (``LinkIndex.link_evidence``: distinctive
  words or phrases beyond names, dates and everyday words), and, when vectors exist, the embedding agrees
  (cosine >= the candidate floor).
* ACCEPT also when the embedding is confident (cosine >= ``identity_strong_cosine``) AND the reports share
  two specific phrases outside any name, or one and a name ('Siberian' + 'plague'); a shared name or one
  broad word ('app') is never enough, and words one title writes together ('dead star') are one phrase.
* NEUTRAL: neither (names only, a date only, a broad topic only, or the embedding disagrees).

Stories are then built so that no chain of pairwise links can join two events (A~B and B~C never makes
A=C on their own): two groups merge only through an accepted pair, when **no** pair across them is rejected
and **strictly more than half** of the pairs across them support it (accepted, or sharing a specific word
that is not part of a name in the titles, or specific words of the page text). A lone report that every
member of exactly one story supports joins that story. A report that links to one member of a story but is
unrelated to the others stays out. This prefers a split (one event shown twice) to a false merge (two
events presented as one story with "Strong evidence"). Real cases (October 7, 2026 editions): a Morning
Rundown digest joined the Maine Senate debate to Cornell's sexual-assault review; "October 7" joined
NASA's picture of the day, a Fauda review and the #October7 hashtag; "James Webb Space Telescope" joined a
planetary-collision study to NASA's PRIMA proposal; "app" and "behind" joined Australia's smart-glasses
privacy probe to a WSJ profile of the billionaire behind Meta's AI app.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from typing import Protocol

ACCEPT, REJECT, NEUTRAL = "accept", "reject", "neutral"
#: pair decisions kept in the developer artifact (the closest rejected/neutral candidates come first)
MAX_LOGGED_PAIRS = 4000


class _Index(Protocol):
    items: dict
    roundups: set

    def conflict(self, a: int, b: int) -> str | None: ...

    def link_evidence(self, a: int, b: int) -> tuple[bool, list[str], str]: ...

    def specific_overlap(self, a: int, b: int) -> list[str]: ...

    def shares_name(self, a: int, b: int, rare: bool = False) -> bool: ...

    def context_support(self, a: int, b: int) -> list[str]: ...

    def shared_units(self, a: int, b: int, shared: set[str]) -> list[set[str]]: ...


@dataclass
class PairDecision:
    a: int
    b: int
    verdict: str
    reasons: list[str] = field(default_factory=list)
    cosine: float | None = None
    shared: list[str] = field(default_factory=list)
    support: bool = False  # ACCEPT, or one specific shared word: counts toward cohesion, never seeds a merge

    def as_dict(self, titles: dict[int, str] | None = None) -> dict:
        out = {"a": self.a, "b": self.b, "verdict": self.verdict, "reasons": self.reasons,
               "cosine": None if self.cosine is None else round(self.cosine, 3), "shared_evidence": self.shared,
               "supports_cohesion": self.support}
        if titles:
            out["a_title"], out["b_title"] = titles.get(self.a, ""), titles.get(self.b, "")
        return out


@dataclass
class GateStats:
    candidate_pairs: int = 0
    accepted_pairs: int = 0
    rejected_pairs: int = 0
    neutral_pairs: int = 0
    roundup_rejections: int = 0
    merges_accepted: int = 0
    merges_blocked_conflict: int = 0
    merges_blocked_cohesion: int = 0
    reasons: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict:
        return {"candidate_pairs": self.candidate_pairs, "accepted_pairs": self.accepted_pairs,
                "rejected_pairs": self.rejected_pairs, "neutral_pairs": self.neutral_pairs,
                "roundup_rejections": self.roundup_rejections, "merges_accepted": self.merges_accepted,
                "merges_blocked_conflict": self.merges_blocked_conflict,
                "merges_blocked_cohesion": self.merges_blocked_cohesion,
                "top_reasons": dict(self.reasons.most_common(8))}


def _cos(u: list[float], v: list[float]) -> float:
    return sum(x * y for x, y in zip(u, v))


class IdentityGate:
    """Pair decisions for one run (cached); ``vectors`` are L2-normalised embeddings by item id, if any."""

    def __init__(self, index: _Index, vectors: dict[int, list[float]] | None = None, min_cosine: float = 0.45,
                 strong_cosine: float = 0.8) -> None:
        self.index = index
        self.vectors = vectors or {}
        self.min_cosine = min_cosine
        self.strong_cosine = strong_cosine
        self.stats = GateStats()
        self._cache: dict[tuple[int, int], PairDecision] = {}

    def cosine(self, a: int, b: int) -> float | None:
        va, vb = self.vectors.get(a), self.vectors.get(b)
        if va is None or vb is None:
            return None
        return _cos(va, vb)

    def decide(self, a: int, b: int) -> PairDecision:
        key = (a, b) if a < b else (b, a)
        if key in self._cache:
            return self._cache[key]
        cos = self.cosine(*key)
        conflict = self.index.conflict(*key)
        if conflict:
            d = PairDecision(*key, REJECT, [conflict], cos)
            if "roundup" in conflict:
                self.stats.roundup_rejections += 1
        else:
            ok, shared, why = self.index.link_evidence(*key)
            specific = self.index.specific_overlap(*key)
            if ok and cos is not None and cos < self.min_cosine:
                d = PairDecision(*key, NEUTRAL, [f"embedding disagrees (cosine {cos:.2f} < {self.min_cosine:.2f})"],
                                 cos, shared)
            elif ok:
                d = PairDecision(*key, ACCEPT, [why], cos, shared, support=True)
            elif cos is not None and cos >= self.strong_cosine and specific and (
                    len(self.index.shared_units(*key, set(specific))) >= 2 or self.index.shares_name(*key, rare=True)):
                # the embedding sees one event AND the reports share two specific words that are not part of
                # a name, or one and a name ('Siberian' + 'plague'): never a name or one broad word alone
                # ('app' joined a smart-glasses privacy probe to a profile of Meta's AI-app billionaire)
                d = PairDecision(*key, ACCEPT, [f"embedding agrees (cosine {cos:.2f}) and shares specific words"],
                                 cos, specific, support=True)
            else:
                context = [] if specific else self.index.context_support(*key)
                agrees = cos is None or cos >= self.min_cosine  # with vectors, support needs the embedding too
                d = PairDecision(*key, NEUTRAL, [why] + ([f"page text shares {', '.join(context[:4])}"] if context else []),
                                 cos, specific or context or shared, support=bool(specific or context) and agrees)
        self.stats.candidate_pairs += 1
        if d.verdict == ACCEPT:
            self.stats.accepted_pairs += 1
        elif d.verdict == REJECT:
            self.stats.rejected_pairs += 1
        else:
            self.stats.neutral_pairs += 1
        self.stats.reasons[d.reasons[0].split(" (")[0] if d.reasons else d.verdict] += 1
        self._cache[key] = d
        return d

    def accepts(self, a: int, b: int) -> bool:
        return self.decide(a, b).verdict == ACCEPT

    def decisions(self) -> list[PairDecision]:
        return list(self._cache.values())

    def pair_log(self, limit: int = MAX_LOGGED_PAIRS) -> list[dict]:
        """Decided pairs for the developer artifact: every accepted pair first (they make the stories, so a false
        merge is found there), then refusals, then the most similar undecided pairs, roundup refusals last. Accepted
        pairs used to come last and a real run's 33,670 decisions cut all of them (October 7, PC)."""
        titles = {i: getattr(it, "normalized_title", "") for i, it in self.index.items.items()}
        rank = {ACCEPT: 0, REJECT: 1, NEUTRAL: 2}

        def order(d: PairDecision) -> tuple:
            roundup = d.verdict == REJECT and any("roundup" in r for r in d.reasons)
            return (3 if roundup else rank.get(d.verdict, 2), -(d.cosine if d.cosine is not None else len(d.shared) / 10))

        return [d.as_dict(titles) for d in sorted(self._cache.values(), key=order)[:limit]]


def cohesive_groups(ids: list[int], gate: IdentityGate, edges: list[tuple[int, int]] | None = None,
                    fragments: set[int] | None = None) -> list[list[int]]:
    """Group ``ids`` into events: no rejected pair inside a group, and a strict majority of accepted pairs
    between any two groups that merge (so a single bridge never joins two events).

    ``edges`` are the candidate pairs (all pairs when None: small sets only). ``fragments`` are trend
    fragments ('Messi', 'Packers'): one that is accepted by members of two different stories joins neither.
    """
    owner = {i: i for i in ids}
    groups: dict[int, list[int]] = {i: [i] for i in ids}
    pairs = edges if edges is not None else list(combinations(ids, 2))
    accepted = []
    for a, b in pairs:
        if a == b or a not in owner or b not in owner:
            continue
        d = gate.decide(a, b)
        if d.verdict == ACCEPT:
            strength = d.cosine if d.cosine is not None else 0.0
            accepted.append((-strength, -len(d.shared), min(a, b), max(a, b)))
    accepted.sort()
    for _, _, a, b in accepted:
        ga, gb = owner[a], owner[b]
        if ga == gb:
            continue
        cross = [gate.decide(x, y) for x in groups[ga] for y in groups[gb]]
        if any(d.verdict == REJECT for d in cross):
            gate.stats.merges_blocked_conflict += 1
            continue
        if 2 * sum(d.support for d in cross) <= len(cross):
            gate.stats.merges_blocked_cohesion += 1
            continue
        keep, drop = (ga, gb) if len(groups[ga]) >= len(groups[gb]) else (gb, ga)
        groups[keep].extend(groups.pop(drop))
        for x in groups[keep]:
            owner[x] = keep
        gate.stats.merges_accepted += 1
    out = _attach_supported(list(groups.values()), gate)
    if fragments:
        out = _drop_ambiguous_fragments(out, gate, fragments)
    return sorted((sorted(g) for g in out), key=lambda g: (-len(g), g))


def _attach_supported(groups: list[list[int]], gate: IdentityGate) -> list[list[int]]:
    """A lone report joins a story of two or more when EVERY member supports it (and none rejects it), and
    exactly one story qualifies ('What to know about Spain's housing protests ...' joins the two reports of
    the Spanish snap election over the housing crisis)."""
    stories = [g for g in groups if len(g) >= 2]
    lone = [g[0] for g in groups if len(g) == 1]
    # without embeddings, support is one shared word and nothing corroborates it ('multimodal' + 'model'
    # attached Mistral Large 4 to EmbeddingGemma 2; 'agent' joined Sierra's protocol to Wikimedia's rogue agents)
    if not stories or not lone or not gate.vectors:
        return groups
    attached: set[int] = set()
    def fits(x: int, g: list[int]) -> bool:
        decisions = [gate.decide(x, m) for m in g]
        if not all(d.support for d in decisions):
            return False
        words = set().union(*(d.shared for d in decisions))
        # one everyday-ish word shared with everyone ('chief') is not enough: two phrases, or a shared name few
        # reports carry, and in both cases a specific word the TITLES share: page-text words alone ('Paramount'
        # + 'effort', 'television') attached a Taylor Sheridan western on Paramount+ to the Warner merger
        return (len(gate.index.shared_units(x, g[0], words, context=True)) >= 2 and len(words) >= 2
                and any(gate.index.specific_overlap(x, m) for m in g)
                or any(gate.index.shares_name(x, m, rare=True) and gate.index.specific_overlap(x, m) for m in g))

    for x in lone:
        homes = [g for g in stories if fits(x, g)]
        if len(homes) == 1:
            homes[0].append(x)
            attached.add(x)
            gate.stats.merges_accepted += 1
    return stories + [[x] for x in lone if x not in attached]


def _drop_ambiguous_fragments(groups: list[list[int]], gate: IdentityGate, fragments: set[int]) -> list[list[int]]:
    """A trend fragment accepted by members of two different multi-report stories belongs to neither."""
    where = {i: k for k, g in enumerate(groups) for i in g}
    out = [list(g) for g in groups]
    for f in fragments:
        if f not in where:
            continue
        home = where[f]
        others = {where[x] for (a, b), d in gate._cache.items() if d.verdict == ACCEPT and f in (a, b)
                  for x in (a, b) if x != f and where.get(x) not in (None, home) and len(groups[where[x]]) >= 2}
        if others and len(out[home]) >= 2:
            out[home].remove(f)
            out.append([f])
    return [g for g in out if g]


def nearest_candidates(ids: list[int], vectors: dict[int, list[float]], k: int, floor: float) -> list[tuple[int, int]]:
    """Each report's ``k`` nearest neighbours with cosine >= ``floor`` (numpy when available)."""
    if len(ids) < 2:
        return []
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        np = None  # type: ignore[assignment]
    pairs: set[tuple[int, int]] = set()
    if np is not None:
        m = np.asarray([vectors[i] for i in ids], dtype=float)
        sims = m @ m.T
        np.fill_diagonal(sims, -math.inf)
        kk = min(k, len(ids) - 1)
        top = np.argpartition(-sims, kk - 1, axis=1)[:, :kk]
        for r, row in enumerate(top):
            for c in row:
                if sims[r, c] >= floor:
                    a, b = ids[r], ids[int(c)]
                    pairs.add((a, b) if a < b else (b, a))
        return sorted(pairs)
    for a in ids:
        sims = sorted(((_cos(vectors[a], vectors[b]), b) for b in ids if b != a), reverse=True)[:k]
        for s, b in sims:
            if s >= floor:
                pairs.add((a, b) if a < b else (b, a))
    return sorted(pairs)


def lexical_candidates(ids: list[int], toks: dict[int, set[str]], max_df: int) -> list[tuple[int, int]]:
    """Pairs that share at least one word used by at most ``max_df`` reports (inverted index, ~O(n * k))."""
    df = Counter(t for i in ids for t in toks.get(i, ()))
    postings: dict[str, list[int]] = {}
    for i in ids:
        for t in toks.get(i, ()):
            if df[t] <= max_df:
                postings.setdefault(t, []).append(i)
    pairs: set[tuple[int, int]] = set()
    for members in postings.values():
        for a, b in combinations(sorted(members), 2):
            pairs.add((a, b))
    return sorted(pairs)
