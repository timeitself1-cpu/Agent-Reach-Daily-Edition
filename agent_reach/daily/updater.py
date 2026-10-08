"""Silent updates: the app follows the ``stable`` branch of its GitHub repository and installs new releases itself.

Before rc17 every release was a zip the user extracted over the folder, followed by a PowerShell command. Now:

* **When:** each time the window opens (``--gui``, before the window appears) and at the hourly scheduled check
  when no refresh is due and no window is open (a window keeps running the code it started with).
* **What:** ``GET /repos/{REPO}/commits/stable`` names the release commit; ``release.json`` at that commit gives its
  version and a plain-English note. Nothing happens when that commit is the installed one (``build.txt``, filled in
  by ``git archive``/GitHub's zip through ``export-subst``) or older than the installed version (never a downgrade).
* **How:** under the refresh lock (no refresh runs meanwhile): download GitHub's zip of exactly that commit,
  unpack it into the data folder's ``updates`` folder and check it (paths, version, build), copy only the files that
  changed over the app folder (the previous ones go to a backup first), delete files the previous release had and
  this one dropped (``installed-files.json``; never anything else), install Python packages only when
  ``requirements.txt`` changed, re-register the scheduled task only when ``scheduler.py`` changed and the task
  exists, and finally run the new version once (``--version``). Any failure restores the backup: the app keeps
  working on the version it had.
* **Never:** in a developer checkout (a ``.git`` folder, or a ``build.txt`` that was not filled in), with
  ``AGENT_REACH_NO_UPDATE=1``, or with ``auto_update`` off in the settings. The ``.venv`` and ``.git`` folders and the
  data folder are never touched. Only api.github.com and codeload.github.com are contacted, over HTTPS.

Files (``%LOCALAPPDATA%\\AgentReachDaily\\updates``): ``status.json`` (last check, last update, last error),
``installed-files.json`` (the files of the installed release), ``backup\\`` (the files the last update replaced).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from pydantic import BaseModel

from agent_reach.daily import __version__
from agent_reach.daily.fsutil import atomic_write_bytes, atomic_write_json, read_json
from agent_reach.daily.lock import LockBusy, RefreshLock
from agent_reach.daily.paths import PROJECT_ROOT, DataPaths
from agent_reach.daily.timeutil import utcnow

log = logging.getLogger(__name__)

REPO = "timeitself1-cpu/Agent-Reach-Daily-Edition"
CHANNEL = "stable"
API = "https://api.github.com"
ALLOWED_HOSTS = frozenset({"api.github.com", "codeload.github.com"})
CHECK_TIMEOUT_S = 5.0  # the window waits for the check: an offline PC must not wait long
DOWNLOAD_TIMEOUT_S = 120.0
MAX_ZIP_BYTES = 100 * 1024 * 1024
PIP_TIMEOUT_S = 20 * 60
SMOKE_TIMEOUT_S = 120
NO_UPDATE_ENV = "AGENT_REACH_NO_UPDATE"
UPDATED_ENV = "AGENT_REACH_JUST_UPDATED"
RELEASE_FILE = "release.json"
BUILD_FILE = "agent_reach/daily/build.txt"
NEVER_TOUCH = (".venv", ".git", "__pycache__")  # path parts the updater never writes, deletes or backs up
_VERSION_RX = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$")
_SHA_RX = re.compile(r"^[0-9a-f]{40}$")

Runner = Callable[..., "subprocess.CompletedProcess"]


class UpdateError(Exception):
    """The update could not be checked or installed (plain-English message); the app is unchanged."""


# ====================================================================== versions and builds
def parse_version(text: str) -> tuple[int, int, int, int, int]:
    """'1.0.0rc17' -> comparable tuple; a final release sorts after its release candidates."""
    m = _VERSION_RX.match(text.strip())
    if not m:
        raise ValueError(f"not a version: {text!r}")
    stage = {"a": 0, "b": 1, "rc": 2, None: 3}[m.group(4)]
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), stage, int(m.group(5) or 0)


def installed_build(project: Path = PROJECT_ROOT) -> str | None:
    """The commit this folder was made from (``build.txt``), or None (a developer checkout, or before rc17)."""
    try:
        text = (project / BUILD_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text if _SHA_RX.match(text) else None


def why_not(project: Path, auto_update: bool) -> str | None:
    """None when this folder may update itself, else the reason (logged, never shown as an error)."""
    if os.environ.get(NO_UPDATE_ENV, "").strip() not in ("", "0"):
        return f"updates are switched off ({NO_UPDATE_ENV})"
    if not auto_update:
        return "automatic updates are off in the settings"
    if (project / ".git").exists():
        return "this is a developer checkout (.git): it is never overwritten"
    if installed_build(project) is None:
        return "this folder does not say which release it is (build.txt)"
    return None


# ====================================================================== status (data folder)
class LastUpdate(BaseModel):
    from_version: str
    to_version: str
    build: str
    at_utc: datetime
    notes: str = ""
    setup_required: str = ""
    shown: bool = False  # the window has told the user


class UpdateStatus(BaseModel):
    last_check_utc: datetime | None = None
    last_result: str = ""  # plain English: what the last check or update did
    last_update: LastUpdate | None = None
    last_error: str = ""
    error_shown: bool = True  # the window has shown last_error (False right after a failed update)


def updates_dir(paths: DataPaths) -> Path:
    return paths.root / "updates"


def load_status(paths: DataPaths) -> UpdateStatus:
    try:
        return UpdateStatus.model_validate(read_json(updates_dir(paths) / "status.json"))
    except (OSError, ValueError):
        return UpdateStatus()


def _save_status(paths: DataPaths, status: UpdateStatus) -> None:
    try:
        atomic_write_json(updates_dir(paths) / "status.json", status.model_dump(mode="json"))
    except OSError:
        log.exception("could not record the update status")


def take_notice(paths: DataPaths) -> tuple[str, str] | None:
    """(kind, text) for the window once after an update ('Updated to ...') or a failed one; then marked shown."""
    status = load_status(paths)
    last = status.last_update
    if not status.error_shown and status.last_error:
        status.error_shown = True
        _save_status(paths, status)
        return "warn", f"{status.last_result} It tries again the next time the app opens."
    if last is None or last.shown:
        return None
    last.shown = True
    _save_status(paths, status)
    text = f"Updated to {label(last.to_version)}."
    if last.notes:
        text += f" {last.notes}"
    if last.setup_required:
        text += f" One more step: {last.setup_required}"
    return "info", text


def label(version: str) -> str:
    """'1.0.0rc17' -> 'version 1.0 (release candidate 17)'."""
    try:
        major, minor, _, stage, n = parse_version(version)
    except ValueError:
        return f"version {version}"
    return f"version {major}.{minor}" + (f" (release candidate {n})" if stage == 2 else "")


# ====================================================================== check
@dataclass
class Release:
    version: str
    build: str  # commit sha on the channel
    notes: str = ""
    setup_required: str = ""


def _client(timeout: float):
    import httpx

    return httpx.Client(timeout=timeout, follow_redirects=True,
                        headers={"Accept": "application/vnd.github+json",
                                 "User-Agent": f"AgentReachDaily/{__version__} (updater)"})


def _get(client, url: str):
    import httpx

    try:
        r = client.get(url)
    except httpx.HTTPError as exc:
        raise UpdateError(f"GitHub could not be reached ({type(exc).__name__}).") from exc
    hosts = {h.url.host for h in r.history} | {r.url.host}
    if r.url.scheme != "https" or not hosts <= ALLOWED_HOSTS:
        raise UpdateError(f"The update was redirected to an unexpected address ({r.url.host}); nothing was changed.")
    if r.status_code != 200:
        raise UpdateError(f"GitHub answered {r.status_code}.")
    return r


def check(client, current_version: str = __version__, current_build: str | None = None) -> Release | None:
    """The newer release on the channel, or None. Raises UpdateError when GitHub cannot be read."""
    sha = str(_get(client, f"{API}/repos/{REPO}/commits/{CHANNEL}").json().get("sha", ""))
    if not _SHA_RX.match(sha):
        raise UpdateError("GitHub's answer did not name a release.")
    if sha == current_build:
        return None
    body = _get(client, f"{API}/repos/{REPO}/contents/{RELEASE_FILE}?ref={sha}").json()
    try:
        info = json.loads(base64.b64decode(body["content"]).decode("utf-8"))
        version = str(info["version"])
        newer = parse_version(version) >= parse_version(current_version)
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateError("The release description on GitHub could not be read.") from exc
    if not newer:
        return None  # the channel is behind this folder: never go back
    return Release(version=version, build=sha, notes=str(info.get("notes") or ""),
                   setup_required=str(info.get("setup_required") or ""))


# ====================================================================== download and unpack
def download(client, release: Release) -> bytes:
    r = _get(client, f"{API}/repos/{REPO}/zipball/{release.build}")
    data = r.content
    if len(data) > MAX_ZIP_BYTES:
        raise UpdateError("The update is unexpectedly large; nothing was changed.")
    return data


def _safe_relpath(name: str) -> str | None:
    """A zip member below the archive's top folder as a relative POSIX path, or None for the top folder itself.
    Absolute paths, drive letters and '..' are refused (a zip must never write outside the app folder)."""
    if name.startswith(("/", "\\")):
        raise UpdateError(f"The update contains an unsafe file name ({name}); nothing was changed.")
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if any(p in ("..", "") or ":" in p for p in parts):
        raise UpdateError(f"The update contains an unsafe file name ({name}); nothing was changed.")
    rest = parts[1:]
    return "/".join(rest) if rest else None


def unpack(data: bytes, release: Release) -> dict[str, bytes]:
    """{relative path: bytes} of the release, checked: it names itself the version and build we asked for."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        files: dict[str, bytes] = {}
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = _safe_relpath(info.filename)
            if rel is None or any(part in NEVER_TOUCH for part in rel.split("/")):
                continue
            files[rel] = zf.read(info)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise UpdateError("The downloaded update is damaged; nothing was changed.") from exc
    try:
        meta = json.loads(files[RELEASE_FILE].decode("utf-8"))
        build = files[BUILD_FILE].decode("utf-8").strip()
        init = files["agent_reach/daily/__init__.py"].decode("utf-8")
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise UpdateError("The downloaded update is incomplete; nothing was changed.") from exc
    if meta.get("version") != release.version or f'__version__ = "{release.version}"' not in init:
        raise UpdateError("The downloaded update is not the announced version; nothing was changed.")
    if build != release.build:
        raise UpdateError("The downloaded update is not the announced release; nothing was changed.")
    return files


# ====================================================================== install (with backup and rollback)
def _console_python() -> str:
    """python.exe next to pythonw.exe (the window runs without a console, but we read the output)."""
    exe = Path(sys.executable)
    console = exe.with_name("python.exe") if exe.name.lower() == "pythonw.exe" else exe
    return str(console if console.exists() else exe)


def _run(args: list[str], *, cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    env = dict(os.environ, **{NO_UPDATE_ENV: "1"})
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, creationflags=flags,
                          env=env)


@dataclass
class Installed:
    written: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    packages: bool = False
    task: bool = False


def _manifest_file(paths: DataPaths) -> Path:
    return updates_dir(paths) / "installed-files.json"


def _previous_files(paths: DataPaths) -> set[str]:
    try:
        data = read_json(_manifest_file(paths))
        return {str(p) for p in data.get("files", [])} if isinstance(data, dict) else set()
    except (OSError, ValueError):
        return set()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def install(paths: DataPaths, project: Path, release: Release, files: dict[str, bytes], *,
            run: Runner = _run, python: str | None = None, task_installed: Callable[[], bool] | None = None) -> Installed:
    """Copy the release over ``project``. On any failure every changed file is put back (UpdateError)."""
    python = python or _console_python()
    backup = updates_dir(paths) / "backup"
    shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True, exist_ok=True)
    added: list[str] = []
    saved: list[str] = []  # files whose previous bytes are in the backup
    done = Installed()
    old_requirements = _read(project / "requirements.txt")
    old_scheduler = _read(project / "agent_reach/daily/scheduler.py")

    def restore() -> None:
        for rel in saved:
            try:
                atomic_write_bytes(project / rel, (backup / rel).read_bytes())
            except OSError:
                log.exception("update rollback: could not restore %s", rel)
        for rel in added:
            try:
                (project / rel).unlink(missing_ok=True)
            except OSError:
                log.exception("update rollback: could not remove %s", rel)

    try:
        for rel, data in sorted(files.items()):
            target = project / rel
            current = _read(target)
            if current == data:
                continue
            if current is None:
                added.append(rel)
            else:
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                (backup / rel).write_bytes(current)
                saved.append(rel)
            atomic_write_bytes(target, data)
            done.written.append(rel)
        for rel in sorted(_previous_files(paths) - set(files)):
            if any(part in NEVER_TOUCH for part in rel.split("/")):
                continue
            current = _read(project / rel)
            if current is None:
                continue
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            (backup / rel).write_bytes(current)
            saved.append(rel)
            (project / rel).unlink()
            done.deleted.append(rel)
        if files.get("requirements.txt") is not None and files["requirements.txt"] != old_requirements:
            proc = run([python, "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "-r",
                        "requirements.txt"], cwd=project, timeout=PIP_TIMEOUT_S)
            if proc.returncode != 0:
                raise UpdateError("The new version needs Python packages that could not be installed "
                                  f"({(proc.stderr or proc.stdout or '').strip()[-300:]}).")
            done.packages = True
        proc = run([python, "-m", "agent_reach.daily", "--version"], cwd=project, timeout=SMOKE_TIMEOUT_S)
        if proc.returncode != 0 or release.version not in (proc.stdout or ""):
            raise UpdateError("The new version did not start "
                              f"({(proc.stderr or proc.stdout or '').strip()[-300:] or 'no answer'}).")
    except UpdateError:
        restore()
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        restore()
        raise UpdateError(f"The update could not be installed ({type(exc).__name__}: {exc}).") from exc
    # the scheduled task: re-registered only when its definition changed and it exists (never a failed update)
    new_scheduler = files.get("agent_reach/daily/scheduler.py")
    if new_scheduler is not None and new_scheduler != old_scheduler and (task_installed or _task_installed)():
        try:
            proc = run([python, "-m", "agent_reach.daily", "--install-task"], cwd=project, timeout=SMOKE_TIMEOUT_S)
            done.task = proc.returncode == 0
            if not done.task:
                log.warning("update: the scheduled task could not be re-registered: %s", (proc.stdout or "")[-300:])
        except (OSError, subprocess.SubprocessError):
            log.exception("update: the scheduled task could not be re-registered")
    try:
        atomic_write_json(_manifest_file(paths), {"version": release.version, "build": release.build,
                                                  "files": sorted(files)})
    except OSError:
        log.exception("update: could not record the installed files")
    return done


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _task_installed() -> bool:
    from agent_reach.daily.scheduler import task_status

    try:
        return task_status().installed
    except Exception:  # noqa: BLE001 - unknown: leave the task as it is
        return False


# ====================================================================== the whole update
@dataclass
class Outcome:
    state: str  # "current" | "updated" | "skipped" | "failed"
    message: str
    release: Release | None = None


def window_lock(paths: DataPaths) -> RefreshLock:
    """Held by an open window: the hourly check never replaces the code a window is running."""
    return RefreshLock(paths.state_dir / "window.lock")


def update(paths: DataPaths, project: Path = PROJECT_ROOT, *, auto_update: bool = True, client=None,
           run: Runner = _run, python: str | None = None, task_installed: Callable[[], bool] | None = None,
           check_timeout: float = CHECK_TIMEOUT_S, background: bool = False,
           announce: Callable[[str], None] | None = None) -> Outcome:
    """Check the channel and install a newer release. Never raises; the status file records what happened.
    ``announce`` is called once an update is found, before it downloads (the window shows a small notice)."""
    reason = why_not(project, auto_update)
    if reason:
        log.info("no update check: %s", reason)
        return Outcome("skipped", reason)
    status = load_status(paths)
    status.last_check_utc = utcnow()
    own = client is None
    client = client or _client(check_timeout)
    wlock: RefreshLock | None = None
    try:
        if background:
            wlock = window_lock(paths)
            try:
                wlock.acquire()
            except LockBusy:
                wlock = None
                return Outcome("skipped", "a window is open; the update waits until it is closed")
        try:
            release = check(client, __version__, installed_build(project))
        except UpdateError as exc:
            status.last_result = f"Could not check for updates: {exc}"
            _save_status(paths, status)
            return Outcome("skipped", status.last_result)
        if release is None:
            status.last_result = f"Up to date ({label(__version__)})."
            _save_status(paths, status)
            return Outcome("current", status.last_result)
        lock = RefreshLock(paths.lock_file, paths.lock_info)
        try:
            lock.acquire({"trigger": "update"})
        except LockBusy:
            return Outcome("skipped", "a refresh is running; the update waits for the next check")
        try:
            log.info("updating %s (%s) -> %s (%s)", __version__, installed_build(project), release.version,
                     release.build)
            if announce is not None:
                announce(f"Updating Agent Reach Daily to {label(release.version)}...")
            if own:
                client.timeout = DOWNLOAD_TIMEOUT_S
            files = unpack(download(client, release), release)
            done = install(paths, project, release, files, run=run, python=python, task_installed=task_installed)
        except UpdateError as exc:
            status.last_error, status.error_shown = str(exc), False
            status.last_result = f"Update to {label(release.version)} failed: {exc} The app keeps {label(__version__)}."
            _save_status(paths, status)
            log.error("update failed: %s", exc)
            return Outcome("failed", status.last_result, release)
        finally:
            lock.release()
        status.last_update = LastUpdate(from_version=__version__, to_version=release.version, build=release.build,
                                        at_utc=utcnow(), notes=release.notes, setup_required=release.setup_required)
        status.last_error = ""
        status.last_result = (f"Updated to {label(release.version)}: {len(done.written)} files changed, "
                              f"{len(done.deleted)} removed" + (", Python packages installed" if done.packages else "")
                              + (", scheduled task renewed" if done.task else "") + ".")
        _save_status(paths, status)
        log.info(status.last_result)
        return Outcome("updated", status.last_result, release)
    except Exception as exc:  # noqa: BLE001 - an update problem must never stop the app from opening
        log.exception("update check failed unexpectedly")
        status.last_result = f"Could not update ({type(exc).__name__}); the app keeps {label(__version__)}."
        _save_status(paths, status)
        return Outcome("failed", status.last_result)
    finally:
        if wlock is not None:
            wlock.release()
        if own:
            client.close()


def relaunch(argv: list[str], *, spawn: Callable[..., object] = subprocess.Popen) -> None:
    """Start the window again with the code just installed (this process still runs the old code)."""
    env = dict(os.environ, **{UPDATED_ENV: "1"})
    flags = 0x08000000 if sys.platform == "win32" else 0
    spawn([sys.executable, "-m", "agent_reach.daily", *argv], cwd=str(PROJECT_ROOT), env=env, creationflags=flags,
          close_fds=True)
