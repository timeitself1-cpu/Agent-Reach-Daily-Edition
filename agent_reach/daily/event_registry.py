"""Persistent event registry for cross-edition timelines.

Each significant event gets a stable record that accumulates history across editions.
The registry lives in ``events/`` (per-event JSON files) alongside the edition cache.

Event lifecycle:
- New event: created when a story's stable_event_id has no registry entry
- Updated: new edition has the same event with new/changed reporting
- Archived: no updates for ARCHIVE_AFTER_DAYS (default 14)

The registry is the source of truth for timelines. The website renders
``/events/<event_id>.json`` and ``/events/index.json`` from these records.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ARCHIVE_AFTER_DAYS = 14


@dataclass
class TimelineEntry:
    """One edition's contribution to an event's history."""
    date: str  # YYYY-MM-DD
    edition: str  # edition date string
    revision: int
    change: str  # "new" | "updated" | "unchanged"
    headline: str
    summary: str
    sources: list[str] = field(default_factory=list)
    source_count: int = 0
    what_changed: str = ""  # human-readable description of what changed
    story_url: str = ""  # link to the story in its edition


@dataclass
class EventRecord:
    """A tracked event with its full timeline."""
    event_id: str
    first_seen: str  # YYYY-MM-DD
    last_updated: str  # YYYY-MM-DD
    status: str = "developing"  # developing | resolved | archived
    category: str = ""
    current_headline: str = ""
    current_summary: str = ""
    timeline: list[TimelineEntry] = field(default_factory=list)
    corrections: list[dict[str, Any]] = field(default_factory=list)
    merged_into: str = ""  # if merged, the surviving event_id

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EventRecord":
        timeline = [TimelineEntry(**e) for e in d.get("timeline", [])]
        return cls(
            event_id=d["event_id"],
            first_seen=d["first_seen"],
            last_updated=d["last_updated"],
            status=d.get("status", "developing"),
            category=d.get("category", ""),
            current_headline=d.get("current_headline", ""),
            current_summary=d.get("current_summary", ""),
            timeline=timeline,
            corrections=d.get("corrections", []),
            merged_into=d.get("merged_into", ""),
        )


class EventRegistry:
    """Persistent registry of tracked events."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.events_dir = self.base_dir / "events"
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, EventRecord] = {}

    def _path(self, event_id: str) -> Path:
        # Shard by first 2 chars to avoid too many files in one dir
        shard = event_id[4:6] if event_id.startswith("evt_") else event_id[:2]
        shard_dir = self.events_dir / shard
        shard_dir.mkdir(parents=True, exist_ok=True)
        return shard_dir / f"{event_id}.json"

    def get(self, event_id: str) -> EventRecord | None:
        if event_id in self._cache:
            return self._cache[event_id]
        path = self._path(event_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = EventRecord.from_dict(json.load(f))
            self._cache[event_id] = record
            return record
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def save(self, record: EventRecord) -> None:
        """Atomic save: temp file + rename."""
        path = self._path(record.event_id)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(record.to_dict(), f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self._cache[record.event_id] = record

    def update_from_story(self, story: Any, edition_date: str, revision: int,
                          change: str = "new", what_changed: str = "") -> EventRecord:
        """Add or update an event from a story in an edition.

        Computes the stable event ID, loads or creates the record, appends
        a timeline entry, and saves.
        """
        from agent_reach.pipeline.evidence import canonical_event_id

        try:
            event_id = canonical_event_id(story)
        except Exception:
            event_id = self._fallback_id(story)

        record = self.get(event_id)

        # Extract outlet names explicitly. Sources may be dicts (public JSON) or objects.
        sources = []
        raw_sources = []
        if isinstance(story, dict):
            raw_sources = story.get("sources", []) or []
            headline = story.get("headline", "") or ""
            raw_summary = story.get("summary", "") or ""
            category = story.get("category", "") or ""
            story_url = story.get("url", "") or ""
        else:
            if hasattr(story, 'sources'):
                raw_sources = story.sources or []
            elif hasattr(story, 'publishers'):
                raw_sources = story.publishers or []
            headline = getattr(story, 'headline', '') or ""
            raw_summary = getattr(story, 'summary', '') or ""
            cat_obj = getattr(story, 'category', '') or ""
            category = cat_obj.value if hasattr(cat_obj, 'value') else str(cat_obj)
            story_url = getattr(story, 'url', '') or ""

        summary = " ".join(raw_summary) if isinstance(raw_summary, list) else str(raw_summary)

        for s in raw_sources:
            if isinstance(s, dict):
                outlet = s.get("outlet") or s.get("publisher") or ""
            elif isinstance(s, str):
                outlet = s
            else:
                outlet = getattr(s, 'outlet', '') or ""
            if outlet:
                sources.append(outlet)

        entry = TimelineEntry(
            date=edition_date,
            edition=edition_date,
            revision=revision,
            change=change,
            headline=headline,
            summary=summary,
            sources=sources[:10],  # cap at 10
            source_count=len(sources),
            what_changed=what_changed,
            story_url=story_url,
        )

        if record is None:
            record = EventRecord(
                event_id=event_id,
                first_seen=edition_date,
                last_updated=edition_date,
                category=category,
                current_headline=entry.headline,
                current_summary=entry.summary,
                timeline=[entry],
            )
        else:
            # Avoid duplicate entries for the same edition+revision
            if not any(e.edition == edition_date and e.revision == revision for e in record.timeline):
                record.timeline.append(entry)
            record.last_updated = edition_date
            record.current_headline = entry.headline
            record.current_summary = entry.summary
            # Revive archived events that get new coverage
            if record.status == "archived":
                record.status = "developing"

        self.save(record)
        return record

    def _fallback_id(self, story: Any) -> str:
        """When no items are available, hash the headline + date."""
        headline = (story.get("headline", "") if isinstance(story, dict)
                    else getattr(story, 'headline', '') or "")
        key = f"{headline.casefold()}|fallback"
        return "evt_" + hashlib.sha256(key.encode()).hexdigest()[:12]

    def archive_stale(self, days: int = ARCHIVE_AFTER_DAYS) -> int:
        """Mark events with no updates in `days` as archived. Returns count archived."""
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
        archived = 0
        for path in self.events_dir.rglob("evt_*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    record = EventRecord.from_dict(json.load(f))
                if record.status == "developing" and record.last_updated < cutoff:
                    record.status = "archived"
                    self.save(record)
                    archived += 1
            except (json.JSONDecodeError, KeyError, OSError):
                continue
        return archived

    def merge_events(self, keep_id: str, drop_id: str) -> EventRecord | None:
        """Merge two events that turned out to be the same. Keeps keep_id's record,
        appends drop_id's timeline (sorted by date), marks drop_id as merged."""
        keep = self.get(keep_id)
        drop = self.get(drop_id)
        if not keep or not drop:
            return None
        # Merge timelines, sorted by date
        combined = sorted(keep.timeline + drop.timeline, key=lambda e: (e.date, e.revision))
        # Deduplicate same edition+revision
        seen = set()
        deduped = []
        for e in combined:
            key = (e.edition, e.revision)
            if key not in seen:
                seen.add(key)
                deduped.append(e)
        keep.timeline = deduped
        keep.last_updated = max(e.date for e in deduped) if deduped else keep.last_updated
        # Merge corrections
        keep.corrections.extend(drop.corrections)
        self.save(keep)
        # Mark dropped as merged
        drop.merged_into = keep_id
        drop.status = "archived"
        self.save(drop)
        return keep

    def index(self) -> list[dict[str, Any]]:
        """Lightweight index of all events for /events/index.json."""
        out = []
        for path in self.events_dir.rglob("evt_*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("merged_into"):
                    continue  # skip merged-away events
                out.append({
                    "event_id": d["event_id"],
                    "first_seen": d["first_seen"],
                    "last_updated": d["last_updated"],
                    "status": d.get("status", "developing"),
                    "category": d.get("category", ""),
                    "headline": d.get("current_headline", ""),
                    "timeline_entries": len(d.get("timeline", [])),
                })
            except (json.JSONDecodeError, KeyError, OSError):
                continue
        # Most recently updated first
        out.sort(key=lambda x: x["last_updated"], reverse=True)
        return out
