"""Windows-only durability checks with REAL Windows file locks and attributes (skipped elsewhere).

A virus scanner, OneDrive, a backup tool or an editor can hold a file of the data folder open without
sharing. These tests hold files open exactly like that (CreateFileW with no share mode) and set the
read-only attribute, then run the real worker command (offline fake world) and the window's controller.
"""

from __future__ import annotations

import contextlib
import os
import stat
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows file locking and attributes")

from agent_reach.daily.app import AppController  # noqa: E402
from agent_reach.daily.paths import PROJECT_ROOT, DataPaths  # noqa: E402
from agent_reach.daily.prefs import load_prefs, save_prefs  # noqa: E402
from agent_reach.daily.store import EditionStore  # noqa: E402
from tests.daily_world import prepare, world_command  # noqa: E402


@contextlib.contextmanager
def held_exclusively(path):
    """Open ``path`` with no sharing at all: every other open fails with a sharing violation."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    GENERIC_READ, OPEN_EXISTING = 0x80000000, 3
    handle = kernel32.CreateFileW(str(path), GENERIC_READ, 0, None, OPEN_EXISTING, 0, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error(), f"could not hold {path}")
    try:
        yield
    finally:
        kernel32.CloseHandle(handle)


@pytest.fixture
def world(tmp_path):
    paths = DataPaths.resolve(tmp_path / "Agent Reach Daily data").ensure()
    prepare(paths.root)
    return paths


def _worker(paths):
    return subprocess.run(world_command(["--refresh-now", "--data-dir", str(paths.root)]), cwd=str(PROJECT_ROOT),
                          capture_output=True, text=True, timeout=180)


def test_progress_file_held_briefly_is_still_deleted(world):
    """October 7, PC: the window read progress.json while the refresh deleted it; Windows refused the delete
    and the file outlived the refresh (test_repeated_daily_use_stays_coherent failed)."""
    import threading
    from datetime import datetime, timezone

    from agent_reach.daily.refresh import ProgressWriter

    writer = ProgressWriter(world, "manual", datetime(2026, 10, 7, tzinfo=timezone.utc))
    writer("start", "Starting refresh")
    held, release = threading.Event(), threading.Event()

    def hold():
        with held_exclusively(world.progress_file):
            held.set()
            release.wait(0.5)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(5)
    threading.Timer(0.3, release.set).start()
    writer.clear()
    t.join()
    assert not world.progress_file.exists()


def test_settings_held_open_are_left_alone(world):
    assert _worker(world).returncode == 0
    before = world.settings.read_bytes()
    with held_exclusively(world.settings):
        snap = AppController(world).snapshot()
        assert any("could not be read just now" in b.text for b in snap.banners)
        out = _worker(world)
        assert out.returncode == 30 and "could not be read" in out.stdout
    assert world.settings.read_bytes() == before
    assert not list(world.root.glob("settings.json.corrupt-*"))
    assert _worker(world).returncode == 0


def test_edition_file_held_open(world):
    assert _worker(world).returncode == 0
    latest = EditionStore(world).load_latest()
    with held_exclusively(latest.path):
        snap = AppController(world).snapshot()
        assert not snap.activity.running
        assert snap.shown is None and any("could not be read" in b.text for b in snap.banners)
        out = _worker(world)  # same date: replacing the held file fails, in plain words
        assert out.returncode == 30 and "could not be saved" in out.stdout, out.stdout
    assert latest.path.exists()  # never moved to quarantine while it was only held
    assert _worker(world).returncode == 0
    assert EditionStore(world).load_latest().edition.revision == 2


def test_read_only_settings(world):
    os.chmod(world.settings, stat.S_IREAD)  # the Windows read-only attribute
    try:
        prefs, warn = load_prefs(world)
        assert warn is None
        with pytest.raises(PermissionError):
            save_prefs(world, prefs)
        assert _worker(world).returncode == 0  # the worker never writes settings
    finally:
        os.chmod(world.settings, stat.S_IREAD | stat.S_IWRITE)


def test_worker_is_ended_by_terminate_process(world):
    """Cancel on Windows is TerminateProcess: the OS frees the byte-range lock at once."""
    import time

    from tests.daily_world import world_spawner

    ctrl = AppController(world, spawner=world_spawner({"AR_WORLD_MODEL_DELAY_S": "2"}))
    assert ctrl.start_refresh(manual=True)
    end = time.monotonic() + 120
    while ctrl.activity().stage != "cluster" and time.monotonic() < end:
        time.sleep(0.1)
    assert ctrl.cancel_refresh()
    snap = AppController(world).snapshot()
    assert not snap.activity.running and snap.state.last_attempt_outcome == "cancelled"
