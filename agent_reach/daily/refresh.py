"""The refresh worker: one code path for scheduled, GUI-launch and manual refreshes.

    due check (no lock, no network)  ->  lock  ->  repair cache, recover a crashed attempt
    ->  re-check due under the lock  ->  mark attempt running
    ->  Ollama check (optionally start it; never pull models)
    ->  pipeline run_once (ingest, clean, enrich, cluster, score, persist; validated ledger)
    ->  stories from validated clusters + cited evidence  ->  optional grounded brief pass
    ->  DailyEdition  ->  publication eligibility  ->  atomic publish + retention
    ->  event registry (observe only)  ->  website (opt-in)  ->  podcast (optional)
    ->  state: success, or failure/no-update with backoff and saved diagnostics

The previous good edition is never modified by a failed, invalid or no-update attempt.
Heavy modules (numpy, scikit-learn, the pipeline) are imported only after the lock is held,
so a not-due scheduler tick exits in about a second.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_reach.daily.edition import DailyEdition
from agent_reach.daily.fsutil import FileUnavailable, atomic_write_json, unlink_with_retry
from agent_reach.daily.lock import LockBusy, RefreshLock
from agent_reach.daily.paths import DataPaths
from agent_reach.daily.prefs import DailyPrefs, load_prefs
from agent_reach.daily.state import (
    RefreshState,
    check_due,
    load_state,
    mark_cancelled,
    mark_failure,
    mark_running,
    mark_success,
    recover_interrupted,
    save_state,
)
from agent_reach.daily.store import EditionStore
from agent_reach.daily.timeutil import central_date, format_central, iso_utc, utcnow

log = logging.getLogger("agent_reach.daily.refresh")

EXIT_PUBLISHED = 0
EXIT_USAGE = 2
EXIT_NOT_DUE = 10
EXIT_BUSY = 11
EXIT_BACKOFF = 12
EXIT_NO_UPDATE = 20
EXIT_FAILED = 30
EXIT_PREREQ = 31
MAX_DIAGNOSTICS = 30
#: Beyond the refresh time limit: the brief pass ends with the time limit, the podcast has its own 15-minute
#: limit and publishing takes seconds. A worker still alive after this is stuck in a call that ignores
#: cancellation (a hung driver, DNS or disk call); the watchdog records that and ends the process.
WATCHDOG_GRACE_S = 25 * 60
BRIEF_PER_CATEGORY = 3  # besides Top Stories, the local model writes notes for each category's top 3


@dataclass
class RefreshOutcome:
    code: int
    outcome: str  # published | not_due | busy | backoff | no_update | failed | prereq_failed
    message: str
    edition: DailyEdition | None = None


class ProgressWriter:
    """Writes state/progress.json for the GUI (stage + message). Best effort."""

    def __init__(self, paths: DataPaths, trigger: str, started: datetime) -> None:
        self.paths = paths
        self.trigger = trigger
        self.started = started

    def __call__(self, stage: str, message: str) -> None:
        log.info("progress [%s] %s", stage, message)
        try:
            atomic_write_json(self.paths.progress_file, {
                "pid": os.getpid(), "trigger": self.trigger, "stage": stage, "message": message,
                "started_utc": iso_utc(self.started), "updated_utc": iso_utc(utcnow()),
            })
        except OSError:
            pass

    def clear(self) -> None:
        unlink_with_retry(self.paths.progress_file)


def watchdog_limit_s(prefs: DailyPrefs) -> float:
    return prefs.max_run_minutes * 60 + WATCHDOG_GRACE_S


class Watchdog:
    """Ends a worker that stopped responding, so no refresh can hold the lock (and the window's
    'Refreshing') forever. Whoever finishes first records the outcome: the worker itself, or the watchdog,
    which saves the state, writes the stack of every thread to diagnostics and exits the process (the
    operating system then frees the lock)."""

    def __init__(self, paths: DataPaths, prefs: DailyPrefs, *, trigger: str, started: datetime, now_fn,
                 limit_s: float, exit_fn: Callable[[int], object] = os._exit) -> None:
        self.paths, self.prefs, self.trigger, self.started, self.now_fn = paths, prefs, trigger, started, now_fn
        self.limit_s, self.exit_fn = limit_s, exit_fn
        self.published: DailyEdition | None = None  # set as soon as the edition is published
        self._owner = threading.Lock()
        self._timer = threading.Timer(limit_s, self._fire)
        self._timer.daemon = True

    def start(self) -> "Watchdog":
        self._timer.start()
        return self

    def finish(self) -> bool:
        """The worker claims the right to record the outcome; False when the watchdog already has it."""
        if self._owner.acquire(blocking=False):
            self._timer.cancel()
            return True
        return False

    def cancel(self) -> None:
        self._timer.cancel()

    def _fire(self) -> None:
        if not self._owner.acquire(blocking=False):
            return  # the worker is already recording its outcome
        try:
            minutes = self.limit_s / 60
            frames = sys._current_frames()
            stacks = {t.name: "".join(traceback.format_stack(frames[t.ident])) for t in threading.enumerate()
                      if t.ident in frames and t is not threading.current_thread()}
            log.error("refresh stopped responding; ended by the watchdog after %.0f minutes", minutes)
            state, _ = load_state(self.paths)
            if self.published is not None:
                ed = self.published
                mark_success(state, started=self.started, finished=ed.generation_completed_utc,
                             edition_date=ed.edition_date.isoformat(), run_id=ed.run_id,
                             message=f"Published {len(ed.stories)} stories; a later step stopped responding.")
            else:
                mark_failure(state, outcome="failed", now=self.now_fn(), prefs=self.prefs,
                             message=f"The refresh stopped responding and was ended after {minutes:.0f} minutes. "
                                     "The previous edition is kept.")
            save_state(self.paths, state)
            _write_diagnostics(self.paths, {"outcome": "watchdog", "trigger": self.trigger,
                                            "started_utc": iso_utc(self.started), "finished_utc": iso_utc(self.now_fn()),
                                            "limit_minutes": round(minutes, 1), "threads": stacks})
            for f in (self.paths.progress_file, self.paths.lock_info):
                unlink_with_retry(f)
            for h in logging.getLogger().handlers:
                try:
                    h.flush()
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001 - the process ends either way
            log.exception("watchdog could not record the stopped refresh")
        finally:
            self.exit_fn(EXIT_FAILED)


def default_ollama_probe(prefs: DailyPrefs):
    from agent_reach.daily.prereqs import check_prefs, start_ollama

    status = check_prefs(prefs)
    if not status.reachable and prefs.start_ollama_if_down:
        log.info("Ollama not reachable; trying to start it")
        status = start_ollama(prefs.ollama_host, [prefs.ollama_model],
                              grouping=[prefs.embed_model, *prefs.embed_fallback_models])
    return status


def _write_diagnostics(paths: DataPaths, payload: dict) -> Path | None:
    try:
        paths.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
        path = paths.diagnostics_dir / f"{stamp}-{payload.get('outcome', 'attempt')}.json"
        atomic_write_json(path, payload)
        files = sorted(paths.diagnostics_dir.glob("*.json"))
        for old in files[:-MAX_DIAGNOSTICS]:
            old.unlink(missing_ok=True)
        return path
    except OSError:
        log.exception("could not write diagnostics")
        return None


def _reconcile_with_cache(state: RefreshState, store: EditionStore) -> bool:
    """If the state file was lost, recover last success from the newest valid cached edition."""
    if state.last_success_utc is not None:
        return False
    latest = store.load_latest().edition
    if latest is None:
        return False
    state.last_success_started_utc = latest.generation_started_utc
    state.last_success_utc = latest.generation_completed_utc
    state.last_success_edition_date = latest.edition_date.isoformat()
    state.last_success_run_id = latest.run_id
    return True


def _files_unavailable(exc: OSError) -> RefreshOutcome:
    """Settings or refresh history exist but another program holds them: never refresh on defaults or
    overwrite the history. Nothing is recorded; the next attempt (the next hourly check) tries again."""
    log.warning("refresh skipped: %s", exc)
    return RefreshOutcome(EXIT_FAILED, "failed", "No refresh: your settings or refresh history could not be read "
                                                 "(the file is open in another program). Nothing was changed; "
                                                 "try again in a minute.")


def _not_due_outcome(due) -> RefreshOutcome:
    if due.reason == "backoff":
        return RefreshOutcome(EXIT_BACKOFF, "backoff",
                              f"Retry after the previous failure is due at {format_central(due.next_retry_utc)}.")
    when = format_central(due.next_due_utc) if due.next_due_utc else "now"
    return RefreshOutcome(EXIT_NOT_DUE, "not_due", f"Next refresh is due {when}.")


def refresh(
    paths: DataPaths,
    *,
    trigger: str = "manual",
    force: bool = False,
    allow_extractive: bool = False,
    now_fn: Callable[[], datetime] = utcnow,
    ollama_probe: Callable[[DailyPrefs], object] | None = None,
) -> RefreshOutcome:
    """Run one refresh attempt if allowed. Never raises for operational failures."""
    paths.ensure()
    try:
        prefs, _ = load_prefs(paths, strict=True)
        state, _ = load_state(paths, strict=True)
    except FileUnavailable as exc:
        return _files_unavailable(exc)
    if not force:
        due = check_due(state, prefs, now_fn())
        if not due.due and state.last_attempt_outcome != "running":
            return _not_due_outcome(due)

    lock = RefreshLock(paths.lock_file, paths.lock_info)
    try:
        lock.acquire({"trigger": trigger})
    except LockBusy:
        return RefreshOutcome(EXIT_BUSY, "busy", "Another refresh is already running.")
    progress: ProgressWriter | None = None
    guard: Watchdog | None = None
    try:
        store = EditionStore(paths)
        try:
            store.repair()
        except OSError:  # e.g. a damaged file held open by a virus scanner: the refresh can still run
            log.exception("cache repair failed; continuing with the cache as it is")
        try:
            state, _ = load_state(paths, strict=True)
        except FileUnavailable as exc:
            return _files_unavailable(exc)
        changed = _reconcile_with_cache(state, store)
        changed |= recover_interrupted(state, now=now_fn(), prefs=prefs)
        if changed:
            save_state(paths, state)
        if not force:
            due = check_due(state, prefs, now_fn())
            if not due.due:
                return _not_due_outcome(due)

        started = now_fn()
        mark_running(state, trigger=trigger, now=started, pid=os.getpid())
        save_state(paths, state)
        progress = ProgressWriter(paths, trigger, started)
        guard = Watchdog(paths, prefs, trigger=trigger, started=started, now_fn=now_fn,
                         limit_s=watchdog_limit_s(prefs)).start()
        progress("start", "Starting refresh")
        try:
            outcome = asyncio.run(_attempt(paths, prefs, store, trigger=trigger, started=started,
                                           allow_extractive=allow_extractive, now_fn=now_fn, progress=progress,
                                           ollama_probe=ollama_probe or default_ollama_probe, guard=guard))
        except Exception as exc:  # noqa: BLE001 - any unexpected error is a failed attempt, never a crash loop
            log.exception("refresh failed unexpectedly")
            outcome = _failed(paths, prefs, trigger, started, now_fn, "failed", EXIT_FAILED,
                              f"Unexpected error: {type(exc).__name__}: {exc}", tb=traceback.format_exc())
        if not guard.finish():
            threading.Event().wait()  # the watchdog is recording the outcome and ends the process
        try:
            state, _ = load_state(paths, strict=True)
        except FileUnavailable:
            pass  # only the lock holder writes the file: the copy in memory is current
        if outcome.outcome == "published" and outcome.edition is not None:
            mark_success(state, started=started, finished=outcome.edition.generation_completed_utc,
                         edition_date=outcome.edition.edition_date.isoformat(), run_id=outcome.edition.run_id,
                         message=outcome.message)
        else:
            mark_failure(state, outcome="no_update" if outcome.outcome == "no_update" else "failed",
                         message=outcome.message, now=now_fn(), prefs=prefs)
            outcome.message += f" Next automatic retry after {format_central(state.next_retry_utc)}."
        save_state(paths, state)
        log.info("refresh finished: %s (%s)", outcome.outcome, outcome.message)
        return outcome
    finally:
        if guard is not None:
            guard.cancel()
        if progress is not None:
            progress.clear()
        lock.release()


def _failed(paths: DataPaths, prefs: DailyPrefs, trigger: str, started: datetime, now_fn, outcome: str, code: int,
            message: str, *, report=None, tb: str | None = None, extra: dict | None = None) -> RefreshOutcome:
    payload = {
        "outcome": outcome, "message": message, "trigger": trigger,
        "started_utc": iso_utc(started), "finished_utc": iso_utc(now_fn()),
        "model": prefs.ollama_model, "embed_model": prefs.embed_model, "sources": prefs.enabled_sources,
    }
    if report is not None:
        payload["run_id"] = report.run_id
        payload["source_health"] = [s.model_dump() for s in report.source_stats]
        payload["accounting"] = report.accounting.model_dump() if report.accounting else None
        payload["llm_mode"] = report.llm_mode
    if tb:
        payload["traceback"] = tb
    payload.update(extra or {})
    _write_diagnostics(paths, payload)
    return RefreshOutcome(code, outcome, message)


async def _attempt(paths: DataPaths, prefs: DailyPrefs, store: EditionStore, *, trigger: str, started: datetime,
                   allow_extractive: bool, now_fn, progress: ProgressWriter, ollama_probe,
                   guard: Watchdog | None = None) -> RefreshOutcome:
    from agent_reach.daily.prereqs import model_present

    progress("prereq", "Checking the local model (Ollama)")
    status = await asyncio.to_thread(ollama_probe, prefs)
    reachable = bool(getattr(status, "reachable", False))
    models = list(getattr(status, "models", []) or [])
    chat_ok = reachable and model_present(prefs.ollama_model, models)
    if not chat_ok and prefs.require_llm and not allow_extractive:
        describe = getattr(status, "describe", None)
        detail = describe() if callable(describe) else "Ollama is unavailable."
        # Fail before fetching anything: no point hammering sources without the model.
        return _failed(paths, prefs, trigger, started, now_fn, "failed", EXIT_PREREQ,
                       f"No new edition: {detail}", extra={"ollama_error": getattr(status, "error", None)})

    from agent_reach.daily.edition import assemble_edition, build_story, evaluate_publication, select_stories
    from agent_reach.daily.prefs import build_settings, config_fingerprint
    from agent_reach.main import run_once
    from agent_reach.storage.db import TrendDatabase

    settings = build_settings(prefs, paths)
    budget = prefs.max_run_minutes * 60
    try:
        report = await asyncio.wait_for(run_once(settings, use_llm=chat_ok, progress=progress), timeout=budget)
    except asyncio.TimeoutError:
        return _failed(paths, prefs, trigger, started, now_fn, "failed", EXIT_FAILED,
                       f"The refresh took longer than {prefs.max_run_minutes:.0f} minutes and was stopped.")
    except Exception as exc:  # noqa: BLE001 - invalid ledger/membership or any pipeline error withholds delivery
        log.exception("pipeline run failed; no edition published")
        return _failed(paths, prefs, trigger, started, now_fn, "failed", EXIT_FAILED,
                       f"The news run was invalid and was not published ({type(exc).__name__}: {str(exc)[:200]}).",
                       tb=traceback.format_exc())

    from agent_reach.daily.feedhealth import record_run

    record_run(paths, report.source_stats, now_fn())  # feed doctor: which feeds keep failing
    progress("edition", "Assembling the daily edition")
    db = TrendDatabase(settings.db_path)
    try:
        evidence = db.load_evidence(report.run_id)
    finally:
        db.close()
    built = [build_story(1, c, evidence, reference=started) for c in report.macro_clusters]
    supported = [s for s in built if s is not None]
    from agent_reach.daily.changes import keep_previous_categories

    kept = keep_previous_categories(supported, store.load_latest().edition)
    if kept:
        log.info("%d carried-over stories kept their previous category", kept)
    from agent_reach.daily.revisions import retain_listed
    supported = retain_listed(supported, store.load_latest().edition, prefs, started)
    selection = select_stories(supported, prefs, now=started)
    selection.dropped_unsupported = max(0, len(built) - len(supported))
    stories = selection.stories

    brief_stats: dict[str, int] = {}
    if chat_ok and prefs.why_it_matters and stories:
        # On a CPU every model call is slow: notes go to Top Stories and each category's top 3.
        brief_ids = {id(s) for s in selection.top}
        per_cat: dict[str, int] = {}
        for s in stories:
            if per_cat.get(s.category.value, 0) < BRIEF_PER_CATEGORY:
                brief_ids.add(id(s))
            per_cat[s.category.value] = per_cat.get(s.category.value, 0) + 1
        brief_stories = [s for s in stories if id(s) in brief_ids]
        progress("brief", f"Writing 'why it matters' notes for {len(brief_stories)} stories")
        from agent_reach.daily.brief import enrich_stories
        from agent_reach.pipeline.clusterer import SemanticClusterer

        remaining = max(30.0, budget - (now_fn() - started).total_seconds())
        try:
            client = SemanticClusterer(settings)._get_client()
            brief_stats = await asyncio.wait_for(
                enrich_stories(brief_stories, settings, client=client, budget_s=min(600.0, remaining)),
                timeout=min(900.0, remaining))
        except (asyncio.TimeoutError, ImportError) as exc:
            log.warning("brief pass skipped: %s", type(exc).__name__)

    from agent_reach.pipeline.summary_checks import verified_story
    for story in stories:
        story.headline, story.sentences = verified_story(story)
    completed = now_fn()
    edition = assemble_edition(report, selection, prefs, started=started, completed=completed,
                               trigger=trigger, config_fingerprint=config_fingerprint(report.effective_config),
                               brief_stats=brief_stats)
    same_day, _ = store.load_date(edition.edition_date)  # the edition this one would replace as a new revision
    decision = evaluate_publication(edition, prefs, allow_extractive=allow_extractive, same_day=same_day)
    if not decision.publishable:
        return _failed(paths, prefs, trigger, started, now_fn, "no_update", EXIT_NO_UPDATE,
                       "No new edition: " + " ".join(decision.reasons) + " The previous edition is kept.",
                       report=report, extra={"stories": len(edition.stories), "coverage": edition.coverage.model_dump()})

    progress("publish", "Publishing the edition")
    previous = store.load_latest().edition
    if previous is not None:
        from agent_reach.daily.changes import compare_editions

        edition.changes = compare_editions(previous, edition)
    try:
        final = store.publish(edition)
    except OSError as exc:
        # the dated file or the pointer is open in another program (or the disk is full / read-only)
        return _failed(paths, prefs, trigger, started, now_fn, "failed", EXIT_FAILED,
                       f"The new edition could not be saved ({type(exc).__name__}: {exc}). It may be open in another "
                       "program, or the disk is full. The previous edition is kept.",
                       report=report, tb=traceback.format_exc())
    if guard is not None:
        guard.published = final
    store.purge(prefs.retention_days, central_date(completed))
    from agent_reach.daily.registry import record_edition

    # observe only (Phase 2): which earlier event each story continues; never changes the edition or the outcome
    await asyncio.to_thread(record_edition, paths, final)
    msg = f"Published {len(final.stories)} stories for {final.edition_date.isoformat()}"
    if final.revision > 1:
        msg += f" (revision {final.revision}, replaces the earlier edition for this date)"
    msg += "."
    from agent_reach.daily.publish import load_settings as publish_settings, publish_after_refresh

    if publish_settings(paths).enabled:
        # opt-in: the edition is already saved here, so a website problem never fails the refresh. Before the
        # podcast, which can take minutes: the website should not wait for a recording (audit F6, Oct 8)
        progress("website", "Publishing to the website")
        result = await asyncio.to_thread(publish_after_refresh, paths, final)
        if result is not None:
            msg += f" {result.message}"
    if prefs.podcast_auto:
        # the edition is already published: a podcast problem is reported, never a failed refresh
        progress("podcast", "Recording the daily podcast")
        from agent_reach.daily.podcast import make_podcast

        try:
            pod = await asyncio.to_thread(make_podcast, paths, final, prefs)
            msg += f" {pod.message}"
        except Exception:  # noqa: BLE001
            log.exception("podcast failed")
    return RefreshOutcome(EXIT_PUBLISHED, "published", msg, final)


def finalize_cancelled(paths: DataPaths, now_fn: Callable[[], datetime] = utcnow) -> bool:
    """After the GUI stops a worker: once the lock is free (the worker is gone) record a user cancellation
    (no backoff) if the worker had started its attempt. False while the worker still holds the lock."""
    lock = RefreshLock(paths.lock_file, None)
    try:
        lock.acquire()
    except LockBusy:
        return False
    try:
        state, _ = load_state(paths)
        if state.last_attempt_outcome != "running":
            return True  # stopped before it began (or it had already finished): nothing to record
        mark_cancelled(state, now=now_fn())
        save_state(paths, state)
        unlink_with_retry(paths.progress_file)
        return True
    finally:
        lock.release()


def status_payload(paths: DataPaths, now: datetime | None = None) -> dict:
    """Machine-readable status for --status (no network, no model)."""
    now = now or utcnow()
    prefs, prefs_warn = load_prefs(paths)
    state, state_warn = load_state(paths)
    store = EditionStore(paths)
    latest = store.load_latest()
    if state.last_success_utc is None:
        _reconcile_with_cache(state, store)
    due = check_due(state, prefs, now)
    return {
        "data_dir": str(paths.root),
        "latest_edition": latest.edition.edition_date.isoformat() if latest.edition else None,
        "latest_revision": latest.edition.revision if latest.edition else None,
        "editions": [d.isoformat() for d in store.list_dates()],
        "corrupt_files": latest.corrupt,
        "due": due.due, "due_reason": due.reason,
        "next_due_utc": iso_utc(due.next_due_utc), "next_retry_utc": iso_utc(due.next_retry_utc),
        "last_success_utc": iso_utc(state.last_success_utc),
        "last_attempt_outcome": state.last_attempt_outcome, "last_attempt_message": state.last_attempt_message,
        "consecutive_failures": state.consecutive_failures,
        "warnings": [w for w in (prefs_warn, state_warn) if w],
    }


def dumps(obj: dict) -> str:
    return json.dumps(obj, indent=2)
