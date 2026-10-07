"""Run with python -m tests.replay_benchmark [--llm] [--output report.json].

Replays the post-enrichment boundary; no page fetching. --llm explicitly opts into
local Ollama. Frozen chart data and synthetic variants are identified in the fixture.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import time

from agent_reach.config import Settings
from agent_reach.models import CleanedTrendItem
from agent_reach.pipeline.clusterer import SemanticClusterer
from tests.test_reliability import (
    test_duplicate_provenance_and_publisher_diversity,
    test_model_assignments_cannot_change_membership,
    test_source_rates_are_comparable_and_outages_uncertain,
)
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


async def benchmark(use_llm: bool = False) -> dict:
    fixture = json.loads((FIXTURES / "reliability_replay.json").read_text(encoding="utf-8"))
    reviews_path = FIXTURES / "reviewed_claims.json"
    reviews = json.loads(reviews_path.read_text()) if reviews_path.exists() else {}
    results = []
    seen = set()
    work = {"embedding_calls": 0, "embedding_seconds": 0.0, "repeated_embedding_requests": 0,
            "label_calls": 0, "repeated_label_requests": 0, "label_seconds": 0.0,
            "grouping_seconds": 0.0, "fetch_seconds": 0.0, "cache_hits": 0}
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(db_path=Path(directory) / "replay.db", outlier_policy="keep_top")
        for case in fixture["cases"]:
            rows = [CleanedTrendItem(**r, normalized_title=r["title"], heuristic_score=0.9)
                    for r in case["items"]]
            clusterer = SemanticClusterer(settings)
            original_client = clusterer._get_client

            class MeasuredClient:
                def __init__(self, client):
                    self.client = client

                def __getattr__(self, name):
                    return getattr(self.client, name)

                async def embed(self, **kwargs):
                    key = hashlib.sha256(json.dumps(kwargs, sort_keys=True).encode()).hexdigest()
                    work["embedding_calls"] += 1
                    work["repeated_embedding_requests"] += int(key in seen)
                    seen.add(key)
                    clock = time.perf_counter()
                    try:
                        return await self.client.embed(**kwargs)
                    finally:
                        work["embedding_seconds"] += time.perf_counter() - clock

            clusterer._get_client = lambda: MeasuredClient(original_client())
            original_chat = clusterer._chat_json
            original_group = clusterer._group

            async def chat(system, user, schema, tag):
                key = hashlib.sha256((settings.ollama_model + system + user).encode()).hexdigest()
                work["label_calls"] += 1
                work["repeated_label_requests"] += int(key in seen)
                seen.add(key)
                clock = time.perf_counter()
                try:
                    return await original_chat(system, user, schema, tag)
                finally:
                    work["label_seconds"] += time.perf_counter() - clock

            async def group(*args, **kwargs):
                clock = time.perf_counter()
                try:
                    return await original_group(*args, **kwargs)
                finally:
                    work["grouping_seconds"] += time.perf_counter() - clock

            clusterer._chat_json = chat
            clusterer._group = group
            # Replay twice to expose repeated model work, without claiming a cache exists.
            outcome = None
            for _ in range(2):
                outcome = await clusterer.cluster(rows, use_llm=use_llm)
            expected = case["expected_groups"]
            expected_pairs = {tuple(sorted((a, b))) for g in expected for a in g for b in g if a < b}
            actual_pairs = {tuple(sorted((a, b))) for c in outcome.clusters
                            for a in c.member_item_ids for b in c.member_item_ids if a < b}
            represented = {i for c in outcome.clusters for i in c.member_item_ids}
            missed = sum(not (set(g) & represented) for g in expected)
            review = []
            for c in outcome.clusters:
                digest = hashlib.sha256(c.summary.encode()).hexdigest()
                review.append({"summary": c.summary, "summary_sha256": digest,
                               "unsupported_claims": reviews.get(digest),
                               "member_item_ids": c.member_item_ids})
            results.append({"case": case["name"], "mode": outcome.mode,
                            "incorrect_merge_pairs": len(actual_pairs - expected_pairs),
                            "important_stories_missed": missed,
                            "missing_expected_pairs": len(expected_pairs - actual_pairs),
                            "summaries": review})
        checks = {}
        for name, check in [
            ("source_outage_false_alerts", test_source_rates_are_comparable_and_outages_uncertain),
            ("syndicated_duplicate_failures", test_duplicate_provenance_and_publisher_diversity),
        ]:
            try:
                check(settings)
                checks[name] = 0
            except AssertionError:
                checks[name] = 1
        with pytest.MonkeyPatch.context() as patch:
            try:
                await asyncio.to_thread(test_model_assignments_cannot_change_membership, settings, patch)
                checks["unsupported_assignment_effects"] = 0
            except AssertionError:
                checks["unsupported_assignment_effects"] = 1
    claims = [s["unsupported_claims"] for r in results for s in r["summaries"]]
    return {"mode": "local_ollama" if use_llm else "offline_heuristic",
            "runtime_seconds": round(time.perf_counter() - start, 4),
            "incorrect_merge_pairs": sum(r["incorrect_merge_pairs"] for r in results),
            "important_stories_missed": sum(r["important_stories_missed"] for r in results),
            "unsupported_summary_claims": sum(claims) if all(c is not None for c in claims) else None,
            "unreviewed_summaries": sum(c is None for c in claims),
            "work": work, "checks": checks, "cases": results}


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(benchmark(args.llm))
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if (result["incorrect_merge_pairs"] or result["important_stories_missed"]
            or result["unsupported_summary_claims"] or (not args.llm and result["unreviewed_summaries"])
            or any(result["checks"].values())):
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
