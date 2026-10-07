"""The embedding layer (rc12): event representation, model prompts, the model-aware cache and the fallback chain.

Every exact model (tag + Ollama digest) is its own embedding space: a vector computed by nomic-embed-text must
never be read back for EmbeddingGemma, and a re-pulled model must not reuse the old one's vectors.
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone

import pytest

from agent_reach.config import Settings
from agent_reach.models import CleanedTrendItem, SourceName
from agent_reach.pipeline.clusterer import SemanticClusterer
from agent_reach.pipeline.embeddings import (EVENT_REPR_VERSION, REPR_MAX_CHARS, EmbeddingCache, EmbeddingUnavailable,
                                             cache_path, embed_reports, event_representation, normalise, task_prefix)
from tests.event_corpus import load_edition, related_pairs, score

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def _item(i: int, title: str, context: str | None = None) -> CleanedTrendItem:
    return CleanedTrendItem(item_id=i, title=title, normalized_title=title, source=SourceName.NEWS_RSS,
                            heuristic_score=0.5, timestamp=NOW, context=context)


class FakeEmbedder:
    """Fake Ollama: deterministic vectors per (model, text); models it does not have raise like Ollama does."""

    def __init__(self, models: dict[str, str], dims: int = 768, sizes: dict[str, int] | None = None):
        self.models = models  # tag -> digest
        self.dims = dims
        self.sizes = sizes or {}
        self.calls: list[tuple[str, int]] = []
        self.texts: list[str] = []

    async def list(self):
        return {"models": [{"model": m, "digest": d} for m, d in self.models.items()]}

    async def embed(self, model, input, keep_alive=None):
        self.calls.append((model, len(input)))
        self.texts.extend(input)
        if model not in self.models:
            raise RuntimeError(f'model "{model}" not found, try pulling it first (status code: 404)')
        n = self.sizes.get(model, self.dims)
        out = []
        for text in input:
            seed = sum(map(ord, model + self.models[model] + text))
            out.append([math.sin(seed * (k + 1)) for k in range(n)])
        return {"embeddings": out}

    async def chat(self, **kw):
        raise ConnectionError("Failed to connect to Ollama")


def _settings(tmp_path, **kw) -> Settings:
    return Settings(db_path=tmp_path / "agent_reach.db", **kw)


ITEMS = [_item(1, "Australia's privacy regulator investigates smart glasses app maker - Reuters",
               "One of your browser extensions seems to be blocking the video player. The Office of the Australian "
               "Information Commissioner opened an investigation into Shenzhen Qingcheng. Subscribe to our newsletter."),
         _item(2, "Privacy watchdog launches investigation into China-based company behind smartglasses app")]


# ------------------------------------------------------------------ representation, prompts, normalisation
def test_event_representation_is_deterministic_and_drops_page_furniture():
    text = event_representation(ITEMS[0])
    assert text == event_representation(ITEMS[0])
    assert text.startswith("Australia's privacy regulator investigates smart glasses app maker.")
    assert "Reuters" not in text  # the outlet suffix says nothing about the event
    assert "browser extension" not in text and "newsletter" not in text.lower()
    assert "Shenzhen Qingcheng" in text
    long = _item(3, "Title", " ".join(["The regulator said the company collected data from many users today."] * 40))
    assert len(event_representation(long)) <= REPR_MAX_CHARS


def test_task_prefixes_follow_the_model_cards():
    assert task_prefix("embeddinggemma-2:270m") == "task: clustering | query: "
    assert task_prefix("embeddinggemma-2:latest") == "task: clustering | query: "
    assert task_prefix("nomic-embed-text") == "clustering: "
    assert task_prefix("mxbai-embed-large") == ""
    assert task_prefix("embeddinggemma-2:270m", "search_document: ") == "search_document: "


def test_matryoshka_truncation_renormalises():
    v = normalise([3.0, 4.0, 12.0], dims=2)
    assert v == pytest.approx([0.6, 0.8])
    assert sum(x * x for x in normalise([1.0] * 768)) == pytest.approx(1.0)
    with pytest.raises(EmbeddingUnavailable):
        normalise([0.0, 0.0])


# ------------------------------------------------------------------ cache identity
def test_cache_key_names_the_exact_embedding_space():
    k = EmbeddingCache.key
    base = k("embeddinggemma-2:270m", "sha256:aaa", 0, "task: clustering | query: x")
    assert base != k("nomic-embed-text", "sha256:aaa", 0, "task: clustering | query: x")
    assert base != k("embeddinggemma-2:latest", "sha256:aaa", 0, "task: clustering | query: x")
    assert base != k("embeddinggemma-2:270m", "sha256:bbb", 0, "task: clustering | query: x")  # re-pulled
    assert base != k("embeddinggemma-2:270m", "sha256:aaa", 256, "task: clustering | query: x")
    assert base != k("embeddinggemma-2:270m", "sha256:aaa", 0, "clustering: x")
    assert EVENT_REPR_VERSION in base and "embeddinggemma-2:270m@sha256:aaa" in base


def test_second_run_reads_the_cache(tmp_path):
    s = _settings(tmp_path)
    fake = FakeEmbedder({"embeddinggemma-2:270m": "sha256:g1"})
    v1, r1 = asyncio.run(embed_reports(fake, s, ITEMS))
    v2, r2 = asyncio.run(embed_reports(fake, s, ITEMS))
    assert (r1.cache_hits, r1.cache_misses) == (0, 2)
    assert (r2.cache_hits, r2.cache_misses) == (2, 0)
    assert len(fake.calls) == 1  # the second run asked the model nothing
    assert all(a == pytest.approx(b, abs=1e-6) for a, b in zip(v1, v2))  # float32 storage
    assert r2.model == "embeddinggemma-2:270m" and r2.dims == 768 and r2.native_dims == 768
    assert fake.texts[0].startswith("task: clustering | query: ")
    assert cache_path(s) == tmp_path / "agent_reach.embeddings.sqlite"


def test_nomic_vectors_are_never_reused_for_embeddinggemma(tmp_path):
    s = _settings(tmp_path)
    nomic_only = FakeEmbedder({"nomic-embed-text:latest": "sha256:n1", "nomic-embed-text": "sha256:n1"})
    _, r1 = asyncio.run(embed_reports(nomic_only, s, ITEMS))
    assert r1.model == "nomic-embed-text"  # gemma missing: the fallback did the run, into the cache
    both = FakeEmbedder({"embeddinggemma-2:270m": "sha256:g1", "nomic-embed-text": "sha256:n1"})
    _, r2 = asyncio.run(embed_reports(both, s, ITEMS))
    assert r2.model == "embeddinggemma-2:270m" and r2.cache_hits == 0 and r2.cache_misses == 2
    assert both.calls == [("embeddinggemma-2:270m", 2)]


def test_a_repulled_model_is_a_new_embedding_space(tmp_path):
    s = _settings(tmp_path)
    asyncio.run(embed_reports(FakeEmbedder({"embeddinggemma-2:270m": "sha256:old"}), s, ITEMS))
    _, run = asyncio.run(embed_reports(FakeEmbedder({"embeddinggemma-2:270m": "sha256:new"}), s, ITEMS))
    assert run.cache_hits == 0


def test_dimensions_never_mix(tmp_path):
    s = _settings(tmp_path, embed_dims=256)
    fake = FakeEmbedder({"embeddinggemma-2:270m": "sha256:g1"})
    vectors, run = asyncio.run(embed_reports(fake, s, ITEMS))
    assert {len(v) for v in vectors} == {256} and run.native_dims == 768
    _, native = asyncio.run(embed_reports(fake, _settings(tmp_path), ITEMS))  # same cache file, native size
    assert native.dims == 768 and native.cache_hits == 0


def test_a_model_that_answers_with_mixed_sizes_is_not_used(tmp_path):
    class Ragged(FakeEmbedder):
        async def embed(self, model, input, keep_alive=None):
            resp = await super().embed(model, input, keep_alive)
            if model == "embeddinggemma-2:270m":
                resp["embeddings"][-1] = resp["embeddings"][-1][:300]
            return resp

    fake = Ragged({"embeddinggemma-2:270m": "sha256:g1", "nomic-embed-text": "sha256:n1"})
    vectors, run = asyncio.run(embed_reports(fake, _settings(tmp_path), ITEMS))
    assert run.model == "nomic-embed-text" and "different sizes" in run.fallbacks[0]
    assert {len(v) for v in vectors} == {768}


def test_an_unusable_cache_file_is_no_cache_not_a_failed_run(tmp_path):
    bad = tmp_path / "not-a-db.sqlite"
    bad.write_bytes(b"this is not sqlite" * 100)
    s = _settings(tmp_path, embed_cache_path=bad)
    _, run = asyncio.run(embed_reports(FakeEmbedder({"embeddinggemma-2:270m": "sha256:g1"}), s, ITEMS))
    assert run.model == "embeddinggemma-2:270m" and run.cache_misses == 2


# ------------------------------------------------------------------ fallback chain, end to end
def _cluster(tmp_path, fake, name="2026-10-07-0935-export.json", **kw):
    corpus = load_edition(name)
    items = [c.item for c in corpus]
    c = SemanticClusterer(_settings(tmp_path, **kw))
    c._client = fake
    outcome = asyncio.run(c.cluster(items, corpus=items, use_llm=True))
    outcome.assert_partition(items)  # invariant 1: every report in exactly one story or discard bucket
    groups = [list(cl.member_item_ids) for cl in outcome.clusters]
    return outcome, score(corpus, groups, related_pairs(name))


def test_embeddinggemma_missing_falls_back_to_nomic_and_says_so(tmp_path):
    outcome, s = _cluster(tmp_path, FakeEmbedder({"nomic-embed-text": "sha256:n1"}))
    sem = outcome.semantic
    assert sem["model_used"] == "nomic-embed-text"
    assert sem["fallback"].startswith("embeddinggemma-2:270m was not used: embeddinggemma-2:270m:")
    assert "not found" in sem["fallback"]
    assert sem["embedding"]["requested_model"] == "embeddinggemma-2:270m"
    assert not s.false_merges


def test_no_embedding_model_at_all_groups_lexically_and_logs_it(tmp_path, caplog):
    outcome, s = _cluster(tmp_path, FakeEmbedder({}))
    sem = outcome.semantic
    assert sem["model_used"] == "none (lexical grouping)"
    assert "lexical" in sem["method"] and "lexical" in outcome.mode
    assert "nomic-embed-text:" in sem["fallback"] and "embeddinggemma-2:270m:" in sem["fallback"]
    assert any("lexical grouping" in r.getMessage() for r in caplog.records)
    assert not s.false_merges and s.correct_pairs > 0  # still useful stories, still no mixed events
    assert outcome.pair_log and all(set(d) >= {"verdict", "reasons", "cosine", "shared_evidence"} for d in outcome.pair_log)
    # the counts describe the grouping itself, not the coherence checks that ask the gate again afterwards
    gate = sem["gate"]
    assert gate["pairs_decided"] >= gate["candidate_pairs"] > 0
    assert gate["merges_accepted"] <= len(outcome.pair_log)


def test_legacy_density_method_still_runs_and_is_reported(tmp_path):
    outcome, _ = _cluster(tmp_path, FakeEmbedder({"embeddinggemma-2:270m": "sha256:g1"}), cluster_method="density")
    assert outcome.semantic["cluster_method"] == "density"
    assert outcome.semantic["model_used"] == "embeddinggemma-2:270m"


def test_unknown_cluster_method_is_refused(tmp_path):
    with pytest.raises(ValueError):
        _settings(tmp_path, cluster_method="kmeans")


def test_benchmark_runs_real_model_rows_and_reports_a_missing_model(tmp_path):
    """The harness the user runs on Windows (Benchmark-Embeddings.ps1), here with a fake Ollama: per model three
    groupings, cosine distributions, cache hit rate; a model that is not pulled is reported, not fatal."""
    from tests.embedding_benchmark import main, markdown, run

    fake = FakeEmbedder({"embeddinggemma-2:270m": "sha256:g1"}, dims=64)
    result = asyncio.run(run(["embeddinggemma-2:270m", "embeddinggemma-2:latest"], True, "http://x", client=fake))
    names = [r["name"] for r in result["rows"]]
    assert names[0].startswith("rc11 published") and result["rows"][0]["false_merges"] == 52
    assert sum(n.startswith("embeddinggemma-2:270m + ") for n in names) == 3
    gemma = result["models"][0]
    assert gemma["cache_hit_rate"] == 1.0 and gemma["dims"] == 64
    assert set(gemma["cosines"]) >= {"same_event", "different_event", "candidate_recall", "suggested_strong_cosine"}
    assert result["models"][1]["model"] == "embeddinggemma-2:latest" and "not found" in result["models"][1]["error"]
    text = markdown(result)
    assert "| rc11 published" in text and "## embeddinggemma-2:latest" in text
    assert main(["--out", str(tmp_path)]) == 0  # offline run writes both files
    assert (tmp_path / "identity-eval.json").exists() and (tmp_path / "identity-eval.md").exists()


def test_benchmark_explains_why_a_model_cannot_be_used():
    """October 7, PC: embeddinggemma:300m downloaded, then Ollama 0.40.0 failed to open it with a raw Windows
    error ('CreateFile ... manifests-v2 ... untrusted mount point'); the advice 'Pull it' was wrong for that."""
    from tests.embedding_benchmark import unavailable_advice

    err = ("ResponseError: CreateFile C:\\Users\\x\\.ollama\\models\\manifests-v2\\ollama.com\\library\\"
           "embeddinggemma\\300m: The path cannot be traversed because it contains an untrusted mount point")
    assert "known bug in Ollama 0.40" in unavailable_advice("embeddinggemma:300m", err)
    assert "Pull it" not in unavailable_advice("embeddinggemma:300m", err)
    assert "Mac" in unavailable_advice("embeddinggemma-2:270m", "this model requires MLX support")
    assert unavailable_advice("x:1b", 'model "x:1b" not found') == "Pull it: ollama pull x:1b"


def test_benchmark_saves_real_vectors_and_replays_them_offline(tmp_path, monkeypatch):
    """The PC run saves each model's vectors; the same rows come back offline from that file (``--replay``)."""
    import tests.embedding_benchmark as bench

    fake = FakeEmbedder({"nomic-embed-text": "sha256:n1"}, dims=32)
    real = asyncio.run(bench.run(["nomic-embed-text"], True, "http://x", client=fake))
    monkeypatch.setattr(bench, "run", lambda *a, **k: _done(real))  # the CLI, with the fake model's result
    assert bench.main(["--ollama", "--models", "nomic-embed-text", "--out", str(tmp_path)]) == 0
    dump = tmp_path / "vectors-nomic-embed-text.json.gz"
    assert dump.exists() and "vectors" not in json.loads((tmp_path / "identity-eval.json").read_text())
    monkeypatch.undo()
    replayed = asyncio.run(bench.run([], False, "http://x", replay=[dump]))
    live = {r["name"]: r for r in real["rows"] if r["name"].startswith("nomic-embed-text + ")}
    again = {r["name"].replace(" (replayed from vectors-nomic-embed-text.json.gz)", ""): r for r in replayed["rows"]
             if "(replayed from" in r["name"]}
    assert set(again) == set(live)
    for name, row in live.items():
        assert (again[name]["false_merges"], again[name]["recall"]) == (row["false_merges"], row["recall"])
    assert "real vectors replayed" in bench.markdown(replayed)


async def _done(value):
    return value
