"""Focused tests for scripts/edition_quality.py (pure stdlib; no network, no Ollama).

These test the benchmark's logic on small synthetic editions and check the label files'
structure. They deliberately assert nothing about how accurate the heuristics are on the real
editions: that is reported by `python scripts/edition_quality.py --evaluate`, not enforced here.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("edition_quality", ROOT / "scripts" / "edition_quality.py")
eq = importlib.util.module_from_spec(_spec)
sys.modules["edition_quality"] = eq
_spec.loader.exec_module(eq)


def src(title, kind="report", outlet="Wire", url=None, origin=None):
    return {"outlet": outlet, "title": title, "kind": kind, "url": url or f"https://example.com/{abs(hash(title))}",
            "reporting_origin": origin}


def story(sid, headline, summary, rank=1, top=None, sources=None, why="because", change="", cov=None, **extra):
    s = {"id": sid, "rank": rank, "top_rank": top, "headline": headline, "summary": summary,
         "why_it_matters": why, "change": change, "sources": sources if sources is not None else [src(headline)],
         "coverage": cov if cov is not None else {"independent_reports": 1, "publishers": ["Wire"]}}
    s.update(extra)
    return s


def edition(stories, quality=None):
    e = {"stories": stories, "top": []}
    if quality:
        e["quality"] = quality
    return e


def checks(findings, name):
    return [f for f in findings if f["check"] == name]


def test_every_check_has_exactly_one_tier_and_failures_are_few_and_named():
    assert set(eq.TIERS.values()) == {eq.FAILURE, eq.WARNING, eq.INFO}
    for name, tier in eq.TIERS.items():
        # editorial judgments must carry a review/adds_little name, never read like a verdict
        if tier == eq.WARNING:
            assert name.endswith("_review") or name == "summary_adds_little", name


def test_empty_summary_is_a_failure_not_a_warning():
    f = eq.check_edition("2026-10-10", edition([story("a", "Big thing happens in town", [])]))
    hit = checks(f, "empty_summary")
    assert hit and hit[0]["tier"] == eq.FAILURE


def test_headline_restating_summary_is_only_a_warning():
    f = eq.check_edition("d", edition([story("a", "Mayor opens new bridge", ["Mayor opens new bridge."])]))
    hit = checks(f, "summary_adds_little")
    assert hit and hit[0]["tier"] == eq.WARNING


def test_informative_summary_is_not_flagged():
    f = eq.check_edition("d", edition([story("a", "Mayor opens new bridge", ["The 2-mile span cost $40 million and links two districts."])]))
    assert not checks(f, "summary_adds_little")


def test_unrelated_source_title_is_review_not_failure():
    s = story("a", "Hurricane lashes Gulf coast", ["Storm hit Florida."],
              sources=[src("Hurricane lashes Gulf coast"), src("College football preview for Saturday", outlet="Fox")])
    hit = checks(eq.check_edition("d", edition([s])), "source_title_review")
    assert hit and hit[0]["tier"] == eq.WARNING and "REVIEW" in hit[0]["message"]


def test_invalid_source_reference_is_a_failure():
    s = story("a", "Mayor opens new bridge", ["It spans two miles."], sources=[{"outlet": "", "title": "x", "kind": "report", "url": "ftp://x"}])
    hit = checks(eq.check_edition("d", edition([s])), "invalid_source_reference")
    assert hit and hit[0]["tier"] == eq.FAILURE


def test_encoding_corruption_detected_but_proper_apostrophe_is_not():
    bad = story("a", "Apple\u0393\u00c7\u00d6s event next week", ["Event details are expected."])
    ok = story("b", "Apple\u2019s event next week", ["Event details are expected."])
    assert checks(eq.check_edition("d", edition([bad])), "encoding_corruption")
    assert not checks(eq.check_edition("d", edition([ok])), "encoding_corruption")


def test_coverage_count_larger_than_truncated_source_list_is_not_a_failure():
    srcs = [src(f"Report {i} on the vote", outlet=f"O{i}") for i in range(8)]
    cov = {"independent_reports": 10, "publishers": [f"O{i}" for i in range(10)]}
    f = eq.check_edition("d", edition([story("a", "Report on the vote", ["Vote counted."], sources=srcs, cov=cov)]))
    assert not checks(f, "coverage_exceeds_sources")


def test_coverage_larger_than_publishers_is_a_failure():
    cov = {"independent_reports": 5, "publishers": ["A", "B"]}
    f = eq.check_edition("d", edition([story("a", "Mayor opens new bridge", ["It spans two miles."], cov=cov)]))
    assert checks(f, "coverage_exceeds_sources")[0]["tier"] == eq.FAILURE


def test_similar_stories_are_a_review_warning_and_shared_url_is_distinct():
    a = story("a", "Russian glide bomb attack kills 15 in Zaporizhzhia", ["Attack on Zaporizhzhia killed at least 15 people."], rank=1)
    b = story("b", "War in Ukraine: strikes kill 15 including a girl", ["Zaporizhzhia attack killed at least 15 people, police said."], rank=2)
    hit = checks(eq.check_edition("d", edition([a, b])), "similar_story_review")
    assert hit and hit[0]["tier"] == eq.WARNING


def test_two_topic_title_is_review():
    s = story("a", "Trump says no attack on Iran. And, ICE agent shoots man in NYC", ["Trump says no attack. And, ICE agent shoots man in NYC."])
    hit = checks(eq.check_edition("d", edition([s])), "two_topics_review")
    assert hit and hit[0]["tier"] == eq.WARNING


def test_top_size_and_why_are_edition_level_warnings():
    stories = [story(f"s{i}", f"Distinct headline number {i} about topic{i}", [f"Details about topic{i} appear here."], rank=i + 1, top=i + 1, why=None) for i in range(9)]
    f = eq.check_edition("d", edition(stories))
    assert checks(f, "top_size_review")[0]["tier"] == eq.WARNING
    why = checks(f, "top_missing_why_review")
    assert len(why) == 1 and why[0]["story"] is None


def test_invalid_top_rank_is_a_failure():
    stories = [story("a", "Alpha story headline", ["Alpha details here."], rank=1, top=1), story("b", "Beta story headline", ["Beta details here."], rank=2, top=1)]
    assert checks(eq.check_edition("d", edition(stories)), "top_rank_invalid")[0]["tier"] == eq.FAILURE


def test_era_follows_quality_block_so_legacy_findings_are_separated():
    legacy = edition([story("a", "Mayor opens bridge", ["Mayor opens bridge."])])
    current = edition([story("a", "Mayor opens bridge", ["Mayor opens bridge."])], quality={"stories_accepted": 1})
    assert eq.check_edition("2026-10-07", legacy)[0]["era"] == "legacy"
    assert eq.check_edition("2026-10-10", current)[0]["era"] == "current"
    findings = eq.check_edition("2026-10-07", legacy) + eq.check_edition("2026-10-10", current)
    text = eq.render_text(findings, [])
    assert "legacy-era (historical, not counted as regressions)" in text


def test_continuity_not_assessable_without_published_event_ids_and_story_id_is_ignored():
    e1 = edition([story("id-old", "Hurricane Isaias hits coast", ["Storm landfall in Florida."])])
    e2 = edition([story("id-new", "Hurricane Isaias hits coast", ["Storm landfall in Florida."])])
    f = eq.check_continuity({"2026-10-08": e1, "2026-10-09": e2})
    assert [x["check"] for x in f] == ["continuity_not_assessable"]
    assert f[0]["tier"] == eq.INFO


def test_continuity_uses_event_id_when_both_editions_publish_it():
    same = story("x1", "Hurricane Isaias hits coast", ["Storm landfall in Florida."], event_id="evt_1")
    same2 = story("x2", "Hurricane Isaias hits coast", ["Storm landfall in Florida."], event_id="evt_1")
    split = story("x3", "Hurricane Isaias hits coast", ["Storm landfall in Florida."], event_id="evt_2")
    ok = eq.check_continuity({"d1": edition([same]), "d2": edition([same2])})
    assert ok == []
    bad = eq.check_continuity({"d1": edition([same]), "d2": edition([split])})
    assert [x["check"] for x in bad] == ["possible_identity_split_review"] and bad[0]["tier"] == eq.WARNING


def test_evaluate_counts_precision_recall_and_unsupported_defects():
    findings = [{"edition": "d", "story": "a", "check": "summary_adds_little", "tier": eq.WARNING, "era": "current", "message": ""},
                {"edition": "d", "story": "c", "check": "source_title_review", "tier": eq.WARNING, "era": "current", "message": ""},
                {"edition": "d", "story": "z", "check": "continuity_not_assessable", "tier": eq.INFO, "era": "current", "message": ""}]
    labels = {"name": "t", "status": "s", "items": [
        {"edition": "d", "story": "a", "label": "defect", "defect_type": "echo", "expected_checks": ["summary_adds_little"], "note": ""},
        {"edition": "d", "story": "b", "label": "defect", "defect_type": "echo", "expected_checks": ["summary_adds_little"], "note": ""},
        {"edition": "d", "story": "u", "label": "defect", "defect_type": "garbled", "expected_checks": [], "note": ""},
        {"edition": "d", "story": "c", "label": "clean", "note": "legit"},
        {"edition": "d", "story": "z", "label": "clean", "note": "info is not a prediction"}]}
    r = eq.evaluate(findings, labels)
    assert (r["defects"], r["defects_detected"], r["defects_with_implemented_check"]) == (3, 1, 2)
    assert r["recall_all_defects"] == 0.33 and r["recall_implemented_checks"] == 0.5
    assert r["precision"] == 0.5 and r["false_positive_rate_on_clean"] == 0.5
    assert [x["story"] for x in r["clean_stories_flagged"]] == ["d c"]
    assert r["defects_with_no_implemented_check"] == ["d u: garbled"]


def _items(name):
    data = json.loads((ROOT / "tests" / "fixtures" / "editorial" / name).read_text(encoding="utf-8"))
    return data, data["items"]


def test_label_files_are_marked_auditor_labeled_and_well_formed():
    for name in ("auditor_labeled_smoke.json", "auditor_labeled_validation.json"):
        data, items = _items(name)
        assert "NOT independently reviewed" in data["status"]
        for it in items:
            assert it["label"] in ("defect", "clean")
            assert it["edition"] and it["story"] and it["note"]
            if it["label"] == "defect":
                assert it["defect_type"] and set(it["expected_checks"]) <= set(eq.TIERS)
            else:
                assert "expected_checks" not in it


def test_validation_sample_is_separate_from_smoke_and_has_both_kinds():
    _, smoke = _items("auditor_labeled_smoke.json")
    _, val = _items("auditor_labeled_validation.json")
    key = lambda i: (i["edition"], i["story"])
    assert not {key(i) for i in smoke} & {key(i) for i in val}
    assert {"defect", "clean"} == {i["label"] for i in val}


def test_label_story_ids_exist_in_published_editions():
    eds = eq.load(ROOT / "website" / "editions")
    for name in ("auditor_labeled_smoke.json", "auditor_labeled_validation.json"):
        for it in _items(name)[1]:
            assert it["edition"] in eds, it
            pinned = _items(name)[0]["edition_revisions"][it["edition"]]
            if eds[it["edition"]].get("revision") != pinned:
                continue  # edition republished since labeling; evaluate() reports these as stale
            assert any(s["id"] == it["story"] for s in eds[it["edition"]]["stories"]), it


def test_cli_is_non_blocking_by_default_and_json_is_valid():
    r = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "edition_quality.py"), "--json", "--evaluate"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert {"summary", "evaluations", "findings"} <= set(out)
    assert all(f["tier"] in (eq.FAILURE, eq.WARNING, eq.INFO) for f in out["findings"])


def test_labels_for_a_republished_edition_are_reported_stale_not_scored():
    eds = {"d": {"revision": 9}}
    labels = {"name": "t", "status": "s", "edition_revisions": {"d": 7},
              "items": [{"edition": "d", "story": "a", "label": "clean", "note": "n"}]}
    r = eq.evaluate([{"edition": "d", "story": "a", "check": "summary_adds_little", "tier": eq.WARNING, "era": "current", "message": ""}], labels, eds)
    assert r["stale_labels_excluded"] == ["d a"] and r["clean"] == 0 and r["clean_stories_flagged"] == []
