"""Event-identity benchmark on the labelled October 7 corpus (rc12).

    python -m tests.embedding_benchmark                       # offline: no Ollama needed (runs anywhere)
    python -m tests.embedding_benchmark --ollama              # + real models through the local Ollama
    python -m tests.embedding_benchmark --ollama --models nomic-embed-text,embeddinggemma:300m,embeddinggemma-2:270m
    python -m tests.embedding_benchmark --replay vectors-nomic-embed-text.json.gz   # real vectors saved on the PC

Every grouping is scored against the gold events of ``tests/fixtures/real/event_gold.json`` with pairwise
precision / recall / F1 and the RAW number of false merges (two different events published as one story),
the error that matters most. Each edition is clustered on its own, as a real refresh would.

Offline rows (always):

* ``rc11 published``: what the rc11 pipeline (nomic-embed-text + HDBSCAN + single-link LinkIndex) actually
  published on the user's PC that day (the five rc11 editions): the baseline.
* ``rc12 published on the PC``: what the first rc12 refreshes published there (nomic-embed-text + identity gate,
  before the rc12b fixes; the two rc12 editions). Every other row covers all editions.
* ``identity, no embeddings``: the rc12 identity gate on lexical candidates (the fallback when no embedding
  model answers).
* ``identity, replayed rc11 neighbourhoods``: reports published in one story get near-identical vectors; the
  worst case for the gate (every published false merge arrives as a confident embedding match).
* ``identity, every pair cosine 1``: the embedding says nothing; only the gate's evidence separates events.

Per real model (``--ollama``; each exact model id is its own embedding space and its own cache):

* ``<model> + HDBSCAN + single-link`` (the rc11 structure: density groups, then any linked pair chains);
* ``<model> + HDBSCAN + identity gate`` (``cluster_method=density``);
* ``<model> + identity gate`` (``cluster_method=identity``, the rc12 default);
* cosine distributions of same-event and different-event pairs, the share of same-event pairs the kNN
  candidates contain, a suggested ``identity_strong_cosine``, embedding time cold and from the cache.

Writes ``<out>/identity-eval.json`` and ``<out>/identity-eval.md``. Nothing here changes settings: the
suggested thresholds are for a person to read.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import random
import re
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from agent_reach.config import Settings
from agent_reach.pipeline.clusterer import LinkIndex
from agent_reach.pipeline.density import density_cluster
from agent_reach.pipeline.embeddings import EmbeddingUnavailable, embed_reports
from agent_reach.pipeline.event_identity import cohesive_groups, lexical_candidates, nearest_candidates
from tests.event_corpus import (EDITIONS, RC11_EDITIONS, RC12_EDITIONS, RC12C_EDITIONS, RC12D_EDITIONS, CorpusItem, load_edition,
                                recorded_groups, related_pairs, score)

# embeddinggemma:300m (the first EmbeddingGemma): October 7, Ollama could run EmbeddingGemma 2 on Macs only, so the
# Windows PC compares nomic with the EmbeddingGemma it can run; EmbeddingGemma 2 is benchmarked once it pulls.
DEFAULT_MODELS = "nomic-embed-text,embeddinggemma:300m,embeddinggemma-2:270m"


def _unit(v: list[float]) -> list[float]:
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def replay_vectors(corpus: list[CorpusItem], seed: int = 7, dims: int = 48) -> dict[int, list[float]]:
    rnd = random.Random(seed)
    base: dict[str, list[float]] = {}
    return {c.item.item_id: _unit([x + rnd.gauss(0, 0.2) for x in base.setdefault(c.recorded, [rnd.gauss(0, 1)
                                                                                                for _ in range(dims)])])
            for c in corpus}


def _fragments(index: LinkIndex, ids: list[int]) -> set[int]:
    return {i for i in ids if len(index.toks[i]) <= 3}


def identity_groups(corpus: list[CorpusItem], settings: Settings, vectors: dict[int, list[float]] | None):
    items = [c.item for c in corpus]
    ids = [it.item_id for it in items]
    index = LinkIndex(items, None, settings.event_max_age_hours)
    if vectors is None:
        edges = lexical_candidates(ids, index.toks, max(6, int(0.1 * len(ids))))
    else:
        index.attach_vectors(vectors, settings.identity_candidate_cosine, settings.identity_strong_cosine)
        edges = nearest_candidates(ids, vectors, settings.identity_neighbors, settings.identity_candidate_cosine)
    return cohesive_groups(ids, index.gate, edges, _fragments(index, ids)), index


def density_groups(corpus: list[CorpusItem], settings: Settings, vectors: dict[int, list[float]],
                   single_link: bool) -> list[list[int]]:
    """HDBSCAN groups, then either rc11's single-link chaining over linked pairs or the rc12 identity gate."""
    items = [c.item for c in corpus]
    res = density_cluster(items, [vectors[it.item_id] for it in items], settings)
    index = LinkIndex(items, None, settings.event_max_age_hours)
    index.attach_vectors(vectors, settings.identity_candidate_cosine, settings.identity_strong_cosine)
    out: list[list[int]] = []
    for g in res.groups:
        if not single_link:
            out += index.components(g, [])
            continue
        parent = {i: i for i in g}

        def find(x: int) -> int:
            while parent[x] != x:
                x = parent[x]
            return x

        for a, b in combinations(g, 2):
            if index.linked(a, b) or (max(len(index.toks[a]), len(index.toks[b])) <= 3 and index._cooccur_link(a, b)):
                parent[find(a)] = find(b)
        comps: dict[int, list[int]] = {}
        for i in g:
            comps.setdefault(find(i), []).append(i)
        out += list(comps.values())
    return out


def _row(name: str, per_edition: dict[str, dict]) -> dict:
    tot = {k: sum(v[k] for v in per_edition.values()) for k in ("false_merges", "missed_merges", "mixed_stories",
                                                                  "true_pairs", "predicted_pairs")}
    correct = tot["predicted_pairs"] - tot["false_merges"]
    p = correct / tot["predicted_pairs"] if tot["predicted_pairs"] else 1.0
    r = correct / tot["true_pairs"] if tot["true_pairs"] else 1.0
    return {"name": name, "precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            **tot, "editions": per_edition}


def _scored(corpora: dict[str, list[CorpusItem]], grouper) -> tuple[dict[str, dict], dict[str, list]]:
    per, examples = {}, {}
    for name, corpus in corpora.items():
        s = score(corpus, grouper(name, corpus), related_pairs(name))
        per[name] = s.as_dict()
        examples[name] = [list(p) for p in s.false_merges[:5]]
    return per, examples


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {}
    q = statistics.quantiles(values, n=100, method="inclusive") if len(values) > 1 else [values[0]] * 99
    return {"n": len(values), "p1": round(q[0], 3), "p5": round(q[4], 3), "p25": round(q[24], 3), "p50": round(q[49], 3),
            "p75": round(q[74], 3), "p95": round(q[94], 3), "p99": round(q[98], 3), "max": round(max(values), 3)}


def cosine_report(corpora: dict[str, list[CorpusItem]], vectors: dict[str, dict[int, list[float]]],
                  settings: Settings) -> dict:
    same, diff = [], []
    covered = total_same = 0
    for name, corpus in corpora.items():
        vec = vectors[name]
        related = related_pairs(name)
        ids = [c.item.item_id for c in corpus]
        edges = {frozenset(e) for e in nearest_candidates(ids, vec, settings.identity_neighbors,
                                                          settings.identity_candidate_cosine)}
        for a, b in combinations(corpus, 2):
            if a.gold is None or b.gold is None:
                continue
            if a.gold != b.gold and frozenset((a.gold, b.gold)) in related:
                continue
            cos = sum(x * y for x, y in zip(vec[a.item.item_id], vec[b.item.item_id]))
            if a.gold == b.gold:
                same.append(cos)
                total_same += 1
                covered += frozenset((a.item.item_id, b.item.item_id)) in edges
            else:
                diff.append(cos)
    ds, dd = _percentiles(same), _percentiles(diff)
    return {"same_event": ds, "different_event": dd,
            "candidate_recall": round(covered / total_same, 3) if total_same else None,
            "different_pairs_above_strong": sum(c >= settings.identity_strong_cosine for c in diff),
            "same_pairs_below_candidate_floor": sum(c < settings.identity_candidate_cosine for c in same),
            "suggested_strong_cosine": round(min(0.99, max(settings.identity_strong_cosine, dd.get("p99", 0) + 0.01)), 2)
            if dd else None}


async def embed_corpora(client, model: str, corpora: dict[str, list[CorpusItem]], cache_dir: Path) -> dict:
    """Embed every edition with ``model``: once cold, once from the cache (a second refresh)."""
    settings = Settings(db_path=cache_dir / "bench.db", embed_model=model, embed_fallback_models=[],
                        embed_cache_path=cache_dir / f"{model.replace(':', '_').replace('/', '_')}.sqlite")
    out = {"model": model, "vectors": {}, "cold_seconds": 0.0, "warm_seconds": 0.0, "cache_hits": 0,
           "reports": 0, "dims": None, "digest": None}
    for name, corpus in corpora.items():
        items = [c.item for c in corpus]
        vecs, run = await embed_reports(client, settings, items)
        out["cold_seconds"] += run.seconds
        _, warm = await embed_reports(client, settings, items)
        out["warm_seconds"] += warm.seconds
        out["cache_hits"] += warm.cache_hits
        out["reports"] += len(items)
        out["dims"], out["digest"] = run.dims, run.digest
        out["vectors"][name] = {it.item_id: v for it, v in zip(items, vecs)}
    out["cache_hit_rate"] = round(out["cache_hits"] / out["reports"], 3) if out["reports"] else None
    out["cold_seconds"], out["warm_seconds"] = round(out["cold_seconds"], 2), round(out["warm_seconds"], 2)
    return out


def load_vectors(path: Path, corpora: dict[str, list[CorpusItem]]) -> tuple[str, dict[str, dict[int, list[float]]]]:
    """Real vectors a benchmark run on the user's PC saved (``vectors-<model>.json.gz``), checked title by title.
    Editions labelled after that run are not in the file and are left out."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    out: dict[str, dict[int, list[float]]] = {}
    for name, corpus in corpora.items():
        if name not in data["editions"]:
            continue
        saved = data["editions"][name]
        out[name] = {}
        for c in corpus:
            row = saved[str(c.item.item_id)]
            if row["title"] != c.title:
                raise ValueError(f"{path.name}: {name} report {c.item.item_id} is {row['title']!r}, corpus has {c.title!r}")
            out[name][c.item.item_id] = row["vector"]
    return data["model"], out


async def run(models: list[str], use_ollama: bool, host: str, client=None, replay: list[Path] | None = None) -> dict:
    corpora = {name: load_edition(name) for name in EDITIONS}
    settings = Settings(db_path=Path(tempfile.gettempdir()) / "agent-reach-bench.db")
    rows, examples = [], {}

    def add(name: str, grouper, only: tuple[str, ...] | None = None) -> None:
        per, ex = _scored({n: c for n, c in corpora.items() if only is None or n in only}, grouper)
        rows.append(_row(name, per))
        examples[name] = ex

    add("rc11 published (nomic + HDBSCAN + single-link; 5 rc11 editions)", lambda n, c: recorded_groups(c),
        only=RC11_EDITIONS)
    add("rc12 published on the PC (nomic + identity gate before rc12b; 2 rc12 editions)",
        lambda n, c: recorded_groups(c), only=RC12_EDITIONS)
    add("rc12c published on the PC (nomic + rc12b identity gate; 2 rc12c editions)",
        lambda n, c: recorded_groups(c), only=RC12C_EDITIONS)
    add("rc12d published on the PC (nomic + rc12d identity gate; 4 rc12d editions)",
        lambda n, c: recorded_groups(c), only=RC12D_EDITIONS)
    add("identity gate, no embeddings (fallback)", lambda n, c: identity_groups(c, settings, None)[0])
    add("identity gate, replayed rc11 neighbourhoods", lambda n, c: identity_groups(c, settings, replay_vectors(c))[0])
    add("identity gate, every pair cosine 1",
        lambda n, c: identity_groups(c, settings, {x.item.item_id: _unit([1.0] * 16) for x in c})[0])
    models_out = []
    dumps: dict[str, dict] = {}  # real vectors per model, written next to the result for offline replay

    def add_model(label: str, vecs: dict[str, dict[int, list[float]]]) -> float:
        clock = time.perf_counter()
        only = tuple(vecs)
        if len(only) < len(corpora):
            label += f" ({len(only)} of {len(corpora)} editions)"
        add(f"{label} + HDBSCAN + single-link (rc11 structure)",
            lambda n, c: density_groups(c, settings, vecs[n], single_link=True), only=only)
        add(f"{label} + HDBSCAN + identity gate (cluster_method=density)",
            lambda n, c: density_groups(c, settings, vecs[n], single_link=False), only=only)
        add(f"{label} + identity gate (cluster_method=identity, default)",
            lambda n, c: identity_groups(c, settings, vecs[n])[0], only=only)
        return round(time.perf_counter() - clock, 2)

    for path in replay or []:
        model, vecs = load_vectors(path, corpora)
        add_model(f"{model} (replayed from {path.name})", vecs)
        models_out.append({"model": model, "replayed_from": path.name,
                           "cosines": cosine_report({n: corpora[n] for n in vecs}, vecs, settings)})
    if use_ollama:
        if client is None:
            from ollama import AsyncClient

            client = AsyncClient(host=host, timeout=600)
        with tempfile.TemporaryDirectory() as tmp:
            for model in models:
                try:
                    emb = await embed_corpora(client, model, corpora, Path(tmp))
                except EmbeddingUnavailable as exc:
                    models_out.append({"model": model, "error": str(exc)[:300]})
                    print(f"  {model}: not available ({str(exc)[:160]}). {unavailable_advice(model, str(exc))}",
                          file=sys.stderr)
                    continue
                vecs = emb.pop("vectors")
                dumps[model] = {name: {str(c.item.item_id): {"title": c.title, "vector": [round(x, 5) for x in vecs[name][c.item.item_id]]}
                                       for c in corpus} for name, corpus in corpora.items()}
                emb["grouping_seconds"] = add_model(model, vecs)
                emb["cosines"] = cosine_report(corpora, vecs, settings)
                models_out.append(emb)
    return {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "corpus": {"editions": list(EDITIONS), "reports": sum(len(c) for c in corpora.values()),
                       "gold_events": sum(len({x.gold for x in c if x.gold}) for c in corpora.values())},
            "settings": {k: getattr(settings, k) for k in ("identity_neighbors", "identity_candidate_cosine",
                                                            "identity_strong_cosine", "event_max_age_hours")},
            "ollama": use_ollama, "rows": rows, "models": models_out, "false_merge_examples": examples,
            "vectors": dumps}


def unavailable_advice(model: str, error: str) -> str:
    """What to do about a model the benchmark could not use, in plain words."""
    if "untrusted mount point" in error:
        # October 7, PC: Ollama 0.40.0 downloaded embeddinggemma:300m, then could not open it (ollama/ollama#18847)
        return ("Ollama downloaded it but cannot open it: a known bug in Ollama 0.40 on Windows saves the model's "
                "index file as a link that Windows refuses to follow. Pulling again does not help; a later Ollama "
                "should fix it.")
    if "MLX" in error:
        return "Ollama can run it only on Mac computers so far."
    return f"Pull it: ollama pull {model}"


def markdown(result: dict) -> str:
    lines = ["# Event identity evaluation (rc12)", "",
             f"Generated {result['generated_utc']} on the labelled October 7 corpus "
             f"({result['corpus']['reports']} reports, {result['corpus']['gold_events']} gold events, "
             f"{len(result['corpus']['editions'])} real editions). Pairwise scores over all reports; "
             "**false merges** = report pairs from different events published in one story.", "",
             "| Grouping | False merges | Mixed stories | Precision | Recall | F1 |", "|---|---:|---:|---:|---:|---:|"]
    for r in result["rows"]:
        lines.append(f"| {r['name']} | {r['false_merges']} | {r['mixed_stories']} | {r['precision']:.3f} | "
                     f"{r['recall']:.3f} | {r['f1']:.3f} |")
    lines += ["", "Settings: " + ", ".join(f"{k}={v}" for k, v in result["settings"].items()), ""]
    if not result["ollama"]:
        lines += ["Real embedding models were not run here (no Ollama). On a PC with Ollama:", "",
                  "    python -m tests.embedding_benchmark --ollama --models "
                  "nomic-embed-text,embeddinggemma:300m,embeddinggemma-2:270m,embeddinggemma-2:latest", ""]
    for m in result["models"]:
        if "error" in m:
            lines += [f"## {m['model']}", "", f"Not available: {m['error']}", ""]
            continue
        c = m["cosines"]
        if "replayed_from" in m:
            lines += [f"## {m['model']} (real vectors replayed from {m['replayed_from']})", ""]
        else:
            lines += [f"## {m['model']} ({m['dims']} dims, digest {m['digest'] or 'unknown'})", "",
                      f"- embedding: {m['reports']} reports in {m['cold_seconds']} s cold, {m['warm_seconds']} s from "
                      f"the cache (hit rate {m['cache_hit_rate']}); grouping {m['grouping_seconds']} s"]
        lines += [f"- same-event cosine: {c['same_event']}", f"- different-event cosine: {c['different_event']}",
                  f"- kNN candidates contain {c['candidate_recall']} of same-event pairs; "
                  f"{c['different_pairs_above_strong']} different-event pairs reach the strong cosine; "
                  f"{c['same_pairs_below_candidate_floor']} same-event pairs fall below the candidate floor",
                  f"- suggested identity_strong_cosine (for a person to review): {c['suggested_strong_cosine']}", ""]
    lines += ["## False merges left (first 5 per edition)", ""]
    for name, per in result["false_merge_examples"].items():
        left = {e: p for e, p in per.items() if p}
        if not left:
            continue
        lines.append(f"**{name}**")
        for edition, pairs in left.items():
            for a, b in pairs:
                lines.append(f"- {edition}: \"{a[:80]}\" + \"{b[:80]}\"")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ollama", action="store_true", help="also run real embedding models through Ollama")
    ap.add_argument("--models", default=DEFAULT_MODELS, help=f"comma-separated Ollama model tags (default {DEFAULT_MODELS})")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--replay", type=Path, action="append", default=[],
                    help="vectors-<model>.json.gz saved by an earlier --ollama run: score those real vectors offline")
    ap.add_argument("--out", type=Path, default=Path("docs") / "eval", help="folder for identity-eval.json/.md")
    args = ap.parse_args(argv)
    result = asyncio.run(run([m.strip() for m in args.models.split(",") if m.strip()], args.ollama, args.host,
                             replay=args.replay))
    args.out.mkdir(parents=True, exist_ok=True)
    # the real vectors (a few MB per model) let the next fix be checked offline against this PC's embeddings
    for model, dump in result.pop("vectors", {}).items():
        name = "vectors-" + re.sub(r"[^A-Za-z0-9._-]+", "_", model) + ".json.gz"
        with gzip.open(args.out / name, "wt", encoding="utf-8") as fh:
            json.dump({"model": model, "editions": dump}, fh)
    (args.out / "identity-eval.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    (args.out / "identity-eval.md").write_text(markdown(result), encoding="utf-8")
    for r in result["rows"]:
        print(f"{r['false_merges']:4d} false merges  P {r['precision']:.3f}  R {r['recall']:.3f}  F1 {r['f1']:.3f}  {r['name']}")
    print(f"written: {args.out / 'identity-eval.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
