"""Refresh bookkeeping: last attempt is stored separately from last success.

Eligibility (all comparisons in UTC):

* elapsed mode (default): due when ``refresh_interval_hours`` (24) have elapsed since the START
  of the last successful refresh. Anchoring on the start keeps the daily time from drifting
  by the run's duration. Elapsed hours ignore DST, so the local clock time shifts by one hour
  across a DST change.
* fixed_central mode: due at the first configured Central wall-clock time strictly after the
  start of the last successful refresh (23/25-hour days handled by ``timeutil``).
* failures (failed, no_update, interrupted) start exponential backoff:
  ``retry_base_minutes * 2**(n-1)`` capped at ``retry_max_hours``. A due refresh is deferred
  until ``next_retry_utc``; scheduler ticks and GUI launches cannot hammer sources or Ollama.
  Manual refreshes bypass the due check and the backoff, but never the lock.
* a missed schedule (powered off, asleep) produces ONE refresh at the next opportunity, never
  a catch-up burst.

Only the lock holder writes this file; the GUI reads it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_reach.daily.fsutil import atomic_write_json, read_json
from agent_reach.daily.paths import DataPaths
from agent_reach.daily.prefs import DailyPrefs
from agent_reach.daily.timeutil import ensure_utc, next_fixed_time_after, parse_hhmm

log = logging.getLogger(__name__)

FAILURE_OUTCOMES = frozenset({"failed", "no_update", "interrupted"})


class RefreshState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    state_version: int = 1
    last_attempt_started_utc: datetime | None = None
    last_attempt_finished_utc: datetime | None = None
    last_attempt_outcome: str | None = None  # running|success|failed|no_update|interrupted|cancelled
    last_attempt_trigger: str | None = None  # scheduled|gui_launch|manual|cli
    last_attempt_message: str = ""
    last_attempt_run_id: str | None = None
    last_attempt_pid: int | None = None
    last_success_started_utc: datetime | None = None
    last_success_utc: datetime | None = None  # completion of the last published edition
    last_success_edition_date: str | None = None
    last_success_run_id: str | None = None
    consecutive_failures: int = 0
    next_retry_utc: datetime | None = None


def load_state(paths: DataPaths) -> tuple[RefreshState, str | None]:
    path = paths.state_file
    if not path.exists():
        return RefreshState(), None
    try:
        return RefreshState.model_validate(read_json(path)), None
    except (OSError, ValueError, ValidationError) as exc:
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        try:
            path.replace(backup)
        except OSError:
            pass
        log.warning("refresh state unreadable (%s); starting from the cached editions", exc)
        return RefreshState(), "Refresh history was unreadable and has been reset."


def save_state(paths: DataPaths, state: RefreshState) -> None:
    atomic_write_json(paths.state_file, state.model_dump(mode="json"))


@dataclass(frozen=True)
class DueInfo:
    due: bool
    reason: str  # never_refreshed | interval_elapsed | scheduled_time_reached | not_yet | backoff
    next_due_utc: datetime | None  # when the regular refresh is/was due (None: never refreshed)
    next_retry_utc: datetime | None  # end of failure backoff, when active

    @property
    def next_attempt_utc(self) -> datetime | None:
        times = [t for t in (self.next_due_utc, self.next_retry_utc) if t is not None]
        return max(times) if times else None


def regular_due_time(state: RefreshState, prefs: DailyPrefs) -> datetime | None:
    anchor = state.last_success_started_utc or state.last_success_utc
    if anchor is None:
        return None
    anchor = ensure_utc(anchor)
    if prefs.schedule_mode == "fixed_central":
        return next_fixed_time_after(anchor, parse_hhmm(prefs.fixed_time_central))
    return anchor + timedelta(hours=prefs.refresh_interval_hours)


def check_due(state: RefreshState, prefs: DailyPrefs, now: datetime) -> DueInfo:
    now = ensure_utc(now)
    regular = regular_due_time(state, prefs)
    retry = ensure_utc(state.next_retry_utc) if state.consecutive_failures and state.next_retry_utc else None
    if regular is not None and now < regular:
        return DueInfo(False, "not_yet", regular, retry if retry and retry > now else None)
    if retry is not None and now < retry:
        return DueInfo(False, "backoff", regular, retry)
    if regular is None:
        return DueInfo(True, "never_refreshed", None, None)
    reason = "scheduled_time_reached" if prefs.schedule_mode == "fixed_central" else "interval_elapsed"
    return DueInfo(True, reason, regular, None)


def backoff_delay(failures: int, prefs: DailyPrefs) -> timedelta:
    minutes = prefs.retry_base_minutes * (2 ** max(0, failures - 1))
    return timedelta(minutes=min(minutes, prefs.retry_max_hours * 60))


def mark_running(state: RefreshState, *, trigger: str, now: datetime, pid: int) -> None:
    state.last_attempt_started_utc = ensure_utc(now)
    state.last_attempt_finished_utc = None
    state.last_attempt_outcome = "running"
    state.last_attempt_trigger = trigger
    state.last_attempt_message = ""
    state.last_attempt_run_id = None
    state.last_attempt_pid = pid


def mark_success(state: RefreshState, *, started: datetime, finished: datetime, edition_date: str,
                 run_id: str, message: str = "") -> None:
    state.last_attempt_finished_utc = ensure_utc(finished)
    state.last_attempt_outcome = "success"
    state.last_attempt_message = message
    state.last_attempt_run_id = run_id
    state.last_success_started_utc = ensure_utc(started)
    state.last_success_utc = ensure_utc(finished)
    state.last_success_edition_date = edition_date
    state.last_success_run_id = run_id
    state.consecutive_failures = 0
    state.next_retry_utc = None


def mark_failure(state: RefreshState, *, outcome: str, message: str, now: datetime, prefs: DailyPrefs,
                 run_id: str | None = None) -> None:
    if outcome not in FAILURE_OUTCOMES:
        raise ValueError(f"not a failure outcome: {outcome}")
    now = ensure_utc(now)
    state.last_attempt_finished_utc = now
    state.last_attempt_outcome = outcome
    state.last_attempt_message = message[:1000]
    state.last_attempt_run_id = run_id or state.last_attempt_run_id
    state.consecutive_failures += 1
    state.next_retry_utc = now + backoff_delay(state.consecutive_failures, prefs)


def mark_cancelled(state: RefreshState, *, now: datetime, message: str = "Refresh cancelled by the user.") -> None:
    """A user cancellation is not a source/model failure: no backoff penalty."""
    state.last_attempt_finished_utc = ensure_utc(now)
    state.last_attempt_outcome = "cancelled"
    state.last_attempt_message = message


def recover_interrupted(state: RefreshState, *, now: datetime, prefs: DailyPrefs) -> bool:
    """Call only while holding the refresh lock: a 'running' attempt then belongs to a dead worker."""
    if state.last_attempt_outcome != "running":
        return False
    started = state.last_attempt_started_utc
    when = f" (started {ensure_utc(started):%Y-%m-%d %H:%M} UTC)" if started else ""
    mark_failure(state, outcome="interrupted", now=now, prefs=prefs,
                 message=f"The previous refresh{when} stopped before finishing (closed, crashed or powered off).")
    if started is not None:
        # Back off from when the dead attempt STARTED: a PC that was off overnight retries at once,
        # while a worker that keeps crashing right after starting is still rate-limited.
        state.next_retry_utc = min(state.next_retry_utc, ensure_utc(started) + backoff_delay(state.consecutive_failures, prefs))
    return True
