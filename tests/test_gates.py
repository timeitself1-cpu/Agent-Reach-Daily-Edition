"""Pre-publish quality gates (daily/gates.py). The cases below are the defects of the October 10, 2026 edition,
VERBATIM from the export AgentReachDaily-2026-10-10.html (supplied by the user).

In that export a failed summary appears as the headline repeated; the live site (rc21) omits the summary element
when it repeats the headline. Both shapes are the same failure, so each is tested: no summary, and a summary
identical to the headline."""
from __future__ import annotations

import json
from datetime import date

import pytest

from agent_reach.daily import gates
from agent_reach.daily.edition import DailyEdition
from agent_reach.daily.gates import GateConfig, check_text, format_quarantine, run_gates, write_quarantine

CFG = GateConfig.from_settings()

GIGABYTE = "Gigabyte's latest BIOS update hints at Intel's Raptor Lake Next Launch in 2027"
AI_SAFETY = "Artificial intelligence and social integration paradox"
MICRO1 = "micro1 Commits $1bn to Buy Company Data for Training AI Agents"
ICE = "NYC man shot by ICE still has bullet in body, lawyers say"
VIBE = ("We Might Be Cooked, As These Vibe-Coded Web Browser Ports Of Halo, The Simpsons: Hit And Run, "
        "And GTA: Vice City Seem To Work Perfectly")

#: (name, headline, summary sentences, lead report text, reasons that must be among the result)
OCT_10 = [
    ("gigabyte-live", GIGABYTE, [], "", {"empty"}),
    ("gigabyte-export", GIGABYTE, [GIGABYTE + "."], "", {"headline_echo"}),
    ("ai-safety", AI_SAFETY, [AI_SAFETY + "."], "", {"headline_echo", "tautology"}),
    ("micro1", MICRO1,
     ["Exceptions that require judgment micro1 will spend $1bn in 12 months buying company data to train AI "
      "agents, financed by Citi and Hercules."], "", {"prompt_leak"}),
    ("ice-fresno", ICE, ["The incident occurred early Friday in Fresno."], "", {"contradiction"}),
    ("vibe-coded", VIBE, [VIBE + "."], "", {"headline_echo"}),
]
GOOD = ("Fed holds rates steady and signals one cut this year",
        ["The Federal Reserve left its benchmark interest rate unchanged on Wednesday and projected a single "
         "quarter-point cut before the end of the year, citing slower hiring."],
        "The Federal Reserve kept rates where they were.")


@pytest.mark.parametrize("name,headline,summary,lead,expected", OCT_10, ids=[c[0] for c in OCT_10])
def test_each_october_10_defect_is_quarantined_with_its_reason(name, headline, summary, lead, expected):
    reasons, _ = check_text(headline, summary, lead, CFG)
    assert expected <= set(reasons), reasons


def test_a_sound_summary_passes():
    assert check_text(GOOD[0], GOOD[1], GOOD[2], CFG) == ([], {})


def test_thin_and_headline_echo():
    h = "Hackers obtain counterfeit TLS certificates for Google and Microsoft"
    assert "thin" in check_text(h, ["Russia says the woman died of pneumonia."], "", CFG)[0]
    echo = ["Hackers have obtained counterfeit TLS certificates for Google and Microsoft, security researchers said, "
            "according to the report."]
    assert "headline_echo" in check_text(h, echo, "", CFG)[0]
    assert gates.headline_overlap(echo[0], h) > 0.6


def test_the_fresno_conflict_names_both_places():
    _, conflicts = check_text(ICE, ["The incident occurred early Friday in Fresno."], "", CFG)
    assert conflicts["headline_or_lead"] == ["New York City"] and "Fresno" in conflicts["summary"]


def test_places_inside_the_headline_place_are_not_contradictions():
    summary = ["Police said the man was shot in Brooklyn on Thursday after a struggle with federal immigration "
               "agents, and that he was taken to a hospital in stable condition."]
    assert check_text("Man shot by ICE agent in NYC, officials say", summary, "", CFG)[0] == []


def test_gulf_of_mexico_is_not_mexico():
    summary = ["Tropical Storm Isaias has formed in the Gulf of Mexico and is forecast to strengthen into a "
               "hurricane before reaching the Texas coast this weekend, forecasters said."]
    assert check_text("Tropical Storm Isaias forms near the United States", summary, "", CFG)[0] == []


@pytest.mark.parametrize("opening", [
    "Here is a summary of the story: the company said it would cut jobs.",
    "As an AI language model, I do not have access to the article.",
    "I cannot verify the claims in this report so here is what the article says about it.",
    "Summarize the following:",
])
def test_instruction_like_openings_are_leaks(opening):
    assert gates.leaked(opening, CFG.leak_patterns)
    assert "prompt_leak" in check_text("Company announces layoffs", [opening, "The company said on Monday it would cut jobs across several divisions this year."], "", CFG)[0]


def test_a_quoted_i_cannot_is_not_a_leak():
    s = ['"I cannot say how long this will last," the mayor told reporters on Monday, as the flooding closed '
         'three bridges and forced hundreds of residents out of their homes.']
    assert gates.leaked(s[0], CFG.leak_patterns) is None


def test_leak_patterns_come_from_the_settings(monkeypatch):
    monkeypatch.setenv("AGENT_REACH_LEAK_PATTERNS", json.dumps(["^zzz"]))
    cfg = GateConfig.from_settings()
    assert cfg.leak_patterns == ("^zzz",) and gates.leaked("zzz wins", cfg.leak_patterns)


def test_a_broken_pattern_does_not_stop_the_gate():
    assert gates.leaked("Exceptions that require judgment", ("(", r"exceptions")) == "exceptions"


def _edition(name: str) -> DailyEdition:
    from pathlib import Path
    return DailyEdition.model_validate_json((Path(__file__).parent / "fixtures" / "real" / name).read_text("utf-8"))


def test_gates_over_a_real_edition_account_for_every_story():
    ed = _edition("2026-10-07-rc12d2-r2.json")
    out = run_gates(ed.stories, CFG)
    assert len(out.accepted) + len(out.quarantined) == len(ed.stories)
    assert out.quarantined and all(r.reasons for r in out.quarantined)
    assert set(out.reason_counts()) <= set(gates.REASONS)
    # nothing the gates keep is empty or thin
    assert all(not {"empty", "thin"} & set(r.reasons) for r in out.results if r not in out.quarantined)


def test_quarantine_log_is_written_per_day_and_listed(tmp_path):
    ed = _edition("2026-10-07-rc12d2-r2.json")
    out = run_gates(ed.stories, CFG)
    write_quarantine(tmp_path, date(2026, 10, 10), "run-a", out)
    write_quarantine(tmp_path, date(2026, 10, 10), "run-b", out)
    write_quarantine(tmp_path, date(2026, 10, 10), "run-b", out)  # a re-run of the same run replaces its entry
    doc = json.loads((tmp_path / "quarantine" / "2026-10-10.json").read_text("utf-8"))
    assert [r["run_id"] for r in doc["runs"]] == ["run-a", "run-b"]
    entry = doc["runs"][-1]["quarantined"][0]
    assert {"story_id", "headline", "summary", "reason", "reasons"} <= set(entry)
    text = format_quarantine(doc)
    assert "quarantined" in text and entry["headline"] in text
    assert "no quarantine log" in format_quarantine(None)


def test_cli_lists_the_days_quarantine(tmp_path, capsys):
    from agent_reach.daily.__main__ import main
    ed = _edition("2026-10-07-rc12d2-r2.json")
    write_quarantine(tmp_path, date(2026, 10, 10), "run-a", run_gates(ed.stories, CFG))
    assert main(["--quarantine", "--date", "2026-10-10", "--data-dir", str(tmp_path)]) == 0
    assert "Quarantine for 2026-10-10" in capsys.readouterr().out
    assert main(["--quarantine", "--date", "2026-10-11", "--data-dir", str(tmp_path)]) == 0
    assert "no quarantine log" in capsys.readouterr().out


def test_refresh_holds_back_failing_stories_and_says_so(daily_env, monkeypatch):
    """End to end in the fake world with the gates on: the fake summaries are one line, so the word minimum is
    lowered; stories with no summary of their own (headline only) are still quarantined, counted and logged."""
    from agent_reach.daily import refresh as R
    from agent_reach.daily.store import EditionStore
    from tests.daily_fakes import OllamaUp

    monkeypatch.setenv("AGENT_REACH_GATES_ENABLED", "1")
    monkeypatch.setenv("AGENT_REACH_GATE_MIN_SUMMARY_WORDS", "1")
    out = R.refresh(daily_env.paths, trigger="manual", force=True, ollama_probe=lambda p: OllamaUp())
    assert out.code == R.EXIT_PUBLISHED, out.message
    ed = EditionStore(daily_env.paths).load_latest().edition
    q = ed.quality
    assert q is not None and q.stories_accepted == len(ed.stories) and q.stories_quarantined >= 1
    assert q.reason_counts.get("empty", 0) >= 1
    assert any("held back by the quality checks" in n for n in ed.notes)
    log = json.loads((daily_env.paths.root / "quarantine" / f"{ed.edition_date.isoformat()}.json").read_text("utf-8"))
    run = log["runs"][-1]
    assert run["stories_quarantined"] == q.stories_quarantined and run["stories_accepted"] == len(ed.stories)
    held = {x["headline"] for x in run["quarantined"]}
    assert held and not held & {s.headline for s in ed.stories}
    assert [s.rank for s in ed.stories] == list(range(1, len(ed.stories) + 1))
    from agent_reach.daily.publish import public_edition
    assert public_edition(ed)["quality"]["stories_quarantined"] == q.stories_quarantined


def test_a_broken_gate_keeps_the_previous_edition(daily_env, monkeypatch):
    from agent_reach.daily import refresh as R
    from agent_reach.daily.store import EditionStore
    from tests.daily_fakes import OllamaUp

    monkeypatch.setenv("AGENT_REACH_GATES_ENABLED", "1")
    monkeypatch.setattr(gates, "run_gates", lambda *a, **k: 1 / 0)
    out = R.refresh(daily_env.paths, trigger="manual", force=True, ollama_probe=lambda p: OllamaUp())
    assert out.code != R.EXIT_PUBLISHED and "quality checks could not run" in out.message
    assert EditionStore(daily_env.paths).load_latest().edition is None
