"""The REAL Daily worker command line in a synthetic offline world, as its own process.

    python -m tests.daily_world --refresh-now --trigger manual --data-dir <folder>

Same arguments as ``python -m agent_reach.daily``. Before the command runs, the network and the local
model are replaced by the deterministic fakes of ``tests/daily_fakes.py`` (fictional feeds on ``.test``
hosts, a fake Ollama), so process-level behaviour (cancel, kill, crash, hang, time limit, the model
going away) can be exercised with real processes, real locks and real files on any machine, without
the internet or Ollama. Nothing here is used by the app itself.

Behaviour switches (environment variables):

    AR_WORLD_MODEL_DELAY_S     seconds every fake model call takes (a slow model; time to cancel)
    AR_WORLD_MODEL_DIES_AFTER  model calls that succeed before every later call fails to connect
    AR_WORLD_MODEL_DOWN        "1": the prerequisite check finds no Ollama at all
    AR_WORLD_RUN_LIMIT_S       the refresh time limit in seconds (the app's own minimum is 5 minutes)
    AR_WORLD_HANG_AT           a progress stage ("cluster", "brief", ...) at which the worker hangs in a
                               blocking call that ignores cancellation (a stuck driver or DNS call)
    AR_WORLD_WATCHDOG_S        overrides the worker's hard watchdog limit (seconds)
    AR_WORLD_ADVANCE_HOUR      "1": simulate a later same-day collection for repeat-publication tests
    AR_WORLD_BRIEF_CALLS       model calls that succeed in the brief pass before it disconnects
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx

# one-line synthetic summaries would all be held back by the pre-publish quality gates (tests/test_gates.py has its own)
os.environ.setdefault("AGENT_REACH_GATES_ENABLED", "0")


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else None


class _SlowDyingModel:
    """Wraps the fake model: optional delay per call, and connection failures after N calls."""

    def __init__(self, inner, delay: float, dies_after: float | None) -> None:
        self.inner, self.delay, self.dies_after, self.n = inner, delay, dies_after, 0

    async def _gate(self) -> None:
        self.n += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.dies_after is not None and self.n > self.dies_after:
            raise httpx.ConnectError("[WinError 10061] No connection could be made (fake model stopped)")

    async def list(self):
        await self._gate()
        return await self.inner.list()

    async def embed(self, *a, **k):
        await self._gate()
        return await self.inner.embed(*a, **k)

    async def chat(self, *a, **k):
        await self._gate()
        return await self.inner.chat(*a, **k)


def install() -> None:
    from agent_reach.daily import refresh as R
    from agent_reach.pipeline import clusterer as C
    from tests import daily_fakes as F

    net = F.FakeNet()
    model = _SlowDyingModel(F.FakeDailyModel(), _env_float("AR_WORLD_MODEL_DELAY_S") or 0.0,
                            _env_float("AR_WORLD_MODEL_DIES_AFTER"))
    httpx.AsyncClient = net.client_class()
    C.SemanticClusterer._get_client = lambda self: model

    async def public_dns(host, port):
        return "93.184.216.34"

    import agent_reach.pipeline.enricher as EN

    EN._resolve_public = public_dns
    down = os.environ.get("AR_WORLD_MODEL_DOWN") == "1"
    R.default_ollama_probe = lambda prefs: F.OllamaDown() if down else F.OllamaUp()
    if os.environ.get('AR_WORLD_ADVANCE_HOUR') == '1':
        from datetime import datetime, timedelta, timezone
        from agent_reach.daily.state import load_state
        from agent_reach.daily.store import EditionStore
        real_refresh = R.refresh

        from agent_reach.daily.timeutil import CENTRAL

        def refresh(paths, **kwargs):
            state, _ = load_state(paths)
            when = datetime.now(timezone.utc)
            local = when.astimezone(CENTRAL)
            if local.hour >= 20:
                # tests make up to three hourly revisions of one date: after 8 pm Central the later ones would
                # cross midnight into a new edition date, so the simulated day starts at noon instead
                when = local.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
            if state.last_success_utc is not None:
                when = max(when, state.last_success_utc + timedelta(hours=1))
            else:
                previous = EditionStore(paths).load_latest().edition
                if previous is not None:
                    when = max(when, previous.generation_completed_utc + timedelta(hours=1))
            kwargs.setdefault('now_fn', lambda: when)
            return real_refresh(paths, **kwargs)

        R.refresh = refresh
    brief_calls = _env_float('AR_WORLD_BRIEF_CALLS')
    if brief_calls is not None:
        real_progress = R.ProgressWriter.__call__

        def progress(self, stage, message):
            if stage == 'brief':
                model.dies_after = model.n + brief_calls
            real_progress(self, stage, message)

        R.ProgressWriter.__call__ = progress
    limit = _env_float("AR_WORLD_RUN_LIMIT_S")
    if limit:
        real_load = R.load_prefs

        def load_prefs(paths, **kw):
            prefs, warn = real_load(paths, **kw)
            return prefs.model_copy(update={"max_run_minutes": limit / 60}), warn

        R.load_prefs = load_prefs
    watchdog = _env_float("AR_WORLD_WATCHDOG_S")
    if watchdog:
        R.watchdog_limit_s = lambda prefs: watchdog
    hang_at = os.environ.get("AR_WORLD_HANG_AT", "").strip()
    if hang_at:
        real_call = R.ProgressWriter.__call__

        def call(self, stage, message):
            real_call(self, stage, message)
            if stage == hang_at:
                time.sleep(10 ** 6)  # blocks the event loop: cancellation can never reach it

        R.ProgressWriter.__call__ = call


def world_settings_entries() -> list[str]:
    from tests import daily_fakes as F

    return F.feed_settings_entries()


def prepare(data_dir) -> None:
    """Settings for the fake world in ``data_dir`` (the three fake channels, podcast off)."""
    from agent_reach.daily.paths import DataPaths
    from agent_reach.daily.prefs import DailyPrefs, save_prefs

    paths = DataPaths.resolve(data_dir).ensure()
    save_prefs(paths, DailyPrefs(enabled_sources=["news_rss", "google_news", "hackernews"],
                                 news_rss_feeds=world_settings_entries(), podcast_auto=False))


def world_command(args: list[str]) -> list[str]:
    """The window's worker command (``... -m agent_reach.daily <args>``) pointed at this fake world."""
    if "agent_reach.daily" in args:
        args = args[args.index("agent_reach.daily") + 1:]
    return [sys.executable, "-m", "tests.daily_world", *args]


def world_spawner(env: dict[str, str] | None = None):
    """A spawner for ``AppController``: starts the fake-world worker as a real background process."""
    import subprocess

    from agent_reach.daily.paths import PROJECT_ROOT

    def spawn(args: list[str]):
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW, like the app
        return subprocess.Popen(world_command(args), cwd=str(PROJECT_ROOT), env={**os.environ, **(env or {})},
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=flags)

    return spawn


def main(argv: list[str] | None = None) -> int:
    install()
    from agent_reach.daily.__main__ import main as daily_main

    return daily_main(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
