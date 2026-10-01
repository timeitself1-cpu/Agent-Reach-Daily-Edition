"""Per-user data layout, independent of the install directory and the working directory.

    %LOCALAPPDATA%\\AgentReachDaily\\
        settings.json                 user preferences
        state\\refresh_state.json      last attempt / last success / backoff
        state\\refresh.lock            cross-process lock file (OS byte-range lock)
        state\\refresh.lock.json       holder info (pid, trigger, started) for display only
        state\\progress.json           current refresh stage for the GUI
        cache\\editions\\YYYY-MM-DD.json  validated daily editions
        cache\\latest.json             pointer to the newest published edition
        cache\\quarantine\\            corrupt cache files moved aside (never silently deleted)
        data\\agent_reach.db           SQLite run history (momentum baselines)
        diagnostics\\                  failed / no-update attempt diagnostics
        logs\\                         rotating logs (gui.log, refresh.log, scheduler.log)
        exports\\                      default folder for exported HTML editions

``AGENT_REACH_DAILY_HOME`` overrides the root (tests, portable installs).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from agent_reach.daily import APP_ID

#: The project folder that contains the ``agent_reach`` package (working directory for workers).
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_root() -> Path:
    override = os.environ.get("AGENT_REACH_DAILY_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_ID
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_ID


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @classmethod
    def resolve(cls, root: str | Path | None = None) -> "DataPaths":
        return cls(Path(root).expanduser().resolve() if root else default_root().resolve())

    @property
    def settings(self) -> Path:
        return self.root / "settings.json"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "refresh_state.json"

    @property
    def lock_file(self) -> Path:
        return self.state_dir / "refresh.lock"

    @property
    def lock_info(self) -> Path:
        return self.state_dir / "refresh.lock.json"

    @property
    def progress_file(self) -> Path:
        return self.state_dir / "progress.json"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def editions_dir(self) -> Path:
        return self.cache_dir / "editions"

    @property
    def latest_pointer(self) -> Path:
        return self.cache_dir / "latest.json"

    @property
    def quarantine_dir(self) -> Path:
        return self.cache_dir / "quarantine"

    @property
    def db(self) -> Path:
        return self.root / "data" / "agent_reach.db"

    @property
    def diagnostics_dir(self) -> Path:
        return self.root / "diagnostics"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    def ensure(self) -> "DataPaths":
        for d in (self.state_dir, self.editions_dir, self.quarantine_dir, self.db.parent,
                  self.diagnostics_dir, self.logs_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self
