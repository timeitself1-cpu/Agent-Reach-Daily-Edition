"""Stage 3a input: the event representation, the local embedding model, and the embedding cache.

**Event representation.** What gets embedded is a deterministic, inspectable text built from one
report: its title (publisher suffixes removed) and the first factual sentences of its page context
(cookie banners, "browser extension" notices and similar page furniture removed), at most
``REPR_MAX_CHARS`` characters, cut at a word. ``EVENT_REPR_VERSION`` names this recipe; any change to
it must bump the version so no vector of the old recipe is reused.

**Model.** The default is Google DeepMind's EmbeddingGemma 2 through Ollama (``embeddinggemma-2:270m``,
the text-only size; 768 dimensions). Its model card documents task prompts of the form
``task: clustering | query: <text>`` (used for every input: the task is symmetric); nomic-embed-text
documents ``clustering: <text>``. Other models get the text unchanged unless ``embed_prefix`` says
otherwise. Vectors are L2-normalised; ``embed_dims`` > 0 truncates to that many leading dimensions
(Matryoshka) and normalises again; 0 keeps the native size.

**Cache.** One SQLite file. The key is ``provider|model@digest|dims|norm|repr|sha256(prompted text)``:
the exact model tag and its Ollama digest, so a re-pulled or different-sized model is a different
embedding space, and a nomic vector can never be read for EmbeddingGemma (or the other way round).
Entries unused for ``CACHE_KEEP_DAYS`` are pruned.

**Fallback.** The configured model first, then ``embed_fallback_models`` in order (default
``nomic-embed-text``), then the caller's lexical grouping. Every step is logged and reported in the
run's semantic diagnostics (the model actually used, and why another one was not).
"""

from __future__ import annotations

import array
import hashlib
import logging
import math
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from agent_reach.config import Settings
from agent_reach.models import CleanedTrendItem
from agent_reach.pipeline.cleaner import normalize_text

log = logging.getLogger(__name__)

EVENT_REPR_VERSION = "event_repr_v2"
NORM_VERSION = "l2v1"
PROVIDER = "ollama"
REPR_MAX_CHARS = 600
CACHE_KEEP_DAYS = 21

#: Page furniture that says nothing about the event (seen in real October 7 excerpts: France 24's
#: "One of your browser extensions seems to be blocking the video player", APOD's site blurb).
BOILERPLATE_RX = re.compile(
    r"browser extensions?|enable javascript|cookies?\b.*\b(?:accept|consent|policy)|sign up for|subscribe to"
    r"|all rights reserved|click here|newsletter|discover the cosmos|each day a different image"
    r"|view the full context on|the post .{0,200} appeared first on", re.IGNORECASE)
#: ' - Reuters', ' | AP News', ': Live updates' style suffixes carry no event information.
TITLE_SUFFIX_RX = re.compile(r"\s+[-|]\s+[A-Z][\w.&' ]{1,40}$")
_SENTENCE_RX = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")


class EmbeddingUnavailable(Exception):
    pass


def event_representation(it: CleanedTrendItem) -> str:
    """The deterministic text that stands for one report (``EVENT_REPR_VERSION``)."""
    title = TITLE_SUFFIX_RX.sub("", normalize_text(it.normalized_title)).strip()
    parts = [title]
    seen = {title.lower()}
    for chunk in (it.context or "").split(" | "):
        for sentence in _SENTENCE_RX.split(normalize_text(chunk)):
            s = sentence.strip()
            key = s.lower()
            if len(s) < 25 or key in seen or BOILERPLATE_RX.search(s) or s.endswith("..."):
                continue
            seen.add(key)
            parts.append(s)
        if sum(len(p) + 1 for p in parts) >= REPR_MAX_CHARS:
            break
    text = ". ".join(p.rstrip(".") for p in parts) + "."
    if len(text) > REPR_MAX_CHARS:
        cut = text[:REPR_MAX_CHARS]
        text = cut[: cut.rfind(" ")] if " " in cut else cut
    return text


def task_prefix(model: str, configured: str = "auto") -> str:
    """The model's documented clustering prompt ('auto'), or exactly what the settings say."""
    if configured != "auto":
        return configured
    name = model.lower()
    if "embeddinggemma" in name:
        return "task: clustering | query: "
    if "nomic-embed" in name:
        return "clustering: "
    return ""


def normalise(v: list[float], dims: int = 0) -> list[float]:
    if dims and len(v) > dims:
        v = v[:dims]
    n = math.sqrt(sum(x * x for x in v))
    if not n or not math.isfinite(n):
        raise EmbeddingUnavailable("the model returned an empty or invalid vector")
    return [x / n for x in v]


@dataclass
class EmbeddingRun:
    """What one run's embedding step did (reported in the semantic diagnostics)."""

    provider: str = PROVIDER
    requested_model: str = ""
    model: str = ""  # the model actually used ("" = none: lexical grouping)
    digest: str = ""
    dims: int = 0
    native_dims: int = 0
    repr_version: str = EVENT_REPR_VERSION
    prefix: str = ""
    items: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    seconds: float = 0.0
    fallbacks: list[str] = field(default_factory=list)  # "<model>: <why it was not used>"
    error: str = ""

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("provider", "requested_model", "model", "digest", "dims", "native_dims",
                                              "repr_version", "prefix", "items", "cache_hits", "cache_misses",
                                              "fallbacks", "error")} | {"seconds": round(self.seconds, 2)}


class EmbeddingCache:
    """Vectors by exact key (model, digest, dims, normalisation, representation version, text hash)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._db: sqlite3.Connection | None = None
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(path), timeout=5)
            self._db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, dims INTEGER NOT NULL, "
                             "vec BLOB NOT NULL, used REAL NOT NULL)")
            self._db.execute("DELETE FROM vectors WHERE used < ?", (time.time() - CACHE_KEEP_DAYS * 86400,))
            self._db.commit()
        except sqlite3.Error as exc:  # an unreadable cache is no cache, never a failed run
            log.warning("embedding cache unavailable (%s); embedding without it", exc)
            self._db = None

    @staticmethod
    def key(model: str, digest: str, dims: int, prompted_text: str) -> str:
        h = hashlib.sha256(prompted_text.encode("utf-8")).hexdigest()
        return f"{PROVIDER}|{model}@{digest or 'nodigest'}|{dims or 'native'}|{NORM_VERSION}|{EVENT_REPR_VERSION}|{h}"

    def get_many(self, keys: list[str]) -> dict[str, list[float]]:
        if self._db is None or not keys:
            return {}
        out: dict[str, list[float]] = {}
        try:
            for k in range(0, len(keys), 500):
                chunk = keys[k:k + 500]
                rows = self._db.execute(f"SELECT key, dims, vec FROM vectors WHERE key IN ({','.join('?' * len(chunk))})",
                                        chunk).fetchall()
                for key, dims, blob in rows:
                    vec = array.array("f")
                    vec.frombytes(blob)
                    if len(vec) == dims:
                        out[key] = list(vec)
            if out:
                now = time.time()
                self._db.executemany("UPDATE vectors SET used = ? WHERE key = ?", [(now, k) for k in out])
                self._db.commit()
        except sqlite3.Error as exc:
            log.warning("embedding cache read failed (%s)", exc)
            return {}
        return out

    def put_many(self, entries: dict[str, list[float]]) -> None:
        if self._db is None or not entries:
            return
        now = time.time()
        try:
            self._db.executemany("INSERT OR REPLACE INTO vectors (key, dims, vec, used) VALUES (?, ?, ?, ?)",
                                 [(k, len(v), array.array("f", v).tobytes(), now) for k, v in entries.items()])
            self._db.commit()
        except sqlite3.Error as exc:
            log.warning("embedding cache write failed (%s)", exc)

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None


def cache_path(settings: Settings) -> Path | None:
    if settings.embed_cache_path is not None:
        return settings.embed_cache_path if str(settings.embed_cache_path) else None
    return Path(settings.db_path).with_name(Path(settings.db_path).stem + ".embeddings.sqlite")


async def _model_digest(client, model: str) -> str:
    """The Ollama digest of ``model`` (a re-pulled model is a different embedding space)."""
    try:
        listing = await client.list()
    except Exception:  # noqa: BLE001 - the digest is extra safety, not a requirement
        return ""
    models = getattr(listing, "models", None)
    if models is None and isinstance(listing, dict):
        models = listing.get("models", [])
    for m in models or []:
        name = getattr(m, "model", None) or (m.get("model") or m.get("name") if isinstance(m, dict) else None)
        digest = getattr(m, "digest", None) or (m.get("digest") if isinstance(m, dict) else None)
        if name and (name == model or name == f"{model}:latest") and digest:
            return str(digest)[:16]
    return ""


async def _embed_model(client, settings: Settings, model: str, texts: list[str], cache: EmbeddingCache,
                       run: EmbeddingRun) -> list[list[float]]:
    prefix = task_prefix(model, settings.embed_prefix)
    prompted = [prefix + t for t in texts]
    digest = await _model_digest(client, model)
    keys = [EmbeddingCache.key(model, digest, settings.embed_dims, p) for p in prompted]
    cached = cache.get_many(list(dict.fromkeys(keys)))
    todo = [i for i, k in enumerate(keys) if k not in cached]
    fresh: dict[str, list[float]] = {}
    native = 0
    try:
        for k in range(0, len(todo), settings.embed_batch_size):
            idx = todo[k:k + settings.embed_batch_size]
            chunk = [prompted[i] for i in idx]
            resp = await client.embed(model=model, input=chunk, keep_alive=settings.ollama_keep_alive)
            got = getattr(resp, "embeddings", None)
            if got is None and isinstance(resp, dict):
                got = resp.get("embeddings")
            if not got or len(got) != len(chunk):
                raise EmbeddingUnavailable(f"embed returned {0 if not got else len(got)} vectors for {len(chunk)} inputs")
            for i, v in zip(idx, got):
                vec = [float(x) for x in v]
                native = native or len(vec)
                if len(vec) != native:
                    raise EmbeddingUnavailable(f"vectors of different sizes ({native} and {len(vec)})")
                fresh[keys[i]] = normalise(vec, settings.embed_dims)
    except EmbeddingUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - model missing, server down, timeout...
        raise EmbeddingUnavailable(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
    vectors = [cached.get(k) or fresh[k] for k in keys]
    dims = {len(v) for v in vectors}
    if len(dims) != 1:  # a cached space of another size must never mix with fresh vectors
        raise EmbeddingUnavailable(f"vectors of different sizes in one run: {sorted(dims)}")
    cache.put_many(fresh)
    run.model, run.digest, run.prefix = model, digest, prefix
    run.dims = dims.pop()
    run.native_dims = native or run.dims
    run.cache_hits = len(keys) - len(todo)
    run.cache_misses = len(todo)
    return vectors


async def embed_reports(client, settings: Settings, items: list[CleanedTrendItem]) -> tuple[list[list[float]], EmbeddingRun]:
    """Embed every item's event representation with the first model that works.

    Raises ``EmbeddingUnavailable`` (with ``run`` attached as ``exc.run``) when no model works; the caller
    then groups lexically and reports why.
    """
    run = EmbeddingRun(requested_model=settings.embed_model, items=len(items))
    texts = [event_representation(it) for it in items]
    models = list(dict.fromkeys([settings.embed_model, *settings.embed_fallback_models]))
    cache = EmbeddingCache(cache_path(settings))
    started = time.perf_counter()
    try:
        for model in models:
            if not model:
                continue
            try:
                vectors = await _embed_model(client, settings, model, texts, cache, run)
            except EmbeddingUnavailable as exc:
                run.fallbacks.append(f"{model}: {str(exc)[:160]}")
                log.warning("embedding model %s unavailable (%s)%s", model, str(exc)[:160],
                            "; trying the next one" if model != models[-1] else "")
                continue
            run.seconds = time.perf_counter() - started
            if run.fallbacks:
                log.warning("embeddings: using fallback model %s (requested %s)", model, settings.embed_model)
            log.info("embeddings: %d reports with %s (%d dims, %s): %d from cache, %d computed in %.1f s",
                     len(items), model, run.dims, EVENT_REPR_VERSION, run.cache_hits, run.cache_misses, run.seconds)
            return vectors, run
    finally:
        cache.close()
    run.seconds = time.perf_counter() - started
    run.error = "no embedding model answered"
    err = EmbeddingUnavailable("; ".join(run.fallbacks) or "no embedding model configured")
    err.run = run  # type: ignore[attr-defined]
    raise err
