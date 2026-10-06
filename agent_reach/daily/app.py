"""GUI controller: everything the window shows, computed from local files only.

Opening the app reads settings, refresh state and the cached edition JSON. It never fetches
articles and never calls the model; refreshes run in a separate background worker process
(``python -m agent_reach.daily``), so the window stays responsive and a refresh started by the
window keeps going if the window is closed. The worker's progress is read from
``state/progress.json``.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from agent_reach.daily import VERSION_LABEL
from agent_reach.daily.edition import DailyEdition, Story, health_summary, newest_published, safe_url
from agent_reach.daily.fsutil import atomic_write_json, read_json
from agent_reach.daily.lock import pid_alive, read_holder_info
from agent_reach.daily.paths import PROJECT_ROOT, DataPaths
from agent_reach.daily.prefs import DailyPrefs, load_prefs
from agent_reach.daily.state import DueInfo, RefreshState, check_due, load_state
from agent_reach.daily.store import EditionStore
from agent_reach.daily.timeutil import (
    central_date,
    format_brief,
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
    date_line: str
    updated: str
    status: str
    status_kind: str  # current | stale | refreshing | failed | empty | demo | archive
    last_success: str
    next_refresh: str
    banners: list[Banner] = field(default_factory=list)  # main screen: demo, failure, stale, damage
    details: list[str] = field(default_factory=list)  # secondary: coverage warnings and edition notes
    coverage_line: str = ""
    corrupt: list[str] = field(default_factory=list)
    failing_feeds: list = field(default_factory=list)  # feed doctor: enabled feeds failing for days


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
        self._developing: tuple[str, dict] | None = None  # (run_id, rank -> first-seen date)

    def developing(self, edition: DailyEdition) -> dict:
        """rank -> date first seen, for stories carried over from earlier editions (cached per edition)."""
        from agent_reach.daily.reading import DEVELOPING_LOOKBACK, developing_since

        if edition.demo:
            return {}
        if self._developing is None or self._developing[0] != edition.run_id:
            earlier = []
            for d in [d for d in self.store.list_dates() if d < edition.edition_date][:DEVELOPING_LOOKBACK]:
                older, _ = self.store.load_date(d)
                if older is not None:
                    earlier.append(older)
            self._developing = (edition.run_id, developing_since(edition, earlier))
        return self._developing[1]

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
        today = central_date(now)
        failed_since_success = (
            state.last_attempt_outcome in ("failed", "no_update", "interrupted")
            and (state.last_success_utc is None or (state.last_attempt_started_utc or now) > state.last_success_utc)
        )

        banners: list[Banner] = []
        if shown is not None and shown.demo:
            banners.append(Banner("demo", "DEMO EDITION - synthetic sample stories to preview the layout. These are NOT "
                                          "real news. Choose Refresh to collect a real edition."))
        if failed_since_success and not activity.running:
            banners.append(Banner("error" if state.last_attempt_outcome == "failed" else "warn",
                                  failure_text(state, has_edition=latest is not None)))
        if (latest is not None and viewing_latest and shown is not None and not shown.demo
                and latest.edition_date < today and not activity.running):
            banners.append(Banner("warn", f"This is the edition for {format_long_date(latest.edition_date)}. "
                                          "Today's edition has not been collected yet."))
        elif shown is not None and not viewing_latest and not shown.demo:
            banners.append(Banner("info", f"You are reading the archived edition for "
                                          f"{format_long_date(shown.edition_date)}. Choose the newest date to return."))
        for w in (prefs_warn, state_warn):
            if w:
                banners.append(Banner("warn", w))
        failing = enabled_failing_feeds(self.paths, prefs, now)
        if failing:
            names = ", ".join(r.name for r in failing[:4]) + (f" and {len(failing) - 4} more" if len(failing) > 4 else "")
            banners.append(Banner("info", f"{len(failing)} feed{'s have' if len(failing) != 1 else ' has'} not worked "
                                          f"for 3 days or more: {names}. Fix the address or turn "
                                          f"{'them' if len(failing) != 1 else 'it'} off in Settings > Publisher feeds."))
        if latest_res.corrupt:
            n = len(latest_res.corrupt)
            banners.append(Banner("warn", f"{n} saved edition {'file is' if n == 1 else 'files are'} damaged and "
                                          f"{'was' if n == 1 else 'were'} skipped; set aside at the next refresh."))

        details: list[str] = []
        coverage_line = ""
        if shown is not None:
            details = list(shown.coverage.warnings) + list(shown.notes)
            coverage_line = coverage_summary(shown)

        heading, date_line = headings(shown, today)
        updated = updated_line(shown.generation_completed_utc) if shown else "No edition collected yet"
        if shown is not None and shown.revision > 1:
            updated += f" (revision {shown.revision})"

        last_success = (f"Last successful refresh {format_brief(state.last_success_utc, now)}"
                        if state.last_success_utc else "No successful refresh yet")
        next_refresh = self._next_refresh_text(due, now, prefs)
        status = self._status_text(state, activity, latest, today, failed_since_success)
        if not activity.running and shown is not None and shown.demo:
            status = "Showing the DEMO edition (sample content, not real news)"
        elif not activity.running and shown is not None and not viewing_latest:
            status = f"Viewing the archived edition for {format_long_date(shown.edition_date)}"
        kind = status_kind(shown=shown, viewing_latest=viewing_latest, latest=latest, today=today,
                           running=activity.running, failed=failed_since_success)
        return Snapshot(prefs=prefs, state=state, due=due, latest=latest, shown=shown, viewing_latest=viewing_latest,
                        activity=activity, first_run=first_run, heading=heading, date_line=date_line, updated=updated,
                        status=status, status_kind=kind, last_success=last_success, next_refresh=next_refresh,
                        banners=banners, details=details, coverage_line=coverage_line, corrupt=latest_res.corrupt,
                        failing_feeds=failing)

    @staticmethod
    def _next_refresh_text(due: DueInfo, now: datetime, prefs: DailyPrefs) -> str:
        if due.reason == "never_refreshed":
            return "Next refresh: when you choose Refresh"
        if due.reason == "backoff" and due.next_retry_utc:
            return f"Next retry {format_brief(due.next_retry_utc, now)} ({humanize_delta(due.next_retry_utc - now)})"
        if due.due:
            return "Next refresh: due now"
        target = due.next_attempt_utc
        return f"Next refresh {format_brief(target, now)} ({humanize_delta(target - now)})" if target else ""

    @staticmethod
    def _status_text(state: RefreshState, activity: RefreshActivity, latest: DailyEdition | None, today: date,
                     failed_since_success: bool) -> str:
        if activity.running:
            who = {"scheduled": "Scheduled refresh", "gui_launch": "Automatic refresh",
                   "manual": "Refreshing"}.get(activity.trigger, "Refreshing")
            since = f" (started {format_clock(activity.started)})" if activity.started else ""
            return f"{who}{since}: {activity.message}"
        if failed_since_success:
            label = {"failed": "Last refresh failed", "no_update": "Last refresh found too little news to publish",
                     "interrupted": "Last refresh was interrupted"}[state.last_attempt_outcome or "failed"]
            return f"{label}; showing the last good edition" if latest else label
        if state.last_attempt_outcome == "cancelled" and latest is None:
            return "Refresh was cancelled"
        if latest is None:
            return "No edition yet"
        if latest.edition_date < today:
            return "Out of date: showing an earlier edition"
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
        """Stop the running worker (blocks for up to ~15 s: call it from a background thread)."""
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


def enabled_failing_feeds(paths: DataPaths, prefs: DailyPrefs, now: datetime) -> list:
    """Feeds the reader can act on (enabled in Publisher feeds) that the feed doctor flags."""
    from agent_reach.daily.feedhealth import failing_feeds, load_feed_health

    enabled = {f.url.lower() for f in prefs.feeds if f.enabled}
    return [r for r in failing_feeds(load_feed_health(paths), now) if r.url.lower() in enabled]


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


# ====================================================================== presentation helpers (no Tk)
def headings(shown: DailyEdition | None, today: date) -> tuple[str, str]:
    """(title, date line) for the header: 'Today's Reach' only for today's real edition."""
    if shown is None:
        return "Today's Reach", "No edition collected yet"
    d = shown.edition_date
    date_line = f"{d:%A}, {format_long_date(d)}"
    if shown.demo:
        return "DEMO Edition", date_line + "  -  sample content, not real news"
    if d == today:
        return "Today's Reach", date_line
    return "Daily Edition", date_line


def status_kind(*, shown: DailyEdition | None, viewing_latest: bool, latest: DailyEdition | None, today: date,
                running: bool, failed: bool) -> str:
    if running:
        return "refreshing"
    if shown is not None and shown.demo:
        return "demo"
    if shown is not None and not viewing_latest:
        return "archive"
    if failed:
        return "failed"
    if latest is None:
        return "empty"
    return "stale" if latest.edition_date < today else "current"


def failure_text(state: RefreshState, *, has_edition: bool) -> str:
    """One plain sentence about the last unsuccessful refresh (no duplicated 'No new edition')."""
    when = format_central(state.last_attempt_finished_utc) if state.last_attempt_finished_utc else "recently"
    reason = (state.last_attempt_message or "").strip()
    for prefix in ("No new edition:", "No new edition -"):
        if reason.startswith(prefix):
            reason = reason[len(prefix):].strip()
    reason = reason.replace(" The previous edition is kept.", "")
    head = {"no_update": "The refresh at {when} found too little news to publish.",
            "interrupted": "The refresh at {when} stopped before finishing."}.get(
        state.last_attempt_outcome or "", "The refresh at {when} did not finish.").format(when=when)
    keep = " Your last good edition is still shown." if has_edition else ""
    return f"{head} {reason}{keep}".replace("  ", " ").strip()


def compact_times(snap: Snapshot) -> list[str]:
    """Short sidebar lines, e.g. 'Updated today 7:20 AM CDT', 'Next: tomorrow 7:05 AM CDT (in 24 h)'."""
    lines = [snap.last_success.replace("Last successful refresh ", "Updated ", 1)]
    nxt = snap.next_refresh
    if nxt.startswith("Next refresh: "):
        nxt = "Next: " + nxt.removeprefix("Next refresh: ")
    elif nxt.startswith("Next refresh "):
        nxt = "Next: " + nxt.removeprefix("Next refresh ")
    nxt = re.sub(r"\s*\(in [^)]*\)$", "", nxt)  # 'in 24 h' is implied by the time; keeps the line short
    if nxt:
        lines.append(nxt)
    if snap.coverage_line:
        lines.append(snap.coverage_line)
    return lines


def feed_note(health) -> str:
    """Details line for a channel made of feeds, e.g. '2 of 75 feeds failed; 3 had nothing new'."""
    feeds = list(health.feeds)
    if not feeds:
        return ""
    noun = "channels" if health.source == "youtube" else "sections" if health.source == "google_news" else "feeds"
    failed = sum(f.status == "failed" for f in feeds)
    empty = sum(f.status == "empty" for f in feeds)
    one = noun[:-1] if len(feeds) == 1 else noun
    parts = [f"{failed} of {len(feeds)} {noun} failed"] if failed else [f"{len(feeds)} {one}"]
    if empty:
        parts.append(f"{empty} had nothing new" if health.source == "youtube" else f"{empty} returned nothing")
    return "; ".join(parts) + " (expand)"


def coverage_summary(edition: DailyEdition) -> str:
    """Compact, honest source-health line, e.g. 'Sources: 6 healthy \u00b7 1 partial'."""
    return "Sources: " + health_summary(edition.source_health)


@dataclass
class PublisherRow:
    publisher: str
    channels: list[str]
    stories: int
    articles: int


def publisher_breakdown(edition: DailyEdition) -> list[PublisherRow]:
    """Which publishers this edition actually cites (incl. those arriving via Google News)."""
    rows: dict[str, PublisherRow] = {}
    for story in edition.stories:
        seen_in_story: set[str] = set()
        for e in story.evidence:
            name = e.publisher or e.source_name
            key = name.lower()
            row = rows.setdefault(key, PublisherRow(name, [], 0, 0))
            row.articles += 1
            if e.source_name not in row.channels:
                row.channels.append(e.source_name)
            if key not in seen_in_story:
                row.stories += 1
                seen_in_story.add(key)
    return sorted(rows.values(), key=lambda r: (-r.stories, -r.articles, r.publisher.lower()))


def story_age(story: Story, now: datetime) -> str:
    """'3h ago' from the newest STATED publication time; never invents an age."""
    newest = newest_published(story)
    if newest is None:
        return "publication time not stated"
    seconds = (now - newest).total_seconds()
    if seconds < 0:
        return "just published"
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))}m ago"
    if seconds < 48 * 3600:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)} days ago"


def story_publishers(story: Story, limit: int = 4) -> tuple[list[tuple[str, str | None]], int]:
    """Distinct (publisher name, safe url) pairs for the compact source line, plus how many more."""
    seen: dict[str, str | None] = {}
    for e in story.evidence:
        name = e.publisher or e.source_name
        if name and name.lower() not in {k.lower() for k in seen}:
            seen[name] = safe_url(e.url)
    items = list(seen.items())
    return items[:limit], max(0, len(items) - limit)


def details_report(snap: Snapshot, paths: DataPaths) -> list[tuple[str, list[tuple[str, str]]]]:
    """Secondary information for the Details window: [(section, [(label, value)])]."""
    st = snap.state
    t = lambda dt: format_central(dt) if dt else "-"  # noqa: E731
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    ed = snap.shown
    if ed is not None:
        acct = ed.accounting
        sections.append(("Edition", [
            ("Edition date", f"{format_long_date(ed.edition_date)} (America/Chicago)" + (" - DEMO" if ed.demo else "")),
            ("Revision", str(ed.revision)),
            ("Refresh started", t(ed.generation_started_utc)),
            ("Edition generated", t(ed.generation_completed_utc)),
            ("Stories", str(len(ed.stories))),
            ("Summaries", "local model" if ed.model.summaries == "local_model" else "extractive (lead sentences)"),
            ("Models", f"{ed.model.llm_model} / {ed.model.embed_model}"),
            ("Pipeline", ed.model.pipeline_mode),
            ("Items", f"{acct.ingested} collected, {acct.passed_filters} passed filters, {acct.clustered} in stories"),
            ("Coverage balanced", "yes" if ed.coverage.balanced else "no"),
            ("Run ID", ed.run_id),
            ("Config fingerprint", ed.config_fingerprint),
        ]))
        if snap.details:
            sections.append(("Notes", [("", d) for d in snap.details]))
    sections.append(("Refresh history", [
        ("Last attempt started", t(st.last_attempt_started_utc)),
        ("Last attempt finished", t(st.last_attempt_finished_utc)),
        ("Last attempt result", (st.last_attempt_outcome or "-") + (f" ({st.last_attempt_trigger})" if st.last_attempt_trigger else "")),
        ("Last attempt message", st.last_attempt_message or "-"),
        ("Last successful refresh", t(st.last_success_utc)),
        ("Failures in a row", str(st.consecutive_failures)),
        ("Next automatic retry", t(st.next_retry_utc) if st.consecutive_failures else "-"),
        ("Schedule", snap.next_refresh or "-"),
    ]))
    sections.append(("Local data", [
        ("Data folder", str(paths.root)),
        ("Editions", str(paths.editions_dir)),
        ("Settings", str(paths.settings)),
        ("Logs", str(paths.logs_dir)),
        ("Exports", str(paths.exports_dir)),
        ("History database", str(paths.db)),
        ("App version", VERSION_LABEL),
    ]))
    return sections


# ====================================================================== window state
def load_window_geometry(paths: DataPaths) -> str | None:
    try:
        data = read_json(paths.state_dir / "window.json")
    except (OSError, ValueError):
        return None
    geo = data.get("geometry") if isinstance(data, dict) else None
    return geo if isinstance(geo, str) and _GEOMETRY_RX.match(geo) else None


def save_window_geometry(paths: DataPaths, geometry: str) -> None:
    if not _GEOMETRY_RX.match(geometry or ""):
        return
    try:
        atomic_write_json(paths.state_dir / "window.json", {"geometry": geometry})
    except OSError:
        pass


_GEOMETRY_RX = re.compile(r"^\d{3,5}x\d{3,5}[+-]-?\d{1,5}[+-]-?\d{1,5}$")



# ====================================================================== appearance
def windows_prefers_dark() -> bool:
    """Windows 'Choose your app mode: Dark' (HKCU ...\\Personalize\\AppsUseLightTheme == 0)."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except (OSError, ValueError):
        return False


def resolve_appearance(preference: str, system_dark: Callable[[], bool] = windows_prefers_dark) -> str:
    """'light' or 'dark' for a preference of 'system', 'light' or 'dark'."""
    if preference in ("light", "dark"):
        return preference
    return "dark" if system_dark() else "light"
