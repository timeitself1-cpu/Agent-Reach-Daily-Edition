"""Event identity on the real October 7, 2026 editions (rc12): no false merges, no bridges, inspectable decisions.

The corpus (``tests/event_corpus.py``) rebuilds every report the five real October 7 editions published, with
gold events (``tests/fixtures/real/event_gold.json``). Two ways of feeding the clusterer are used:

* **replay**: each report gets the embedding neighbourhood rc11 actually gave it: reports that rc11 put in one
  story get near-identical vectors. This is the worst case for the new layer, because every false merge rc11
  published is handed to it as a confident embedding match; the identity gate must undo them.
* **identical**: every report gets the SAME vector (cosine 1 for every pair): the embedding says nothing, so
  only the gate's evidence can keep events apart.
"""

from __future__ import annotations

import asyncio
import random
from itertools import combinations

import pytest

from agent_reach.config import Settings
from agent_reach.models import CleanedTrendItem, RawTrendItem, SourceName
from agent_reach.pipeline.clusterer import LinkIndex, SemanticClusterer
from agent_reach.pipeline.embeddings import event_representation
from agent_reach.pipeline.event_identity import ACCEPT, NEUTRAL, REJECT, IdentityGate, PairDecision, cohesive_groups
from tests.event_corpus import EDITIONS, load_edition, recorded_groups, related_pairs, score


def _unit(v: list[float]) -> list[float]:
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def replay_vectors(corpus, seed: int = 7, dims: int = 48) -> dict[int, list[float]]:
    rnd = random.Random(seed)
    base: dict[str, list[float]] = {}
    out = {}
    for c in corpus:
        b = base.setdefault(c.recorded, [rnd.gauss(0, 1) for _ in range(dims)])
        out[c.item.item_id] = _unit([x + rnd.gauss(0, 0.2) for x in b])
    return out


class VectorOllama:
    """Fake Ollama: embeddings from a table (by event representation); the chat model is gone (heuristic labels)."""

    def __init__(self, items: list[CleanedTrendItem], vectors: dict[int, list[float]], models=("embeddinggemma-2:270m",)):
        self.by_text = {event_representation(it): vectors[it.item_id] for it in items}
        self.models = list(models)
        self.embed_calls: list[str] = []

    async def list(self):
        return {"models": [{"model": m, "digest": f"sha256:{abs(hash(m)):x}"} for m in ["llama3.1:8b", *self.models]]}

    async def embed(self, model, input, keep_alive=None):
        self.embed_calls.append(model)
        if model not in self.models:
            raise RuntimeError(f'model "{model}" not found, try pulling it first')
        out = []
        for text in input:
            body = text.split(" | query: ", 1)[-1] if text.startswith("task: ") else text.removeprefix("clustering: ")
            out.append(self.by_text[body])
        return {"embeddings": out}

    async def chat(self, **kw):
        raise ConnectionError("Failed to connect to Ollama")


def run_clusterer(corpus, vectors, tmp_path, **settings):
    items = [c.item for c in corpus]
    fake = VectorOllama(items, vectors)
    folder = tmp_path / corpus[0].edition  # one embedding cache per edition: the same title gets other vectors
    folder.mkdir(exist_ok=True)
    s = Settings(db_path=folder / "t.db", **settings)
    c = SemanticClusterer(s)
    c._client = fake
    outcome = asyncio.run(c.cluster(items, corpus=items, use_llm=True))
    return outcome, [list(cl.member_item_ids) for cl in outcome.clusters]


@pytest.mark.parametrize("name", EDITIONS)
def test_rc11_published_these_false_merges(name):
    """The baseline: what the rc11 pipeline (nomic-embed-text + HDBSCAN + single-link LinkIndex) published."""
    corpus = load_edition(name)
    s = score(corpus, recorded_groups(corpus), related_pairs(name))
    expected = {"2026-10-07-selftest-r1.json": 0, "2026-10-07-selftest-r2.json": 6, "2026-10-07-selftest2-r1.json": 11,
                "2026-10-07-selftest2-r2.json": 15, "2026-10-07-0935-export.json": 20}
    assert len(s.false_merges) == expected[name]


@pytest.mark.parametrize("name", EDITIONS)
def test_no_false_merges_when_rc11_neighbourhoods_are_replayed(name, tmp_path):
    corpus = load_edition(name)
    outcome, groups = run_clusterer(corpus, replay_vectors(corpus), tmp_path)
    s = score(corpus, groups, related_pairs(name))
    assert s.false_merges == [], s.false_merges
    assert outcome.semantic["model_used"] == "embeddinggemma-2:270m"


@pytest.mark.parametrize("name", EDITIONS)
def test_no_false_merges_when_every_pair_looks_identical(name, tmp_path):
    corpus = load_edition(name)
    same = _unit([1.0] * 16)
    outcome, groups = run_clusterer(corpus, {c.item.item_id: same for c in corpus}, tmp_path)
    s = score(corpus, groups, related_pairs(name))
    assert s.false_merges == [], s.false_merges


def test_replay_keeps_most_true_pairs(tmp_path):
    """Precision first, but not by splitting everything: most same-event pairs stay together."""
    true = correct = 0
    for name in EDITIONS:
        corpus = load_edition(name)
        _, groups = run_clusterer(corpus, replay_vectors(corpus), tmp_path)
        s = score(corpus, groups, related_pairs(name))
        true += s.true_pairs
        correct += s.correct_pairs
    assert correct / true >= 0.6


# ------------------------------------------------------------------ the named October 7 cases
def _index(name: str):
    corpus = load_edition(name)
    items = [c.item for c in corpus]
    return corpus, LinkIndex(items, items)


def _id(corpus, start: str) -> int:
    return next(c.item.item_id for c in corpus if c.title.startswith(start))


def _together(groups, a: int, b: int) -> bool:
    return any(a in g and b in g for g in groups)


def _replayed_groups(name, tmp_path):
    corpus = load_edition(name)
    return corpus, run_clusterer(corpus, replay_vectors(corpus), tmp_path)[1]


def test_maine_senate_debate_does_not_absorb_cornell(tmp_path):
    """Case A: the export's #6 'Collins Distances Herself from Trump in Maine Senate Debate' carried the
    Washington Post's Cornell charts, PBS's News Wrap on Sally Yates' Cornell review and NBC's Morning Rundown."""
    corpus, groups = _replayed_groups("2026-10-07-0935-export.json", tmp_path)
    collins = [_id(corpus, p) for p in ("What happened in the first Maine Senate debate", "In first Maine Senate debate",
                                        "Susan Collins and Troy Jackson clash")]
    cornell = [_id(corpus, p) for p in ("Reports of sexual violence are up", "News Wrap: Cornell says Sally Yates")]
    rundown = _id(corpus, "Battleground candidates clash over Trump and Cornell")
    assert any(set(collins) <= set(g) for g in groups)  # the debate is still one story
    for x in cornell + [rundown]:
        assert not any(_together(groups, x, c) for c in collins)
    assert not any(rundown in g and len(g) > 1 for g in groups)  # the roundup bridges nothing


def test_morning_rundown_cannot_bridge_two_stories():
    corpus, index = _index("2026-10-07-0935-export.json")
    rundown = _id(corpus, "Battleground candidates clash over Trump and Cornell")
    debate = _id(corpus, "Susan Collins and Troy Jackson clash")
    d = index.gate.decide(rundown, debate)
    assert d.verdict == REJECT and "roundup" in d.reasons[0]
    assert rundown in index.roundups


def test_planetary_collisions_do_not_absorb_nasa_prima(tmp_path):
    """Case B: 'James Webb Space Telescope Investigates Planetary Collisions' (#3) carried Mashable's 'NASA's
    Prima space telescope would aim to see what James Webb can't'."""
    corpus, groups = _replayed_groups("2026-10-07-0935-export.json", tmp_path)
    prima = _id(corpus, "NASA's Prima space telescope")
    webb = [_id(corpus, "Worlds collide!"), _id(corpus, "NASA's Webb finds signs")]
    assert _together(groups, *webb)
    assert not any(_together(groups, prima, w) for w in webb)
    corpus, index = _index("2026-10-07-0935-export.json")
    d = index.gate.decide(_id(corpus, "NASA's Prima space telescope"), _id(corpus, "Worlds collide!"))
    assert d.verdict != ACCEPT and "names" in d.reasons[0]  # 'James Webb Space Telescope' is one name, not evidence


def test_october_7_is_a_date_not_a_story(tmp_path):
    """Case C: #10 'NASA Features Supernova Remnant Pa 30 and Satellite Puzzler' joined APOD 'October 7', The
    Atlantic's Fauda review, the #October7 hashtag and 'October 2026 Satellite Puzzler'."""
    corpus, groups = _replayed_groups("2026-10-07-0935-export.json", tmp_path)
    parts = [_id(corpus, p) for p in ("APOD: 2026 October 7", "Why You Should Watch", "#October7", "October 2026 Satellite")]
    for a, b in combinations(parts, 2):
        assert not _together(groups, a, b)
    election = [_id(corpus, "Scars from Oct. 7"), _id(corpus, "3 years later, Netanyahu faces reckoning")]
    assert _together(groups, *election)  # the Israeli election story (which is ABOUT October 7) stays one story
    corpus, index = _index("2026-10-07-0935-export.json")
    d = index.gate.decide(_id(corpus, "APOD: 2026 October 7"), _id(corpus, "Why You Should Watch"))
    assert d.verdict != ACCEPT and "date" in d.reasons[0]


def test_smart_glasses_probe_is_not_the_meta_ai_app_billionaire(tmp_path):
    """Case D: Tech #1 'Privacy Watchdog Launches Investigation into China-Based Company' (event A: Australia's
    privacy regulator investigates Shenzhen Qingcheng, maker of the HeyCyan app in Kmart's smartglasses) also
    carried WSJ's 'The Mulleted, Meme-Loving Billionaire Behind Meta's Hit AI App' (event B). A and B must stay
    separate; 'app', 'AI', 'privacy', 'technology' or 'smart devices' are not enough to merge them."""
    for name in ("2026-10-07-0935-export.json", "2026-10-07-selftest2-r1.json"):
        corpus, groups = _replayed_groups(name, tmp_path)
        a = _id(corpus, "Privacy watchdog launches investigation")
        b = _id(corpus, "The Mulleted, Meme-Loving Billionaire")
        assert not _together(groups, a, b)
        corpus, index = _index(name)
        d = index.gate.decide(_id(corpus, "Privacy watchdog launches investigation"),
                              _id(corpus, "The Mulleted, Meme-Loving Billionaire"))
        assert d.verdict != ACCEPT


def test_broad_shared_concepts_never_merge_two_events():
    """Technology, apps, AI, privacy, smart devices: two different events that share only such words stay apart
    even when the embedding calls them identical."""
    now = RawTrendItem(title="x", source=SourceName.NEWS_RSS).timestamp
    titles = ["Privacy regulator opens investigation into smart glasses app maker over AI data",
              "Billionaire behind hit AI app says privacy and smart devices are the technology of the future",
              "Smart glasses sales grow as AI apps reach more devices"]
    items = [CleanedTrendItem(item_id=i, title=t, normalized_title=t, source=SourceName.NEWS_RSS, heuristic_score=0.5,
                              timestamp=now) for i, t in enumerate(titles, 1)]
    background = [CleanedTrendItem(item_id=100 + k, title=f"Unrelated report number {k} about weather in town {k}",
                                   normalized_title=f"Unrelated report number {k} about weather in town {k}",
                                   source=SourceName.NEWS_RSS, heuristic_score=0.5, timestamp=now) for k in range(40)]
    index = LinkIndex(items, items + background)
    same = _unit([1.0] * 8)
    index.attach_vectors({i: same for i in (1, 2, 3)}, 0.45, 0.8)
    assert cohesive_groups([1, 2, 3], index.gate) == [[1], [2], [3]]


class TableGate(IdentityGate):
    """A gate whose verdicts come from a table (pairs not in it are neutral, no support)."""

    def __init__(self, index, table: dict[tuple[int, int], str]):
        super().__init__(index)
        self.table = table

    def decide(self, a, b):
        key = (min(a, b), max(a, b))
        if key not in self._cache:
            verdict = self.table.get(key, NEUTRAL)
            self._cache[key] = PairDecision(*key, verdict, [verdict], 0.9, [], support=verdict == ACCEPT)
        return self._cache[key]


def test_no_transitive_merge_through_one_report():
    """A ~ B and B ~ C never make A = C on their own (single-link chaining is how rc11 bridged stories): even
    when the gate accepts both bridges, A and C are never in one story."""
    now = RawTrendItem(title="x", source=SourceName.NEWS_RSS).timestamp
    titles = ["Senate debate: candidates clash over tariffs and farm subsidies",
              "Candidates clash over tariffs while campus assault reviews draw scrutiny",
              "Campus assault reviews: university hires former prosecutor"]
    items = [CleanedTrendItem(item_id=i, title=t, normalized_title=t, source=SourceName.NEWS_RSS, heuristic_score=0.5,
                              timestamp=now) for i, t in enumerate(titles, 1)]
    index = LinkIndex(items, items)
    assert not index.gate.accepts(1, 3)
    groups = cohesive_groups([1, 2, 3], TableGate(index, {(1, 2): ACCEPT, (2, 3): ACCEPT}))
    assert not any({1, 3} <= set(g) for g in groups)
    # and a real conflict between A and C blocks the bridge outright
    groups = cohesive_groups([1, 2, 3], TableGate(index, {(1, 2): ACCEPT, (2, 3): ACCEPT, (1, 3): REJECT}))
    assert not any({1, 3} <= set(g) for g in groups)


def test_rejected_candidates_are_explained():
    """Developer diagnostics: every decision carries cosine, shared evidence and reasons."""
    corpus, index = _index("2026-10-07-0935-export.json")
    vectors = replay_vectors(corpus)
    index.attach_vectors(vectors, 0.45, 0.8)
    rundown = _id(corpus, "Battleground candidates clash over Trump and Cornell")
    debate = _id(corpus, "Susan Collins and Troy Jackson clash")
    d = index.gate.decide(debate, rundown).as_dict({debate: "Maine debate", rundown: "Morning Rundown"})
    assert d["verdict"] == "reject" and d["reasons"] == ["multi-story roundup"]
    assert d["cosine"] is not None and d["cosine"] > 0.8  # rc11's embedding neighbourhood said "same story"
    assert d["a_title"] and d["b_title"]
    log = index.gate.pair_log()
    assert log and log[0]["verdict"] != "accept"  # the closest non-accepted pairs come first
