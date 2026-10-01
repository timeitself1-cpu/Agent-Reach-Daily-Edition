"""Daily app: preferences, Central-time semantics, due/not-due logic and failure backoff."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone

import pytest

from agent_reach.daily import prefs as P
from agent_reach.daily import state as S
from agent_reach.daily import timeutil as T

UTC = timezone.utc


# ------------------------------------------------------------------ preferences
def test_default_prefs_are_general_news_with_daily_momentum(daily_paths):
    prefs, warning = P.load_prefs(daily_paths)
    assert warning is None
    assert prefs.ollama_model == "llama3.1:8b" and prefs.embed_model == "nomic-embed-text"
    assert {"google_news", "news_rss"} <= set(prefs.enabled_sources)
    assert not {"github", "producthunt", "arxiv"} & set(prefs.enabled_sources)  # tech-only feeds are opt-in
    s = P.build_settings(prefs, daily_paths)
    assert s.velocity_windows_hours == [24.0, 48.0, 168.0]
    assert s.velocity_window_tolerance == 0.25
    assert s.db_path == daily_paths.db
    assert s.retention_days >= P.MIN_DB_RETENTION_DAYS  # the 7-day window always has history


def test_prefs_persist_round_trip(daily_paths):
    prefs = P.DailyPrefs(max_stories=9, schedule_mode="fixed_central", fixed_time_central="6:5")
    P.save_prefs(daily_paths, prefs)
    loaded, warning = P.load_prefs(daily_paths)
    assert warning is None
    assert loaded.max_stories == 9 and loaded.fixed_time_central == "06:05"


def test_corrupt_settings_reset_to_defaults_and_keep_a_copy(daily_paths):
    daily_paths.settings.write_text("{not json", encoding="utf-8")
    prefs, warning = P.load_prefs(daily_paths)
    assert prefs == P.DailyPrefs()
    assert warning and "reset" in warning
    assert list(daily_paths.root.glob("settings.json.corrupt-*"))


def test_invalid_values_are_reset_individually(daily_paths):
    daily_paths.settings.write_text(json.dumps({"max_stories": 12, "refresh_interval_hours": 0,
                                                "enabled_sources": ["nope"], "ollama_host": "ftp://x"}))
    prefs, warning = P.load_prefs(daily_paths)
    assert prefs.max_stories == 12  # valid value kept
    assert prefs.refresh_interval_hours == 24.0 and prefs.ollama_host == "http://localhost:11434"
    assert "enabled_sources" in warning and "refresh_interval_hours" in warning


@pytest.mark.parametrize("bad", [{"enabled_sources": []}, {"fixed_time_central": "25:00"}, {"retention_days": 0}])
def test_invalid_settings_are_rejected(bad):
    with pytest.raises(ValueError):
        P.DailyPrefs(**bad)


# ------------------------------------------------------------------ Central time
def test_edition_date_follows_central_midnight():
    assert T.central_date(datetime(2026, 10, 2, 4, 59, tzinfo=UTC)) == date(2026, 10, 1)  # 11:59 PM CDT
    assert T.central_date(datetime(2026, 10, 2, 5, 0, tzinfo=UTC)) == date(2026, 10, 2)  # midnight CDT
    assert T.central_date(datetime(2026, 12, 2, 5, 59, tzinfo=UTC)) == date(2026, 12, 1)  # 11:59 PM CST


def test_display_uses_cdt_and_cst():
    assert T.format_central(datetime(2026, 10, 1, 12, 5, tzinfo=UTC)) == "October 1, 2026 at 7:05 AM CDT"
    assert T.format_central(datetime(2026, 12, 1, 13, 5, tzinfo=UTC)) == "December 1, 2026 at 7:05 AM CST"
    assert T.edition_heading(date(2026, 10, 1)) == "Trending news for October 1, 2026"


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError):
        T.ensure_utc(datetime(2026, 10, 1, 12, 0))
    assert T.parse_utc("2026-10-01T12:00:00") is None  # no zone: not trusted
    assert T.parse_utc("2026-10-01T12:00:00Z") == datetime(2026, 10, 1, 12, tzinfo=UTC)


def test_dst_gap_and_fold_resolution():
    # 2026-03-08: 02:30 does not exist in Chicago -> 03:30 CDT
    gap = T.resolve_local(date(2026, 3, 8), time(2, 30))
    assert (gap.hour, gap.minute, gap.tzname()) == (3, 30, "CDT")
    # 2026-11-01: 01:30 happens twice -> the first (CDT)
    fold = T.resolve_local(date(2026, 11, 1), time(1, 30))
    assert fold.tzname() == "CDT"
    assert T.local_day_length_hours(date(2026, 3, 8)) == 23
    assert T.local_day_length_hours(date(2026, 11, 1)) == 25
    assert T.local_day_length_hours(date(2026, 10, 1)) == 24


def test_fixed_time_schedule_keeps_wall_clock_across_dst():
    before = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)  # Oct 31 07:00 CDT
    nxt = T.next_fixed_time_after(before, time(7, 0))
    assert T.to_central(nxt).date() == date(2026, 11, 1) and T.to_central(nxt).hour == 7
    assert nxt - before == timedelta(hours=25)  # fall-back day is 25 hours long


def test_brief_relative_format():
    now = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
    assert T.format_brief(datetime(2026, 10, 1, 12, 5, tzinfo=UTC), now) == "today 7:05 AM CDT"
    assert T.format_brief(datetime(2026, 10, 2, 12, 5, tzinfo=UTC), now) == "tomorrow 7:05 AM CDT"
    assert T.format_brief(datetime(2026, 9, 30, 12, 5, tzinfo=UTC), now) == "yesterday 7:05 AM CDT"
    assert T.format_brief(datetime(2026, 9, 20, 12, 5, tzinfo=UTC), now) == "Sep 20, 7:05 AM CDT"


# ------------------------------------------------------------------ due / backoff
T0 = datetime(2026, 10, 1, 12, 5, tzinfo=UTC)


def _success_state(started=T0):
    st = S.RefreshState()
    S.mark_running(st, trigger="manual", now=started, pid=1)
    S.mark_success(st, started=started, finished=started + timedelta(minutes=20), edition_date="2026-10-01", run_id="r1")
    return st


def test_never_refreshed_is_due():
    due = S.check_due(S.RefreshState(), P.DailyPrefs(), T0)
    assert due.due and due.reason == "never_refreshed"


def test_due_exactly_24_elapsed_hours_after_the_successful_start():
    st, prefs = _success_state(), P.DailyPrefs()
    assert not S.check_due(st, prefs, T0 + timedelta(hours=24) - timedelta(seconds=1)).due
    due = S.check_due(st, prefs, T0 + timedelta(hours=24))
    assert due.due and due.reason == "interval_elapsed"
    assert due.next_due_utc == T0 + timedelta(hours=24)  # anchored on the START, not the 20-minute run


def test_fixed_central_mode_uses_wall_clock():
    st = _success_state()
    prefs = P.DailyPrefs(schedule_mode="fixed_central", fixed_time_central="06:00")
    due = S.check_due(st, prefs, T0 + timedelta(hours=1))
    assert not due.due and T.format_central(due.next_due_utc) == "October 2, 2026 at 6:00 AM CDT"


def test_missed_schedule_yields_one_refresh_not_a_burst():
    st = _success_state()
    week_later = T0 + timedelta(days=7)
    assert S.check_due(st, P.DailyPrefs(), week_later).due
    S.mark_running(st, trigger="scheduled", now=week_later, pid=2)
    S.mark_success(st, started=week_later, finished=week_later + timedelta(minutes=10), edition_date="2026-10-08",
                   run_id="r2")
    assert not S.check_due(st, P.DailyPrefs(), week_later + timedelta(minutes=11)).due


def test_backoff_doubles_and_is_capped():
    prefs = P.DailyPrefs(retry_base_minutes=30, retry_max_hours=6)
    assert [S.backoff_delay(n, prefs) for n in (1, 2, 3, 4, 5, 9)] == [
        timedelta(minutes=30), timedelta(hours=1), timedelta(hours=2), timedelta(hours=4), timedelta(hours=6),
        timedelta(hours=6)]


def test_failure_defers_a_due_refresh_until_backoff_ends():
    st, prefs = S.RefreshState(), P.DailyPrefs()
    S.mark_running(st, trigger="scheduled", now=T0, pid=1)
    S.mark_failure(st, outcome="failed", message="Ollama down", now=T0, prefs=prefs)
    blocked = S.check_due(st, prefs, T0 + timedelta(minutes=29))
    assert not blocked.due and blocked.reason == "backoff"
    assert S.check_due(st, prefs, T0 + timedelta(minutes=30)).due
    S.mark_failure(st, outcome="no_update", message="too little news", now=T0, prefs=prefs)
    assert st.consecutive_failures == 2 and st.next_retry_utc == T0 + timedelta(hours=1)


def test_success_clears_backoff_but_keeps_attempt_and_success_separate():
    st, prefs = S.RefreshState(), P.DailyPrefs()
    S.mark_failure(st, outcome="failed", message="x", now=T0, prefs=prefs)
    S.mark_running(st, trigger="manual", now=T0 + timedelta(hours=1), pid=3)
    assert st.last_attempt_outcome == "running" and st.last_success_utc is None
    S.mark_success(st, started=T0 + timedelta(hours=1), finished=T0 + timedelta(hours=1, minutes=5),
                   edition_date="2026-10-01", run_id="r")
    assert st.consecutive_failures == 0 and st.next_retry_utc is None
    assert st.last_attempt_started_utc == T0 + timedelta(hours=1)
    assert st.last_success_utc == T0 + timedelta(hours=1, minutes=5)


def test_cancel_is_not_penalised_and_crash_is_recovered_as_interrupted():
    st, prefs = S.RefreshState(), P.DailyPrefs()
    S.mark_running(st, trigger="manual", now=T0, pid=1)
    S.mark_cancelled(st, now=T0 + timedelta(minutes=1))
    assert st.consecutive_failures == 0 and st.last_attempt_outcome == "cancelled"
    S.mark_running(st, trigger="scheduled", now=T0, pid=1)
    assert S.recover_interrupted(st, now=T0 + timedelta(hours=1), prefs=prefs)
    assert st.last_attempt_outcome == "interrupted" and st.consecutive_failures == 1
    assert not S.recover_interrupted(st, now=T0, prefs=prefs)
    with pytest.raises(ValueError):
        S.mark_failure(st, outcome="success", message="", now=T0, prefs=prefs)


def test_state_persists_and_corrupt_state_is_reset(daily_paths):
    st = _success_state()
    S.save_state(daily_paths, st)
    loaded, warning = S.load_state(daily_paths)
    assert warning is None and loaded.last_success_run_id == "r1"
    daily_paths.state_file.write_text("[1, 2", encoding="utf-8")
    loaded, warning = S.load_state(daily_paths)
    assert loaded == S.RefreshState() and warning
    assert list(daily_paths.state_dir.glob("refresh_state.json.corrupt-*"))


def test_interrupted_backoff_counts_from_the_dead_attempt_start():
    prefs = P.DailyPrefs()
    overnight = S.RefreshState()
    S.mark_running(overnight, trigger="scheduled", now=T0, pid=1)
    S.recover_interrupted(overnight, now=T0 + timedelta(hours=9), prefs=prefs)
    assert S.check_due(overnight, prefs, T0 + timedelta(hours=9)).due  # powered off overnight: retry now
    crash_loop = S.RefreshState()
    S.mark_running(crash_loop, trigger="scheduled", now=T0, pid=1)
    S.recover_interrupted(crash_loop, now=T0 + timedelta(minutes=2), prefs=prefs)
    blocked = S.check_due(crash_loop, prefs, T0 + timedelta(minutes=2))
    assert not blocked.due and blocked.reason == "backoff"
