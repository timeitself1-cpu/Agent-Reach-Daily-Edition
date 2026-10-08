"""Silent updates (agent_reach.daily.updater): a fake GitHub serves a release of the app's ``stable`` branch, and a
fake app folder is updated, kept, or put back. No network; the real app folder (a git checkout) is never touched."""

from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import httpx
import pytest

from agent_reach.daily import __version__, updater as U
from agent_reach.daily.lock import RefreshLock

ROOT = Path(__file__).resolve().parents[1]
OLD = "a" * 40
NEW = "b" * 40
VERSION = "1.0.0rc99"


def release_files(version: str = VERSION, build: str = NEW, **extra: bytes) -> dict[str, bytes]:
    files = {
        "release.json": json.dumps({"version": version, "notes": "Faster refreshes.", "setup_required": ""}).encode(),
        "agent_reach/daily/build.txt": f"{build}\n".encode(),
        "agent_reach/daily/__init__.py": f'__version__ = "{version}"\n'.encode(),
        "agent_reach/daily/app.py": b"# new app\n",
        "agent_reach/daily/new_module.py": b"# added in this release\n",
        "requirements.txt": b"httpx>=0.27\n",
        "AgentReachDaily.cmd": b"@echo off\r\nrem same as before\r\n",
    }
    files.update(extra)
    return files


def make_zip(files: dict[str, bytes], top: str = "timeitself1-cpu-Agent-Reach-Daily-Edition-bbbbbbb") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{top}/", b"")
        for name, data in files.items():
            zf.writestr(f"{top}/{name}" if not name.startswith("..") else name, data)
    return buf.getvalue()


class FakeGitHub:
    """api.github.com (branch head, release.json, zipball redirect) and codeload.github.com (the zip)."""

    def __init__(self, files: dict[str, bytes] | None = None, sha: str = NEW, zip_bytes: bytes | None = None) -> None:
        self.files = files or release_files()
        self.sha = sha
        self.zip = zip_bytes if zip_bytes is not None else make_zip(self.files)
        self.calls: list[str] = []
        self.offline = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.url.host}{request.url.path}")
        if self.offline:
            raise httpx.ConnectError("offline")
        path = request.url.path
        if request.url.host == "api.github.com" and path == f"/repos/{U.REPO}/commits/stable":
            return httpx.Response(200, json={"sha": self.sha})
        if request.url.host == "api.github.com" and path == f"/repos/{U.REPO}/contents/release.json":
            assert request.url.params["ref"] == self.sha
            return httpx.Response(200, json={"encoding": "base64",
                                             "content": base64.b64encode(self.files["release.json"]).decode()})
        if request.url.host == "api.github.com" and path == f"/repos/{U.REPO}/zipball/{self.sha}":
            return httpx.Response(302, headers={"Location": f"https://codeload.github.com/{U.REPO}/legacy.zip/{self.sha}"})
        if request.url.host == "codeload.github.com":
            return httpx.Response(200, content=self.zip)
        return httpx.Response(404, json={"message": "Not Found"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=True)


class Runner:
    """Stands in for pip, the new version's --version and --install-task."""

    def __init__(self, version_ok: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.version_ok = version_ok

    def __call__(self, args, *, cwd, timeout):
        self.calls.append(list(args[1:]))
        if args[-1] == "--version":
            return subprocess.CompletedProcess(args, 0 if self.version_ok else 1,
                                               stdout=f"Agent Reach Daily {VERSION}\n" if self.version_ok else "",
                                               stderr="" if self.version_ok else "ImportError: boom")
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")


@pytest.fixture(autouse=True)
def updates_allowed(monkeypatch):
    monkeypatch.delenv(U.NO_UPDATE_ENV, raising=False)  # conftest switches updates off for every other test


@pytest.fixture
def app(tmp_path) -> Path:
    """An installed app folder of the previous release (from a zip: build.txt filled in, no .git)."""
    root = tmp_path / "Agent-Reach"
    files = {
        "agent_reach/daily/build.txt": f"{OLD}\n",
        "agent_reach/daily/__init__.py": f'__version__ = "{__version__}"\n',
        "agent_reach/daily/app.py": "# old app\n",
        "agent_reach/daily/dropped.py": "# removed by the new release\n",
        "requirements.txt": "httpx>=0.27\n",
        "AgentReachDaily.cmd": "@echo off\r\nrem same as before\r\n",
        "my-notes.txt": "the user's own file\n",
        ".venv/Scripts/python.exe": "not really python",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(text.encode())
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _remember_files(daily_paths, *names: str) -> None:
    """installed-files.json as the previous update left it."""
    U.updates_dir(daily_paths).mkdir(parents=True, exist_ok=True)
    (U.updates_dir(daily_paths) / "installed-files.json").write_text(json.dumps({"files": list(names)}))


# ---------------------------------------------------------------------------------------------------- versions
def test_versions_compare_and_name_the_release():
    assert U.parse_version("1.0.0rc17") > U.parse_version("1.0.0rc9")
    assert U.parse_version("1.0.0") > U.parse_version("1.0.0rc99") > U.parse_version("1.0.0b3")
    with pytest.raises(ValueError):
        U.parse_version("rc17")
    assert U.label("1.0.0rc17") == "version 1.0 (release candidate 17)" and U.label("1.0.0") == "version 1.0"


def test_this_repository_describes_its_release_for_the_updater():
    """release.json names the version in __init__.py; build.txt is filled in by git archive (export-subst)."""
    assert json.loads((ROOT / "release.json").read_text())["version"] == __version__
    assert "agent_reach/daily/build.txt export-subst" in (ROOT / ".gitattributes").read_text()
    if not (ROOT / ".git").exists():  # an installed folder (the self-test on the PC): build.txt names its commit
        assert U.installed_build(ROOT) is not None
        return
    assert (ROOT / "agent_reach/daily/build.txt").read_text().strip() == "$Format:%H$"
    assert U.installed_build(ROOT) is None and U.why_not(ROOT, True)  # a developer checkout never updates itself
    git = shutil.which("git")
    if git is None or subprocess.run([git, "cat-file", "-e", "HEAD:agent_reach/daily/build.txt"], cwd=ROOT,
                                     capture_output=True).returncode != 0:
        pytest.skip("build.txt is not committed in this checkout yet")
    tar = subprocess.run([git, "archive", "--format=tar", "HEAD", "agent_reach/daily/build.txt"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
        text = tf.extractfile("agent_reach/daily/build.txt").read().decode().strip()
    head = subprocess.run([git, "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    assert text == head  # what a zip of this commit says it is


# ---------------------------------------------------------------------------------------------------- updating
def test_an_update_replaces_only_what_changed_and_keeps_everything_else(daily_paths, app):
    _remember_files(daily_paths, "agent_reach/daily/dropped.py", "agent_reach/daily/app.py")
    gh, run = FakeGitHub(), Runner()
    out = U.update(daily_paths, app, client=gh.client(), run=run, python="py", task_installed=lambda: True)
    assert out.state == "updated", out.message
    assert (app / "agent_reach/daily/app.py").read_bytes() == b"# new app\n"
    assert (app / "agent_reach/daily/new_module.py").exists()
    assert not (app / "agent_reach/daily/dropped.py").exists()  # the previous release had it, this one does not
    assert (app / "my-notes.txt").read_text() == "the user's own file\n"  # never in a release: never touched
    assert (app / ".venv/Scripts/python.exe").read_text() == "not really python"
    assert U.installed_build(app) == NEW
    # unchanged requirements: no package install; scheduler.py unchanged: the task is left alone
    assert run.calls == [["-m", "agent_reach.daily", "--version"]]
    backup = U.updates_dir(daily_paths) / "backup"
    assert (backup / "agent_reach/daily/app.py").read_bytes() == b"# old app\n"
    assert not (backup / "AgentReachDaily.cmd").exists()  # identical bytes are not rewritten
    status = U.load_status(daily_paths)
    assert status.last_update.to_version == VERSION and status.last_update.build == NEW
    assert json.loads((U.updates_dir(daily_paths) / "installed-files.json").read_text())["build"] == NEW
    # the window says so once
    kind, text = U.take_notice(daily_paths)
    assert kind == "info" and text == "Updated to version 1.0 (release candidate 99). Faster refreshes."
    assert U.take_notice(daily_paths) is None
    # the next check finds this build installed: nothing to do, nothing downloaded
    gh.calls.clear()
    assert U.update(daily_paths, app, client=gh.client(), run=run, python="py").state == "current"
    assert gh.calls == [f"api.github.com/repos/{U.REPO}/commits/stable"]


def test_new_packages_and_a_changed_scheduled_task_are_installed(daily_paths, app):
    files = release_files(**{"requirements.txt": b"httpx>=0.27\nrich>=13\n",
                             "agent_reach/daily/scheduler.py": b"# new task definition\n"})
    gh, run = FakeGitHub(files), Runner()
    out = U.update(daily_paths, app, client=gh.client(), run=run, python="py", task_installed=lambda: True)
    assert out.state == "updated" and "Python packages installed" in out.message and "scheduled task renewed" in out.message
    assert run.calls[0][:3] == ["-m", "pip", "install"] and run.calls[-1] == ["-m", "agent_reach.daily", "--install-task"]


def test_a_new_version_that_does_not_start_is_rolled_back(daily_paths, app):
    _remember_files(daily_paths, "agent_reach/daily/dropped.py")
    before = _snapshot(app)
    out = U.update(daily_paths, app, client=FakeGitHub().client(), run=Runner(version_ok=False), python="py")
    assert out.state == "failed" and "did not start" in out.message and "keeps version" in out.message
    assert _snapshot(app) == before  # every file as it was, the added ones gone, the deleted one back
    kind, text = U.take_notice(daily_paths)
    assert kind == "warn" and "tries again the next time the app opens" in text
    assert U.take_notice(daily_paths) is None


@pytest.mark.parametrize("zip_bytes, reason", [
    (make_zip({**release_files(), "../escape.py": b"x"}, top="t"), "unsafe file name"),
    (make_zip(release_files(build="c" * 40)), "not the announced release"),
    (make_zip(release_files(version="1.0.0rc98")), "not the announced version"),
    (b"not a zip", "damaged"),
])
def test_a_wrong_or_unsafe_download_changes_nothing(daily_paths, app, zip_bytes, reason):
    before = _snapshot(app)
    out = U.update(daily_paths, app, client=FakeGitHub(zip_bytes=zip_bytes).client(), run=Runner(), python="py")
    assert out.state == "failed" and reason in out.message
    assert _snapshot(app) == before and not (app.parent / "escape.py").exists()


def test_never_older_never_the_same_and_never_a_developer_checkout(daily_paths, app, monkeypatch):
    run = Runner()
    older = FakeGitHub(release_files(version="1.0.0rc1"))
    assert U.update(daily_paths, app, client=older.client(), run=run).state == "current"
    assert all("zipball" not in c for c in older.calls)
    same = FakeGitHub(sha=OLD)
    assert U.update(daily_paths, app, client=same.client(), run=run).state == "current"
    # no check at all: switched off, environment variable, a git checkout, a folder without build.txt
    quiet = FakeGitHub()
    assert U.update(daily_paths, app, auto_update=False, client=quiet.client()).state == "skipped"
    monkeypatch.setenv(U.NO_UPDATE_ENV, "1")
    assert U.update(daily_paths, app, client=quiet.client()).state == "skipped"
    monkeypatch.delenv(U.NO_UPDATE_ENV)
    (app / ".git").mkdir()
    assert "developer checkout" in U.update(daily_paths, app, client=quiet.client()).message
    (app / ".git").rmdir()
    (app / "agent_reach/daily/build.txt").write_text("$Format:%H$\n")
    assert U.update(daily_paths, app, client=quiet.client()).state == "skipped"
    assert quiet.calls == [] and run.calls == []


def test_offline_or_busy_the_app_just_opens(daily_paths, app):
    gh = FakeGitHub()
    gh.offline = True
    out = U.update(daily_paths, app, client=gh.client(), run=Runner())
    assert out.state == "skipped" and "could not be reached" in out.message
    gh.offline = False
    with RefreshLock(daily_paths.lock_file):  # a refresh is running: its code is not replaced under it
        out = U.update(daily_paths, app, client=gh.client(), run=Runner())
    assert out.state == "skipped" and "refresh is running" in out.message
    assert all("zipball" not in c for c in gh.calls)
    with U.window_lock(daily_paths):  # the hourly check waits while a window is open
        out = U.update(daily_paths, app, client=gh.client(), run=Runner(), background=True)
    assert out.state == "skipped" and "window is open" in out.message
    assert U.update(daily_paths, app, client=gh.client(), run=Runner(), python="py", background=True).state == "updated"


def test_a_redirect_to_another_site_is_refused(daily_paths, app):
    gh = FakeGitHub()
    original = gh.handler

    def elsewhere(request):
        if request.url.host == "api.github.com" and "zipball" in request.url.path:
            return httpx.Response(302, headers={"Location": "https://example.com/evil.zip"})
        if request.url.host == "example.com":
            return httpx.Response(200, content=gh.zip)
        return original(request)

    client = httpx.Client(transport=httpx.MockTransport(elsewhere), follow_redirects=True)
    out = U.update(daily_paths, app, client=client, run=Runner())
    assert out.state == "failed" and "unexpected address" in out.message and U.installed_build(app) == OLD


# ---------------------------------------------------------------------------------------------------- entry points
def test_the_window_restarts_on_the_new_code_after_an_update(daily_paths, monkeypatch):
    pytest.importorskip("tkinter")
    from agent_reach.daily import __main__ as M, gui

    opened, spawned = [], []
    monkeypatch.setattr(gui, "run_gui", lambda paths: opened.append(paths) or 0)
    monkeypatch.setattr(U, "relaunch", lambda argv: spawned.append(argv))
    monkeypatch.setattr(U, "update", lambda paths, **kw: U.Outcome("updated", "Updated."))
    assert M.main(["--gui", "--data-dir", str(daily_paths.root)]) == 0
    assert spawned == [["--gui", "--data-dir", str(daily_paths.root)]] and opened == []
    monkeypatch.setattr(U, "update", lambda paths, **kw: U.Outcome("current", "Up to date."))
    assert M.main(["--gui", "--data-dir", str(daily_paths.root)]) == 0 and len(opened) == 1
    # the restarted window does not check again
    monkeypatch.setenv(U.UPDATED_ENV, "1")
    monkeypatch.setattr(U, "update", lambda paths, **kw: pytest.fail("checked twice"))
    assert M.main(["--gui", "--data-dir", str(daily_paths.root)]) == 0 and len(opened) == 2


def test_the_hourly_check_updates_only_when_nothing_is_due(daily_paths, monkeypatch):
    from agent_reach.daily import __main__ as M
    from agent_reach.daily.refresh import RefreshOutcome

    calls = []
    monkeypatch.setattr(U, "update", lambda paths, **kw: calls.append(kw) or U.Outcome("current", "Up to date."))
    monkeypatch.setattr("agent_reach.daily.refresh.refresh",
                        lambda paths, **kw: RefreshOutcome(10, "not_due", "Next refresh is due later."))
    assert M.main(["--refresh-if-due", "--data-dir", str(daily_paths.root)]) == 10
    assert calls and calls[0]["background"] is True
    calls.clear()
    monkeypatch.setattr("agent_reach.daily.refresh.refresh",
                        lambda paths, **kw: RefreshOutcome(0, "published", "Published 40 stories."))
    assert M.main(["--refresh-if-due", "--data-dir", str(daily_paths.root)]) == 0 and calls == []


def test_the_window_shows_what_the_update_did(daily_paths):
    from datetime import datetime, timezone

    from agent_reach.daily.app import AppController

    status = U.UpdateStatus(last_update=U.LastUpdate(from_version="1.0.0rc16", to_version="1.0.0rc17", build=NEW,
                                                     at_utc=datetime(2026, 10, 9, tzinfo=timezone.utc),
                                                     notes="Updates install themselves."))
    U._save_status(daily_paths, status)
    snap = AppController(daily_paths).snapshot()
    assert any(b.kind == "info" and b.text.startswith("Updated to version 1.0 (release candidate 17).")
               for b in snap.banners)
    assert not any("Updated to" in b.text for b in AppController(daily_paths).snapshot().banners)  # once


def test_details_say_how_the_app_updates(daily_paths):
    from agent_reach.daily.app import AppController, details_report

    ctrl = AppController(daily_paths)
    rows = dict(row for _, section in details_report(ctrl.snapshot(), daily_paths) for row in section)
    if (ROOT / ".git").exists():
        assert rows["Updates"].startswith("Off: this is a developer checkout")  # a checkout never updates itself
    else:  # the self-test in the installed folder on the PC
        assert rows["Updates"].startswith("Automatic: when the app opens")
