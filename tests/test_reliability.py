"""Offline regressions for the v2.1 reliability boundaries."""
import asyncio
from collections import Counter
from datetime import timedelta
import json
import socket
import sqlite3
import time

import httpx
import pytest

from agent_reach import main
from agent_reach.config import Settings
from agent_reach.models import (CleanedTrendItem, MacroCluster, PipelineAccounting, PipelineReport,
                                RawTrendItem, SourceStat)
from agent_reach.pipeline.cleaner import TrendCleaner
from agent_reach.pipeline.clusterer import (ClusterOutcome, DraftCluster, LinkIndex,
                                           SemanticClusterer, _relabel_schema)
from agent_reach.pipeline import enricher
from agent_reach.pipeline.evidence import platforms, publishers
from agent_reach.pipeline.scorer import EntityMatcher, TrendScorer, _RefRun
from agent_reach.storage.db import SCHEMA, TrendDatabase


def item(i, title, source="hackernews", **extra):
    return CleanedTrendItem(item_id=i, title=title, normalized_title=title,
                            source=source, heuristic_score=0.8, **extra)


def test_model_assignments_cannot_change_membership(settings, monkeypatch):
    clusterer = SemanticClusterer(settings)
    rows = [item(1, "Acme launches a new database"), item(2, "Acme database launch"),
            item(3, "Acme suffers a prolonged outage")]
    async def malicious(*args):
        return {"groups": [{"group_id": 1, "headline": "Acme database launch"}],
                "assignments": [{"item_id": 1, "group_id": 1}]}
    monkeypatch.setattr(clusterer, "_chat_json", malicious)
    drafts, orphans = asyncio.run(clusterer._relabel(
        [DraftCluster([1, 2], "", "", needs_label=True)], [3], {r.item_id: r for r in rows}))
    assert drafts[0].item_ids == [1, 2] and orphans == [3]
    assert "assignments" not in _relabel_schema()["properties"]


def test_event_separation_and_label_independent_membership(settings):
    rows = [item(1, "Acme launches new database tooling"),
            item(2, "Acme launches database tools today"),
            item(3, "Acme database outage affects customers"),
            item(4, "Acme database outage disrupts customers")]
    index = LinkIndex(rows)
    assert index.components([1, 2, 3, 4], ["Acme"]) == [[1, 2], [3, 4]]
    assert index.components([1, 2, 3, 4], []) == [[1, 2], [3, 4]]
    drafts = [DraftCluster([1, 2], "Database launch", "Tech", ["Acme"], "Launch.", 8),
              DraftCluster([3, 4], "Database outage", "Tech", ["Acme"], "Outage.", 8)]
    c = SemanticClusterer(settings)
    assert len(c._deterministic_merge(drafts, index)) == 2
    clusters, _ = c._finalize(drafts, {r.item_id: r for r in rows})
    assert clusters[0].entity_id == clusters[1].entity_id
    assert clusters[0].event_id != clusters[1].event_id
    assert len(clusters) == 2
    old = rows[1].model_copy(update={"timestamp": rows[0].timestamp - timedelta(days=8)})
    assert len(LinkIndex([rows[0], old]).components([1, 2], [])) == 2


def test_same_entity_full_stories_need_event_evidence():
    rows = [item(1, "Acme Corporation announces a new campus"),
            item(2, "Acme Corporation faces an employee lawsuit")]
    assert LinkIndex(rows).components([1, 2], ["Acme Corporation"]) == [[1], [2]]
    launches = [item(1, "Acme launches database tooling today"),
                item(2, "Acme launches browser extensions today")]
    assert LinkIndex(launches).components([1, 2], ["Acme"]) == [[1], [2]]


def test_reassignment_is_unambiguous_and_coherent():
    rows = [item(1, "Acme database launches today"), item(2, "Acme database outage today"),
            item(3, "Acme")]
    drafts = [DraftCluster([1], "Launch", "Tech", ["Acme"]),
              DraftCluster([2], "Outage", "Tech", ["Acme"])]
    assert SemanticClusterer._rehome_orphans(drafts, [3], LinkIndex(rows)) == [3]
    assert [d.item_ids for d in drafts] == [[1], [2]]


def test_duplicate_provenance_and_publisher_diversity(settings):
    raw = [RawTrendItem(title="Acme releases a secure database update", source=s,
                        url="https://publisher.example/story", raw_score=1000)
           for s in ["hackernews", "google_news", "hackernews"]]
    cleaner = TrendCleaner(settings)
    clean = cleaner._score(cleaner._dedupe([(r, r.title) for r in raw], Counter()))
    assert len(clean) == 1 and len(clean[0].observations) == 3
    assert clean[0].raw_weight == 3
    assert platforms(clean) == ["google_news", "hackernews"]
    assert publishers(clean) == ["publisher.example"]
    # Repeated copies on one platform cannot inflate the size component.
    repeated = clean[0].model_copy(update={"duplicate_count": 30})
    assert TrendScorer.heuristic_relevance(clean) == TrendScorer.heuristic_relevance([repeated])


def seed(db, run_id, now, rows, sources, config=None):
    db.begin_run(run_id, now)
    db.save_context(run_id, [SourceStat(source=s, ok=ok, item_count=1, latency_ms=1)
                            for s, ok in sources.items()], config or {"region": "US"})
    db.save_items(run_id, rows, rows, now)
    n = sum(r.raw_weight for r in rows)
    report = PipelineReport(run_id=run_id, execution_time=0, ingested_count=n,
        filtered_count=n, cluster_count=0, macro_clusters=[],
        accounting=PipelineAccounting(ingested=n, passed_filters=n,
            clustering_candidates=n, clustered=0, discarded={"density_noise": n}))
    db.finish_run(report, now + 1)


def test_source_rates_are_comparable_and_outages_uncertain(settings):
    db = TrendDatabase(settings.db_path)
    now = time.time()
    try:
        before = [item(1, "Acme", "hackernews"), item(2, "Other", "hackernews"),
                  item(3, "Other", "google_news")]
        after = [item(1, "Acme", "hackernews"), item(2, "Other", "hackernews"),
                 *[item(i + 3, "Other", "google_news") for i in range(20)]]
        sources = {"hackernews": True, "google_news": True}
        seed(db, "before", now - 3600, before, sources)
        seed(db, "after", now, after, sources)
        scorer = TrendScorer(settings, db)
        refs = scorer._reference_runs("after", now)
        _, _, windows, velocity, _ = scorer._entity_velocity(EntityMatcher("Acme"), ["acme", "other"], refs)
        assert velocity == 50 and windows[0].growth == 0
        assert not scorer.coverage_uncertain
        db.save_context("after", [SourceStat(source=s, ok=s == "hackernews", item_count=1, latency_ms=1)
                                  for s in sources], {"region": "US"})
        scorer._reference_runs("after", now)
        assert scorer.coverage_uncertain
        assert scorer._momentum(90, "coverage_uncertain", True) == "UNCERTAIN"
        cluster = MacroCluster(cluster_id="acme", headline="Acme", category="Tech",
            relevance_score=8, velocity_score=50, summary="Acme observed.",
            raw_item_count=1, primary_entities=["Acme"], sources=["hackernews"], member_item_ids=[1])
        scored, _ = scorer.score_sync([cluster], after, "after", now)
        assert scored[0].momentum == "UNCERTAIN" and scored[0].velocity_score == 50
        assert scored[0].momentum_uncertain
        db.save_context("after", [], {"region": "GB"})
        assert all(r is None for r in scorer._reference_runs("after", now).values())
        assert scorer.coverage_uncertain
    finally:
        db.close()


def test_fading_is_reachable(settings):
    db = TrendDatabase(settings.db_path)
    try:
        scorer = TrendScorer(settings, db)
        refs = {1: _RefRun("before", 0, ["acme"] * 8 + ["other"] * 2)}
        _, _, _, velocity, is_new = scorer._entity_velocity(EntityMatcher("Acme"), ["acme"] + ["other"] * 9, refs)
        assert velocity < 25 and not is_new
        assert scorer._momentum(velocity, "historical", is_new) == "FADING"
    finally:
        db.close()


@pytest.mark.parametrize("ids", [[1, 1], [], [2]])
def test_partition_rejects_bad_ids(ids):
    with pytest.raises(ValueError, match="partition"):
        ClusterOutcome([], {"density_noise": ids}, "test").assert_partition([item(1, "Acme")])


def test_final_accounting_fails_closed():
    with pytest.raises(ValueError, match="unbalanced"):
        PipelineAccounting(ingested=2, passed_filters=2, clustering_candidates=2, clustered=1)


def test_failed_run_persists_diagnostics_but_cannot_be_a_baseline(mock_http, settings, monkeypatch):
    def broken(*args):
        raise ValueError("injected accounting imbalance")
    monkeypatch.setattr(main, "build_accounting", broken)
    with pytest.raises(ValueError, match="imbalance"):
        asyncio.run(main.run_once(settings, use_llm=False))
    db = TrendDatabase(settings.db_path)
    try:
        row = db._conn.execute("SELECT * FROM runs").fetchone()
        assert row["status"] == "invalid" and "imbalance" in row["diagnostics"]
        assert db.count_runs() == 0
        assert db.find_reference_run(time.time(), 0, time.time() + 60, "unused") is None
        assert db._conn.execute("SELECT COUNT(*) FROM cleaned_evidence").fetchone()[0] > 0
        assert json.loads(row["effective_config"])["enabled_sources"]
    finally:
        db.close()


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["93.184.216.34", "10.0.0.1"],
                                       ["::1"], ["169.254.169.254"], ["224.0.0.1"]])
def test_dns_rejects_every_nonpublic_answer(addresses, monkeypatch):
    async def run():
        async def dns(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses]
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
        with pytest.raises(ValueError, match="non-public"):
            await enricher._resolve_public("untrusted.example", 443)
    asyncio.run(run())


def test_redirects_pin_dns_preserve_sni_and_block_private_targets(monkeypatch):
    requests = []
    async def resolve(host, port):
        if host == "private.example":
            raise ValueError("non-public destination")
        return "93.184.216.34"
    monkeypatch.setattr(enricher, "_resolve_public", resolve)
    def handler(request):
        requests.append(request)
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "public.example"
        assert request.extensions["sni_hostname"] == "public.example"
        assert request.headers["connection"] == "close"
        return httpx.Response(302, headers={"location": "https://private.example/secret"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
            return await enricher.ContentEnricher(Settings())._get(
                "https://public.example/", client, asyncio.Semaphore(1), "text/html")
    assert asyncio.run(run()) is None
    assert len(requests) == 1


def test_relative_redirect_revalidates_and_bounds_body(monkeypatch):
    lookups, requests = [], []
    async def resolve(host, port):
        lookups.append(host)
        return "93.184.216.34"
    monkeypatch.setattr(enricher, "_resolve_public", resolve)
    def handler(request):
        requests.append(request)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/article"})
        return httpx.Response(200, content=b"a" * 60000, headers={"content-type": "text/html"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
            return await enricher.ContentEnricher(Settings(enrich_max_bytes=50000))._get(
                "https://public.example/start", client, asyncio.Semaphore(1), "text/html")
    got = asyncio.run(run())
    assert len(got.body) == 50000 and got.url == "https://public.example/article"
    assert len(lookups) == len(requests) == 2


def test_merge_membership_ignores_model_labels(settings):
    rows = [item(1, "Acme launches new database tooling"),
            item(2, "Acme launches new database tools")]
    drafts = [DraftCluster([1], "Unrelated label", "Tech", ["Invented entity"]),
              DraftCluster([2], "Another label", "News", ["Another entity"])]
    merged = SemanticClusterer(settings)._deterministic_merge(drafts, LinkIndex(rows))
    assert len(merged) == 1 and sorted(merged[0].item_ids) == [1, 2]
    assert merged[0].needs_label


def test_ambiguous_fragment_does_not_bridge_events():
    rows = [item(1, "Acme launches new database tooling"),
            item(2, "Acme database outage affects customers"), item(3, "Acme")]
    assert LinkIndex(rows).components([1, 2, 3], ["Acme"]) == [[1], [2], [3]]


def test_legacy_migration_is_idempotent_and_excludes_unknown_history(settings):
    with sqlite3.connect(settings.db_path) as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO runs(run_id, started_at, finished_at) VALUES('old',1,2)")
    for _ in range(2):
        db = TrendDatabase(settings.db_path)
        try:
            assert db._conn.execute("SELECT status FROM runs WHERE run_id='old'").fetchone()[0] == "unknown"
            assert db.find_reference_run(1, 0, 10, "new") is None
            assert db._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "3"
        finally:
            db.close()


def test_completed_run_persists_context_and_exported_members(mock_http, fake_ollama, settings):
    report = asyncio.run(main.run_once(settings))
    db = TrendDatabase(settings.db_path)
    try:
        payload = json.loads(db._conn.execute("SELECT payload FROM clusters LIMIT 1").fetchone()[0])
        assert payload["member_item_ids"] and payload["event_id"]
        evidence = [json.loads(r[0]) for r in db._conn.execute("SELECT payload FROM cleaned_evidence")]
        assert any(e["context"] for e in evidence)
        assert all(len(e["observations"]) == e["duplicate_count"] for e in evidence)
        assert report.valid and report.schema_version == 3
        assert report.model_dump()["macro_clusters"][0]["member_item_ids"]
        db.invalidate_run(report.run_id, "later diagnostic")
        with pytest.raises(ValueError, match="running"):
            db.finish_run(report, time.time())
        assert db.cluster_history(report.macro_clusters[0].cluster_id) == []
    finally:
        db.close()


def test_new_entity_only_on_uncompared_source_is_not_new(settings):
    db = TrendDatabase(settings.db_path)
    try:
        scorer = TrendScorer(settings, db)
        ref = _RefRun("before", 0, [], {"hackernews": ["other"]}, {"hackernews": ["other"]})
        _, _, _, velocity, is_new = scorer._entity_velocity(EntityMatcher("Acme"), ["acme"], {1: ref})
        assert velocity == 50 and not is_new
    finally:
        db.close()
