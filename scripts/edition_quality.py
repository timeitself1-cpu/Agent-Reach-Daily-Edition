"""Editorial quality report for published editions (read-only, stdlib only, non-blocking).

    python scripts/edition_quality.py                 # text report over website/editions
    python scripts/edition_quality.py --json          # machine-readable
    python scripts/edition_quality.py --markdown      # for a CI job summary
    python scripts/edition_quality.py --evaluate      # score checks against the labeled samples

Three kinds of output, kept apart on purpose:

  failure  Deterministic facts about the published data (empty summary, invalid source
           reference, a coverage count larger than the sources behind it, ...). These are
           true or false without editorial judgment.
  warning  Heuristics that mark a story or pair FOR HUMAN REVIEW (summary adds nothing to the
           headline, a cited title shares little with the headline, two stories look alike,
           ...). A warning is never a claim that a story is wrong, unsupported or duplicated.
  info     Context, e.g. cross-edition continuity that cannot be assessed.

Nothing here verifies facts: it only reads the stored headline, summary, source titles and
metadata, never the cited articles, and keyword overlap is not evidence of support.

Historical editions: ``era`` is ``current`` when the edition carries the ``quality`` block that
the publisher's editorial review writes, otherwise ``legacy``. Legacy findings are reported
separately and never count toward the current-state totals, so an old edition cannot make a
later fix look like a regression.

Cross-edition continuity uses the edition's own event identity. The story ``id`` is an evidence
fingerprint that is expected to change (agent_reach/daily/edition.py), so it is never compared.
Continuity is assessed only between two editions that both publish ``event_id``; otherwise it is
reported as not assessable.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "editorial"

FAILURE, WARNING, INFO = "failure", "warning", "info"

# check name -> tier. Failures are deterministic data facts; warnings need a human.
TIERS = {
    "empty_summary": FAILURE,
    "duplicate_story_id": FAILURE,
    "invalid_source_reference": FAILURE,
    "coverage_exceeds_sources": FAILURE,
    "top_rank_invalid": FAILURE,
    "encoding_corruption": FAILURE,
    "summary_adds_little": WARNING,
    "source_title_review": WARNING,
    "similar_story_review": WARNING,
    "shared_report_url_review": WARNING,
    "two_topics_review": WARNING,
    "top_size_review": WARNING,
    "top_not_rank_prefix_review": WARNING,
    "top_missing_why_review": WARNING,
    "updated_without_delta_review": WARNING,
    "possible_identity_split_review": WARNING,
    "continuity_not_assessable": INFO,
}

STOP = set("the a an of to in on for and as at by with from is are after over into new says say its it be has have will not no".split())
MOJIBAKE = re.compile("\u0393\u00c7|\u00e2\u20ac|\u00c3[\u0080-\u00bf]|\ufffd")
TWO_TOPICS = re.compile(r"[.?!]\s+And,\s", re.I)
ROUNDUP = re.compile(r"\b(newsletter|live updates|live blog|podcast|week in review|morning briefing)\b", re.I)
SOURCE_KINDS = {"report", "repeat", "signal"}
SOURCE_LIST_CAP = 8  # every published story lists at most 8 sources


def toks(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9$]+", (s or "").lower()) if w not in STOP and len(w) > 2}


def jac(a: str, b: str) -> float:
    x, y = toks(a), toks(b)
    return len(x & y) / max(1, len(x | y))


def norm_url(u: str) -> str:
    return (u or "").split("?")[0].rstrip("/")


def era(e: dict) -> str:
    return "current" if e.get("quality") else "legacy"


def has_event_ids(e: dict) -> bool:
    s = e.get("stories") or []
    return bool(s) and all(x.get("event_id") for x in s)


def load(dir_: Path) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(dir_.glob("20??-??-??.json"))}


def _f(edition, e, check, story, message):
    return {"edition": edition, "era": era(e), "tier": TIERS[check], "check": check, "story": story, "message": message}


def check_edition(date: str, e: dict) -> list[dict]:
    out: list[dict] = []
    S = e.get("stories") or []

    def add(check, story, msg):
        out.append(_f(date, e, check, story, msg))

    seen_ids: set[str] = set()
    for s in S:
        sid = s.get("id")
        if sid in seen_ids:
            add("duplicate_story_id", sid, "story id appears twice in this edition")
        seen_ids.add(sid)
    tops = sorted(s["top_rank"] for s in S if s.get("top_rank"))
    if tops != list(range(1, len(tops) + 1)) or len(tops) > 10:
        add("top_rank_invalid", None, f"top_rank values {tops} are not 1..N with N<=10")
    elif len(tops) != 10:
        add("top_size_review", None, f"Top list has {len(tops)} stories (expected 10 unless selection is intentionally short)")
    top = [s for s in S if s.get("top_rank")]
    if sorted(s["rank"] for s in top) != sorted(s["rank"] for s in S)[: len(top)]:
        add("top_not_rank_prefix_review", None, "Top set is not the first N ranks; selection rule is not visible in the data")

    no_why = [s["id"] for s in top if not s.get("why_it_matters")]
    if no_why:
        add("top_missing_why_review", None, f"{len(no_why)} of {len(top)} Top stories have no why_it_matters (edition-level: this is a pipeline property, not a per-story verdict)")

    for s in S:
        sid, head = s["id"], s.get("headline", "")
        summ = " ".join(s.get("summary") or [])
        if not summ.strip():
            add("empty_summary", sid, "no summary text")
        elif toks(summ) <= toks(head) or jac(head, summ) > 0.8:
            add("summary_adds_little", sid, "summary has no terms beyond the headline (review whether it explains what happened)")
        if MOJIBAKE.search(head + " " + summ + " " + (s.get("why_it_matters") or "")):
            add("encoding_corruption", sid, "encoding-corruption characters in headline/summary/why")
        for src in s.get("sources") or []:
            url = src.get("url") or ""
            if not url.startswith(("http://", "https://")) or not src.get("outlet") or src.get("kind") not in SOURCE_KINDS:
                add("invalid_source_reference", sid, f"source missing a valid url/outlet/kind: {str(src)[:80]}")
            elif MOJIBAKE.search(src.get("title") or ""):
                add("encoding_corruption", sid, f"corrupt source title: {src['title'][:60]}")
        if TWO_TOPICS.search(head + " " + summ):
            add("two_topics_review", sid, "headline/summary appears to join two topics ('... And, ...')")
        reports = [x for x in s.get("sources") or [] if x.get("kind") == "report"]
        odd = [x for x in reports if jac(head, x.get("title", "")) < 0.12 or ROUNDUP.search(x.get("title", ""))]
        if odd:
            add("source_title_review", sid, "cited report titles share little with the headline (REVIEW; same event may be worded differently): "
                + "; ".join(f"{x.get('outlet')}: {x.get('title', '')[:50]}" for x in odd))
        cov = s.get("coverage") or {}
        origins = {x.get("reporting_origin") for x in reports if x.get("reporting_origin")}
        indep = cov.get("independent_reports", 0)
        # The public `sources` list is capped (8 entries in every published edition), so a longer
        # coverage count is only a defect when the list is not truncated or publishers disagree.
        truncated = len(s.get("sources") or []) >= SOURCE_LIST_CAP
        publishers = cov.get("publishers")
        if (publishers is not None and indep > len(publishers)) or (not truncated and indep > len(reports)) \
                or (not truncated and origins and indep > len(origins)):
            add("coverage_exceeds_sources", sid, f"independent_reports={indep} but publishers={len(publishers or [])}, listed reports={len(reports)}, origins={len(origins)}")
        if s.get("change") == "updated" and summ and jac(head, summ) > 0.8:
            add("updated_without_delta_review", sid, "labelled 'updated' but summary only restates the headline")

    for a, b in itertools.combinations(S, 2):
        shared = {norm_url(x["url"]) for x in a.get("sources", []) if x.get("kind") == "report" and x.get("url")} & \
                 {norm_url(x["url"]) for x in b.get("sources", []) if x.get("kind") == "report" and x.get("url")}
        if shared:
            add("shared_report_url_review", f"{a['id']}|{b['id']}", f"{len(shared)} report URL(s) cited by both stories: '{a['headline'][:45]}' / '{b['headline'][:45]}'")
        ta = toks(a["headline"] + " " + " ".join(a.get("summary") or []))
        tb = toks(b["headline"] + " " + " ".join(b.get("summary") or []))
        common = ta & tb
        jc = len(common) / max(1, len(ta | tb))
        j = jac(a["headline"], b["headline"])
        if not shared and (j >= 0.5 or (len(common) >= 4 and jc >= 0.2)):
            add("similar_story_review", f"{a['id']}|{b['id']}", f"headline j={j:.2f}, content {jc:.2f}: '{a['headline'][:45]}' / '{b['headline'][:45]}' (REVIEW: may be one event or related events)")
    return out


def check_continuity(eds: dict[str, dict]) -> list[dict]:
    """Assess continuity with each edition's own published event identity, never the story id."""
    out: list[dict] = []
    dates = list(eds)
    for d1, d2 in zip(dates, dates[1:]):
        e1, e2 = eds[d1], eds[d2]
        if not (has_event_ids(e1) and has_event_ids(e2)):
            out.append(_f(d2, e2, "continuity_not_assessable", None,
                          f"{d1} -> {d2}: no published event_id on every story of both editions; the story id is an evidence fingerprint and is not compared"))
            continue
        by_event = {s["event_id"]: s for s in e1["stories"]}
        for b in e2["stories"]:
            if b["event_id"] in by_event:
                continue
            for a in e1["stories"]:
                if jac(a["headline"], b["headline"]) >= 0.6:
                    out.append(_f(d2, e2, "possible_identity_split_review", f"{a['event_id']}>{b['event_id']}",
                                  f"near-identical headline under a different event_id ({d1} -> {d2}): '{b['headline'][:55]}' (REVIEW)"))
    return out


def run(eds: dict[str, dict]) -> list[dict]:
    out: list[dict] = []
    for d, e in eds.items():
        out += check_edition(d, e)
    return out + check_continuity(eds)


# ---------------------------------------------------------------- label evaluation

def _hits(findings: list[dict], edition: str, story: str | None):
    keys = {story} if story else {None}
    return [f for f in findings if f["edition"] == edition and
            (f["story"] in keys or (story and story in str(f["story"]).replace(">", "|").split("|")))]


def evaluate(findings: list[dict], labels: dict) -> dict:
    """Story-level precision/recall for one labeled sample.

    A defect counts as detected only when one of its ``expected_checks`` fired on that story;
    defects with no implemented check (empty ``expected_checks``) are listed separately and
    count against overall recall. Precision = detected defects / (detected defects + clean
    stories that received any failure or warning). Info findings are never predictions.
    """
    detected, missed, no_check, fp, tn = [], [], [], [], []
    for it in labels["items"]:
        fl = [f for f in _hits(findings, it["edition"], it.get("story")) if f["tier"] != INFO]
        fired = {f["check"] for f in fl}
        if it["label"] == "defect":
            if not it["expected_checks"]:
                no_check.append(it)
            elif fired & set(it["expected_checks"]):
                detected.append(it)
            else:
                missed.append(it)
        else:
            (fp if fl else tn).append((it, sorted(fired)))
    nd = len(detected) + len(missed) + len(no_check)
    checkable = len(detected) + len(missed)
    flagged = len(detected) + len(fp)
    name = lambda i: f"{i['edition']} {i['story']}: {i['defect_type']}"
    return {
        "sample": labels.get("name"),
        "status": labels.get("status"),
        "defects": nd,
        "clean": len(fp) + len(tn),
        "defects_detected": len(detected),
        "recall_all_defects": round(len(detected) / nd, 2) if nd else None,
        "defects_with_implemented_check": checkable,
        "recall_implemented_checks": round(len(detected) / checkable, 2) if checkable else None,
        "missed_despite_implemented_check": [name(i) for i in missed],
        "defects_with_no_implemented_check": [name(i) for i in no_check],
        "precision": round(len(detected) / flagged, 2) if flagged else None,
        "clean_stories_flagged": [{"story": f"{i['edition']} {i['story']}", "note": i["note"], "fired": c} for i, c in fp],
        "false_positive_rate_on_clean": round(len(fp) / (len(fp) + len(tn)), 2) if (fp or tn) else None,
    }

def summarize(findings: list[dict]) -> dict:
    s: dict = {}
    for f in findings:
        s.setdefault(f["edition"], {"era": f["era"]}).setdefault(f["tier"], {}).setdefault(f["check"], 0)
        s[f["edition"]][f["tier"]][f["check"]] += 1
    return s


def render_text(findings, evals) -> str:
    lines = ["Editorial quality report (non-blocking). failure = deterministic data fact; warning = flagged FOR HUMAN REVIEW, not a verdict.", ""]
    for d, v in summarize(findings).items():
        lines.append(f"{d} [{v['era']}]")
        for tier in (FAILURE, WARNING, INFO):
            if tier in v:
                lines.append(f"  {tier}: " + ", ".join(f"{k}={n}" for k, n in sorted(v[tier].items())))
    cur = [f for f in findings if f["era"] == "current"]
    lines += ["", f"current-era totals: failures={sum(f['tier'] == FAILURE for f in cur)} warnings={sum(f['tier'] == WARNING for f in cur)}",
              f"legacy-era (historical, not counted as regressions): failures={sum(f['tier'] == FAILURE and f['era'] == 'legacy' for f in findings)} warnings={sum(f['tier'] == WARNING and f['era'] == 'legacy' for f in findings)}"]
    for ev in evals:
        lines += ["", f"Label sample '{ev['sample']}' ({ev['status']}):", json.dumps(ev, indent=1, ensure_ascii=False)]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--editions", default=str(ROOT / "website" / "editions"))
    ap.add_argument("--smoke", default=str(FIXTURES / "auditor_labeled_smoke.json"))
    ap.add_argument("--validation", default=str(FIXTURES / "auditor_labeled_validation.json"))
    ap.add_argument("--evaluate", action="store_true", help="score the checks against the labeled samples")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--fail-on-failures", action="store_true", help="exit 1 if a CURRENT-era deterministic failure exists (off by default; not used in CI)")
    a = ap.parse_args()
    eds = load(Path(a.editions))
    findings = run(eds)
    evals = []
    if a.evaluate:
        for p in (a.smoke, a.validation):
            if Path(p).exists():
                evals.append(evaluate(findings, json.loads(Path(p).read_text(encoding="utf-8"))))
    if a.json:
        print(json.dumps({"summary": summarize(findings), "evaluations": evals, "findings": findings}, indent=1, ensure_ascii=False))
    elif a.markdown:
        print("```\n" + render_text(findings, evals) + "\n```")
    else:
        print(render_text(findings, evals))
    bad = a.fail_on_failures and any(f["tier"] == FAILURE and f["era"] == "current" for f in findings)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

