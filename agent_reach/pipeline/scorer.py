"""Relevance (1-10) and momentum velocity (0-100) scoring.

Velocity model
--------------
For every primary entity of a cluster we measure its *rate*: the share of kept items in a
source whose title mentions the entity, averaged equally across compatible sources.
Configuration or substantial coverage changes suppress directional momentum labels. For each
lookback window w (CLI default 1h, 6h, 24h; the daily app uses 24h, 48h, 7d) we locate the
completed run closest to ``now - w`` within ``w * (1 +/- velocity_window_tolerance)`` and
recompute the same rate against that run's stored titles, so even entities that were never
extracted before get a true historical baseline. A run is used for at most one window.

    growth_w   = (rate_now - rate_w) / max(rate_w, one_item_floor_w)
    signal_w   = tanh(2 * growth_w)                      # bounded -1..1
    velocity   = 50 + 50 * sum(weight_w * signal_w) / sum(weight_w over available windows)

50 = flat, >50 accelerating, <50 decaying. With no history (first runs) the score falls back
to a cold-start estimate from engagement and cross-source corroboration.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass, field

from agent_reach.pipeline.evidence import platforms, publishers
from agent_reach.config import Settings
from agent_reach.models import CleanedTrendItem, MacroCluster, VelocityWindow
from agent_reach.pipeline.cleaner import STOPWORDS, dedupe_key
from agent_reach.storage.db import TrendDatabase

log = logging.getLogger(__name__)

GENERIC_ENTITY_TOKENS = frozenset(
    {"nfl", "nba", "mlb", "nhl", "ai", "news", "game", "team", "city", "state", "united", "states", "world",
     "new", "york", "north", "south", "east", "west", "university", "national", "international", "open"}
)


class EntityMatcher:
    """Matches an entity phrase, or its distinctive tail token ('Green Bay Packers' -> 'packers')."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.key = dedupe_key(label)
        parts = self.key.split()
        patterns = [re.escape(self.key)] if self.key else []
        if len(parts) > 1:
            tail = parts[-1]
            if len(tail) >= 4 and tail not in STOPWORDS and tail not in GENERIC_ENTITY_TOKENS:
                patterns.append(re.escape(tail))
        self.rx = re.compile(r"\b(?:" + "|".join(patterns) + r")\b") if patterns else None

    def count(self, title_keys: list[str]) -> int:
        if self.rx is None:
            return 0
        return sum(1 for t in title_keys if self.rx.search(t))


@dataclass
class _RefRun:
    run_id: str
    started_at: float
    title_keys: list[str]
    current_by_source: dict[str, list[str]] = field(default_factory=dict)
    prior_by_source: dict[str, list[str]] = field(default_factory=dict)


class TrendScorer:
    def __init__(self, settings: Settings, db: TrendDatabase) -> None:
        self.settings = settings
        self.db = db
        self.coverage_uncertain = False
        self.coverage_notes: list[str] = []

    # ............................................................ relevance
    @staticmethod
    def heuristic_relevance(members: list[CleanedTrendItem]) -> float:
        """1..10 from engagement, source diversity and cluster size."""
        if not members:
            return 1.0
        mean_h = sum(m.heuristic_score for m in members) / len(members)
        diversity = min(1.0, len(platforms(members)) / 3)
        size = min(1.0, math.log2(1 + len(members)) / math.log2(9))
        publisher_diversity = min(1.0, len(publishers(members)) / 3)
        h = 0.40 * mean_h + 0.20 * diversity + 0.15 * publisher_diversity + 0.25 * size
        return 1 + 9 * h

    # ............................................................ velocity helpers
    def _reference_runs(self, run_id: str, now: float) -> dict[float, _RefRun | None]:
        refs: dict[float, _RefRun | None] = {}
        self.coverage_uncertain = False
        self.coverage_notes = []
        current_sources, config = self.db.run_context(run_id)
        current = self.db.load_observations(run_id)
        def comparable_config(c: dict) -> dict:
            return {k: v for k, v in c.items() if k not in {"enabled_sources", "db_path", "report_top_n", "report_width", "retention_days"}}
        tol = self.settings.velocity_window_tolerance
        used: set[str] = set()
        for hours in self.settings.velocity_windows_hours:
            w = hours * 3600
            row = self.db.find_reference_run(now - w, now - (1 + tol) * w, now - (1 - tol) * w, run_id)
            refs[hours] = None
            if row is None:
                continue
            rid = row["run_id"]
            if rid in used:
                # One observation never counts as two windows (e.g. 24h and 48h on a daily cadence).
                self.coverage_notes.append(f"{hours:g}h no distinct reference run")
                continue
            used.add(rid)
            previous_sources, previous_config = self.db.run_context(rid)
            common = current_sources & previous_sources
            union = current_sources | previous_sources
            if not config or not previous_config or comparable_config(config) != comparable_config(previous_config):
                self.coverage_uncertain = True
                self.coverage_notes.append(f"{hours:g}h configuration changed or unavailable")
                continue
            lost = 1 - len(common) / max(1, len(union))
            if not common or lost > self.settings.velocity_max_coverage_change:
                self.coverage_uncertain = True
            previous = self.db.load_observations(rid)
            # An empty filtered source has no denominator. Never treat missing data as zero attention.
            common = {src for src in common if current.get(src) and previous.get(src)}
            if not common or len(common) < len(current_sources & previous_sources):
                self.coverage_uncertain = True
            self.coverage_notes.append(f"{hours:g}h comparable sources: {', '.join(sorted(common)) or 'none'}")
            if common:
                refs[hours] = _RefRun(rid, row["started_at"], [],
                    {src: [dedupe_key(t) for t in current[src]] for src in common},
                    {src: [dedupe_key(t) for t in previous[src]] for src in common})
        return refs

    def _entity_velocity(
        self, matcher: EntityMatcher, cur_keys: list[str], refs: dict[float, _RefRun | None]
    ) -> tuple[int, float, list[VelocityWindow], float | None, bool]:
        """Returns (freq_now, rate_now, windows, velocity|None, is_new)."""
        total_now = max(1, len(cur_keys))
        freq_now = matcher.count(cur_keys)
        rate_now = 100.0 * freq_now / total_now
        windows: list[VelocityWindow] = []
        weighted, weight_sum = 0.0, 0.0
        all_zero_base = True
        any_window = False
        any_current_evidence = False
        for (hours, ref), weight in zip(refs.items(), self._weights()):
            if ref is None:
                windows.append(VelocityWindow(window_hours=hours, current_rate=round(rate_now, 3)))
                continue
            any_window = True
            window_rate = rate_now
            total_ref = max(1, len(ref.title_keys))
            base_rate = 100.0 * matcher.count(ref.title_keys) / total_ref
            floor = 100.0 / total_ref
            if ref.current_by_source:
                sources = sorted(ref.current_by_source)
                window_rate = sum(100 * matcher.count(ref.current_by_source[src]) / len(ref.current_by_source[src]) for src in sources) / len(sources)
                base_rate = sum(100 * matcher.count(ref.prior_by_source[src]) / len(ref.prior_by_source[src]) for src in sources) / len(sources)
                floor = sum(100 / len(ref.prior_by_source[src]) for src in sources) / len(sources)
            any_current_evidence |= window_rate > 0
            growth = (window_rate - base_rate) / max(base_rate, floor)
            if base_rate > 0:
                all_zero_base = False
            signal = math.tanh(2 * growth)
            weighted += weight * signal
            weight_sum += weight
            windows.append(
                VelocityWindow(
                    window_hours=hours,
                    baseline_rate=round(base_rate, 3),
                    current_rate=round(window_rate, 3),
                    growth=round(growth, 3),
                )
            )
        if not any_window or weight_sum == 0:
            return freq_now, rate_now, windows, None, False
        velocity = 50 + 50 * (weighted / weight_sum)
        return freq_now, rate_now, windows, velocity, all_zero_base and any_current_evidence

    def _weights(self) -> list[float]:
        w = list(self.settings.velocity_window_weights)
        n = len(self.settings.velocity_windows_hours)
        if len(w) < n:
            w += [w[-1] if w else 1.0] * (n - len(w))
        return w[:n]

    @staticmethod
    def _momentum(velocity: float, basis: str, is_new: bool) -> str:
        if basis == "coverage_uncertain":
            return "UNCERTAIN"
        if basis == "cold_start":
            return "BASELINE"
        if is_new:
            return "NEW"
        if velocity >= 75:
            return "SURGING"
        if velocity >= 60:
            return "RISING"
        if velocity > 40:
            return "STEADY"
        if velocity >= 25:
            return "COOLING"
        return "FADING"

    # ............................................................ main
    def score_sync(
        self, clusters: list[MacroCluster], cleaned: list[CleanedTrendItem], run_id: str, now: float
    ) -> tuple[list[MacroCluster], list[tuple[str, str, int, float]]]:
        by_id = {c.item_id: c for c in cleaned}
        cur_keys: list[str] = []
        for c in cleaned:
            cur_keys.extend([dedupe_key(c.normalized_title)] * max(1, c.duplicate_count))
        refs = self._reference_runs(run_id, now)
        have_history = any(r is not None for r in refs.values())
        snapshots: dict[str, tuple[str, str, int, float]] = {}
        w_rel = self.settings.rank_relevance_weight

        for cl in clusters:
            members = [by_id[i] for i in cl.member_item_ids if i in by_id]
            # ---- relevance
            h_rel = self.heuristic_relevance(members)
            llm_rel = cl.llm_relevance
            rel = 0.65 * llm_rel + 0.35 * h_rel if llm_rel is not None else h_rel
            cl.relevance_score = int(max(1, min(10, round(rel))))

            # ---- velocity
            entity_results = []
            for label in cl.primary_entities:
                m = EntityMatcher(label)
                if not m.key:
                    continue
                freq, rate, windows, vel, is_new = self._entity_velocity(m, cur_keys, refs)
                if freq == 0:
                    continue  # entity name not grounded in any title this run
                entity_results.append((freq, vel, windows, is_new))
                prev = snapshots.get(m.key)
                if prev is None or freq > prev[2]:
                    snapshots[m.key] = (m.key, label, freq, round(rate, 4))

            if not entity_results:
                # fall back to the cluster headline as a pseudo-entity
                m = EntityMatcher(cl.headline.split(":")[-1].strip())
                freq, rate, windows, vel, is_new = self._entity_velocity(m, cur_keys, refs)
                if freq:
                    entity_results.append((freq, vel, windows, is_new))

            scored = [(f, v, w, n) for f, v, w, n in entity_results if v is not None]
            if have_history and scored:
                total_f = sum(f for f, *_ in scored)
                velocity = sum(f * v for f, v, *_ in scored) / total_f
                lead = max(scored, key=lambda x: x[0])
                cl.velocity_windows = lead[2]
                cl.velocity_basis = "historical"
                is_new = all(n for *_, n in scored)
            else:
                mean_h = sum(m.heuristic_score for m in members) / len(members) if members else 0.5
                diversity = min(1.0, len(cl.sources) / 3)
                velocity = 50 + 30 * (2 * mean_h - 1) + 10 * diversity
                cl.velocity_basis = "cold_start"
                is_new = False
                if entity_results:
                    cl.velocity_windows = entity_results[0][2]
            comparable = {src for ref in refs.values() if ref for src in ref.current_by_source}
            uncovered = have_history and not (set(cl.sources) & comparable)
            cl.momentum_uncertain = self.coverage_uncertain or uncovered
            cl.momentum_note = "; ".join(self.coverage_notes)
            if uncovered:
                cl.momentum_note += "; cluster has no comparable source evidence"
            if cl.momentum_uncertain:
                cl.velocity_basis = "coverage_uncertain"
                velocity = 50.0  # uncertain history must not boost or penalize the ranking
            cl.velocity_score = round(max(0.0, min(100.0, velocity)), 1)
            cl.momentum = self._momentum(cl.velocity_score, cl.velocity_basis, is_new)
            cl.combined_score = round(w_rel * cl.relevance_score * 10 + (1 - w_rel) * cl.velocity_score, 2)

        clusters.sort(key=lambda c: (c.combined_score, c.relevance_score, c.raw_item_count), reverse=True)
        return clusters, list(snapshots.values())

    async def score(
        self, clusters: list[MacroCluster], cleaned: list[CleanedTrendItem], run_id: str, now: float
    ) -> tuple[list[MacroCluster], list[tuple[str, str, int, float]]]:
        return await asyncio.to_thread(self.score_sync, clusters, cleaned, run_id, now)
