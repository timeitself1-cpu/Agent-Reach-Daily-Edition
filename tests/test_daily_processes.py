"""Agent Reach Daily with REAL processes: the window's controller starts the real worker command as a
background process (in the offline fake world of ``tests/daily_world.py``), and the tests cancel it, kill it,
hang it, let its model go away, damage its files and restart the "window" (a new controller) afterwards.

The rule under test: the window never stays on 'Refreshing' once no worker is running, it never stops a
process that is not a refresh worker, and every ending is explained in plain words.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from agent_reach.daily.app import AppController
from agent_reach.daily.fsutil import atomic_write_json
from agent_reach.daily.paths import PROJECT_ROOT, DataPaths
from agent_reach.daily.prefs import load_prefs, save_prefs
from agent_reach.daily.render_html import render_edition_html
from agent_reach.daily.state import load_state
from agent_reach.daily.store import EditionStore
from tests.daily_world import prepare, world_command, world_settings_entries, world_spawner

TIMEOUT_S = 120


@pytest.fixture
def world(tmp_path):
    paths = DataPaths.resolve(tmp_path / "Agent Reach Daily data").ensure()  # a folder name with spaces
    prepare(paths.root)
    return paths


def _controller(paths, **env):
    return AppController(paths, spawner=world_spawner({k: str(v) for k, v in env.items()}))


def _wait(ctrl, *, stage: str | None = None, timeout: float = TIMEOUT_S) -> None:
    """Until the refresh reaches ``stage`` (or, without a stage, until no refresh is running)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        act = ctrl.activity()
        if (stage is None and not act.running) or (stage is not None and act.stage == stage):
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {stage or 'the refresh to end'}")


def _reopen(paths):
    """A new window: a fresh controller that knows nothing about earlier processes."""
    return AppController(paths).snapshot()


def _run(paths, *args, env=None):
    return subprocess.run(world_command(["--data-dir", str(paths.root), *args]), cwd=str(PROJECT_ROOT),
                          env={**os.environ, **(env or {})}, capture_output=True, text=True, timeout=TIMEOUT_S)


def _assert_idle(paths):
    snap = _reopen(paths)
    assert not snap.activity.running and snap.status_kind != "refreshing"
    assert not paths.progress_file.exists()
    return snap


def test_refresh_from_the_window_then_reopen(world):
    ctrl = _controller(world)
    assert ctrl.start_refresh(manual=True)
    assert ctrl.snapshot().status_kind == "refreshing"
    _wait(ctrl)
    snap = _assert_idle(world)
    assert snap.status == "Up to date" and snap.shown is not None and not snap.banners
    assert load_state(world)[0].last_attempt_outcome == "success"


def test_cancel_immediately_after_starting(world):
    ctrl = _controller(world, AR_WORLD_MODEL_DELAY_S=1)
    assert ctrl.start_refresh(manual=True)
    started = time.monotonic()
    assert ctrl.cancel_refresh()  # before the worker wrote any progress
    assert time.monotonic() - started < 4
    snap = _assert_idle(world)
    assert snap.state.last_attempt_outcome in (None, "cancelled")
    assert snap.state.consecutive_failures == 0


def test_cancel_halfway(world):
    ctrl = _controller(world, AR_WORLD_MODEL_DELAY_S=2)
    ctrl.start_refresh(manual=True)
    _wait(ctrl, stage="cluster")
    assert ctrl.cancel_refresh()
    snap = _assert_idle(world)
    assert snap.state.last_attempt_outcome == "cancelled" and snap.state.consecutive_failures == 0
    assert snap.status == "Refresh was cancelled"
    assert ctrl.start_refresh(manual=True)  # and the next refresh starts normally
    _wait(ctrl)
    assert load_state(world)[0].last_attempt_outcome == "success"


def test_worker_killed_halfway_is_explained_and_recovered(world):
    ctrl = _controller(world, AR_WORLD_MODEL_DELAY_S=2)
    ctrl.start_refresh(manual=True)
    _wait(ctrl, stage="cluster")
    ctrl.child.kill()  # Task Manager / a crash: nothing is recorded by the worker
    ctrl.child.wait()
    snap = _reopen(world)
    assert not snap.activity.running
    assert snap.status == "Last refresh was interrupted"
    assert "stopped before finishing" in snap.banners[0].text
    out = _run(world, "--refresh-now")
    assert out.returncode == 0, out.stdout + out.stderr
    st = load_state(world)[0]
    assert st.last_attempt_outcome == "success" and st.consecutive_failures == 0
    assert _assert_idle(world).status == "Up to date"


def test_window_killed_while_its_worker_runs(world):
    """The window process dies (killed); its refresh continues, and the next window shows it running."""
    code = ("import sys, time; from agent_reach.daily.app import AppController; "
            "from agent_reach.daily.paths import DataPaths; from tests.daily_world import world_spawner; "
            "c = AppController(DataPaths.resolve(sys.argv[1]), spawner=world_spawner({'AR_WORLD_MODEL_DELAY_S': '1'})); "
            "c.start_refresh(manual=True); print('started', flush=True); time.sleep(600)")
    window = subprocess.Popen([sys.executable, "-c", code, str(world.root)], cwd=str(PROJECT_ROOT),
                              stdout=subprocess.PIPE, text=True)
    assert window.stdout.readline().strip() == "started"
    ctrl = AppController(world)
    _wait(ctrl, stage="cluster")
    window.kill()
    window.wait()
    assert AppController(world).snapshot().activity.running  # the worker lives on and holds the lock
    _wait(ctrl)
    assert _assert_idle(world).status == "Up to date"


def test_time_limit_ends_the_refresh(world):
    ctrl = _controller(world, AR_WORLD_MODEL_DELAY_S=4, AR_WORLD_RUN_LIMIT_S=6)
    ctrl.start_refresh(manual=True)
    _wait(ctrl)
    snap = _assert_idle(world)
    assert snap.state.last_attempt_outcome == "failed"
    assert "took longer than" in snap.banners[0].text and "Traceback" not in snap.banners[0].text


def test_a_hung_worker_is_ended_by_the_watchdog(world):
    """A call that ignores cancellation (a stuck driver or DNS lookup) cannot keep 'Refreshing' forever."""
    ctrl = _controller(world, AR_WORLD_HANG_AT="cluster", AR_WORLD_RUN_LIMIT_S=2, AR_WORLD_WATCHDOG_S=6)
    ctrl.start_refresh(manual=True)
    _wait(ctrl, timeout=60)
    snap = _assert_idle(world)
    assert snap.state.last_attempt_outcome == "failed"
    assert "stopped responding" in snap.banners[0].text
    reports = sorted(world.diagnostics_dir.glob("*-watchdog.json"))
    assert reports and "time.sleep" in json.loads(reports[-1].read_text())["threads"]["MainThread"]
    assert not world.lock_info.exists()


def test_model_missing_and_model_going_away(world):
    out = _run(world, "--refresh-now", env={"AR_WORLD_MODEL_DOWN": "1"})
    assert out.returncode == 31
    snap = _assert_idle(world)
    assert "Ollama is not running" in snap.banners[0].text
    assert _run(world, "--refresh-now").returncode == 0  # a good edition first
    first = EditionStore(world).load_latest().edition
    out = _run(world, "--refresh-now", env={"AR_WORLD_MODEL_DIES_AFTER": "2"})
    assert out.returncode == 20, out.stdout
    snap = _assert_idle(world)
    assert "stopped answering during the refresh" in snap.banners[0].text
    assert snap.shown.run_id == first.run_id  # the good edition is kept


def test_model_going_away_late_is_said_in_the_edition(world):
    out = _run(world, "--refresh-now", env={"AR_WORLD_MODEL_DIES_AFTER": "5"})
    assert out.returncode == 0, out.stdout
    ed = EditionStore(world).load_latest().edition
    assert ed.model.summaries == "local_model" and ed.model.brief_calls_failed
    out = _run(world, "--refresh-now", env={"AR_WORLD_MODEL_DIES_AFTER": "4"})
    ed = EditionStore(world).load_latest().edition
    if out.returncode == 0:  # every brief call failed: one plain note, no claim of notes that are not there
        assert any("stopped answering before writing them" in n for n in ed.notes)


def test_stale_files_and_an_unrelated_process_are_left_alone(world):
    """After a power loss: progress.json and the lock-holder file name a pid that now belongs to another
    program. The window must not show a refresh, must not stop that program, and Refresh must work."""
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        info = {"pid": other.pid, "trigger": "scheduled", "stage": "cluster", "message": "Grouping",
                "started_utc": "2026-10-01T12:00:00Z"}
        atomic_write_json(world.progress_file, info)
        atomic_write_json(world.lock_info, info)
        world.lock_file.write_bytes(b"")
        ctrl = _controller(world)
        assert not ctrl.snapshot().activity.running
        assert not ctrl.cancel_refresh()
        assert other.poll() is None  # still alive
        assert ctrl.start_refresh(manual=True)
        _wait(ctrl)
        assert load_state(world)[0].last_attempt_outcome == "success"
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_damaged_files_degrade_gracefully(world):
    store = EditionStore(world)
    assert _run(world, "--refresh-now").returncode == 0
    good = store.load_latest().edition
    (world.editions_dir / "2026-09-30.json").write_text("{ not json", encoding="utf-8")  # malformed
    (world.editions_dir / "2026-10-01.json").write_text(good.model_dump_json()[:500], encoding="utf-8")  # cut short
    world.state_file.write_text("[1, 2", encoding="utf-8")
    world.settings.write_text(json.dumps({"prefs_version": 8, "max_stories": "lots",
                                          "enabled_sources": ["news_rss", "google_news", "hackernews"],
                                          "news_rss_feeds": world_settings_entries(),
                                          "podcast_auto": False}), encoding="utf-8")
    snap = _reopen(world)
    assert snap.shown.run_id == good.run_id  # older damaged files do not hide today's edition
    texts = " ".join(b.text for b in snap.banners)
    assert "max_stories" in texts and "Refresh history was unreadable" in texts
    out = _run(world, "--refresh-now")
    assert out.returncode == 0, out.stdout + out.stderr
    assert sorted(p.name.split(".")[0] for p in world.quarantine_dir.iterdir()) == ["2026-09-30", "2026-10-01"]
    latest = store.load_latest()
    latest.path.write_bytes(latest.path.read_bytes()[:300])  # the newest edition cut short (power loss)
    snap = _reopen(world)
    assert snap.shown is None and len(snap.corrupt) == 1 and not snap.activity.running
    assert "could not be read" in " ".join(b.text for b in snap.banners)
    assert _run(world, "--refresh-now").returncode == 0
    snap = _assert_idle(world)
    assert not snap.corrupt and snap.status == "Up to date" and snap.shown is not None


def test_missing_folders_are_recreated(world):
    import shutil

    assert _run(world, "--refresh-now").returncode == 0
    for d in (world.cache_dir, world.state_dir, world.logs_dir, world.diagnostics_dir):
        shutil.rmtree(d)
    snap = _reopen(world)
    assert snap.shown is None and not snap.activity.running
    assert _run(world, "--refresh-now").returncode == 0
    assert _assert_idle(world).shown is not None


def test_repeated_daily_use_stays_coherent(world, tmp_path):
    """Refresh, close, reopen, refresh, change settings, refresh: history, revisions, changes and exports."""
    ctrl = _controller(world)
    for k in range(3):
        if k == 2:
            prefs, _ = load_prefs(world)
            save_prefs(world, prefs.model_copy(update={"max_stories": 5, "follow_topics": ["Norvale"]}))
        ctrl = _controller(world)  # a new window each time
        assert ctrl.start_refresh(manual=True)
        _wait(ctrl)
        snap = _assert_idle(world)
        assert snap.status == "Up to date" and snap.shown.revision == k + 1
    ed = snap.shown
    assert [r.revision for r in ed.previous_revisions] == [1, 2]
    assert ed.changes is not None and ed.changes.compared_revision == 2
    assert len(ed.top_ranks) <= 5
    st = load_state(world)[0]
    assert st.last_success_run_id == ed.run_id and st.consecutive_failures == 0
    page = render_edition_html(ed)
    (tmp_path / "export.html").write_text(page, encoding="utf-8")
    assert "revision 3" in page and "<script" not in page.lower()
    assert sum(1 for _ in world.diagnostics_dir.glob("*.json")) == 0
