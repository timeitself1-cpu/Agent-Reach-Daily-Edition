"""Daily app: the GUI controller (no Tk), the demo edition and daily-cadence momentum windows."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_reach.daily import app as A
from agent_reach.daily.edition import DailyEdition
from agent_reach.daily.fsutil import atomic_write_json
from agent_reach.daily.paths import PROJECT_ROOT
from agent_reach.daily.prefs import DailyPrefs, build_settings
from agent_reach.daily.state import RefreshState, mark_failure, mark_running, mark_success, save_state
from agent_reach.daily.store import EditionStore
from tests.daily_fakes import make_edition, make_story

UTC = timezone.utc
T0 = datetime(2026, 10, 1, 12, 5, tzinfo=UTC)  # 7:05 AM CDT


class FakeChild:
    def __init__(self) -> None:
        self.running = True

    def poll(self):
        return None if self.running else 0


class Spawner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.children: list[FakeChild] = []

    def __call__(self, args):
        self.calls.append(args)
        child = FakeChild()
        self.children.append(child)
        return child


def _ctrl(paths, now=T0 + timedelta(hours=1)):
    spawner = Spawner()
    return A.AppController(paths, now_fn=lambda: now, spawner=spawner), spawner


def _publish(paths, started=T0, run_id="r1"):
    ed = EditionStore(paths).publish(make_edition(started=started, run_id=run_id))
    st = RefreshState()
    mark_running(st, trigger="manual", now=started, pid=1)
    mark_success(st, started=started, finished=ed.generation_completed_utc, edition_date=ed.edition_date.isoformat(),
                 run_id=run_id)
    save_state(paths, st)
    return ed


def test_first_run_is_a_friendly_empty_state(daily_paths):
    ctrl, _ = _ctrl(daily_paths)
    snap = ctrl.snapshot()
    assert snap.first_run and snap.shown is None and snap.status_kind == "empty"
    assert snap.status == "No edition yet" and snap.banners == []
    assert snap.heading == "Today's Reach" and "No successful refresh" in snap.last_success


def test_current_edition_reads_as_todays_reach(daily_paths):
    _publish(daily_paths)
    snap = _ctrl(daily_paths)[0].snapshot()
    assert snap.status_kind == "current" and snap.status == "Up to date"
    assert snap.heading == "Today's Reach" and snap.date_line == "Thursday, October 1, 2026"
    assert snap.last_success == "Last successful refresh today 7:20 AM CDT"
    assert snap.next_refresh.startswith("Next refresh tomorrow 7:05 AM CDT")
    assert snap.banners == [] and snap.coverage_line == "Sources: 1 OK"


def test_yesterdays_edition_is_clearly_stale(daily_paths):
    _publish(daily_paths, started=T0 - timedelta(days=1))
    snap = _ctrl(daily_paths)[0].snapshot()
    assert snap.status_kind == "stale" and snap.heading == "Daily Edition"
    assert snap.date_line == "Wednesday, September 30, 2026"
    assert snap.shown.edition_date.isoformat() == "2026-09-30"  # never re-dated because the app was opened
    assert any("Today's edition has not been collected yet" in b.text for b in snap.banners)


def test_failed_refresh_keeps_the_last_good_edition_in_plain_words(daily_paths):
    _publish(daily_paths)
    from agent_reach.daily.state import load_state

    st, _ = load_state(daily_paths)
    mark_running(st, trigger="scheduled", now=T0 + timedelta(minutes=50), pid=1)
    mark_failure(st, outcome="failed", now=T0 + timedelta(minutes=55), prefs=DailyPrefs(),
                 message="No new edition: Ollama is not running at http://localhost:11434.")
    save_state(daily_paths, st)
    snap = _ctrl(daily_paths)[0].snapshot()
    assert snap.status_kind == "failed" and snap.shown is not None
    assert snap.status == "Last refresh failed; showing the last good edition"
    text = snap.banners[0].text
    assert snap.banners[0].kind == "error" and "No new edition:" not in text
    assert "Ollama is not running" in text and "last good edition is still shown" in text
    assert "Traceback" not in text
    assert snap.next_refresh.startswith("Next refresh tomorrow")  # backoff ends before the regular refresh


def test_refreshing_state_and_no_double_workers(daily_paths):
    ctrl, spawner = _ctrl(daily_paths)
    assert ctrl.start_refresh(manual=True)
    assert spawner.calls[0][1:] == ["-m", "agent_reach.daily", "--refresh-now", "--trigger", "manual", "--data-dir",
                                    str(daily_paths.root)]
    assert not ctrl.start_refresh(manual=True)  # the first worker is still running
    assert len(spawner.calls) == 1
    atomic_write_json(daily_paths.progress_file, {"pid": os.getpid(), "trigger": "manual", "stage": "cluster",
                                                  "message": "Grouping and summarizing stories",
                                                  "started_utc": "2026-10-01T13:00:00Z"})
    snap = ctrl.snapshot()
    assert snap.status_kind == "refreshing"
    assert snap.status == "Refreshing (started 8:00 AM CDT): Grouping and summarizing stories"
    spawner.children[0].running = False
    daily_paths.progress_file.unlink()
    assert ctrl.snapshot().status_kind == "empty"


def test_stale_progress_file_from_a_dead_worker_is_not_refreshing(daily_paths):
    atomic_write_json(daily_paths.progress_file, {"pid": 2 ** 22 + 12345, "stage": "ingest", "message": "x"})
    assert not _ctrl(daily_paths)[0].snapshot().activity.running


def test_launch_refresh_only_when_due(daily_paths):
    ctrl, spawner = _ctrl(daily_paths)
    assert not ctrl.maybe_auto_refresh()  # first run: the user starts the first refresh
    _publish(daily_paths)
    assert not ctrl.maybe_auto_refresh()  # fresh edition: not due
    ctrl.now_fn = lambda: T0 + timedelta(hours=25)
    assert ctrl.maybe_auto_refresh()
    assert "--refresh-if-due" in spawner.calls[-1] and "gui_launch" in spawner.calls[-1]


def test_demo_edition_is_unmistakable(daily_paths):
    ctrl, _ = _ctrl(daily_paths)
    demo = ctrl.load_demo()
    snap = ctrl.snapshot()
    assert demo.demo and snap.status_kind == "demo" and snap.heading == "DEMO Edition"
    assert snap.banners[0].kind == "demo" and "NOT real news" in snap.banners[0].text
    assert "not real news" in snap.status and "not real news" in snap.date_line
    assert EditionStore(daily_paths).list_dates() == []  # the demo never enters the news cache


def test_demo_sample_file_is_valid_and_synthetic():
    path = PROJECT_ROOT / "samples" / "DEMO-edition.json"
    ed = DailyEdition.model_validate_json(path.read_bytes())
    assert ed.demo and ed.run_id.startswith("DEMO") and "DEMO" in ed.overview
    links = [e for s in ed.stories for e in s.evidence]
    assert all(e.url is None or e.url.startswith("https://example.") for e in links)
    assert all("DEMO" in e.title or "demo" in e.title for e in links)
    assert len({s.category for s in ed.stories}) >= 5


def test_archive_selection_and_filters(daily_paths):
    _publish(daily_paths, started=T0 - timedelta(days=1), run_id="old")
    _publish(daily_paths, run_id="new")
    ctrl, _ = _ctrl(daily_paths)
    ctrl.selected_date = (T0 - timedelta(days=1)).date()
    snap = ctrl.snapshot()
    assert snap.status_kind == "archive" and snap.shown.run_id == "old"
    assert "archived edition" in snap.status
    stories = snap.shown.stories
    assert [s.category.value for s in A.filter_stories(stories, "Sports", "")] == ["Sports"]
    assert len(A.filter_stories(stories, "All", "earthquake")) == 1
    assert A.filter_stories(stories, "All", "no such words") == []


def test_story_age_never_invents_a_publication_time():
    now = T0
    assert A.story_age(make_story(hours_ago=3, now=now), now) == "3h ago"
    assert A.story_age(make_story(hours_ago=0.25, now=now), now) == "15m ago"
    assert A.story_age(make_story(hours_ago=72, now=now), now) == "3 days ago"
    assert A.story_age(make_story(hours_ago=None, now=now), now) == "publication time not stated"


def test_story_publishers_are_deduplicated_and_links_are_safe():
    s = make_story()
    s.evidence.append(s.evidence[0].model_copy(update={"url": "javascript:alert(1)", "publisher": "Evil"}))
    s.evidence.append(s.evidence[0].model_copy(update={"publisher": "wire one"}))
    pubs, more = A.story_publishers(s)
    assert pubs == [("Wire One", s.evidence[0].url), ("Evil", None)] and more == 0


def test_details_report_holds_the_technical_information(daily_paths):
    _publish(daily_paths)
    snap = _ctrl(daily_paths)[0].snapshot()
    sections = dict(A.details_report(snap, daily_paths))
    edition = dict(sections["Edition"])
    assert edition["Run ID"] == "r1" and edition["Revision"] == "1"
    assert edition["Refresh started"] == "October 1, 2026 at 7:05 AM CDT"
    assert dict(sections["Local data"])["Data folder"] == str(daily_paths.root)
    assert dict(sections["Refresh history"])["Last attempt result"] == "success (manual)"


def test_window_geometry_round_trip_and_validation(daily_paths):
    A.save_window_geometry(daily_paths, "1100x820+40+30")
    assert A.load_window_geometry(daily_paths) == "1100x820+40+30"
    (daily_paths.state_dir / "window.json").write_text(json.dumps({"geometry": "huge; rm -rf"}))
    assert A.load_window_geometry(daily_paths) is None


# ------------------------------------------------------------------ daily-cadence momentum windows
class FakeHistory:
    """The three TrendDatabase methods the scorer's reference-run search uses."""

    def __init__(self, runs: dict[str, float], config: dict) -> None:
        self.runs, self.config = runs, config

    def run_context(self, run_id):
        return {"news_rss"}, self.config

    def load_observations(self, run_id):
        return {"news_rss": ["Norvale ferry strike", "Port Calder earthquake"]}

    def find_reference_run(self, target, lo, hi, exclude):
        rows = [(rid, ts) for rid, ts in self.runs.items() if rid != exclude and lo <= ts <= hi]
        if not rows:
            return None
        rid, ts = min(rows, key=lambda r: abs(r[1] - target))
        return {"run_id": rid, "started_at": ts, "kept_count": 2}


def _refs(tmp_path, runs: dict[str, float], tolerance: float | None = None):
    from agent_reach.pipeline.scorer import TrendScorer

    settings = build_settings(DailyPrefs(), type("P", (), {"db": tmp_path / "x.db"})())
    if tolerance is not None:
        settings = settings.model_copy(update={"velocity_window_tolerance": tolerance})
    scorer = TrendScorer(settings, FakeHistory(runs, {"k": 1}))
    now = 1_000_000_000.0
    return scorer._reference_runs("now", now), scorer


def test_daily_windows_find_daily_and_weekly_baselines(tmp_path):
    hour = 3600.0
    now = 1_000_000_000.0
    refs, _ = _refs(tmp_path, {"now": now, "yesterday": now - 23 * hour, "2d": now - 49 * hour, "week": now - 167 * hour})
    assert {h: (r.run_id if r else None) for h, r in refs.items()} == {24.0: "yesterday", 48.0: "2d", 168.0: "week"}


def test_one_historical_run_never_satisfies_two_windows(tmp_path):
    now = 1_000_000_000.0
    refs, scorer = _refs(tmp_path, {"now": now, "only": now - 30 * 3600.0}, tolerance=0.5)  # inside 24h and 48h ranges
    used = [h for h, r in refs.items() if r is not None]
    assert used == [24.0]
    assert any("48h no distinct reference run" in n for n in scorer.coverage_notes)


def test_hourly_runs_do_not_fake_daily_momentum(tmp_path):
    now = 1_000_000_000.0
    refs, _ = _refs(tmp_path, {"now": now, "h1": now - 3600.0, "h6": now - 6 * 3600.0})
    assert all(r is None for r in refs.values())  # 1h/6h-old runs are outside every daily window


def test_launcher_and_cli_entry_points_compile():
    import py_compile

    for name in ("AgentReachDaily.pyw",):
        py_compile.compile(str(Path(PROJECT_ROOT) / name), doraise=True)


@pytest.mark.parametrize("args,code", [(["--help"], 0), (["--version"], 0)])
def test_daily_cli_smoke(args, code):
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, "-m", "agent_reach.daily", *args], cwd=PROJECT_ROOT,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == code and "Agent Reach Daily" in proc.stdout


def test_cli_status_export_and_reset(daily_paths, tmp_path):
    import subprocess
    import sys

    def run(*args):
        return subprocess.run([sys.executable, "-m", "agent_reach.daily", *args, "--data-dir", str(daily_paths.root)],
                              cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60)

    assert run("--export-html", str(tmp_path / "x.html")).returncode == 2  # nothing to export yet
    _publish(daily_paths)
    status = json.loads(run("--status").stdout)
    assert status["latest_edition"] == "2026-10-01" and status["editions"] == ["2026-10-01"]
    out = tmp_path / "exports dir" / "today.html"
    assert run("--export-html", str(out)).returncode == 0 and "Trending news for" in out.read_text()
    refused = run("--reset-cache")
    assert refused.returncode == 2 and "--yes" in refused.stderr
    assert EditionStore(daily_paths).list_dates()
    assert run("--reset-cache", "--yes").returncode == 0
    assert EditionStore(daily_paths).list_dates() == []


def test_refresh_command_crash_is_logged_not_lost(daily_paths, monkeypatch):
    import logging

    from agent_reach.daily import __main__ as M
    from agent_reach.daily import refresh as R

    def boom(*a, **k):
        raise RuntimeError("unexpected disk problem")

    monkeypatch.setattr(R, "refresh", boom)
    try:
        assert M.main(["--refresh-now", "--data-dir", str(daily_paths.root)]) == 30
    finally:
        for h in list(logging.getLogger().handlers):
            if h.get_name() and h.get_name().startswith("agent_reach_daily_"):
                h.close()
                logging.getLogger().removeHandler(h)
    log = (daily_paths.logs_dir / "refresh.log").read_text()
    assert "refresh command crashed" in log and "unexpected disk problem" in log
