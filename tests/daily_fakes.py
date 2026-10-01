"""Deterministic offline fixtures for Agent Reach Daily: fake publisher feeds, article pages
and a fake local model. Nothing here touches the network or a real Ollama.

All stories are SYNTHETIC (fictional places, products and teams on ``.test`` hosts). They cover
the six edition categories, several publication ages (fresh, a day old, a stale week-old story,
no stated publication time) and enough cross-source corroboration for the real density
clustering, coherence checks and ledger to form a complete edition.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from email.utils import format_datetime
from datetime import datetime, timezone

import httpx

from tests.fakes import RealAsyncClient

NOW = time.time()


def _ago(hours: float) -> str:
    return format_datetime(datetime.fromtimestamp(NOW - hours * 3600, tz=timezone.utc))


# topic key -> (category, label headline, two-sentence summary, entities, relevance, keywords)
TOPICS: dict[str, dict] = {
    "harbor": dict(category="News", headline="Norvale Harbor Ferry Strike Halts Island Service",
                   summary="Ferry workers in Norvale began a 48-hour strike over pay, halting service to three islands. "
                           "The port authority said talks with the union resume on Friday.",
                   entities=["Norvale", "Norvale Port Authority"], relevance=8,
                   keywords=["norvale", "ferry strike"]),
    "summit": dict(category="News", headline="Coastal Nations Agree Methane Pledge at Lumen Summit",
                   summary="Delegates at the Lumen climate summit agreed to cut methane leaks by 30 percent by 2035. "
                           "Twelve coastal nations signed the pledge on the final day.",
                   entities=["Lumen Summit"], relevance=9, keywords=["lumen", "methane pledge"]),
    "quake": dict(category="News", headline="Magnitude 6.8 Earthquake Strikes Near Port Calder",
                  summary="A magnitude 6.8 earthquake struck near Port Calder early on Wednesday. "
                          "Officials reported damaged roads and no confirmed deaths.",
                  entities=["Port Calder"], relevance=9, keywords=["port calder", "earthquake"]),
    "final": dict(category="Sports", headline="Riverton Hawks Win Championship Final in Overtime",
                  summary="The Riverton Hawks beat the Glenmore Owls 3-2 in overtime to win the championship final. "
                          "Captain Ana Brill scored the winning goal.",
                  entities=["Riverton Hawks", "Glenmore Owls"], relevance=8, keywords=["riverton hawks", "glenmore owls"]),
    "marathon": dict(category="Sports", headline="Kestrel City Marathon Sets Course Record",
                     summary="Runner Joel Okafor set a course record of 2:04:51 at the Kestrel City marathon. "
                             "Organisers said 31,000 people finished the race.",
                     entities=["Kestrel City Marathon", "Joel Okafor"], relevance=7, keywords=["kestrel city marathon"]),
    "film": dict(category="Entertainment", headline="Halcyon Studio Film Northern Lantern Tops Box Office",
                 summary="Northern Lantern, the new Halcyon Studio drama, opened at number one with $48 million. "
                         "Critics praised its lead performance.",
                 entities=["Northern Lantern", "Halcyon Studio"], relevance=7, keywords=["northern lantern"]),
    "exoplanet": dict(category="Science & AI", headline="Astronomers Detect Water Vapour on Exoplanet Tessa-9b",
                      summary="Astronomers using the Orion space telescope detected water vapour on the exoplanet Tessa-9b. "
                              "The planet orbits a red dwarf 120 light years away.",
                      entities=["Tessa-9b", "Orion telescope"], relevance=8, keywords=["tessa-9b", "water vapour"]),
    "model": dict(category="Science & AI", headline="Corvid Labs Releases Open Model Corvid-3",
                  summary="Corvid Labs released Corvid-3, an open-weight language model, under a permissive licence. "
                          "Developers began publishing benchmark results within hours.",
                  entities=["Corvid Labs", "Corvid-3"], relevance=8, keywords=["corvid-3", "corvid labs"]),
    "ransomware": dict(category="Tech", headline="Ransomware Attack Disrupts Halden Hospital Network",
                       summary="A ransomware attack disrupted computer systems at hospitals in the Halden region. "
                               "Staff switched to paper records while the network was restored.",
                       entities=["Halden"], relevance=8, keywords=["halden hospital", "ransomware"]),
    "fridge": dict(category="Tech", headline="Firmware Update Bricks Frostline Smart Fridges",
                   summary="A faulty Frostline firmware update disabled thousands of smart fridges. "
                           "The company said a fix is rolling out this week.",
                   entities=["Frostline"], relevance=7, keywords=["frostline"]),
    "stale": dict(category="News", headline="Mayor of Oakdene Resigns After Audit",
                  summary="The mayor of Oakdene resigned after an audit found missing funds. "
                          "The city council appointed an interim mayor.",
                  entities=["Oakdene"], relevance=7, keywords=["oakdene"]),
}

#: Feed items: (feed key, title, link host/path, hours ago or None for no pubDate, description)
FEED_ITEMS: dict[str, list[tuple[str, str, float | None, str]]] = {
    "world": [
        ("Norvale ferry strike halts island service as workers walk out", "https://wire-one.test/norvale-ferry-strike", 3,
         "Ferry workers in Norvale began a 48-hour strike over pay."),
        ("Lumen summit: coastal nations agree methane pledge", "https://wire-one.test/lumen-methane-pledge", 5,
         "Delegates agreed to cut methane leaks by 30 percent by 2035."),
        ("Magnitude 6.8 earthquake strikes near Port Calder", "https://wire-one.test/port-calder-earthquake", 2,
         "Officials reported damaged roads near Port Calder."),
        ("Oakdene mayor resigns after audit finds missing funds", "https://wire-one.test/oakdene-mayor-audit", 160,
         "The mayor of Oakdene resigned after an audit."),
    ],
    "us": [
        ("Norvale ferry strike: island service halted by pay dispute", "https://daily-two.test/norvale-strike", 4,
         "Service to three islands is halted."),
        ("Coastal nations sign Lumen summit methane pledge", "https://daily-two.test/lumen-summit-pledge", 6,
         "Twelve coastal nations signed the methane pledge."),
        ("Port Calder earthquake: magnitude 6.8 quake damages roads", "https://daily-two.test/calder-quake", 1,
         "No deaths were confirmed after the earthquake."),
        ("Oakdene mayor resigns as audit reveals missing funds", "https://daily-two.test/oakdene-resigns", 150,
         "The city council appointed an interim mayor."),
    ],
    "sports": [
        ("Riverton Hawks beat Glenmore Owls in overtime championship final", "https://sports-three.test/hawks-owls-final", 8,
         "Ana Brill scored the winning goal in overtime."),
        ("Kestrel City marathon course record falls to Joel Okafor", "https://sports-three.test/kestrel-marathon", 20,
         "Joel Okafor ran 2:04:51."),
        ("Glenmore Owls fall to Riverton Hawks in overtime championship final", "https://sports-three.test/owls-fall", 7,
         "The Riverton Hawks won 3-2."),
        ("Kestrel City marathon: Okafor sets course record in 2:04:51", "https://sports-three.test/okafor-record", 19,
         "31,000 people finished the Kestrel City marathon."),
    ],
    "arts": [
        ("Northern Lantern tops box office for Halcyon Studio", "https://arts-four.test/northern-lantern-box-office", 30,
         "Northern Lantern opened with $48 million."),
        ("Halcyon Studio drama Northern Lantern opens at number one box office", "https://arts-four.test/lantern-opens", None,
         "Critics praised the lead performance."),
    ],
    "science": [
        ("Water vapour detected on exoplanet Tessa-9b by Orion telescope", "https://science-five.test/tessa-9b-water", 10,
         "The planet orbits a red dwarf 120 light years away."),
        ("Orion telescope finds water vapour on exoplanet Tessa-9b", "https://science-five.test/orion-tessa", 11,
         "Astronomers detected water vapour."),
        ("Corvid Labs releases open model Corvid-3", "https://science-five.test/corvid-3", 9,
         "Corvid-3 is an open-weight language model."),
    ],
}

#: Google News items (aggregator): (title with " - Publisher", hours ago)
GOOGLE_NEWS = [
    ("Port Calder earthquake of magnitude 6.8 damages roads - Wire One", 2),
    ("Norvale ferry strike halts island service - Daily Two", 3),
    ("Lumen summit methane pledge agreed by coastal nations - Wire One", 5),
]

#: Hacker News front page (tech): (title, url, hours ago, points)
HN = [
    ("Corvid-3: Corvid Labs releases open model weights", "https://corvid-labs.test/blog/corvid-3", 8, 900),
    ("Ransomware attack disrupts Halden hospital network", "https://tech-six.test/halden-hospital-ransomware", 6, 650),
    ("Halden hospital ransomware attack forces paper records", "https://tech-six.test/halden-paper", 5, 400),
    ("Frostline firmware update bricks smart fridges", "https://tech-six.test/frostline-fridges", 12, 700),
    ("Frostline smart fridges bricked by firmware update", "https://frostline.test/status", 11, 300),
]

PAGES: dict[str, tuple[str, str]] = {
    "wire-one.test/norvale-ferry-strike": ("Norvale ferry strike halts island service",
                                           "Ferry workers in Norvale began a 48-hour strike over pay on Tuesday, halting service to three islands. "
                                           "The Norvale Port Authority said talks with the union resume on Friday."),
    "wire-one.test/lumen-methane-pledge": ("Coastal nations agree methane pledge",
                                           "Delegates at the Lumen climate summit agreed to cut methane leaks by 30 percent by 2035. "
                                           "Twelve coastal nations signed the pledge, which affects offshore gas operators."),
    "wire-one.test/port-calder-earthquake": ("Earthquake strikes near Port Calder",
                                             "A magnitude 6.8 earthquake struck near Port Calder early on Wednesday. Officials reported "
                                             "damaged roads and no confirmed deaths. Schools in the region will stay closed until inspections finish."),
    "sports-three.test/hawks-owls-final": ("Hawks win final",
                                           "The Riverton Hawks beat the Glenmore Owls 3-2 in overtime. Captain Ana Brill scored the winning goal."),
    "science-five.test/tessa-9b-water": ("Water vapour on Tessa-9b",
                                         "Astronomers using the Orion space telescope detected water vapour on Tessa-9b, "
                                         "which orbits a red dwarf 120 light years away."),
    "tech-six.test/halden-hospital-ransomware": ("Ransomware hits Halden hospitals",
                                                 "A ransomware attack disrupted computer systems at hospitals in the Halden region. "
                                                 "Staff switched to paper records and some planned operations were postponed."),
}


def _page(title: str, para: str) -> str:
    return (f"<html><head><title>{title}</title><meta name=\"description\" content=\"{para[:150]}\"></head>"
            f"<body><article><h1>{title}</h1><p>{para}</p></article></body></html>")


def _rss(items: str, title: str = "Fake feed") -> bytes:
    return f'<?xml version="1.0"?><rss><channel><title>{title}</title>{items}</channel></rss>'.encode()


def _rss_item(title: str, link: str, hours: float | None, desc: str) -> str:
    pub = f"<pubDate>{_ago(hours)}</pubDate>" if hours is not None else ""
    return f"<item><title>{title}</title><link>{link}</link>{pub}<description>{desc}</description></item>"


FEED_TITLES = {"world": "Wire One - World", "us": "Daily Two - US", "sports": "Sports Three",
               "arts": "Arts Four", "science": "Science Five"}
FEED_CATEGORY = {"world": "News", "us": "News", "sports": "Sports", "arts": "Entertainment", "science": "Science & AI"}


def feed_settings_entries() -> list[str]:
    return [f"{FEED_CATEGORY[k]}|https://feeds.test/{k}.xml" for k in FEED_ITEMS]


class FakeNet:
    """HTTP handler with switchable failures (e.g. one feed down, everything down)."""

    def __init__(self) -> None:
        self.down: set[str] = set()  # feed keys or hosts that return 503
        self.offline = False
        self.requests: list[str] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        host, path = req.url.host, req.url.path
        self.requests.append(f"{host}{path}")
        if self.offline:
            raise httpx.ConnectError("network is unreachable", request=req)
        if host in self.down:
            return httpx.Response(503)
        if host == "feeds.test":
            key = path.strip("/").removesuffix(".xml")
            if key in self.down:
                return httpx.Response(503)
            items = "".join(_rss_item(*row) for row in FEED_ITEMS.get(key, []))
            return httpx.Response(200, content=_rss(items, FEED_TITLES.get(key, key)))
        if "news.google" in host:
            items = "".join(
                f"<item><title>{t}</title><link>https://news.google.com/rss/articles/{i}</link>"
                f"<pubDate>{_ago(h)}</pubDate><source url=\"https://{t.rsplit(' - ', 1)[1].lower().replace(' ', '-')}.test\">"
                f"{t.rsplit(' - ', 1)[1]}</source></item>"
                for i, (t, h) in enumerate(GOOGLE_NEWS))
            return httpx.Response(200, content=_rss(items, "Google News"))
        if "algolia" in host:
            hits = [{"objectID": str(i), "title": t, "url": u, "points": p, "num_comments": 80,
                     "created_at_i": int(NOW - h * 3600)} for i, (t, u, h, p) in enumerate(HN)]
            return httpx.Response(200, json={"hits": hits})
        key = f"{host}{path}"
        if key in PAGES:
            return httpx.Response(200, text=_page(*PAGES[key]), headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404)

    def client_class(self):
        net = self

        class _Client(RealAsyncClient):
            def __init__(self, *a, **k):
                k["transport"] = httpx.MockTransport(net.handler)
                super().__init__(*a, **k)

        return _Client


# ------------------------------------------------------------------------- fake model
def _topic_of(text: str) -> str | None:
    t = text.lower()
    best, hits = None, 0
    for key, spec in TOPICS.items():
        n = sum(t.count(k) for k in spec["keywords"])
        if n > hits:
            best, hits = key, n
    return best


def fake_vec(text: str) -> list[float]:
    t = text.lower()
    keys = list(TOPICS)
    v = [0.0] * (len(keys) + 4)
    for d, key in enumerate(keys):
        v[d] += sum(3.0 for k in TOPICS[key]["keywords"] if k in t)
    for w in re.findall(r"[a-z]+", t):
        v[len(keys) + int(hashlib.md5(w.encode()).hexdigest(), 16) % 4] += 0.1
    return v


#: Brief-pass answers per topic: (details, why_it_matters). Some are deliberately ungrounded.
BRIEF_ANSWERS = {
    "harbor": ("Service to three islands is halted.", "Island residents lose their ferry link while the 48-hour strike lasts."),
    "summit": ("", "The pledge affects offshore gas operators in the twelve signing nations."),
    "quake": ("Schools in the region will stay closed until inspections finish.",
              "Families near Port Calder face school closures until inspections finish."),
    # invented name + invented number: must be rejected
    "final": ("", "Coach Marta Velez said the win earns the Hawks a $5 million bonus."),
    # generic filler: must be rejected
    "film": ("", "This highlights the importance of the film industry for the region."),
    # hedged speculation not present in the evidence: must be rejected
    "exoplanet": ("", "This could transform the search for life across the galaxy."),
    "ransomware": ("Some planned operations were postponed.",
                   "Patients in the Halden region face postponed operations while systems are restored."),
}


class FakeDailyModel:
    """Fake Ollama AsyncClient: embeddings, group labels and brief answers. Counts every call."""

    def __init__(self, *, brief_raises: bool = False, brief_garbage: bool = False) -> None:
        self.calls = {"embed": 0, "chat": 0, "brief": 0, "label": 0}
        self.brief_raises = brief_raises
        self.brief_garbage = brief_garbage

    async def list(self):
        class Mdl:
            model = "llama3.1:8b"

        class L:
            models = [Mdl()]

        return L()

    async def embed(self, model, input, keep_alive=None):
        self.calls["embed"] += 1
        return {"embeddings": [fake_vec(x) for x in input]}

    async def chat(self, model, messages, format, options, keep_alive):
        self.calls["chat"] += 1
        user = messages[1]["content"]
        if "Story 1:" in user:
            return self._brief(user)
        self.calls["label"] += 1
        out = []
        for gid, body in re.findall(r"^Group (\d+):\n((?:  - .*\n?)+)", user, re.M):
            key = _topic_of(body)
            if key is None:
                out.append(dict(group_id=gid, headline="Unrelated Items", category="News", primary_entities=[],
                                summary="[INSUFFICIENT_DATA]", relevance_score=1))
                continue
            spec = TOPICS[key]
            out.append(dict(group_id=gid, headline=spec["headline"], category=spec["category"],
                            primary_entities=spec["entities"], summary=spec["summary"],
                            relevance_score=spec["relevance"]))
        return {"message": {"content": json.dumps({"groups": out, "assignments": []})}}

    def _brief(self, user: str):
        self.calls["brief"] += 1
        if self.brief_raises:
            raise ConnectionError("model went away")
        if self.brief_garbage:
            return {"message": {"content": "Sorry, I cannot help with that."}}
        stories = []
        for sid, body in re.findall(r"^Story (\d+):\n((?:  .*\n?)+)", user, re.M):
            key = _topic_of(body)
            details, why = BRIEF_ANSWERS.get(key, ("", ""))
            stories.append({"id": int(sid), "details": details, "why_it_matters": why})
        return {"message": {"content": json.dumps({"stories": stories})}}


class OllamaUp:
    """Stand-in for prereqs.OllamaStatus when the model is available."""

    reachable = True
    models = ["llama3.1:8b", "nomic-embed-text:latest"]
    missing: list[str] = []
    error = None

    def describe(self) -> str:
        return "Ollama is running with the required models."


class OllamaDown:
    reachable = False
    models: list[str] = []
    missing: list[str] = []
    error = "ConnectError: connection refused"

    def describe(self) -> str:
        return "Ollama is not running at http://localhost:11434."


# ------------------------------------------------------------------------- edition builders
def make_story(rank: int = 1, *, headline: str = "Norvale Ferry Strike Halts Island Service", category: str = "News",
               hours_ago: float | None = 3, now: datetime | None = None, entity_id: str | None = None,
               url: str | None = None, platforms: list[str] | None = None, relevance: int = 8, items: int = 2,
               tech_only: bool = False, labels: list[str] | None = None, why: str | None = None,
               sentences: list[str] | None = None):
    from datetime import timedelta

    from agent_reach.daily.edition import EvidenceLink, Story

    now = now or datetime.now(timezone.utc)
    published = now - timedelta(hours=hours_ago) if hours_ago is not None else None
    slug = re.sub(r"[^a-z0-9]+", "-", headline.lower()).strip("-")
    return Story(
        rank=rank, story_id=f"ev-{slug}", entity_id=entity_id if entity_id is not None else f"ent-{slug}",
        headline=headline, category=category, sentences=sentences or [f"{headline} according to two reports."],
        why_it_matters=why, labels=labels or [], momentum="BASELINE", velocity_basis="cold_start",
        relevance_score=relevance, velocity_score=50.0, combined_score=float(relevance * 10),
        platforms=platforms or ["news_rss"], raw_item_count=items, member_item_ids=list(range(1, items + 1)),
        tech_only=tech_only,
        evidence=[EvidenceLink(item_id=1, source=(platforms or ["news_rss"])[0], source_name="News feeds",
                               title=headline, url=url or f"https://wire-one.test/{slug}", publisher="Wire One",
                               excerpt="Excerpt text.", published_at_utc=published, retrieved_at_utc=now)],
    )


def make_edition(stories=None, *, started: datetime | None = None, demo: bool = False, run_id: str = "run-1"):
    from datetime import timedelta

    from agent_reach.daily.edition import AccountingSummary, Coverage, DailyEdition, ModelInfo, SourceHealth
    from agent_reach.daily.timeutil import central_date

    started = started or datetime(2026, 10, 1, 12, 5, tzinfo=timezone.utc)
    stories = stories if stories is not None else [make_story(1, now=started),
                                                   make_story(2, headline="Port Calder Earthquake Damages Roads", now=started),
                                                   make_story(3, headline="Riverton Hawks Win Final", category="Sports", now=started)]
    for i, s in enumerate(stories, start=1):
        s.rank = i
    return DailyEdition(
        demo=demo, edition_date=central_date(started), run_id=run_id, trigger="manual",
        generation_started_utc=started, generation_completed_utc=started + timedelta(minutes=15),
        model=ModelInfo(llm_model="llama3.1:8b", embed_model="nomic-embed-text", pipeline_mode="ollama", summaries="local_model"),
        config_fingerprint="abc", pipeline_schema_version=3,
        accounting=AccountingSummary(ingested=10, passed_filters=8, clustering_candidates=8, clustered=6,
                                     discarded_total=4, balanced=True),
        source_health=[SourceHealth(source="news_rss", name="News feeds", status="ok", item_count=10)],
        coverage=Coverage(sources_attempted=1, sources_ok=1, category_counts={"News": 2, "Sports": 1},
                          general_news_available=True, balanced=True),
        overview=f"{len(stories)} stories.", stories=stories,
    )
