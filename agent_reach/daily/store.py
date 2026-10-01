"""Dated edition cache with an atomic latest-edition pointer.

Publication order (only the refresh-lock holder publishes):

1. validate the edition and its JSON round trip;
2. atomically replace ``cache/editions/YYYY-MM-DD.json``;
3. atomically replace ``cache/latest.json`` (date, revision, run_id, SHA-256 of the file).

A crash between 2 and 3 leaves a complete newer dated file and an older pointer whose
checksum no longer matches; readers then fall back to scanning dated files, and the next
lock holder repairs the pointer. Readers never see partial JSON because every write is a
temp-file + rename.

Same-date replacement: a second successful refresh on the same Central date replaces that
date's file with ``revision + 1`` and appends the replaced revision to ``previous_revisions``
(run_id and completion time). Earlier dates are never rewritten or re-dated.

Readers (the GUI) never move or delete files. Corrupt files are reported and skipped; the
next refresh worker moves them to ``cache/quarantine``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from pydantic import ValidationError

from agent_reach.daily.edition import DailyEdition, Revision
from agent_reach.daily.fsutil import atomic_write_json, atomic_write_text, cleanup_stale_temp_files, read_json
from agent_reach.daily.paths import DataPaths

log = logging.getLogger(__name__)

DATE_FILE_RX = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")
POINTER_VERSION = 1


@dataclass
class LoadResult:
    edition: DailyEdition | None
    path: Path | None = None
    pointer_ok: bool = False
    corrupt: list[str] = field(default_factory=list)


class EditionStore:
    def __init__(self, paths: DataPaths) -> None:
        self.paths = paths

    # ------------------------------------------------------------ reading
    def edition_path(self, d: date) -> Path:
        return self.paths.editions_dir / f"{d.isoformat()}.json"

    def list_dates(self) -> list[date]:
        out = []
        if not self.paths.editions_dir.is_dir():
            return out
        for p in self.paths.editions_dir.iterdir():
            m = DATE_FILE_RX.match(p.name)
            if m:
                try:
                    out.append(date.fromisoformat(m.group(1)))
                except ValueError:
                    continue
        return sorted(out, reverse=True)

    def _read(self, path: Path) -> tuple[DailyEdition | None, str | None, bytes | None]:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None, None, None
        except OSError as exc:
            return None, f"{path.name}: {exc}", None
        try:
            edition = DailyEdition.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            return None, f"{path.name}: {str(exc).splitlines()[0][:160]}", raw
        if path.stem != edition.edition_date.isoformat():
            return None, f"{path.name}: file name does not match edition_date {edition.edition_date}", raw
        return edition, None, raw

    def load_date(self, d: date) -> tuple[DailyEdition | None, str | None]:
        edition, problem, _ = self._read(self.edition_path(d))
        return edition, problem

    def read_pointer(self) -> dict | None:
        try:
            data = read_json(self.paths.latest_pointer)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and data.get("pointer_version") == POINTER_VERSION else None

    def load_latest(self) -> LoadResult:
        """Newest valid edition. Uses the pointer when its checksum matches, else scans dates."""
        corrupt: list[str] = []
        pointer = self.read_pointer()
        if pointer:
            try:
                path = self.edition_path(date.fromisoformat(str(pointer.get("edition_date"))))
            except ValueError:
                path = None
            if path is not None:
                edition, problem, raw = self._read(path)
                if problem:
                    corrupt.append(problem)
                if edition is not None and raw is not None and hashlib.sha256(raw).hexdigest() == pointer.get("sha256"):
                    newer = [d for d in self.list_dates() if d > edition.edition_date]
                    if not newer:
                        return LoadResult(edition, path, pointer_ok=True, corrupt=corrupt)
        for d in self.list_dates():
            edition, problem, _ = self._read(self.edition_path(d))
            if problem:
                corrupt.append(problem)
                continue
            if edition is not None:
                return LoadResult(edition, self.edition_path(d), pointer_ok=False, corrupt=corrupt)
        return LoadResult(None, None, pointer_ok=False, corrupt=corrupt)

    def has_any(self) -> bool:
        return bool(self.list_dates())

    # ------------------------------------------------------------ writing (lock holder only)
    def publish(self, edition: DailyEdition) -> DailyEdition:
        if edition.demo:
            raise ValueError("demo editions are never written to the news cache")
        path = self.edition_path(edition.edition_date)
        existing, _ = self.load_date(edition.edition_date)
        payload = edition.model_dump(mode="json")
        if existing is not None:
            payload["revision"] = existing.revision + 1
            payload["previous_revisions"] = [
                r.model_dump(mode="json") for r in existing.previous_revisions
            ] + [Revision(revision=existing.revision, run_id=existing.run_id,
                          generation_completed_utc=existing.generation_completed_utc).model_dump(mode="json")]
        final = DailyEdition.model_validate(payload)
        text = final.model_dump_json(indent=2)
        DailyEdition.model_validate_json(text)  # the exact bytes we publish must load
        atomic_write_text(path, text)
        raw = path.read_bytes()
        atomic_write_json(self.paths.latest_pointer, {
            "pointer_version": POINTER_VERSION,
            "edition_date": final.edition_date.isoformat(),
            "file": f"editions/{path.name}",
            "revision": final.revision,
            "run_id": final.run_id,
            "generation_completed_utc": final.generation_completed_utc.isoformat(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
        log.info("published edition %s revision %d (%d stories)", final.edition_date, final.revision, len(final.stories))
        return final

    def repair(self) -> list[str]:
        """Quarantine corrupt files, drop stale temp files and re-point latest. Lock holder only."""
        actions: list[str] = []
        self.paths.quarantine_dir.mkdir(parents=True, exist_ok=True)
        for d in self.list_dates():
            path = self.edition_path(d)
            edition, problem, raw = self._read(path)
            if problem and raw is not None:
                target = self.paths.quarantine_dir / f"{path.name}.{int(time.time())}.corrupt"
                shutil.move(str(path), str(target))
                actions.append(f"quarantined {path.name}: {problem}")
        removed = cleanup_stale_temp_files(self.paths.editions_dir) + cleanup_stale_temp_files(self.paths.cache_dir)
        if removed:
            actions.append(f"removed {removed} stale temp file(s)")
        result = self.load_latest()
        if result.edition is not None and not result.pointer_ok and result.path is not None:
            raw = result.path.read_bytes()
            atomic_write_json(self.paths.latest_pointer, {
                "pointer_version": POINTER_VERSION,
                "edition_date": result.edition.edition_date.isoformat(),
                "file": f"editions/{result.path.name}",
                "revision": result.edition.revision,
                "run_id": result.edition.run_id,
                "generation_completed_utc": result.edition.generation_completed_utc.isoformat(),
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
            actions.append(f"latest pointer repaired -> {result.path.name}")
        elif result.edition is None and self.paths.latest_pointer.exists():
            self.paths.latest_pointer.unlink()
            actions.append("removed latest pointer with no valid edition")
        for a in actions:
            log.warning("cache repair: %s", a)
        return actions

    def purge(self, retention_days: int, today: date) -> list[date]:
        """Delete editions older than the retention window; never the newest valid edition."""
        keep_from = today - timedelta(days=retention_days - 1)
        latest = self.load_latest().edition
        removed = []
        for d in self.list_dates():
            if d >= keep_from or (latest is not None and d == latest.edition_date):
                continue
            try:
                self.edition_path(d).unlink()
                removed.append(d)
            except OSError as exc:
                log.warning("could not remove old edition %s: %s", d, exc)
        if removed:
            log.info("retention: removed %d edition(s) older than %d days", len(removed), retention_days)
        return removed

    def reset(self) -> int:
        """Explicit user action: delete every cached edition and the pointer (settings are kept)."""
        n = 0
        for d in self.list_dates():
            try:
                self.edition_path(d).unlink()
                n += 1
            except OSError:
                pass
        for p in (self.paths.latest_pointer,):
            try:
                p.unlink()
            except OSError:
                pass
        if self.paths.quarantine_dir.is_dir():
            shutil.rmtree(self.paths.quarantine_dir, ignore_errors=True)
        return n
