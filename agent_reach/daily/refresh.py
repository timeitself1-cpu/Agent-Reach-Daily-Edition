"""The refresh worker: one code path for scheduled, GUI-launch and manual refreshes.

    due check (no lock, no network)  ->  lock  ->  repair cache, recover a crashed attempt
    ->  re-check due under the lock  ->  mark attempt running
    ->  Ollama check (optionally start it; never pull models)
    ->  pipeline run_once (ingest, clean, enrich, cluster, score, persist; validated ledger)
    ->  stories from validated clusters + cited evidence  ->  optional grounded brief pass
    ->  DailyEdition  ->  publication eligibility  ->  atomic publish + retention
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
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agent_reach.daily.edition import DailyEdition
from agent_reach.daily.fsutil import atomic_write_json
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
        try:
            self.paths.progress_file.unlink()
        except OSError:
            pass


def default_ollama_probe(prefs: DailyPrefs):
    from agent_reach.daily.prereqs import check_ollama, start_ollama

    models = [prefs.ollama_model, prefs.embed_model]
    status = check_ollama(prefs.ollama_host, models)
    if not status.reachable and prefs.start_ollama_if_down:
        log.info("Ollama not reachable; trying to start it")
        status = start_ollama(prefs.ollama_host, models)
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
    prefs, _ = load_prefs(paths)
    state, _ = load_state(paths)
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
    try:
        store = EditionStore(paths)
        store.repair()
        state, _ = load_state(paths)
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
        progress("start", "Starting refresh")
        try:
            outcome = asyncio.run(_attempt(paths, prefs, store, trigger=trigger, started=started,
                                           allow_extractive=allow_extractive, now_fn=now_fn,
                                           progress=progress, ollama_probe=ollama_probe or default_ollama_probe))
        except Exception as exc:  # noqa: BLE001 - any unexpected error is a failed attempt, never a crash loop
            log.exception("refresh failed unexpectedly")
            outcome = _failed(paths, prefs, trigger, started, now_fn, "failed", EXIT_FAILED,
                              f"Unexpected error: {type(exc).__name__}: {exc}", tb=traceback.format_exc())
        state, _ = load_state(paths)
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
                   allow_extractive: bool, now_fn, progress: ProgressWriter, ollama_probe) -> RefreshOutcome:
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

    progress("edition", "Assembling the daily edition")
    db = TrendDatabase(settings.db_path)
    try:
        evidence = db.load_evidence(report.run_id)
    finally:
        db.close()
    built = [build_story(1, c, evidence) for c in report.macro_clusters]
    supported = [s for s in built if s is not None]
    selection = select_stories(supported, prefs, now=started)
    selection.dropped_unsupported = len(built) - len(supported)
    stories = selection.stories

    if chat_ok and prefs.why_it_matters and stories:
        progress("brief", f"Writing 'why it matters' notes for {len(stories)} stories")
        from agent_reach.daily.brief import enrich_stories
        from agent_reach.pipeline.clusterer import SemanticClusterer

        remaining = max(30.0, budget - (now_fn() - started).total_seconds())
        try:
            client = SemanticClusterer(settings)._get_client()
            await asyncio.wait_for(enrich_stories(stories, settings, client=client, budget_s=min(600.0, remaining)),
                                   timeout=min(900.0, remaining))
        except (asyncio.TimeoutError, ImportError) as exc:
            log.warning("brief pass skipped: %s", type(exc).__name__)

    completed = now_fn()
    edition = assemble_edition(report, selection, prefs, started=started, completed=completed,
                               trigger=trigger, config_fingerprint=config_fingerprint(report.effective_config))
    decision = evaluate_publication(edition, prefs, allow_extractive=allow_extractive)
    if not decision.publishable:
        return _failed(paths, prefs, trigger, started, now_fn, "no_update", EXIT_NO_UPDATE,
                       "No new edition: " + " ".join(decision.reasons) + " The previous edition is kept.",
                       report=report, extra={"stories": len(edition.stories), "coverage": edition.coverage.model_dump()})

    progress("publish", "Publishing the edition")
    final = store.publish(edition)
    store.purge(prefs.retention_days, central_date(completed))
    msg = f"Published {len(final.stories)} stories for {final.edition_date.isoformat()}"
    if final.revision > 1:
        msg += f" (revision {final.revision}, replaces the earlier edition for this date)"
    return RefreshOutcome(EXIT_PUBLISHED, "published", msg + ".", final)


def finalize_cancelled(paths: DataPaths, now_fn: Callable[[], datetime] = utcnow) -> bool:
    """After the GUI stops a worker: record a user cancellation (no backoff) if the lock is free."""
    lock = RefreshLock(paths.lock_file, None)
    try:
        lock.acquire()
    except LockBusy:
        return False
    try:
        state, _ = load_state(paths)
        if state.last_attempt_outcome != "running":
            return False
        mark_cancelled(state, now=now_fn())
        save_state(paths, state)
        try:
            paths.progress_file.unlink()
        except OSError:
            pass
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
