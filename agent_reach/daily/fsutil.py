"""Atomic file replacement: readers see the old complete file or the new complete file, never a mix.

Write to a temporary file in the destination directory, flush and fsync it, then
``os.replace`` it over the target (atomic on NTFS and POSIX within one volume). Windows can
refuse the rename while another process briefly holds the target open (a reader, an
antivirus scan), so the rename is retried for a short bounded time.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

TMP_SUFFIX = ".tmp"


def replace_with_retry(src: str | Path, dst: str | Path, attempts: int = 40, delay_s: float = 0.05) -> None:
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay_s)


def unlink_with_retry(path: Path, attempts: int = 40, delay_s: float = 0.05) -> bool:
    """Delete ``path``; False when it cannot be deleted. Windows refuses to delete a file another process has
    open for a moment (the window reading progress.json; October 7, PC: the file outlived its refresh)."""
    for attempt in range(attempts):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if attempt == attempts - 1:
                return False
            time.sleep(delay_s)
        except OSError:
            return False
    return False


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=TMP_SUFFIX, dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        replace_with_retry(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=False, ensure_ascii=False) + "\n")


class FileUnavailable(OSError):
    """A file exists but cannot be read right now (open in another program, no permission). It is NOT
    damaged: callers must not reset or move it."""


#: How long a read waits for another program (a virus scanner, OneDrive, a backup tool) to let go of a file.
READ_RETRY_S = 3.0


def read_json(path: Path) -> Any:
    """Read JSON with a short retry for transient Windows sharing violations."""
    last: Exception | None = None
    for _ in range(int(READ_RETRY_S / 0.05)):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError as exc:
            last = exc
            time.sleep(0.05)
    raise last  # type: ignore[misc]


def cleanup_stale_temp_files(directory: Path, older_than_s: float = 3600.0) -> int:
    """Remove temp files left by a writer that crashed before its rename."""
    removed = 0
    if not directory.is_dir():
        return 0
    cutoff = time.time() - older_than_s
    for p in directory.glob(f".*{TMP_SUFFIX}"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed
