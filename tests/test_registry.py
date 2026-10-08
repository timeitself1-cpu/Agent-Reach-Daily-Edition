"""The event registry (agent_reach/daily/registry.py) on real editions of October 7: stable ids, first and last
seen, idempotent recording, the candidate window, undecided matches kept apart, and the file round trip.
Matching quality is scored in tests/test_cross_edition.py."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from agent_reach.daily import registry as R
from agent_reach.daily.edition import DailyEdition

REAL = Path(__file__).parent / "fixtures" / "real"


def real(name: str) -> DailyEdition:
    return DailyEdition.model_validate(json.loads((REAL / f"2026-10-07-{name}.json").read_text(encoding="utf-8")))


def story(ed: DailyEdition, start: str):
    return next(s for s in ed.stories if s.headline.startswith(start))


def test_one_event_keeps_its_id_and_records_when_it_was_seen():
    reg = R.Registry()
    first, later = real("rc12d-r2"), real("rc12d2-r2")
    d1 = {d.rank: d for d in R.apply_edition(reg, first)}
    d2 = {d.rank: d for d in R.apply_edition(reg, later)}
    a, b = story(first, "Christa Pike"), story(later, "Christa Pike")
    assert d1[a.rank].tier == "new" and R.is_event_id(d1[a.rank].event_id)
    assert d2[b.rank].event_id == d1[a.rank].event_id and d2[b.rank].tier in {"reports", "wording"}
    assert d2[b.rank].reason and d2[b.rank].confidence >= 0.5  # explained, with a confidence
    ev = reg.events[d1[a.rank].event_id]
    assert ev.first_seen_utc == first.generation_completed_utc and ev.last_seen_utc == later.generation_completed_utc
    assert [x.edition_date for x in ev.appearances] == ["2026-10-07", "2026-10-07"] and ev.headline == b.headline
    assert any(k.startswith("u:") for k in ev.reports) and ev.names


def test_recording_an_edition_twice_changes_nothing_and_demo_editions_are_ignored():
    reg = R.Registry()
    ed = real("rc12d2-r2")
    R.apply_edition(reg, ed)
    before = reg.model_dump_json()
    assert R.apply_edition(reg, ed) == [] and reg.model_dump_json() == before
    assert R.apply_edition(R.Registry(), ed.model_copy(update={"demo": True, "run_id": "demo"})) == []


def test_events_older_than_the_window_are_not_continued():
    reg = R.Registry()
    R.apply_edition(reg, real("rc12d-r2"))
    later = real("rc12d2-r2")
    later = later.model_copy(update={"generation_completed_utc": later.generation_completed_utc
                                     + timedelta(days=R.WINDOW_DAYS + 1)})
    assert all(d.tier == "new" for d in R.apply_edition(reg, later))


def test_an_undecided_match_is_kept_apart_and_names_its_candidates():
    reg = R.Registry()
    R.apply_edition(reg, real("rc12d-r2"))
    pike = next(e for e in reg.events.values() if e.headline.startswith("Christa Pike"))
    twin = pike.model_copy(deep=True, update={"event_id": "ev-20261007-00000000"})
    reg.events[twin.event_id] = twin  # two events with the same evidence: nothing decides between them
    later = real("rc12d2-r2")
    d = next(x for x in R.match_edition(reg, later) if x.rank == story(later, "Christa Pike").rank)
    assert d.event_id is None and d.tier == "new" and set(d.ambiguous) == {pike.event_id, twin.event_id}
    assert "undecided" in d.reason


def test_the_registry_file_round_trips(daily_paths, tmp_path):
    reg = R.Registry()
    R.apply_edition(reg, real("rc12d-r2"))
    path = R.registry_file(daily_paths)
    R.save_registry(path, reg)
    assert R.load_registry(path) == reg and json.loads(path.read_text(encoding="utf-8"))["schema"] == R.REGISTRY_SCHEMA
    assert R.load_registry(tmp_path / "missing.json") == R.Registry()


def test_recording_after_a_refresh_never_fails_and_survives_a_damaged_file(daily_paths):
    path = R.registry_file(daily_paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{damaged", encoding="utf-8")
    decisions = R.record_edition(daily_paths, real("rc12d-r2"))
    assert decisions and (path.parent / "events.json.damaged").read_text(encoding="utf-8") == "{damaged"
    assert len(R.load_registry(path).events) == len(decisions)
    assert R.record_edition(daily_paths, real("rc12d-r2")) == []  # already recorded
    later = R.record_edition(daily_paths, real("rc12d2-r2"))
    assert sum(d.tier != "new" for d in later) >= 12  # 16 on Oct 8 (Christa Pike, Hamilton, the Nobels, ...)
    assert R.record_edition(daily_paths, "not an edition") is None  # a bug is logged, never raised
