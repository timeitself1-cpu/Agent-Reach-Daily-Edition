"""One cross-process refresh lock for scheduled, GUI-launch and manual refreshes.

The lock is an operating-system byte-range lock on ``state/refresh.lock`` (``msvcrt.locking``
on Windows, ``fcntl.flock`` elsewhere). The OS releases it when the holding process exits for
any reason, including a crash, a kill from Task Manager or a power loss, so a crashed worker
can never leave a permanently stuck flag. ``refresh.lock.json`` records who holds the lock
(pid, trigger, start time) for display only; it is never used to decide ownership.

Byte-range locks are per open handle, so a second acquisition from the same process also
fails while the first is held. A hung (not crashed) worker is bounded by the worker's own
run timeout and the scheduled task's execution time limit.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_reach.daily.fsutil import atomic_write_json, read_json


class LockBusy(Exception):
    """Another refresh holds the lock."""


class RefreshLock:
    def __init__(self, lock_path: Path, info_path: Path | None = None) -> None:
        self.lock_path = Path(lock_path)
        self.info_path = Path(info_path) if info_path else None
        self._fh = None
        self._thread_lock = threading.Lock()

    @property
    def held(self) -> bool:
        return self._fh is not None

    def acquire(self, info: dict[str, Any] | None = None) -> None:
        """Non-blocking. Raises LockBusy when another holder exists."""
        with self._thread_lock:
            if self._fh is not None:
                raise LockBusy("lock already held by this object")
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(self.lock_path, "a+b")
            try:
                _os_lock(fh)
            except OSError as exc:
                fh.close()
                raise LockBusy(str(exc)) from exc
            self._fh = fh
        if self.info_path is not None:
            payload = {"pid": os.getpid(), "acquired_utc": datetime.now(timezone.utc).isoformat(), **(info or {})}
            try:
                atomic_write_json(self.info_path, payload)
            except OSError:
                pass

    def release(self) -> None:
        with self._thread_lock:
            fh, self._fh = self._fh, None
        if fh is None:
            return
        if self.info_path is not None:
            try:
                self.info_path.unlink()
            except OSError:
                pass
        try:
            _os_unlock(fh)
        finally:
            fh.close()

    def __enter__(self) -> "RefreshLock":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def read_holder_info(info_path: Path) -> dict[str, Any] | None:
    try:
        data = read_json(info_path)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


if sys.platform == "win32":
    import msvcrt

    def _os_lock(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)

    def _os_unlock(fh) -> None:
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _os_lock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _os_unlock(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def pid_alive(pid: int | None) -> bool:
    """Best-effort liveness check used only for display (never for lock ownership)."""
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
