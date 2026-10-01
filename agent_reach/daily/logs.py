"""Rotating log files in the data directory (one file per process role to avoid rotation clashes).

``refresh.log`` is written only by the refresh-lock holder, ``scheduler.log`` by quick
--refresh-if-due checks, ``gui.log`` by the desktop window. Under pythonw.exe there is no
console, so console logging is added only when a real stderr exists.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from agent_reach.daily.paths import DataPaths

FORMAT = "%(asctime)s %(levelname)-7s %(process)d %(name)s: %(message)s"


def setup_logging(paths: DataPaths, role: str, level: str = "INFO", console: bool | None = None) -> logging.Handler:
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler = RotatingFileHandler(paths.logs_dir / f"{role}.log", maxBytes=1_000_000, backupCount=5,
                                  encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter(FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    handler.set_name(f"agent_reach_daily_{role}")
    for h in list(root.handlers):
        if h.get_name() == handler.get_name():
            root.removeHandler(h)
    root.addHandler(handler)
    if console is None:
        console = sys.stderr is not None and hasattr(sys.stderr, "write")
    if console and not any(getattr(h, "_ar_console", False) for h in root.handlers):
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S"))
        stream._ar_console = True  # type: ignore[attr-defined]
        root.addHandler(stream)
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return handler


def move_logging(paths: DataPaths, from_role: str, to_role: str, level: str = "INFO") -> None:
    """Switch the file handler (e.g. from scheduler.log to refresh.log once the lock is held)."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if h.get_name() == f"agent_reach_daily_{from_role}":
            root.removeHandler(h)
            h.close()
    setup_logging(paths, to_role, level, console=False)
