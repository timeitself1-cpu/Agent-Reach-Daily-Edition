"""Editorial quality benchmark for published editions (read-only, stdlib only).

Usage:
    python scripts/edition_quality.py [--editions DIR] [--gold FILE] [--json] [--strict]

Automated checks FLAG candidates for human review; they do not verify facts.
Keyword overlap is never treated as proof that a source supports a claim.
The gold file lists human-reviewed defects (and reviewed false positives) so
the checks' recall/precision can be tracked over time.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STOP = set("the a an of to in on for and as at by with from is are after over into new says say its it be has have will not no".split())
MOJIBAKE = re.compile("\u0393\u00c7|\u00e2\u20ac|\u00c3[\u0080-\u00bf]|\ufffd")
MULTI_TOPIC = re.compile(r"[.?!]\s+And,\s", re.I)
ROUNDUP = re.compile(r"\b(newsletter|live updates|live blog|podcast|week in review|morning briefing)\b", re.I)


def toks(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9$]+", (s or "").lower()) if w not in STOP and len(w) > 2}


def jac(a: str, b: str) -> float:
    x, y = toks(a), toks(b)
    return len(x & y) / max(1, len(x | y))


def norm_url(u: str) -> str:
    return (u or "").split("?")[0].rstrip("/")


def load(dir_: Path) -> dict[str, dict]:
    out = {}
    for p in sorted(dir_.glob("20??-??-??.json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def check_edition(date: str, e: dict) -> list[dict]:
    F, S = [], e.get("stories", [])

    def add(check, sev, sid, msg):
        F.append({"edition": date, "check": check, "severity": sev, "story": sid, "message": msg})

    top = [s for s in S if s.get("top_rank")]
    if len(top) != 10:
        add("top_size", "medium", None, f"Top list has {len(top)} stories, expected 10")
    ranked = sorted(s["rank"] for s in S)[: len(top)]
    if sorted(s["rank"] for s in top) != ranked:
        add("top_not_rank_prefix", "low", None, "Top set is not the first N ranks (selection rule not visible to readers)")
    for s in S:
        sid, head = s["id"], s.get("headline", "")
        summ = " ".join(s.get("summary") or [])
        text = head + " " + summ
        if not summ.strip():
            add("empty_summary", "high", sid, "no summary")
        elif toks(summ) <= toks(head) or jac(head, summ) > 0.8:
            add("headline_echo", "medium", sid, "summary adds no new terms beyond the headline")
        if MOJIBAKE.search(text):
            add("mojibake", "medium", sid, "encoding corruption in headline/summary")
        for src in s.get("sources", []):
            if MOJIBAKE.search(src.get("title", "")):
                add("mojibake_source", "low", sid, f"corrupt source title: {src['title'][:60]}")
                break
        if MULTI_TOPIC.search(text):
            add("multi_topic_title", "high", sid, "headline/summary joins two topics ('... And, ...')")
        reports = [x for x in s.get("sources", []) if x.get("kind") == "report"]
        weak = [x for x in reports if jac(head, x.get("title", "")) < 0.12 or ROUNDUP.search(x.get("title", ""))]
        if weak:
            add("source_title_mismatch", "review", sid,
                "report titles share little with the headline (REVIEW; not proof): " + "; ".join(f"{x['outlet']}: {x['title'][:50]}" for x in weak))
        cov = s.get("coverage") or {}
        origins = {x.get("reporting_origin") for x in reports if x.get("reporting_origin")}
        if origins and cov.get("independent_reports", 0) > len(origins):
            add("coverage_overcount", "medium", sid, f"independent_reports={cov['independent_reports']} > distinct origins={len(origins)}")
        if s.get("top_rank") and not s.get("why_it_matters"):
            add("top_missing_why", "low", sid, "Top story has no why_it_matters")
        if s.get("change") == "updated" and summ and jac(head, summ) > 0.8:
            add("updated_without_delta", "medium", sid, "'updated' but summary just restates headline")
    for a, b in itertools.combinations(S, 2):
        shared = {norm_url(x["url"]) for x in a["sources"] if x.get("kind") == "report"} & \
                 {norm_url(x["url"]) for x in b["sources"] if x.get("kind") == "report"}
        j = jac(a["headline"], b["headline"])
        ta = toks(a["headline"] + " " + " ".join(a.get("summary") or []))
        tb = toks(b["headline"] + " " + " ".join(b.get("summary") or []))
        common = ta & tb
        jc = len(common) / max(1, len(ta | tb))
        if shared or j >= 0.5 or (len(common) >= 4 and jc >= 0.2):
            add("duplicate_candidate", "high" if shared else "review", f"{a['id']}|{b['id']}",
                f"j={j:.2f} content={jc:.2f} shared_urls={len(shared)}: '{a['headline'][:50]}' / '{b['headline'][:50]}'")
    return F


def check_continuity(eds: dict[str, dict]) -> list[dict]:
    F, dates = [], list(eds)
    for d1, d2 in zip(dates, dates[1:]):
        prev = {s["id"] for s in eds[d1]["stories"]}
        for b in eds[d2]["stories"]:
            for a in eds[d1]["stories"]:
                j = jac(a["headline"], b["headline"])
                if j >= 0.55 and a["id"] != b["id"]:
                    F.append({"edition": d2, "check": "id_break", "severity": "high", "story": f"{a['id']}>{b['id']}",
                              "message": f"near-identical headline (j={j:.2f}) changes id {d1}->{d2}: '{b['headline'][:55]}'"})
                    if b.get("change") == "new":
                        F.append({"edition": d2, "check": "new_but_recurring", "severity": "medium", "story": b["id"],
                                  "message": "labelled 'new' but headline recurs from previous edition"})
    return F


def score_gold(findings: list[dict], gold: dict) -> dict:
    keys = {(f["edition"], f["story"]): f["check"] for f in findings}
    by_story = {}
    for f in findings:
        by_story.setdefault((f["edition"], f["story"]), set()).add(f["check"])
        for part in str(f["story"]).split("|") + str(f["story"]).split(">"):
            by_story.setdefault((f["edition"], part), set()).add(f["check"])
    hit, miss = [], []
    for k in gold.get("defects", []):
        got = by_story.get((k["edition"], k["story"]), set())
        (hit if got & set(k["expected_checks"]) else miss).append(k["note"])
    fp = []
    for k in gold.get("not_defects", []):
        got = by_story.get((k["edition"], k["story"]), set()) & set(k["checks"])
        if got:
            fp.append(k["note"])
    n = len(gold.get("defects", []))
    return {"known_defects": n, "detected": len(hit), "recall": round(len(hit) / n, 2) if n else None,
            "missed": miss, "reviewed_false_positives_still_flagged": fp}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--editions", default=str(ROOT / "website" / "editions"))
    ap.add_argument("--gold", default=str(ROOT / "tests" / "fixtures" / "editorial_gold.json"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="exit 1 if a known gold defect is missed")
    a = ap.parse_args()
    eds = load(Path(a.editions))
    findings = []
    for d, e in eds.items():
        findings += check_edition(d, e)
    findings += check_continuity(eds)
    gold_p = Path(a.gold)
    result = score_gold(findings, json.loads(gold_p.read_text(encoding="utf-8"))) if gold_p.exists() else None
    summary = {}
    for f in findings:
        summary.setdefault(f["edition"], {}).setdefault(f["check"], 0)
        summary[f["edition"]][f["check"]] += 1
    if a.json:
        print(json.dumps({"summary": summary, "gold": result, "findings": findings}, indent=1, ensure_ascii=False))
    else:
        print("Automated flags per edition (candidates for human review, not verdicts):")
        for d, c in summary.items():
            print(" ", d, dict(sorted(c.items())))
        if result:
            print("Gold answer key:", json.dumps(result, ensure_ascii=False, indent=1))
    return 1 if (a.strict and result and result["missed"]) else 0


if __name__ == "__main__":
    sys.exit(main())
