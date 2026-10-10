"""The golden set: stories whose right outcome is known (``tests/golden/golden.json``), run through the same gates and
headline style a refresh applies, as a self-check BEFORE an edition is saved or published.

Why: the quality gates are plain rules (patterns, a gazetteer, word overlap). A tweak to one of them, or to a
setting such as ``AGENT_REACH_LEAK_PATTERNS``, can quietly stop catching the October 10, 2026 defects or start
rejecting good stories. ``refresh`` runs this first; any case that no longer behaves as recorded fails the attempt and
the previous edition stays (invariant 8). It is deterministic, offline and takes milliseconds.

A case states ``expect`` ("accept" or "quarantine"), the ``reasons`` that must be among the gate's reasons, optionally
the ``conflicts`` (entities) a contradiction must name and the ``normalized_headline`` the published headline must equal.
Nothing is ever edited to make the run pass: a failure is a gate that changed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agent_reach.daily.gates import GateConfig, check_text
from agent_reach.daily.headlines import HeadlineConfig, normalize_headline

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "tests" / "golden" / "golden.json"


@dataclass
class GoldenReport:
    checked: int = 0
    failures: list[str] = field(default_factory=list)
    available: bool = True

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        if not self.available:
            return "the golden set was not found, so the self-check was skipped"
        if self.ok:
            return f"all {self.checked} golden cases behave as recorded"
        return f"{len(self.failures)} of {self.checked} golden cases changed: " + "; ".join(self.failures[:5])


def load_cases(path: Path | None = None) -> list[dict]:
    data = json.loads((path or GOLDEN_PATH).read_text(encoding="utf-8"))
    return list(data["cases"])


def _vouching(case: dict) -> str:
    """The story's own prose as the publisher sees it: the lead report and any summary that is not the headline."""
    head = case["headline"].strip().rstrip(".").lower()
    own = [s for s in case["summary"] if s.strip().rstrip(".").lower() != head]
    return " ".join([case.get("lead") or ""] + own)


def check_case(case: dict, gate_cfg: GateConfig, head_cfg: HeadlineConfig) -> list[str]:
    """What is wrong with this case now (an empty list: it behaves as recorded)."""
    problems: list[str] = []
    reasons, conflicts = check_text(case["headline"], case["summary"], case.get("lead") or "", gate_cfg)
    if case["expect"] == "accept" and reasons:
        problems.append(f"should pass but was held back ({', '.join(reasons)})")
    if case["expect"] == "quarantine":
        missing = [r for r in case.get("reasons", []) if r not in reasons]
        if not reasons:
            problems.append("should be held back but passed")
        elif missing:
            problems.append(f"no longer held back for {', '.join(missing)} (now: {', '.join(reasons)})")
    wanted = case.get("conflicts")
    if wanted:
        named = json.dumps(conflicts, default=str).lower()
        if not all(w.lower() in named for w in wanted):
            problems.append(f"contradiction no longer names {', '.join(wanted)}")
    expected_headline = case.get("normalized_headline")
    if expected_headline is not None:
        got = normalize_headline(case["headline"], vouching_text=_vouching(case), cfg=head_cfg)
        if got != expected_headline:
            problems.append(f"headline became {got!r}, expected {expected_headline!r}")
    return problems


def run_golden(gate_cfg: GateConfig | None = None, head_cfg: HeadlineConfig | None = None,
               path: Path | None = None) -> GoldenReport:
    gate_cfg = gate_cfg or GateConfig.from_settings()
    head_cfg = head_cfg or HeadlineConfig.from_settings()
    target = path or GOLDEN_PATH
    if not target.is_file():
        return GoldenReport(available=False)
    report = GoldenReport()
    for case in load_cases(target):
        report.checked += 1
        for problem in check_case(case, gate_cfg, head_cfg):
            report.failures.append(f"{case['id']}: {problem}")
    return report
