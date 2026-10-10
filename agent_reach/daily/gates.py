"""Pre-publish quality gates: the last look at each story's public text, after the sentence-by-sentence source
check (``summary_checks.verified_story``) and before an edition is assembled, saved, rendered or published.

A story that fails is *quarantined*, never silently dropped: it is counted in the edition (``QualityReport``),
written with its reasons to ``quarantine/YYYY-MM-DD.json`` in the data folder, and listed by
``python -m agent_reach.daily --quarantine``. These gates only ever take a story out. They never write text, so
every sentence that remains is still one the source check accepted.

Reason codes: ``empty``, ``thin``, ``headline_echo``, ``tautology``, ``prompt_leak``, ``contradiction``.
The regression cases are the October 10, 2026 edition's defects (``tests/golden``, ``tests/test_gates.py``).

No model and no network is used (the gates must be deterministic and fast, and must run when Ollama is down).
The contradiction check is therefore a gazetteer plus capitalised-name comparison, not a full NER model: it
catches a summary that puts the story somewhere else than its headline and report do (Fresno under NYC), and
misses what it does not know (places outside ``places.py``). It does NOT compare people and organisations: a
first version that compared capitalised names flagged 'Fed' against 'Federal Reserve', 'US' against 'Federal
Reserve' and 'France' against 'French' on the October 7 editions, 4 of 79 stories, none of them wrong. A person
or organisation swap is left to the sentence source check until a model-based check can be tested.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from agent_reach.daily import places

REASONS = ("empty", "thin", "headline_echo", "tautology", "prompt_leak", "contradiction")

#: Auxiliaries and copulas: 'is', 'has', 'will' say nothing about what happened.
AUXILIARIES = frozenset("""is are was were be been being am has have had having will would can could may might must
shall should do does did""".split())
#: Capitalised words that are not names when they open a sentence or follow a quotation.
_NOT_NAMES = frozenset("""the this that these those it its a an in on at for after before as with their his her they he
she we you i but and or if when while after according however also still now here there new more most one two
three four five six seven eight nine ten mr mrs ms dr""".split())
_ACRONYM_RX = re.compile(r"\b[A-Z][A-Z0-9&]{1,5}\b")
_NAME_RX = re.compile(r"\b[A-Z][a-z][A-Za-z'’-]*(?:\s+[A-Z][a-z][A-Za-z'’-]*){0,3}")


@dataclass
class GateResult:
    story_id: str
    rank: int
    headline: str
    summary: str
    reasons: list[str] = field(default_factory=list)
    conflicts: dict[str, Any] = field(default_factory=dict)

    @property
    def quarantined(self) -> bool:
        return bool(self.reasons)

    def to_json(self) -> dict:
        out = {"story_id": self.story_id, "rank": self.rank, "headline": self.headline, "summary": self.summary,
               "reason": self.reasons[0] if self.reasons else None, "reasons": list(self.reasons)}
        if self.conflicts:
            out["conflicting_entities"] = self.conflicts
        return out


@dataclass
class GateConfig:
    min_summary_words: int = 15
    max_headline_overlap: float = 0.60
    leak_patterns: tuple[str, ...] = ()

    @classmethod
    def from_settings(cls, settings=None) -> "GateConfig":
        if settings is None:
            from agent_reach.config import Settings
            settings = Settings()
        return cls(min_summary_words=settings.gate_min_summary_words,
                   max_headline_overlap=settings.gate_max_headline_overlap,
                   leak_patterns=tuple(settings.leak_patterns))


# ---------------------------------------------------------------------------------------------- the checks
def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", text)


def content_stems(text: str) -> set[str]:
    """Stopword-free, lower-cased, lightly stemmed words (the same stems the other edition checks use)."""
    from agent_reach.daily.edition import _headline_stems
    return _headline_stems(text)


def headline_overlap(summary: str, headline: str) -> float:
    """Share of the summary's content words that the headline already uses (0 for a summary without any)."""
    s = content_stems(summary)
    return len(s & content_stems(headline)) / len(s) if s else 0.0


def _first_sentence(summary: str) -> str:
    from agent_reach.daily.edition import SENTENCE_SPLIT_RX
    text = re.sub(r"^[\s*_#>\-]+", "", summary.strip())
    first = SENTENCE_SPLIT_RX.split(text, maxsplit=1)[0] if text else ""
    # 'Exceptions that require judgment...' ends in an ellipsis the splitter may keep: compare on the whole opening
    return first.strip()


def leaked(summary: str, patterns: tuple[str, ...]) -> str | None:
    """The pattern that the summary's first sentence matches (anchored at its start), or None."""
    first = _first_sentence(summary)
    for pattern in patterns:
        try:
            if re.match(pattern, first, re.IGNORECASE):
                return pattern
        except re.error:
            continue  # a bad pattern in the settings must not stop the gate; the others still run
    return None


def _verbs(text: str) -> set[str]:
    """Words that look like a main verb: the pipeline's headline verbs, irregular pasts, '-ed' forms; auxiliaries
    and copulas excluded."""
    from agent_reach.daily.edition import IRREGULAR_PAST
    from agent_reach.pipeline.cleaner import HEADLINE_VERBS
    out = set()
    for w in re.findall(r"[a-z]+", text.lower()):
        if w in AUXILIARIES:
            continue
        if w in HEADLINE_VERBS or w in IRREGULAR_PAST or (len(w) > 4 and w.endswith("ed") and not w.endswith("eed")):
            out.add(w)
    return out


def names_in(text: str, *, skip_title_case: bool = False) -> set[str]:
    """Capitalised names and acronyms, lower-cased (a sentence-initial common word is not a name). A Title Case
    headline capitalises everything, so with ``skip_title_case`` only its acronyms count."""
    out = {m.group(0).lower() for m in _ACRONYM_RX.finditer(text)}
    from agent_reach.pipeline.summary_checks import _title_case
    if skip_title_case and _title_case(text):
        return out
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for m in _NAME_RX.finditer(sentence):
            parts = m.group(0).split()
            if parts[0].lower() in _NOT_NAMES:
                parts = parts[1:]
            if m.start() == 0 and len(parts) == 1 and m.group(0).lower() not in ("",) and not parts[0].isupper():
                continue  # a lone capitalised word opening a sentence is just a word ('Artificial intelligence ...')
            name = " ".join(parts)
            if name:
                out.add(name.lower())
    return out


def adds_something(summary: str, headline: str) -> bool:
    """The summary has at least one content verb, or one named entity, that the headline does not."""
    head_stems = content_stems(headline)
    head_words = {w.lower() for w in _words(headline)}
    if any(v[:5] not in head_stems and v not in head_words for v in _verbs(summary)):
        return True
    head_names = {tok for n in names_in(headline) for tok in n.split()}
    for n in names_in(summary):
        if any(tok not in head_names and tok not in head_words and tok not in _NOT_NAMES for tok in n.split()):
            return True
    return False


def location_conflict(headline: str, summary: str, lead_excerpt: str) -> dict | None:
    """The summary names places and none of them is, or lies in or around, a place the headline or the lead
    report names: {'headline': [...], 'summary': [...]}. Quiet when either side names no listed place."""
    reference = places.places_in(" ".join([headline, lead_excerpt or ""]))
    claimed = places.places_in(summary)
    if not reference or not claimed:
        return None
    if any(places.related(c, r) for c in claimed for r in reference):
        return None
    return {"kind": "location", "headline_or_lead": [places.label(p) for p in reference],
            "summary": [places.label(p) for p in claimed]}


def check_text(headline: str, summary: list[str], lead_excerpt: str = "", cfg: GateConfig | None = None
               ) -> tuple[list[str], dict]:
    """(reason codes, conflicting entities) for one story's public headline and summary sentences."""
    cfg = cfg or GateConfig.from_settings()
    text = " ".join(s.strip() for s in summary if s and s.strip())
    reasons: list[str] = []
    conflicts: dict[str, Any] = {}
    n_words = len(_words(text))
    if not text:
        return ["empty"], {}
    if n_words < cfg.min_summary_words:
        reasons.append("thin")
    if headline_overlap(text, headline) > cfg.max_headline_overlap:
        reasons.append("headline_echo")
    if not adds_something(text, headline):
        reasons.append("tautology")
    pattern = leaked(next((x for x in summary if x and x.strip()), ""), cfg.leak_patterns)  # the opening sentence
    if pattern:
        reasons.append("prompt_leak")
        conflicts["leak_pattern"] = pattern
    conflict = location_conflict(headline, text, lead_excerpt)
    if conflict:
        reasons.append("contradiction")
        conflicts.update(conflict)
    return reasons, conflicts


def _lead_excerpt(story) -> str:
    """The lead report's text: the first cited report that is not a bare signal (title + excerpt)."""
    from agent_reach.daily.strength import SIGNAL_SOURCES
    for ev in story.evidence:
        if ev.source not in SIGNAL_SOURCES:
            return " ".join(x for x in (ev.title, ev.excerpt) if x)
    return ""


def public_text(story) -> tuple[str, list[str]]:
    """The headline and summary exactly as the website would show them (``publish._public_story``)."""
    from agent_reach.pipeline.summary_checks import useful_summary, verified_story
    headline, body = verified_story(story)
    return headline, useful_summary(headline, body)


def check_story(story, cfg: GateConfig | None = None) -> GateResult:
    headline, summary = public_text(story)
    reasons, conflicts = check_text(headline, summary, _lead_excerpt(story), cfg)
    return GateResult(story_id=story.story_id[:12], rank=story.rank, headline=headline,
                      summary=" ".join(summary), reasons=reasons, conflicts=conflicts)


# ---------------------------------------------------------------------------------------------- the stage
@dataclass
class GateOutcome:
    accepted: list
    results: list[GateResult]

    @property
    def quarantined(self) -> list[GateResult]:
        return [r for r in self.results if r.quarantined]

    def reason_counts(self) -> dict[str, int]:
        counts = {code: 0 for code in REASONS}
        for r in self.quarantined:
            for code in r.reasons:
                counts[code] += 1
        return {k: v for k, v in counts.items() if v}


def run_gates(stories: list, cfg: GateConfig | None = None) -> GateOutcome:
    """Check every story; ``accepted`` keeps the order of ``stories``. Raises on a bug in a gate: the caller
    treats that as a failed refresh (the last good edition stays), never as 'everything passed'."""
    cfg = cfg or GateConfig.from_settings()
    results = [check_story(s, cfg) for s in stories]
    accepted = [s for s, r in zip(stories, results) if not r.quarantined]
    return GateOutcome(accepted=accepted, results=results)


def quarantine_document(edition_date: date, run_id: str, outcome: GateOutcome, generated: datetime | None = None) -> dict:
    return {"date": edition_date.isoformat(), "run_id": run_id,
            "generated_utc": (generated or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stories_accepted": len(outcome.accepted), "stories_quarantined": len(outcome.quarantined),
            "reason_counts": outcome.reason_counts(), "quarantined": [r.to_json() for r in outcome.quarantined]}


def write_quarantine(root, edition_date: date, run_id: str, outcome: GateOutcome, keep_runs: int = 20) -> None:
    """Add this run to ``<data folder>/quarantine/YYYY-MM-DD.json`` (one file per day, newest run last)."""
    from agent_reach.daily.fsutil import atomic_write_json, read_json

    path = root / "quarantine" / f"{edition_date.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = read_json(path) or {}
    except Exception:  # noqa: BLE001 - a damaged log is replaced; the log must never stop a refresh
        existing = {}
    runs = [r for r in existing.get("runs", []) if r.get("run_id") != run_id]
    runs.append(quarantine_document(edition_date, run_id, outcome))
    atomic_write_json(path, {"schema": "agent_reach.quarantine", "date": edition_date.isoformat(),
                             "runs": runs[-keep_runs:]})


def format_quarantine(doc: dict | None) -> str:
    """The plain-text listing for ``--quarantine``: the day's newest run."""
    if not doc or not doc.get("runs"):
        return "Nothing was quarantined for this date (no quarantine log)."
    run = doc["runs"][-1]
    lines = [f"Quarantine for {doc['date']} (run {run['run_id']}, {run['generated_utc']}): "
             f"{run['stories_accepted']} accepted, {run['stories_quarantined']} quarantined"]
    if run["reason_counts"]:
        lines.append("  reasons: " + ", ".join(f"{k} {v}" for k, v in run["reason_counts"].items()))
    for q in run["quarantined"]:
        lines.append(f"- [{', '.join(q['reasons'])}] #{q['rank']} {q['headline']}")
        lines.append(f"    summary: {q['summary'] or '(none)'}")
        if q.get("conflicting_entities"):
            lines.append(f"    conflict: {q['conflicting_entities']}")
    return "\n".join(lines)
