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
from agent_reach.pipeline.event_identity import (ACCEPT, COMMON_NAME_AND_PHRASE, NEUTRAL, REJECT, IdentityGate, PairDecision,
                                                 cohesive_groups)
from tests.event_corpus import (EDITIONS, RC11_EDITIONS, RC12_EDITIONS, RC12C_EDITIONS, load_edition, recorded_groups,
                                related_pairs, score)


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


@pytest.mark.parametrize("name", RC11_EDITIONS)
def test_rc11_published_these_false_merges(name):
    """The baseline: what the rc11 pipeline (nomic-embed-text + HDBSCAN + single-link LinkIndex) published."""
    corpus = load_edition(name)
    s = score(corpus, recorded_groups(corpus), related_pairs(name))
    expected = {"2026-10-07-selftest-r1.json": 0, "2026-10-07-selftest-r2.json": 6, "2026-10-07-selftest2-r1.json": 11,
                "2026-10-07-selftest2-r2.json": 15, "2026-10-07-0935-export.json": 20}
    assert len(s.false_merges) == expected[name]


@pytest.mark.parametrize("name", RC12_EDITIONS)
def test_rc12_published_these_false_merges_on_the_pc(name):
    """What the first rc12 refreshes published on the user's PC (nomic-embed-text + identity gate, before rc12b):
    the merge pass grew stories one lone report at a time, and 'agents' + 'hack', 'France' + 'protests' counted as
    two distinctive phrases. The replay and identical-vector tests below cover these editions too."""
    corpus = load_edition(name)
    s = score(corpus, recorded_groups(corpus), related_pairs(name))
    assert len(s.false_merges) == {"2026-10-07-rc12-r1.json": 19, "2026-10-07-rc12-r2.json": 7}[name]


@pytest.mark.parametrize("name", RC12C_EDITIONS)
def test_rc12c_published_these_false_merges_on_the_pc(name):
    """The rc12c refreshes on the user's PC (13:41, 13:50; rc12b gate on nomic-embed-text): Kimmel's monologue in
    the Trump Accounts story, Eva Marie Saint in Frank Mancuso's obituary, three polls, two 'retreats', Belgium in
    France's protests, two RTX Spark laptops. The fixes are below and in the replay test."""
    corpus = load_edition(name)
    s = score(corpus, recorded_groups(corpus), related_pairs(name))
    assert len(s.false_merges) == {"2026-10-07-rc12c-r1.json": 19, "2026-10-07-rc12c-r2.json": 7}[name]


#: False merges still open, by edition (each has a strict xfail test of its own below)
OPEN_FALSE_MERGES = {"2026-10-07-rc12c-r1.json": {frozenset((
    "Microsoft and Nvidia launch Surface Laptop Ultra with RTX Spark",
    "Nvidia RTX Spark for $2,999.99: HP leak reveals RTX Spark laptop pricing ahead of launch"))}}


#: False merges the gate prevents only at a real run's proportions with the cosines the PC recorded: in this
#: 72-report edition 'Trump' is in 4 titles (scarce), and replayed vectors put the golf club at cosine 0.96 with
#: the forces' retreat (0.70 and 0.76 on the PC). test_a_common_name_and_one_word_never_attach_a_lone_report
#: rebuilds the real run.
SMALL_RUN_MERGES = {"2026-10-07-rc12d-r2.json": {frozenset((
    "From Iran to the U.K., Trump Is Being Forced Into Retreat",
    "Trump wants to turn his private golf club into a presidential retreat")), frozenset((
    "Trump's Retreat: From the Gulf to Britain, American Forces Pull Back",
    "Trump wants to turn his private golf club into a presidential retreat"))}}


@pytest.mark.parametrize("name", EDITIONS)
def test_no_false_merges_when_rc11_neighbourhoods_are_replayed(name, tmp_path):
    corpus = load_edition(name)
    outcome, groups = run_clusterer(corpus, replay_vectors(corpus), tmp_path)
    s = score(corpus, groups, related_pairs(name))
    known = OPEN_FALSE_MERGES.get(name, set()) | SMALL_RUN_MERGES.get(name, set())
    unexpected = [m for m in s.false_merges if frozenset(m) not in known]
    assert unexpected == [], unexpected
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


def test_hacked_shop_notification_is_not_wikimedias_rogue_agents(tmp_path):
    """Case E (the first real-model benchmark on the user's PC, October 7, nomic-embed-text + identity gate):
    'Asos confirms hackers sent 'unauthorised' notification to app users' joined Wikimedia's report on OpenAI's
    rogue agents through 'confirms' in both titles and 'sent', 'third-party' in both page leads. A reporting
    verb and words common in the run's page text are not evidence of one event."""
    corpus = load_edition("2026-10-07-selftest-r2.json")
    rnd = random.Random(3)
    wiki = [_id(corpus, p) for p in ('OpenAI "rogue" agent', "OpenAI agents tried to hack", "Wikimedia confirms OpenAI")]
    asos = _id(corpus, "Asos confirms hackers")
    topic = [rnd.gauss(0, 1) for _ in range(32)]
    vectors = {}
    for c in corpus:
        i = c.item.item_id
        noise = [rnd.gauss(0, 1) for _ in range(32)]
        weight = 0.15 if i in wiki else 0.9 if i == asos else 3.0  # Asos: cosine ~0.6 to the Wikimedia reports
        vectors[i] = _unit([t + weight * n for t, n in zip(topic, noise)])
    _, groups = run_clusterer(corpus, vectors, tmp_path)
    assert any(_together(groups, a, b) for a, b in combinations(wiki, 2))  # the Wikimedia story still forms
    assert not any(_together(groups, asos, w) for w in wiki)
    corpus, index = _index("2026-10-07-selftest-r2.json")
    for w in wiki:
        assert not index.gate.decide(asos, w).support


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
    for a, b in combinations(sorted(vectors), 2):
        index.gate.decide(a, b)
    log = index.gate.pair_log(limit=60)
    # accepted pairs make the stories (a false merge is found among them): they come first and survive the limit;
    # then refusals, then undecided pairs, roundup refusals last
    ranks = [3 if "roundup" in d["reasons"][0] else ["accept", "reject", "neutral"].index(d["verdict"]) for d in log]
    assert ranks == sorted(ranks) and ranks[0] == 0
    accepted = sum(d.verdict == ACCEPT for d in index.gate.decisions())
    assert ranks.count(0) == min(accepted, 60)


def test_merge_pass_never_grows_a_story_one_lone_report_at_a_time(monkeypatch):
    """Case F (the first rc12 refresh on the user's PC, October 7): after grouping, the merge pass tried every
    story with every single report and accepted the union when the lone report 'fitted' that one story, which
    skips the grouping step's rule that exactly one story of the run must qualify. One report at a time,
    'Hegseth's handling of Iran war', a DIY-fertilizer story and Michigan's Mike Rogers on Canada joined the
    leaked Paxton audio. Merging two drafts needs accepted pairs; lone reports are attached once, by grouping."""
    import agent_reach.pipeline.event_identity as ei
    from agent_reach.config import Settings
    from agent_reach.pipeline.clusterer import DraftCluster

    now = RawTrendItem(title="x", source=SourceName.NEWS_RSS).timestamp
    titles = ["Paxton privately blames campaign woes on Iran war, gas prices",
              "Paxton admits Trump's Iran war and US gas prices are plaguing Republicans in leaked audio",
              "Hegseth's handling of Iran war",
              "DIY fertilizer is a blessing as farmers face steep prices due to the Iran war"]
    items = [CleanedTrendItem(item_id=i, title=t, normalized_title=t, source=SourceName.NEWS_RSS, heuristic_score=0.5,
                              timestamp=now) for i, t in enumerate(titles, 1)]
    index = LinkIndex(items, items)
    index._gate = TableGate(index, {(1, 2): ACCEPT})
    index._gate.vectors = {i: [1.0] for i in range(1, 5)}  # with embeddings: the attach pass runs

    def attach_everything(groups, gate):  # every lone report 'fits' the story it is offered
        stories = [g for g in groups if len(g) >= 2]
        lone = [x for g in groups if len(g) == 1 for x in g]
        return [stories[0] + lone] if stories else groups
    monkeypatch.setattr(ei, "_attach_supported", attach_everything)
    assert index.components([1, 2, 3], []) == [[1, 2, 3]]  # what the old merge pass asked
    clusterer = SemanticClusterer(Settings())
    drafts = [DraftCluster([1, 2], "Paxton", "News"), DraftCluster([3], "Hegseth", "News"),
              DraftCluster([4], "Fertilizer", "News")]
    merged = clusterer._deterministic_merge(drafts, index)
    assert sorted(sorted(d.item_ids) for d in merged) == [[1, 2], [3], [4]]


def test_first_rc12_refresh_cases_stay_apart(tmp_path):
    """Case G (rc12 on the user's PC, October 7, 12:13): with the edition's own neighbourhoods replayed as embeddings,
    the Paxton leak, France's stun-grenade ban and OpenAI's agents at Wikipedia keep only their own reports."""
    corpus, groups = _replayed_groups("2026-10-07-rc12-r1.json", tmp_path)
    paxton = [_id(corpus, "Exclusive: Paxton privately blames"), _id(corpus, "Paxton admits Trump's Iran war")]
    assert _together(groups, *paxton)
    for other in ("Michigan's Mike Rogers", "Hegseth's handling of Iran war", "DIY fertilizer"):
        assert not any(_together(groups, _id(corpus, other), p) for p in paxton)
    france = _id(corpus, "France halts use of stun grenades")
    assert not _together(groups, france, _id(corpus, "Belgian students rally"))
    assert not _together(groups, _id(corpus, "OpenAI agents tried to hack"), _id(corpus, "South Korea says AI agents"))
    assert not _together(groups, _id(corpus, "Tropical Storm Isaias forms"), _id(corpus, "G2 geomagnetic storm"))
    corpus, index = _index("2026-10-07-rc12-r1.json")
    d = index.gate.decide(_id(corpus, "OpenAI agents tried to hack"), _id(corpus, "South Korea says AI agents"))
    assert d.verdict != ACCEPT  # 'agents' is a broad concept and 'hack' a kind of event: neither says which event
    d = index.gate.decide(_id(corpus, "France halts use of stun grenades"), _id(corpus, "Belgian students rally"))
    assert d.verdict != ACCEPT  # 'France' + 'protests': who and what kind, not what happened


def test_rc12c_refresh_cases_stay_apart(tmp_path):
    """Case H (rc12c on the user's PC, October 7, 13:41): a lone report joined a story through one everyday title
    word ('dies', 'president') plus a name or word only the PAGES share; "don't" + 'poll' counted as two
    distinctive phrases; 'Congress' in both titles counted as a rare shared name; 'student protests' counted as two
    shared words (Belgium's protests joined France's)."""
    corpus, groups = _replayed_groups("2026-10-07-rc12c-r1.json", tmp_path)
    mancuso = [_id(corpus, "Frank G. Mancuso Sr. Dies"), _id(corpus, "Frank Mancuso Sr., Former Chief")]
    assert _together(groups, *mancuso)
    assert not any(_together(groups, _id(corpus, "Oscar-winning actress Eva Marie Saint"), m) for m in mancuso)
    accounts = [_id(corpus, "WATCH: Trump announces eligible"), _id(corpus, "President Trump announces automatic")]
    assert not any(_together(groups, _id(corpus, "Jimmy Kimmel on Trump"), a) for a in accounts)
    polls = [_id(corpus, p) for p in ("Most US voters say", "As voters weigh incumbents", "Americans don't want")]
    for a, b in combinations(polls, 2):
        assert not _together(groups, a, b)
    corpus, index = _index("2026-10-07-rc12c-r1.json")
    d = index.gate.decide(_id(corpus, "Most US voters say"), _id(corpus, "Americans don't want"))
    assert d.verdict != ACCEPT and "don't" not in d.shared  # a negation is no subject
    assert not index.shares_name(_id(corpus, "Most US voters say"), _id(corpus, "As voters weigh incumbents"),
                                 rare=True, titles=True)  # 'Congress' says where, not what
    photos, belgium = _id(corpus, "Photos: The Student Protests in France"), _id(corpus, "Over 100 arrested in Belgium")
    assert not index.link_evidence(photos, belgium)[0]  # 'student protests' is one phrase, one piece of evidence
    pike = [c.item.item_id for c in corpus if c.title == "Christa Pike"]
    assert pike and index.link_evidence(pike[0], _id(corpus, "Christa Pike 'conscious and speaking'"))[0]


def test_rc12d_refresh_cases_stay_apart(tmp_path):
    """Case H (rc12d on the user's PC, October 7, 16:43): 'Gaza' + 'war' counted as two distinctive phrases and put
    a Gaza child's illness in the October 7 anniversary story; Nature's 'Nobel Prizes 2026' (its lead names the
    medicine and physics prizes too) joined the chemistry prize."""
    corpus, groups = _replayed_groups("2026-10-07-rc12d-r2.json", tmp_path)
    mourn = [_id(corpus, "Israelis mourn Oct. 7 attack"), _id(corpus, "Israelis mourn 7 October attack")]
    assert _together(groups, *mourn)
    assert not any(_together(groups, _id(corpus, "Gaza child"), m) for m in mourn)
    chemistry = [_id(corpus, p) for p in ("Nobel Prize in Chemistry 2026 to", "Henri B. Kagan and Kenso Soai win",
                                          "Nobel prize in chemistry awarded")]
    assert all(_together(groups, chemistry[0], c) for c in chemistry[1:])
    nature = _id(corpus, "Nobel Prizes 2026: brain switches")
    assert not any(_together(groups, nature, c) for c in chemistry)
    corpus, index = _index("2026-10-07-rc12d-r2.json")
    assert not index.link_evidence(_id(corpus, "Gaza child"), _id(corpus, "Israelis mourn Oct. 7 attack"))[0]
    assert _id(corpus, "Nobel Prizes 2026: brain switches") in index.roundups
    assert _id(corpus, "Nobel Prize in Chemistry 2026 to") not in index.roundups


def test_a_common_name_and_one_word_need_the_embedding_too():
    """Case H: in a real run (1,329 reports) a name counted as rare up to 6% of the run, so 'Trump' + 'retreat'
    were two distinctive phrases and US forces pulling back joined Trump's golf-club 'presidential retreat'
    (cosine 0.69). A name in more than 2% of the run plus one specific word now needs strong embedding agreement:
    'Russia' + 'plague' stays one event."""
    import random

    now = RawTrendItem(title="x", source=SourceName.NEWS_RSS).timestamp
    rnd = random.Random(3)

    def word() -> str:
        return "".join(rnd.choice("bcdfghklmnprstvz") + rnd.choice("aeiou") for _ in range(4))

    titles = ["From Iran to the U.K., Trump is being forced into retreat",
              "Trump wants to turn Florida golf course into presidential retreat",
              "Trump's retreat: from the Gulf to Britain, American forces pull back",
              "Trump wants to turn his private golf club into a presidential retreat"]
    titles += [f"Officials say Trump weighs {word()} plan for {word()}" for _ in range(30)]
    titles += [f"Regulators review {word()} rules for {word()} growers" for _ in range(600)]
    items = [CleanedTrendItem(item_id=i, title=t, normalized_title=t, source=SourceName.NEWS_RSS, heuristic_score=0.5,
                              timestamp=now) for i, t in enumerate(titles, 1)]
    index = LinkIndex(items, items)
    assert index.name_cap < index.df["trump"] <= index.rare_cap  # as on the PC: 'Trump' is 'rare' at 6%
    assert index.link_evidence(1, 2)[2] == COMMON_NAME_AND_PHRASE and not index.link_evidence(1, 2)[0]
    assert index.link_evidence(2, 4)[0]  # the two golf-club reports share their whole wording
    far = [0.69, (1 - 0.69 ** 2) ** 0.5]
    index.attach_vectors({**{i: [1.0, 0.0] for i in index.items}, 2: far, 4: far}, 0.45, 0.8)
    assert index.gate.decide(1, 2).verdict == NEUTRAL and index.gate.decide(2, 4).verdict == ACCEPT
    index.attach_vectors({i: [1.0, 0.0] for i in index.items}, 0.45, 0.8)  # the embedding sees one event
    assert index.gate.decide(1, 2).verdict == ACCEPT


def test_a_common_name_and_one_word_never_attach_a_lone_report():
    """Case H again, rc12d on the PC: the golf-club report was alone in its run, and a lone report joined the US
    forces story because the attach rule still counted 'Trump' as a rare name (6% of the run) while the pair rule
    already called it common (2%). It was neutral with both members (cosine 0.76 and 0.70), as here."""
    now = RawTrendItem(title="x", source=SourceName.NEWS_RSS).timestamp
    rnd = random.Random(5)

    def word() -> str:
        return "".join(rnd.choice("bcdfghklmnprstvz") + rnd.choice("aeiou") for _ in range(4))

    titles = ["From Iran to the U.K., Trump Is Being Forced Into Retreat",
              "Trump's Retreat: From the Gulf to Britain, American Forces Pull Back",
              "Trump wants to turn his private golf club into a presidential retreat"]
    titles += [f"Officials say Trump weighs {word()} plan for {word()}" for _ in range(15)]
    titles += [f"Officials say Trump's {word()} plan for {word()} stalls" for _ in range(15)]
    titles += [f"Regulators review {word()} rules for {word()} growers" for _ in range(600)]
    items = [CleanedTrendItem(item_id=i, title=t, normalized_title=t, source=SourceName.NEWS_RSS, heuristic_score=0.5,
                              timestamp=now) for i, t in enumerate(titles, 1)]
    index = LinkIndex(items, items)
    assert index.name_cap < index.name_df("trump") <= index.rare_cap  # as on the PC
    # the recorded cosines: forces 0.868 with each other; the golf club 0.757 and 0.701 with them
    y = (0.701 - 0.868 * 0.757) / (1 - 0.868 ** 2) ** 0.5
    vectors = {i: [0.0, 0.0, 0.0, 1.0] for i in index.items}
    vectors.update({1: [1.0, 0.0, 0.0, 0.0], 2: [0.868, (1 - 0.868 ** 2) ** 0.5, 0.0, 0.0],
                    3: [0.757, y, (1 - 0.757 ** 2 - y ** 2) ** 0.5, 0.0]})
    index.attach_vectors(vectors, 0.45, 0.8)
    gate = index.gate
    assert gate.decide(1, 2).verdict == ACCEPT
    assert gate.decide(1, 3).verdict == NEUTRAL and gate.decide(2, 3).verdict == NEUTRAL
    assert cohesive_groups([1, 2, 3], gate) == [[1, 2], [3]]


@pytest.mark.xfail(strict=True, reason="open: two RTX Spark laptop stories share five title words (October 7, rc12c)")
def test_two_laptops_with_one_chip_are_two_stories(tmp_path):
    """Microsoft's Surface Laptop Ultra launch and an HP price leak share 'Nvidia RTX Spark laptop launch': the
    words say which chip, not which event. No rule yet tells a product name from what happened."""
    corpus, groups = _replayed_groups("2026-10-07-rc12c-r1.json", tmp_path)
    assert not _together(groups, _id(corpus, "Microsoft and Nvidia launch Surface"), _id(corpus, "Nvidia RTX Spark for"))
