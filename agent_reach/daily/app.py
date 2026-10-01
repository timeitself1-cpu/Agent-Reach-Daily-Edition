"""GUI controller: everything the window shows, computed from local files only.

Opening the app reads settings, refresh state and the cached edition JSON. It never fetches
articles and never calls the model; refreshes run in a separate background worker process
(``python -m agent_reach.daily``), so the window stays responsive and a refresh started by the
window keeps going if the window is closed. The worker's progress is read from
``state/progress.json``.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from agent_reach.daily.edition import DailyEdition, Story
from agent_reach.daily.fsutil import read_json
from agent_reach.daily.lock import pid_alive, read_holder_info
from agent_reach.daily.paths import PROJECT_ROOT, DataPaths
from agent_reach.daily.prefs import DailyPrefs, load_prefs
from agent_reach.daily.state import DueInfo, RefreshState, check_due, load_state
from agent_reach.daily.store import EditionStore
from agent_reach.daily.timeutil import (
    central_date,
    edition_heading,
    format_central,
    format_clock,
    format_long_date,
    humanize_delta,
    parse_utc,
    updated_line,
    utcnow,
)

log = logging.getLogger(__name__)
CREATE_NO_WINDOW = 0x08000000


@dataclass
class Banner:
    kind: str  # info | warn | error | demo
    text: str


@dataclass
class RefreshActivity:
    running: bool
    stage: str = ""
    message: str = ""
    trigger: str = ""
    pid: int | None = None
    started: datetime | None = None


@dataclass
class Snapshot:
    """Everything the window renders, recomputed on each poll."""

    prefs: DailyPrefs
    state: RefreshState
    due: DueInfo
    latest: DailyEdition | None
    shown: DailyEdition | None
    viewing_latest: bool
    activity: RefreshActivity
    first_run: bool
    heading: str
    updated: str
    status: str
    last_success: str
    next_refresh: str
    banners: list[Banner] = field(default_factory=list)
    corrupt: list[str] = field(default_factory=list)


def default_spawner(args: list[str]) -> subprocess.Popen:
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen(args, cwd=str(PROJECT_ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)


def worker_python() -> str:
    """pythonw.exe (no console) when available next to the running interpreter."""
    exe = sys.executable
    if sys.platform == "win32" and exe.lower().endswith("python.exe"):
        candidate = exe[:-len("python.exe")] + "pythonw.exe"
        try:
            from pathlib import Path

            if Path(candidate).exists():
                return candidate
        except OSError:
            pass
    return exe


class AppController:
    def __init__(self, paths: DataPaths, *, now_fn: Callable[[], datetime] = utcnow,
                 spawner: Callable[[list[str]], object] = default_spawner) -> None:
        self.paths = paths
        self.now_fn = now_fn
        self.spawner = spawner
        self.store = EditionStore(paths)
        self.child = None
        self.selected_date: date | None = None  # None = follow the latest edition
        self.demo: DailyEdition | None = None

    # ------------------------------------------------------------ data
    def activity(self) -> RefreshActivity:
        if self.child is not None and getattr(self.child, "poll", lambda: 0)() is None:
            running_child = True
        else:
            running_child = False
            self.child = None
        try:
            prog = read_json(self.paths.progress_file)
        except (OSError, ValueError):
            prog = None
        holder = read_holder_info(self.paths.lock_info)
        pid = (prog or {}).get("pid") or (holder or {}).get("pid")
        alive = pid_alive(pid) if pid else False
        if not (running_child or alive):
            return RefreshActivity(False)
        prog = prog or {}
        return RefreshActivity(True, stage=str(prog.get("stage", "starting")),
                               message=str(prog.get("message", "Starting refresh")),
                               trigger=str(prog.get("trigger") or (holder or {}).get("trigger") or ""),
                               pid=pid, started=parse_utc(prog.get("started_utc")))

    def list_dates(self) -> list[date]:
        return self.store.list_dates()

    def snapshot(self) -> Snapshot:
        now = self.now_fn()
        prefs, prefs_warn = load_prefs(self.paths)
        state, state_warn = load_state(self.paths)
        latest_res = self.store.load_latest()
        latest = latest_res.edition
        if state.last_success_utc is None and latest is not None:
            state.last_success_started_utc = latest.generation_started_utc
            state.last_success_utc = latest.generation_completed_utc
        due = check_due(state, prefs, now)
        activity = self.activity()

        shown, viewing_latest = latest, True
        if self.demo is not None:
            shown, viewing_latest = self.demo, False
        elif self.selected_date is not None and (latest is None or self.selected_date != latest.edition_date):
            archived, problem = self.store.load_date(self.selected_date)
            if archived is not None:
                shown, viewing_latest = archived, False
            else:
                self.selected_date = None

        first_run = latest is None and state.last_attempt_outcome is None and not activity.running
        banners: list[Banner] = []
        for w in (prefs_warn, state_warn):
            if w:
                banners.append(Banner("warn", w))
        if latest_res.corrupt:
            banners.append(Banner("warn", f"{len(latest_res.corrupt)} cached file(s) are damaged and were skipped; "
                                          "they will be set aside at the next refresh."))
        if shown is not None and shown.demo:
            banners.append(Banner("demo", "DEMO EDITION - sample content to preview the layout. These are NOT real "
                                          "news stories. Use Refresh now to collect a real edition."))
        elif shown is not None and not viewing_latest:
            banners.append(Banner("info", f"You are reading the archived edition for "
                                          f"{format_long_date(shown.edition_date)}. Choose the newest date to return."))

        today = central_date(now)
        failed_since_success = (
            state.last_attempt_outcome in ("failed", "no_update", "interrupted")
            and (state.last_success_utc is None or (state.last_attempt_started_utc or now) > state.last_success_utc)
        )
        if latest is not None and viewing_latest and shown is not None and not shown.demo:
            if latest.edition_date < today:
                banners.append(Banner("warn", f"This is the edition for {format_long_date(latest.edition_date)}. "
                                              "Today's edition has not been collected yet."))
        if failed_since_success and not activity.running:
            kind = "error" if state.last_attempt_outcome == "failed" else "warn"
            when = format_central(state.last_attempt_finished_utc) if state.last_attempt_finished_utc else "recently"
            keep = " The last good edition is still shown." if latest is not None else ""
            banners.append(Banner(kind, f"The refresh at {when} did not produce a new edition. "
                                        f"{state.last_attempt_message}{keep}"))
        if shown is not None:
            for w in shown.coverage.warnings:
                banners.append(Banner("warn", w))
            for n in shown.notes:
                banners.append(Banner("info", n))

        heading = edition_heading(shown.edition_date) if shown else "Agent Reach Daily"
        if shown is not None and shown.demo:
            heading = "DEMO - " + heading
        updated = updated_line(shown.generation_completed_utc) if shown else "No edition collected yet"
        if shown is not None and shown.revision > 1:
            updated += f" (revision {shown.revision})"

        last_success = (f"Last successful refresh: {format_central(state.last_success_utc)}"
                        if state.last_success_utc else "Last successful refresh: never")
        next_refresh = self._next_refresh_text(due, now, prefs)
        status = self._status_text(state, activity, latest, today, failed_since_success)
        return Snapshot(prefs=prefs, state=state, due=due, latest=latest, shown=shown, viewing_latest=viewing_latest,
                        activity=activity, first_run=first_run, heading=heading, updated=updated, status=status,
                        last_success=last_success, next_refresh=next_refresh, banners=banners,
                        corrupt=latest_res.corrupt)

    @staticmethod
    def _next_refresh_text(due: DueInfo, now: datetime, prefs: DailyPrefs) -> str:
        if due.reason == "never_refreshed":
            return "Next refresh: as soon as you start one"
        if due.reason == "backoff" and due.next_retry_utc:
            return (f"Next retry after a failed attempt: {format_central(due.next_retry_utc)} "
                    f"({humanize_delta(due.next_retry_utc - now)})")
        if due.due:
            return "Next refresh: due now (runs when the scheduled task or this window next checks)"
        target = due.next_attempt_utc
        mode = "daily at " + prefs.fixed_time_central + " Central" if prefs.schedule_mode == "fixed_central" \
            else f"every {prefs.refresh_interval_hours:g} hours"
        return f"Next refresh due: {format_central(target)} ({humanize_delta(target - now)}; {mode})" if target else ""

    @staticmethod
    def _status_text(state: RefreshState, activity: RefreshActivity, latest: DailyEdition | None, today: date,
                     failed_since_success: bool) -> str:
        if activity.running:
            who = {"scheduled": "scheduled", "gui_launch": "automatic", "manual": "manual"}.get(activity.trigger, "")
            since = f" since {format_clock(activity.started)}" if activity.started else ""
            return f"Refreshing ({who} refresh{since}): {activity.message}".replace("( ", "(")
        if failed_since_success:
            label = {"failed": "Last attempt failed", "no_update": "Last attempt found nothing to publish",
                     "interrupted": "Last attempt was interrupted"}[state.last_attempt_outcome or "failed"]
            return f"{label}; showing the last good edition" if latest else label
        if state.last_attempt_outcome == "cancelled":
            return "Last refresh was cancelled"
        if latest is None:
            return "No edition yet"
        if latest.edition_date < today:
            return "Showing an earlier edition"
        return "Up to date"

    # ------------------------------------------------------------ actions
    def worker_args(self, *, manual: bool, allow_extractive: bool = False) -> list[str]:
        args = [worker_python(), "-m", "agent_reach.daily"]
        args += ["--refresh-now", "--trigger", "manual"] if manual else ["--refresh-if-due", "--trigger", "gui_launch"]
        if allow_extractive:
            args.append("--allow-extractive")
        args += ["--data-dir", str(self.paths.root)]
        return args

    def start_refresh(self, *, manual: bool = True, allow_extractive: bool = False) -> bool:
        if self.activity().running:
            return False
        self.demo = None
        self.selected_date = None
        self.child = self.spawner(self.worker_args(manual=manual, allow_extractive=allow_extractive))
        return True

    def maybe_auto_refresh(self) -> bool:
        """On launch: start a background refresh only if an edition exists and one is due."""
        snap = self.snapshot()
        if snap.first_run or snap.latest is None or not snap.prefs.refresh_on_launch:
            return False
        if snap.activity.running or not snap.due.due:
            return False
        return self.start_refresh(manual=False)

    def cancel_refresh(self) -> bool:
        act = self.activity()
        if not act.running or not act.pid:
            return False
        import os
        import signal

        try:
            os.kill(int(act.pid), signal.SIGTERM)
        except OSError as exc:
            log.warning("could not stop refresh worker %s: %s", act.pid, exc)
            return False
        if self.child is not None:
            try:
                self.child.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass
            self.child = None
        from agent_reach.daily.refresh import finalize_cancelled

        for _ in range(20):
            if finalize_cancelled(self.paths, self.now_fn):
                break
            import time

            time.sleep(0.25)
        return True

    def load_demo(self) -> DailyEdition:
        from agent_reach.daily.paths import PROJECT_ROOT as root

        path = root / "samples" / "DEMO-edition.json"
        edition = DailyEdition.model_validate_json(path.read_bytes())
        if not edition.demo:
            raise ValueError("the sample file is not marked as a demo edition")
        self.demo = edition
        return edition


def filter_stories(stories: list[Story], category: str | None, query: str) -> list[Story]:
    q = (query or "").strip().lower()
    out = []
    for s in stories:
        if category and category != "All" and s.category.value != category:
            continue
        if q:
            hay = " ".join([s.headline, *s.sentences, s.why_it_matters or "", " ".join(s.labels),
                            *(e.title for e in s.evidence), *(e.publisher or "" for e in s.evidence)]).lower()
            if q not in hay:
                continue
        out.append(s)
    return out
