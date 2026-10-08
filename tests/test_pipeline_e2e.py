"""Full five-stage dry run: mock HTTP + fake Ollama, REAL HDBSCAN + trafilatura + SQLite."""
import asyncio

import pytest

from agent_reach import main as M


def _run(settings, use_llm=True):
    return asyncio.run(M.run_once(settings, use_llm=use_llm))


def test_ledger_balances_and_matches_clusters(mock_http, fake_ollama, settings):
    r = _run(settings)
    a = r.accounting
    assert a.balanced, f"{a.ingested} != {a.discarded_total} + {a.clustered}"
    assert sum(c.raw_item_count for c in r.macro_clusters) == a.clustered
    assert all(n >= 0 for n in a.discarded.values())


def test_entity_isolation_samsung_fdroid_never_share_a_cluster(mock_http, fake_ollama, settings):
    r = _run(settings)
    for c in r.macro_clusters:
        text = " ".join(c.primary_entities + [c.headline])
        assert not ("Samsung" in text and "F-Droid" in text)


def test_insufficient_and_filler_clusters_are_dropped(mock_http, fake_ollama, settings):
    r = _run(settings)
    report = M.render_report(r, settings)
    assert "INSUFFICIENT" not in report
    assert "no specific information" not in report.lower()
    assert not any("Lizzie" in c.headline or c.headline == "Cleveland" for c in r.macro_clusters)
    assert r.accounting.discarded.get("insufficient_data", 0) > 0


def test_fragments_resolve_and_category_guard_applies(mock_http, fake_ollama, settings):
    r = _run(settings)
    nfl = next(c for c in r.macro_clusters if "Packers" in c.headline)
    assert nfl.category.value == "Sports"  # fake LLM said "Tech"


def test_llm_sees_scraped_context_and_summaries_have_no_urls(mock_http, fake_ollama, settings):
    r = _run(settings)
    assert r.enrichment.get("with_context", 0) > 0
    assert any("Jordan Love threw" in p or "Green Bay Packers" in p for p in fake_ollama.prompts)
    assert "https://" not in " ".join(c.summary for c in r.macro_clusters)


def test_no_llm_mode_balances(mock_http, fake_ollama, settings):
    r = _run(settings, use_llm=False)
    assert r.accounting.balanced
    assert r.llm_mode.startswith("heuristic")


def test_a_run_stopped_by_a_time_limit_is_marked_invalid(mock_http, fake_ollama, settings, monkeypatch):
    """asyncio.wait_for cancels run_once (CancelledError is not an Exception): the run must not stay 'running'."""
    import sqlite3

    from agent_reach.pipeline.clusterer import SemanticClusterer

    async def slow_cluster(self, *a, **kw):
        await asyncio.sleep(30)

    monkeypatch.setattr(SemanticClusterer, "cluster", slow_cluster)

    async def limited():
        await asyncio.wait_for(M.run_once(settings, use_llm=True), timeout=0.5)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(limited())
    with sqlite3.connect(settings.db_path) as conn:
        assert [r[0] for r in conn.execute("SELECT status FROM runs")] == ["invalid"]
