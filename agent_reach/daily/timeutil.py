"""Time handling: UTC internally, America/Chicago for edition dates and display.

* Every stored timestamp, lock and elapsed-time comparison is UTC.
* An edition is dated by the Central calendar date of its refresh START, so a run that
  crosses local midnight keeps one consistent date.
* Display uses the zone's own abbreviation (CDT or CST) for the instant shown.
* Fixed daily Central-time schedules use wall-clock times. On the spring-forward day
  (23 hours) a time inside the skipped hour resolves to the same elapsed offset after the
  gap (02:30 -> 03:30 CDT). On the fall-back day (25 hours) an ambiguous time resolves to
  its first occurrence (01:30 CDT, not 01:30 CST).

Windows has no IANA database, so the ``tzdata`` package is a hard requirement.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CENTRAL_TZ_NAME = "America/Chicago"

try:
    CENTRAL = ZoneInfo(CENTRAL_TZ_NAME)
except ZoneInfoNotFoundError as exc:  # pragma: no cover - only without tzdata on Windows
    raise RuntimeError(
        "Time zone data for America/Chicago is missing. Install it with: pip install tzdata"
    ) from exc

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Aware UTC datetime. Naive input is rejected: ambiguity here causes wrong dates."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime; pass an aware datetime")
    return dt.astimezone(timezone.utc)


def parse_utc(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else None


def iso_utc(dt: datetime | None) -> str | None:
    return ensure_utc(dt).isoformat().replace("+00:00", "Z") if dt else None


def to_central(dt: datetime) -> datetime:
    return ensure_utc(dt).astimezone(CENTRAL)


def central_date(dt: datetime) -> date:
    """Central calendar date of an instant (used to date editions by refresh start)."""
    return to_central(dt).date()


def format_long_date(d: date) -> str:
    """'October 1, 2026' (no zero padding; strftime %-d is not portable to Windows)."""
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"


def format_short_date(d: date) -> str:
    return f"{d:%a} {MONTHS[d.month - 1][:3]} {d.day}, {d.year}"


def format_clock(dt: datetime) -> str:
    """'7:05 AM CDT' for an instant, in Central time with the correct abbreviation."""
    local = to_central(dt)
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'} {local.tzname()}"


def format_central(dt: datetime) -> str:
    """'October 1, 2026 at 7:05 AM CDT'."""
    return f"{format_long_date(to_central(dt).date())} at {format_clock(dt)}"


def format_brief(dt: datetime, now: datetime) -> str:
    """'today 7:05 AM CDT', 'yesterday 9:10 PM CDT', 'tomorrow 7:05 AM CDT' or 'Oct 3, 7:05 AM CDT'."""
    day = to_central(dt).date()
    delta = (day - to_central(now).date()).days
    names = {0: "today", -1: "yesterday", 1: "tomorrow"}
    when = names.get(delta) or f"{MONTHS[day.month - 1][:3]} {day.day},"
    return f"{when} {format_clock(dt)}"


def edition_heading(edition_date: date) -> str:
    return f"Trending news for {format_long_date(edition_date)}"


def updated_line(completed: datetime) -> str:
    return f"Updated {format_central(completed)}"


def parse_hhmm(text: str) -> time:
    hh, _, mm = text.strip().partition(":")
    t = time(int(hh), int(mm or 0))
    return t


def resolve_local(d: date, t: time) -> datetime:
    """Aware Central datetime for a wall-clock time on a date, resolving DST gaps and folds.

    Gap (spring forward): the wall time does not exist; return the instant reached by
    applying the pre-transition offset (02:30 CST == 03:30 CDT). Fold (fall back): the wall
    time occurs twice; return the first occurrence (fold=0, daylight time).
    """
    naive = datetime.combine(d, t)
    candidate = naive.replace(tzinfo=CENTRAL, fold=0)
    round_trip = candidate.astimezone(timezone.utc).astimezone(CENTRAL)
    if round_trip.replace(tzinfo=None) != naive:
        return round_trip  # nonexistent local time, shifted past the gap
    return candidate


def next_fixed_time_after(after: datetime, at: time) -> datetime:
    """First instant (UTC) strictly after ``after`` whose Central wall-clock time is ``at``."""
    after = ensure_utc(after)
    day = to_central(after).date()
    for offset in range(0, 4):
        candidate = resolve_local(day + timedelta(days=offset), at).astimezone(timezone.utc)
        if candidate > after:
            return candidate
    raise AssertionError("unreachable: a daily time always recurs within 2 days")


def local_day_length_hours(d: date) -> float:
    """Elapsed hours in a Central calendar day (23 on spring-forward, 25 on fall-back)."""
    start = datetime.combine(d, time(0), tzinfo=CENTRAL)
    end = datetime.combine(d + timedelta(days=1), time(0), tzinfo=CENTRAL)
    return (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() / 3600


def humanize_delta(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "now"
    if seconds < 90:
        return "in a minute"
    minutes = round(seconds / 60)
    if minutes < 90:
        return f"in {minutes} min"
    hours = seconds / 3600
    if hours < 36:
        return f"in {hours:.0f} h"
    return f"in {hours / 24:.0f} days"
