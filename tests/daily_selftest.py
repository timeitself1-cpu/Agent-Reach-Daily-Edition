"""Agent Reach Daily self-test for the reader's own PC: real Windows, real Ollama, real news.

    .\\.venv\\Scripts\\python.exe -m tests.daily_selftest            (or Test-AgentReachDaily.ps1)

Everything runs in a NEW scratch data folder under %TEMP% (its name contains spaces on purpose). The real
data folder (%LOCALAPPDATA%\\AgentReachDaily) is only read: its settings.json is copied so the test refresh
uses your own feeds, and ``--status`` of it is recorded. Nothing there is written, moved or deleted, and no
process other than the test's own refresh workers is ever stopped.

Parts (each is PASS / FAIL / SKIP / INFO in report.txt; a part that breaks is a FAIL, never a crash):

1. environment   Python, packages, Tk, paths with spaces, the project registered in .venv
2. launchers     the Desktop / Start menu shortcuts, AgentReachDaily.cmd and AgentReachDaily.pyw each open
                 the window from another folder (the window reports itself and closes after 3 s)
3. ollama        the real Ollama: running, a missing model, nothing listening, another program listening
4. offline suite the full pytest suite on this PC (window tests on the real display, real Windows file
                 locks, process kill and cancel) - needs requirements-dev.txt
5. real refresh  cancel right after starting; cancel halfway; one full refresh started the way the Refresh
                 button starts it (pythonw worker), with its stage timeline, the HTML export, the podcast,
                 the edition as text and an automatic review of it; then a restarted window
6. model drop    a refresh whose connection to Ollama is cut halfway (a local relay that is closed)
7. repeat use    a second refresh after changing settings (revision 2, what changed, coherent state)
8. by hand       (--interactive) you quit Ollama when asked: the app's own start of Ollama and a refresh
                 while it is gone

Results: a folder and a zip on the Desktop (AgentReach-selftest-<time>.zip) to send back. The zip holds
the report, the logs of the scratch folder, the edition (JSON, HTML, text), the podcast transcript (not the
audio) and the test suite output. It contains no settings values except feed names.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_reach.daily import __version__  # noqa: E402
from agent_reach.daily.app import AppController  # noqa: E402
from agent_reach.daily.paths import PROJECT_ROOT, DataPaths, default_root  # noqa: E402
from agent_reach.daily.prefs import DailyPrefs, load_prefs, save_prefs  # noqa: E402
from agent_reach.daily.state import load_state  # noqa: E402
from agent_reach.daily.store import EditionStore  # noqa: E402

WIN = sys.platform == "win32"
#: --world: a dry run of the harness itself in the offline fake world (tests/daily_world.py), no Ollama/news
WORLD: dict[str, str] | None = None


def controller(paths: DataPaths, **env: object) -> AppController:
    """The window's controller; its Refresh starts the real worker (or the fake-world worker with --world)."""
    if WORLD is None:
        return AppController(paths)
    from tests.daily_world import world_spawner

    return AppController(paths, spawner=world_spawner({**WORLD, **{k: str(v) for k, v in env.items()}}))


# ====================================================================== report
@dataclass
class Check:
    part: str
    name: str
    status: str  # PASS | FAIL | SKIP | INFO
    detail: str = ""
    seconds: float = 0.0


@dataclass
class Report:
    out: Path
    checks: list[Check] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    running: str = ""  # the part in progress: a run that stops early still says where (report.txt is rewritten)
    finished: bool = False

    def add(self, part: str, name: str, status: str, detail: str = "", seconds: float = 0.0) -> None:
        self.checks.append(Check(part, name, status, detail.strip(), round(seconds, 1)))
        mark = {"PASS": "ok  ", "FAIL": "FAIL", "SKIP": "skip", "INFO": "info"}[status]
        first = detail.strip().splitlines()[0][:110] if detail.strip() else ""
        print(f"  [{mark}] {name}" + (f": {first}" if first else ""), flush=True)
        self.write()

    def check(self, part: str, name: str, ok: bool, detail: str = "", seconds: float = 0.0) -> bool:
        self.add(part, name, "PASS" if ok else "FAIL", detail, seconds)
        return ok

    def write(self) -> None:
        counts = {s: sum(c.status == s for c in self.checks) for s in ("PASS", "FAIL", "SKIP", "INFO")}
        lines = [f"Agent Reach Daily {__version__} self-test", f"Finished {datetime.now():%Y-%m-%d %H:%M}",
                 f"Total time {(time.time() - self.started) / 60:.0f} min", "Result: " + ", ".join(
                     f"{n} {s}" for s, n in counts.items()), ""]
        if not self.finished:
            lines[1] = f"NOT FINISHED - last written {datetime.now():%Y-%m-%d %H:%M}, during part: {self.running or '-'}"
        part = None
        for c in self.checks:
            if c.part != part:
                part = c.part
                lines += ["", f"== {part}"]
            lines.append(f"[{c.status}] {c.name}" + (f"  ({c.seconds:.0f} s)" if c.seconds >= 1 else ""))
            lines += [f"       {line}" for line in c.detail.splitlines()]
        (self.out / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (self.out / "report.json").write_text(json.dumps([asdict(c) for c in self.checks], indent=2), encoding="utf-8")


def guarded(report: Report, part: str):
    """Run one part; an exception inside it is a FAIL with its traceback, never the end of the test."""
    def wrap(fn):
        def run(*a, **k):
            print(f"\n== {part}", flush=True)
            report.running = part
            report.write()
            started = time.monotonic()
            try:
                return fn(*a, **k)
            except Exception:  # noqa: BLE001
                report.add(part, "part stopped by an unexpected error", "FAIL", traceback.format_exc(),
                           time.monotonic() - started)
                return None
        return run
    return wrap


# ====================================================================== helpers
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def scratch_paths(base: Path, name: str, prefs: DailyPrefs) -> DataPaths:
    paths = DataPaths.resolve(base / name).ensure()
    save_prefs(paths, prefs)
    return paths


def wait_activity(ctrl: AppController, *, stage: str | None = None, timeout: float = 600.0,
                  timeline: list | None = None) -> bool:
    """Poll like the window does (it polls every second while a refresh runs). True when reached."""
    end, last = time.monotonic() + timeout, None
    t0 = time.monotonic()
    while time.monotonic() < end:
        act = ctrl.activity()
        if timeline is not None and act.running and (act.stage, act.message) != last:
            last = (act.stage, act.message)
            timeline.append((round(time.monotonic() - t0, 1), act.stage, act.message))
        if stage is None and not act.running:
            return True
        if stage is not None and act.running and act.stage == stage:
            return True
        if stage is not None and not act.running and ctrl.child is None:
            return False  # ended before reaching the stage
        time.sleep(0.5)
    return False


def lock_free(paths: DataPaths) -> bool:
    from agent_reach.daily.lock import LockBusy, RefreshLock

    lock = RefreshLock(paths.lock_file, None)
    try:
        lock.acquire()
    except LockBusy:
        return False
    lock.release()
    return True


def snapshot_text(paths: DataPaths) -> str:
    snap = AppController(paths).snapshot()
    banners = "\n".join(f"banner ({b.kind}): {b.text}" for b in snap.banners)
    return f"window status: {snap.status}\nrunning: {snap.activity.running}\n{banners}".strip()


class HttpJunk(threading.Thread):
    """Another program listening on a port: answers every request with a web page."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = b"<html><body>Router admin page</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_POST = do_GET  # noqa: N815

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]

    def run(self) -> None:
        self.server.serve_forever()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class Relay(threading.Thread):
    """A local TCP relay to the real Ollama that can be cut, as if Ollama quit in the middle of a refresh."""

    def __init__(self, host: str, port: int) -> None:
        super().__init__(daemon=True)
        self.target = (host, port)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(32)
        self.port = self.sock.getsockname()[1]
        self.conns: list[socket.socket] = []
        self.cut_done = False
        self.requests = 0

    def run(self) -> None:
        while not self.cut_done:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            try:
                upstream = socket.create_connection(self.target, timeout=10)
                upstream.settimeout(None)
            except OSError:
                client.close()
                continue
            self.requests += 1
            self.conns += [client, upstream]
            for a, b in ((client, upstream), (upstream, client)):
                threading.Thread(target=self._pipe, args=(a, b), daemon=True).start()

    @staticmethod
    def _pipe(a: socket.socket, b: socket.socket) -> None:
        try:
            while True:
                data = a.recv(65536)
                if not data:
                    break
                b.sendall(data)
        except OSError:
            pass
        finally:
            for s in (a, b):
                with contextlib.suppress(OSError):
                    s.close()

    def cut(self) -> None:
        self.cut_done = True
        for s in [self.sock, *self.conns]:
            with contextlib.suppress(OSError):
                s.close()


def ollama_target(host: str) -> tuple[str, int]:
    from urllib.parse import urlsplit

    parts = urlsplit(host)
    return parts.hostname or "127.0.0.1", parts.port or 11434


# ====================================================================== the edition, read for a human
def edition_text(ed) -> str:
    from agent_reach.daily.edition import category_sections, top_stories
    from agent_reach.daily.timeutil import format_central

    out = [f"Edition {ed.edition_date} revision {ed.revision} - run {ed.run_id}",
           f"generated {format_central(ed.generation_completed_utc)}; summaries: {ed.model.summaries}; "
           f"pipeline: {ed.model.pipeline_mode}",
           f"label batches {ed.model.label_calls} (failed {ed.model.label_calls_failed}); brief batches "
           f"{ed.model.brief_calls} (failed {ed.model.brief_calls_failed})", "", "NOTES"]
    out += [f"- {n}" for n in [*ed.coverage.warnings, *ed.notes]]
    groups = [("TOP STORIES", top_stories(ed))] + [(c.upper(), s) for c, s in category_sections(ed)]
    for title, stories in groups:
        out += ["", f"==== {title} ({len(stories)})"]
        for s in stories:
            out += ["", f"#{s.rank} [{s.category.value}] {s.headline}",
                    f"   relevance {s.relevance_score}, {s.raw_item_count} signals, labels {s.labels}, "
                    f"strength {s.evidence_strength.level if s.evidence_strength else '-'}"]
            out += [f"   | {x}" for x in s.sentences]
            if s.why_it_matters:
                out.append(f"   WHY: {s.why_it_matters}")
            for e in s.evidence:
                when = format_central(e.published_at_utc) if e.published_at_utc else "time not stated"
                out.append(f"   - {e.source_name} / {e.publisher or '-'}: {e.title} ({when})")
                out.append(f"     {e.url or '(no link)'}")
    return "\n".join(out) + "\n"


def review_edition(ed, prefs: DailyPrefs) -> list[str]:
    """Things a careful reader would notice. Each is a candidate for a regression fixture, not a verdict."""
    import re

    from agent_reach.daily.edition import category_sections, looks_english, same_topic, safe_url, top_stories
    from agent_reach.pipeline.cleaner import dedupe_key, significant_tokens

    found: list[str] = []
    stories = ed.stories
    toks = {s.rank: significant_tokens(dedupe_key(s.headline)) for s in stories}
    for i, a in enumerate(stories):
        for b in stories[i + 1:]:
            shared = toks[a.rank] & toks[b.rank]
            jac = len(shared) / max(1, len(toks[a.rank] | toks[b.rank]))
            # 'Lionel Messi Bids Farewell to Argentina Fans ...' / 'Messi Signs Off in Tears After One Last Argentina
            # Master Class' (October 7) shared two names and nothing else
            names = {w for w in shared if any(w.capitalize() in x for x in (a.headline, b.headline))}
            if same_topic(a, b) or jac >= 0.4 or len(names) >= 2:
                found.append(f"possible duplicate: #{a.rank} '{a.headline}' / #{b.rank} '{b.headline}'")
    seen_sentences: dict[str, int] = {}
    for s in stories:
        h = s.headline
        if len(h.split()) > 18 or h.rstrip().endswith((":", "-", ",")) or (h.isupper() and len(h) > 12):
            found.append(f"#{s.rank} headline shape: '{h}'")
        for text in [h, *s.sentences, s.why_it_matters or ""]:
            if re.search(r"https?://|\bwww\.|\[|INSUFFICIENT|�|â€|Ã", text):
                found.append(f"#{s.rank} odd characters or link in text: '{text[:120]}'")
            if re.search(r"\bnot (?:specified|mentioned|provided|stated)\b|\bthe (?:provided |given )?(?:text|"
                         r"excerpts?|evidence)\b", text, re.IGNORECASE):
                found.append(f"#{s.rank} the model talks about its input: '{text[:140]}'")
        evidence = " ".join(e.title + " " + (e.excerpt or "") for e in s.evidence).lower()
        for x in s.sentences:
            last = re.findall(r"[A-Za-z]+", x)[-1:] or [""]
            if last[0][:1].isupper() and len(last[0]) <= 5 and not re.search(rf"\b{last[0].lower()}\b", evidence):
                found.append(f"#{s.rank} sentence may end inside a word ('{last[0]}'): '{x[-80:]}'")
            if len(x.split()) < 4 or not x.rstrip().endswith((".", "!", "?", "\"", "”", "'")):
                found.append(f"#{s.rank} short or unfinished sentence: '{x}'")
            if not looks_english(x):
                found.append(f"#{s.rank} not English: '{x[:120]}'")
            key = x.lower()
            if key in seen_sentences and seen_sentences[key] != s.rank:
                found.append(f"#{s.rank} repeats a sentence of #{seen_sentences[key]}: '{x[:120]}'")
            seen_sentences.setdefault(key, s.rank)
        if s.why_it_matters and s.why_it_matters.lower() in {x.lower() for x in s.sentences}:
            found.append(f"#{s.rank} 'why it matters' repeats the summary")
        for e in s.evidence:
            if e.url and safe_url(e.url) is None:
                found.append(f"#{s.rank} malformed link: {e.url[:120]}")
            if e.published_at_utc and e.published_at_utc > ed.generation_completed_utc:
                found.append(f"#{s.rank} publication time after the edition: {e.published_at_utc}")
        newest = max((e.published_at_utc for e in s.evidence if e.published_at_utc), default=None)
        if newest is not None:
            age = (ed.generation_completed_utc - newest).total_seconds() / 3600
            if age > prefs.max_story_age_hours:
                found.append(f"#{s.rank} newest report {age:.0f} h old: '{s.headline}'")
        else:
            found.append(f"#{s.rank} no stated publication time at all: '{s.headline}'")
    if not top_stories(ed):
        found.append("Top Stories is empty")
    for cat, items in category_sections(ed):
        if len(items) == 1:
            found.append(f"section {cat} has a single story")
    return found


# ====================================================================== parts
def part_environment(report: Report, args) -> None:
    P = "1. environment"
    report.add(P, "versions", "INFO", f"Agent Reach Daily {__version__}\nPython {sys.version.split()[0]} at "
                                       f"{sys.executable}\n{platform.platform()}\nproject {PROJECT_ROOT}")
    report.check(P, "project path has spaces (as on your PC)", True, str(PROJECT_ROOT) if " " in str(PROJECT_ROOT)
                 else f"{PROJECT_ROOT} (no space; the scratch folders below have spaces)")
    try:
        import tkinter

        root = tkinter.Tk()
        scale = root.winfo_fpixels("1i") / 96.0
        size = f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}"
        root.destroy()
        report.check(P, "Tk opens a window", True, f"screen {size}, display scaling {scale:.0%}")
    except Exception as exc:  # noqa: BLE001
        report.check(P, "Tk opens a window", False, f"{type(exc).__name__}: {exc}")
    if WIN:
        venv = PROJECT_ROOT / ".venv" / "Scripts"
        report.check(P, "pythonw.exe in .venv", (venv / "pythonw.exe").exists(), str(venv / "pythonw.exe"))
        python = venv / "python.exe"
        if python.exists():
            out = subprocess.run([str(python), "-m", "agent_reach.daily", "--version"], cwd=tempfile.gettempdir(),
                                 capture_output=True, text=True, timeout=120)
            report.check(P, "'python -m agent_reach.daily' works from another folder",
                         out.returncode == 0, (out.stdout + out.stderr).strip()[:300]
                         + ("" if out.returncode == 0 else "\nRun Setup-AgentReachDaily.ps1 again (rc11 registers "
                                                          "the project in .venv)."))
    real = default_root()
    report.add(P, "your real data folder (read only)", "INFO", f"{real}\nexists: {real.exists()}")
    if real.exists():
        from agent_reach.daily.refresh import status_payload

        status = status_payload(DataPaths.resolve(real))
        (report.out / "real-data-status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
        report.add(P, "your real data folder status", "INFO",
                   f"latest edition {status['latest_edition']} rev {status['latest_revision']}; last attempt "
                   f"{status['last_attempt_outcome']}; failures in a row {status['consecutive_failures']}; "
                   f"damaged files {len(status['corrupt_files'])}")
        copied = copy_history(DataPaths.resolve(real), report.out / "history")
        from agent_reach.daily.registry import registry_file

        events = registry_file(DataPaths.resolve(real))
        if events.exists():  # the event registry's decisions, to check against the answer key
            (report.out / "history").mkdir(parents=True, exist_ok=True)
            shutil.copy2(events, report.out / "history" / "events.json")
        report.add(P, "your recent editions (copied for the event-tracking answer key)", "INFO",
                   f"{len(copied)} dated edition(s): {', '.join(copied) or 'none'}")


#: Days of real editions the self-test brings back. Each date keeps only its last revision; these are the
#: day-to-day material for event identity across editions (PLAN Phase 2.1b: an answer key of 7+ days).
HISTORY_DAYS = 14


def copy_history(paths: DataPaths, target: Path, days: int = HISTORY_DAYS) -> list[str]:
    """Copy the newest ``days`` dated editions (read only; damaged files are skipped, never touched)."""
    from agent_reach.daily.store import EditionStore

    store = EditionStore(paths)
    copied = []
    for d in sorted(store.list_dates(), reverse=True):
        if len(copied) >= days:
            break
        src = store.edition_path(d)
        try:
            data = src.read_bytes()
            json.loads(data.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        target.mkdir(parents=True, exist_ok=True)
        (target / src.name).write_bytes(data)
        copied.append(d.isoformat())
    return sorted(copied)


def file_association(ext: str) -> str:
    """What Explorer runs for a file type (assoc + ftype, and the user's own choice in the registry)."""
    out = []
    for cmd in (["cmd.exe", "/c", "assoc", ext],):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
            line = (res.stdout or res.stderr).strip()
            out.append(line)
            if "=" in line:
                res = subprocess.run(["cmd.exe", "/c", "ftype", line.split("=", 1)[1]], capture_output=True,
                                     text=True, timeout=20, stdin=subprocess.DEVNULL)
                out.append((res.stdout or res.stderr).strip())
        except (OSError, subprocess.SubprocessError) as exc:
            out.append(f"{type(exc).__name__}: {exc}")
    try:
        import winreg

        key = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            out.append("your choice: " + str(winreg.QueryValueEx(k, "ProgId")[0]))
    except (ImportError, OSError):
        pass
    return "; ".join(x for x in out if x) or "unknown"


def launch_held_note(held_s: float) -> str:
    """Windows held the double-click itself (October 7, 18:16: 250 s for AgentReachDaily.cmd, with the window
    never asked to open): almost always the 'Open File - Security Warning' dialog for a file from a downloaded zip."""
    if held_s < 20:
        return ""
    return (f"\nWindows held the launch for {held_s:.0f} s before starting it. That is usually the 'Open File - "
            "Security Warning' dialog Windows shows for files from a downloaded zip. Run "
            "Setup-AgentReachDaily.ps1 again: it clears that mark from the project's files.")


def part_launchers(report: Report, args, base: Path) -> None:
    P = "2. launchers"
    if not WIN:
        report.add(P, "launchers", "SKIP", "Windows only")
        return
    home = base / "launcher data"
    targets = []
    for folder in ("Desktop", "Programs"):
        try:
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            csidl = {"Desktop": 0x10, "Programs": 0x02}[folder]
            ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
            lnk = Path(buf.value) / "Agent Reach.lnk"
            targets.append((f"{folder} shortcut", lnk))
        except Exception:  # noqa: BLE001
            pass
    targets += [("AgentReachDaily.cmd", PROJECT_ROOT / "AgentReachDaily.cmd"),
                ("AgentReachDaily.pyw (double-click)", PROJECT_ROOT / "AgentReachDaily.pyw")]
    for name, target in targets:
        if not target.exists():
            report.add(P, name, "SKIP", f"not found: {target} (Setup creates the shortcuts)")
            continue
        result = base / f"smoke-{name.split()[0].replace('.', '-')}.json"
        started = time.monotonic()
        # a double-click in Explorer: ShellExecute with the file's own handler, from another folder. (rc11's
        # first harness ran 'cmd /c start' with captured output: the window inherited the pipe and the
        # harness waited on it for 60 s.) The launched program inherits this process's environment.
        saved = {k: os.environ.get(k) for k in ("AGENT_REACH_DAILY_SMOKE_FILE", "AGENT_REACH_DAILY_HOME")}
        os.environ.update(AGENT_REACH_DAILY_SMOKE_FILE=str(result), AGENT_REACH_DAILY_HOME=str(home))
        try:
            os.startfile(str(target), cwd=tempfile.gettempdir())  # type: ignore[attr-defined]
            held = time.monotonic() - started
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        while not result.exists() and time.monotonic() - started < 90:
            time.sleep(0.5)
        if not result.exists():
            detail = "the window did not report within 90 s"
            detail += launch_held_note(held)
            if target.suffix.lower() == ".pyw":
                detail += "\n.pyw files open with: " + file_association(".pyw")
            report.check(P, name, False, detail, time.monotonic() - started)
            continue
        time.sleep(0.5)
        info = json.loads(result.read_text(encoding="utf-8"))
        ok = info.get("ok") and Path(info.get("project_root", "")) == PROJECT_ROOT and ".venv" in info.get("python", "")
        report.check(P, f"{name} opens the window", bool(ok),
                     f"python {info.get('python')}\nwindow '{info.get('title')}', status '{info.get('status')}', "
                     f"size {info.get('geometry')}, scaling {info.get('scale')}\n{info.get('error') or ''}",
                     time.monotonic() - started)
    if (home / "logs").exists():
        shutil.copytree(home / "logs", report.out / "launcher-logs", dirs_exist_ok=True)


def expected_fallback(prefs: DailyPrefs, used: str | None, platform: str | None = None) -> bool:
    """The refresh grouped stories with a fallback model because Ollama cannot run the configured one on this
    computer (EmbeddingGemma 2 on Windows): information, not a failure the user could fix."""
    from agent_reach.daily.prereqs import mac_only_in_ollama

    base = (used or "").split(":")[0]
    return (bool(used) and used != prefs.embed_model and mac_only_in_ollama(prefs.embed_model, platform)
            and base in {m.split(":")[0] for m in prefs.embed_fallback_models})


def part_ollama(report: Report, args, base: Path, prefs: DailyPrefs) -> bool:
    """Returns whether the real Ollama is ready (the real-refresh parts need it)."""
    from agent_reach.daily.prereqs import check_ollama, check_prefs, mac_only_in_ollama

    P = "3. ollama"
    st = check_ollama(args.ollama_host, [prefs.ollama_model],
                      grouping=[prefs.embed_model, *prefs.embed_fallback_models])
    ready = st.ready
    if st.reachable and st.grouping_missing and st.grouping_fallback and mac_only_in_ollama(prefs.embed_model):
        # October 7: Ollama runs EmbeddingGemma 2 on Macs only so far; nothing the user can fix, so not a FAIL
        report.add(P, f"grouping model {prefs.embed_model}", "INFO",
                   f"not installed: Ollama {st.version or '(version unknown)'} can run it only on Macs so far. "
                   f"Refreshes group stories with {st.grouping_fallback}.")
    elif st.reachable and st.grouping_missing:
        # rc12: without EmbeddingGemma the refresh still works on the fallback model; say so, then test on
        report.add(P, f"grouping model {prefs.embed_model}", "FAIL",
                   f"missing (Ollama {st.version or 'version unknown'}): run 'ollama pull {prefs.embed_model}'; if "
                   f"that fails, update Ollama first. Refreshes group stories with "
                   f"{st.grouping_fallback or 'shared words'} until then.")
    report.check(P, "Ollama running with the chat model", ready,
                 f"{st.describe()}\nversion {st.version}; models: {', '.join(st.models) or 'none'}")
    st_prefs = check_prefs(prefs)
    report.check(P, "a missing grouping model never blocks a refresh", st_prefs.ready == st.ready, st_prefs.describe())
    st2 = check_ollama(args.ollama_host, ["agent-reach-selftest-missing-model"])
    report.check(P, "a missing model is named in plain words", st2.reachable and bool(st2.missing)
                 and "ollama pull agent-reach-selftest-missing-model" in st2.describe(), st2.describe())
    closed = f"http://127.0.0.1:{free_port()}"
    st3 = check_ollama(closed, [prefs.ollama_model])
    report.check(P, "nothing listening: 'not running' (simulated on a free port; your Ollama keeps running)",
                 not st3.reachable and "is not running" in st3.describe(), st3.describe())
    junk = HttpJunk()
    junk.start()
    try:
        st4 = check_ollama(f"http://127.0.0.1:{junk.port}", [prefs.ollama_model])
        report.check(P, "another program on the port: no crash, not treated as Ollama",
                     not st4.reachable and "Another program answers" in st4.describe(), st4.describe())
        # the whole refresh against it: fails fast before fetching any news, with a plain message
        paths = scratch_paths(base, "other program on the port", prefs.model_copy(update={
            "ollama_host": f"http://127.0.0.1:{junk.port}", "start_ollama_if_down": False}))
        out = run_worker(paths, timeout=180)
        report.check(P, "a refresh against it stops at once with a plain message",
                     out.returncode == 31 and "Traceback" not in out.stdout, out.stdout.strip()[-400:])
        report.add(P, "what the window shows then", "INFO", snapshot_text(paths))
    finally:
        junk.stop()
    paths = scratch_paths(base, "missing model", prefs.model_copy(update={"ollama_model": "agent-reach-selftest-missing"}))
    out = run_worker(paths, timeout=180)
    report.check(P, "a refresh with a missing model stops at once", out.returncode == 31 and "ollama pull" in out.stdout,
                 out.stdout.strip()[-400:])
    report.add(P, "what the window shows then", "INFO", snapshot_text(paths))
    return ready


def run_worker(paths: DataPaths, *extra: str, timeout: float = 3600) -> subprocess.CompletedProcess:
    """The worker command exactly as the scheduled task runs it, but in the console Python (output visible)."""
    args = [sys.executable, "-m", "agent_reach.daily", "--refresh-now", "--trigger", "manual",
            "--data-dir", str(paths.root), *extra]
    env = None
    if WORLD is not None:
        from tests.daily_world import world_command

        args, env = world_command(args), {**os.environ, **WORLD}
    return subprocess.run(args, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=timeout, env=env)


def part_pytest(report: Report, args) -> None:
    P = "4. offline test suite"
    import importlib.util

    if importlib.util.find_spec("pytest") is None:
        report.add(P, "pytest", "SKIP", "pytest is not installed: .venv\\Scripts\\python.exe -m pip install -r "
                                        "requirements-dev.txt (Test-AgentReachDaily.ps1 does this)")
        return
    started = time.monotonic()
    # a test file that does not load (e.g. a file of another version left in the folder) must not stop the rest
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "-rfEs",
                          "--continue-on-collection-errors"],
                         cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=3600)
    (report.out / "pytest-output.txt").write_text(out.stdout + "\n" + out.stderr, encoding="utf-8")
    import re

    broken = sorted(set(re.findall(r"ERROR collecting (\S+)", out.stdout)))
    if broken:
        report.add(P, "test files that do not load (not part of this release?)", "FAIL",
                   "\n".join(broken) + "\nThese files import code this release does not have. If they come from other "
                   "work in this folder, keep that work safe before deleting them.")
    lines = out.stdout.splitlines()
    tail = "\n".join(line for line in lines[-25:] if line.strip())
    # the FAILED lines need -rf, and the count line is the backstop: with only -rs the October 7 self-test showed
    # PASS for '1 failed, 449 passed ... 2 errors' (the 2 errors were the stray files above)
    failed = [line for line in lines if line.startswith("FAILED ")]
    counted = re.search(r"\b(\d+) failed\b", lines[-1] if lines else "")
    ok = out.returncode == 0 or (bool(broken) and not failed and not counted)
    report.check(P, "full offline suite (window, Windows locks, process kill/cancel, pipeline)", ok,
                 "\n".join(failed[:10] + [tail]), time.monotonic() - started)
    gui_skips = [line for line in lines if line.startswith("SKIPPED") and "test_daily_gui" in line]
    if gui_skips:
        report.add(P, "window tests ran inside the test suite", "FAIL",
                   "\n".join(gui_skips)[:800] + "\nTk could not start inside the test run (the window itself is "
                   "checked again in part 2). If this repeats, send the zip.")


def part_refresh_ux(report: Report, args, base: Path, prefs: DailyPrefs) -> None:
    P = "5. real refresh: cancel"
    paths = scratch_paths(base, "cancel test", prefs.model_copy(update={"podcast_auto": False}))
    ctrl = controller(paths, AR_WORLD_MODEL_DELAY_S=2)
    started = time.monotonic()
    ctrl.start_refresh(manual=True)
    time.sleep(0.5)
    stopped = ctrl.cancel_refresh()
    report.check(P, "cancel right after starting", stopped and not ctrl.activity().running and lock_free(paths),
                 f"stopped in {time.monotonic() - started:.1f} s\n{snapshot_text(paths)}", time.monotonic() - started)
    ctrl = controller(paths, AR_WORLD_MODEL_DELAY_S=2)
    ctrl.start_refresh(manual=True)
    reached = wait_activity(ctrl, stage="cluster", timeout=900)
    if not reached:
        report.check(P, "cancel halfway", False, "the refresh never reached the grouping step\n" + snapshot_text(paths))
        wait_activity(ctrl, timeout=args.limit_s)
        return
    t = time.monotonic()
    stopped = ctrl.cancel_refresh()
    st = load_state(paths)[0]
    report.check(P, "cancel halfway (while the model groups stories)",
                 stopped and not ctrl.activity().running and lock_free(paths) and st.last_attempt_outcome == "cancelled"
                 and st.consecutive_failures == 0,
                 f"stopped in {time.monotonic() - t:.1f} s; outcome {st.last_attempt_outcome}\n{snapshot_text(paths)}")
    snap = AppController(paths).snapshot()  # a restarted window
    report.check(P, "restarted window after cancel: not refreshing, Refresh available", not snap.activity.running,
                 snap.status)


def part_full_refresh(report: Report, args, base: Path, prefs: DailyPrefs) -> DataPaths | None:
    from agent_reach.daily.render_html import render_edition_html

    P = "5. real refresh: full"
    paths = scratch_paths(base, "real refresh", prefs)
    ctrl = controller(paths)  # the same call the Refresh button makes: a pythonw worker in the background
    timeline: list = []
    started = time.monotonic()
    report.check(P, "Refresh starts a background worker", ctrl.start_refresh(manual=True),
                 " ".join(ctrl.worker_args(manual=True)))
    finished = wait_activity(ctrl, timeout=args.limit_s, timeline=timeline)
    took = time.monotonic() - started
    report.add(P, "progress the window showed", "INFO",
               "\n".join(f"{t:7.1f} s  [{stage}] {msg}" for t, stage, msg in timeline))
    st = load_state(paths)[0]
    report.check(P, "refresh finished and published", finished and st.last_attempt_outcome == "success",
                 f"{st.last_attempt_outcome}: {st.last_attempt_message}", took)
    for name in ("refresh.log", "scheduler.log", "gui.log"):
        if (paths.logs_dir / name).exists():
            shutil.copy2(paths.logs_dir / name, report.out / f"real-refresh-{name}")
    if paths.diagnostics_dir.exists():
        for f in paths.diagnostics_dir.glob("*.json"):
            shutil.copy2(f, report.out / f"real-refresh-diagnostics-{f.name}")
        for f in (paths.diagnostics_dir / "semantic").glob("semantic-*.json"):  # rc12: every gate decision
            shutil.copy2(f, report.out / f"real-refresh-{f.name}")
    ed = EditionStore(paths).load_latest().edition
    if ed is None:
        report.add(P, "edition", "FAIL", snapshot_text(paths))
        return None
    import re

    log_text = (paths.logs_dir / "refresh.log").read_text(encoding="utf-8", errors="replace") \
        if (paths.logs_dir / "refresh.log").exists() else ""
    stages = list(dict.fromkeys(re.findall(r"progress \[(\w+)\]", log_text)))  # in order, from the worker's log
    report.check(P, "every stage ran (ingest, events, scoring, edition, publish)",
                 {"ingest", "cluster", "score", "edition", "publish"} <= set(stages), " -> ".join(stages))
    (report.out / "edition.json").write_text(ed.model_dump_json(indent=2), encoding="utf-8")
    (report.out / "edition.txt").write_text(edition_text(ed), encoding="utf-8")
    page = render_edition_html(ed)
    (report.out / "edition.html").write_text(page, encoding="utf-8")
    report.check(P, "HTML export", "<script" not in page.lower() and ed.stories[0].headline.split()[0] in page,
                 f"{len(page) // 1024} KB, {len(ed.stories)} stories")
    report.add(P, "edition", "INFO",
               f"{len(ed.stories)} stories, {len(ed.top_ranks)} in Top Stories; summaries {ed.model.summaries}; "
               f"{sum(1 for s in ed.stories if s.why_it_matters)} 'why it matters'; label batches "
               f"{ed.model.label_calls} (failed {ed.model.label_calls_failed})\nnotes: " + " | ".join(ed.notes))
    g = ed.model.grouping
    grouping_detail = (f"used: {ed.model.embed_model_used or 'none'}; {g.get('fallback') or 'no fallback'}; "
                       f"{g.get('candidate_pairs', 0)} candidate pairs, {g.get('accepted_pairs', 0)} accepted, "
                       f"{g.get('refused_pairs', 0)} refused, {g.get('roundups', 0)} roundups")
    if expected_fallback(prefs, ed.model.embed_model_used):
        # October 7 (PC, rc12c): the Mac-only grouping model was named INFO in part 3 but FAIL here
        report.add(P, f"stories grouped by the fallback model ({ed.model.embed_model_used})", "INFO",
                   f"{prefs.embed_model} runs only on Macs in Ollama so far; " + grouping_detail)
    else:
        report.check(P, f"stories grouped by the configured embedding model ({prefs.embed_model})",
                     ed.model.embed_model_used == prefs.embed_model, grouping_detail)
    findings = review_edition(ed, prefs)
    report.add(P, "automatic read-through (for a human to confirm)", "INFO",
               "\n".join(findings) if findings else "nothing noticed")
    audio = paths.podcasts_dir / f"{ed.edition_date.isoformat()}.wav"
    transcript = audio.with_suffix(".txt")
    from agent_reach.daily.podcast import default_synthesizer

    if default_synthesizer() is None:
        report.add(P, "podcast recorded with the Windows voice", "SKIP", "no speech engine on this machine")
    elif prefs.podcast_auto:
        from agent_reach.daily.podcast import wav_seconds

        ok = audio.exists() and wav_seconds(audio) > 30
        report.check(P, "podcast recorded with the Windows voice", ok,
                     f"{audio.name}: {wav_seconds(audio) / 60:.1f} min" if audio.exists() else
                     "no audio: " + st.last_attempt_message)
    else:
        from agent_reach.daily.podcast import make_podcast

        res = make_podcast(paths, ed, prefs)
        report.check(P, "podcast recorded with the Windows voice", res.ok, res.message)
    if transcript.exists():
        shutil.copy2(transcript, report.out / "podcast-transcript.txt")
    snap = AppController(paths).snapshot()  # the window opened again after the refresh
    report.check(P, "restarted window: up to date, not refreshing", snap.status == "Up to date"
                 and not snap.activity.running, snapshot_text(paths))
    return paths


def part_model_drop(report: Report, args, base: Path, prefs: DailyPrefs) -> None:
    P = "6. Ollama goes away during a refresh"
    host, port = ollama_target(args.ollama_host)
    relay = Relay(host, port)
    relay.start()
    paths = scratch_paths(base, "model drop", prefs.model_copy(update={
        "ollama_host": f"http://127.0.0.1:{relay.port}", "start_ollama_if_down": False, "podcast_auto": False}))
    ctrl = controller(paths, AR_WORLD_MODEL_DELAY_S=1, AR_WORLD_MODEL_DIES_AFTER=3)  # --world: no relay to cut
    ctrl.start_refresh(manual=True)
    if not wait_activity(ctrl, stage="cluster", timeout=900):
        relay.cut()
        report.check(P, "the refresh reached the grouping step", False, snapshot_text(paths))
        return
    time.sleep(args.drop_after_s)
    relay.cut()  # connections reset, new ones refused: what a crashed or quit Ollama looks like
    t = time.monotonic()
    finished = wait_activity(ctrl, timeout=args.limit_s)
    st = load_state(paths)[0]
    plain = "Traceback" not in st.last_attempt_message
    report.check(P, "the refresh ends by itself (no hang, no crash)", finished and not ctrl.activity().running
                 and lock_free(paths), f"ended {time.monotonic() - t:.0f} s after the cut", time.monotonic() - t)
    ed = EditionStore(paths).load_latest().edition
    if st.last_attempt_outcome == "success" and ed is not None:
        honest = ed.model.summaries == "extractive" or ed.model.label_calls_failed == 0 or any(
            "stopped answering" in n for n in ed.notes)
        report.check(P, "published, and honest about the model", honest,
                     f"summaries {ed.model.summaries}; label batches {ed.model.label_calls} failed "
                     f"{ed.model.label_calls_failed}; brief failed {ed.model.brief_calls_failed}\nnotes: "
                     + " | ".join(ed.notes))
    else:
        report.check(P, "no edition, explained in plain words", plain and bool(st.last_attempt_message),
                     f"{st.last_attempt_outcome}: {st.last_attempt_message}")
    report.add(P, "what the window shows then", "INFO", snapshot_text(paths))
    if (paths.logs_dir / "refresh.log").exists():
        shutil.copy2(paths.logs_dir / "refresh.log", report.out / "model-drop-refresh.log")


def part_repeat(report: Report, args, paths: DataPaths) -> None:
    P = "7. repeated use"
    prefs, _ = load_prefs(paths)
    first = EditionStore(paths).load_latest().edition
    # follow a name from the best-corroborated story: the most likely to still be there (a 3-report #1 story
    # vanished from the next refresh on October 7, which is the event-layer problem, not Following)
    lead = max(first.stories, key=lambda s: (s.evidence_strength.independent_reports if s.evidence_strength else 0,
                                             -s.rank)) if first and first.stories else None
    follow = (lead.entities or [lead.headline.split()[0]])[:1] if lead else []
    save_prefs(paths, prefs.model_copy(update={"max_stories": 8, "follow_topics": follow, "podcast_auto": False}))
    ctrl = controller(paths)
    started = time.monotonic()
    ctrl.start_refresh(manual=True)
    wait_activity(ctrl, timeout=args.limit_s)
    st = load_state(paths)[0]
    ed = EditionStore(paths).load_latest().edition
    ok = (st.last_attempt_outcome == "success" and ed is not None and ed.revision == 2
          and ed.changes is not None and len(ed.top_ranks) <= 8 and st.last_success_run_id == ed.run_id)
    report.check(P, "second refresh after changing settings: revision 2, what changed, state agrees", ok,
                 (f"revision {ed.revision}; changes: {ed.changes.summary() if ed.changes else '-'}; top {len(ed.top_ranks)}"
                  if ed else "no edition") + f"\n{st.last_attempt_outcome}: {st.last_attempt_message}",
                 time.monotonic() - started)
    if ed is not None:
        (report.out / "edition-2.txt").write_text(edition_text(ed), encoding="utf-8")
        (report.out / "edition-2.json").write_text(ed.model_dump_json(indent=2), encoding="utf-8")
        # every gate decision of this refresh too: a mixed story seen only here could not be traced (rc12d, Gaza)
        for f in (paths.diagnostics_dir / "semantic").glob(f"semantic-{ed.run_id}.json"):
            shutil.copy2(f, report.out / f"edition-2-{f.name}")
        snap = AppController(paths).snapshot()
        from agent_reach.daily.reading import followed

        if not follow or followed(ed.stories, snap.prefs.follow_topics):
            report.check(P, "Following section from the changed settings", True, f"follow {follow}")
        else:
            gone = lead is not None and not any(s.story_id == lead.story_id or s.headline == lead.headline
                                                for s in ed.stories)
            if gone:
                report.add(P, "Following section from the changed settings", "INFO",
                           f"follow {follow}: that story ('{lead.headline}') is not in the next edition at all "
                           "(refresh-to-refresh churn, a known next-phase problem), so there was nothing to follow")
            else:
                report.check(P, "Following section from the changed settings", False, f"follow {follow}")


def part_interactive(report: Report, args, base: Path, prefs: DailyPrefs) -> None:
    P = "8. by hand: Ollama quit"
    input("\n>>> Quit Ollama now (right-click the llama icon by the clock > Quit Ollama), then press Enter... ")
    from agent_reach.daily.prereqs import check_ollama

    st = check_ollama(args.ollama_host, [prefs.ollama_model])
    report.check(P, "Ollama really stopped", not st.reachable, st.describe())
    paths = scratch_paths(base, "ollama quit", prefs.model_copy(update={"start_ollama_if_down": False,
                                                                        "podcast_auto": False}))
    out = run_worker(paths, timeout=300)
    report.check(P, "refresh with Ollama gone and auto-start off: stops at once, plain message", out.returncode == 31,
                 out.stdout.strip()[-400:])
    report.add(P, "what the window shows then", "INFO", snapshot_text(paths))
    paths = scratch_paths(base, "ollama auto start", prefs.model_copy(update={"podcast_auto": False}))
    started = time.monotonic()
    out = run_worker(paths, timeout=args.limit_s)
    st = check_ollama(args.ollama_host, [prefs.ollama_model])
    report.check(P, "the app starts the installed Ollama by itself and refreshes", st.reachable and out.returncode == 0,
                 out.stdout.strip()[-400:], time.monotonic() - started)


# ====================================================================== main
def collect_zip(out: Path) -> Path:
    target = out.with_suffix(".zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file() and f.suffix.lower() != ".wav":
                z.write(f, f.relative_to(out.parent))
    return target


def desktop() -> Path:
    for p in (Path.home() / "Desktop", Path.home() / "OneDrive" / "Desktop", Path.home()):
        if p.is_dir():
            return p
    return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tests.daily_selftest", description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=None, help="folder for the results (default: your Desktop)")
    p.add_argument("--quick", action="store_true", help="skip the second real refresh (repeated use)")
    p.add_argument("--offline", action="store_true", help="only parts that need no internet and no Ollama")
    p.add_argument("--skip-pytest", action="store_true", help="skip the offline test suite")
    p.add_argument("--interactive", action="store_true", help="add the steps where you quit Ollama by hand")
    p.add_argument("--ollama-host", default=None, help="default: the address in your settings")
    p.add_argument("--drop-after-s", type=float, default=20.0, help="seconds into grouping before the model drop")
    p.add_argument("--keep-scratch", action="store_true", help="keep the scratch data folders under %%TEMP%%")
    p.add_argument("--world", action="store_true", help=argparse.SUPPRESS)  # dry run of this harness, fake world
    args = p.parse_args(argv)
    # the self-test starts the app many times: none of those starts may install an update in the middle of it
    os.environ["AGENT_REACH_NO_UPDATE"] = "1"

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = (args.out or desktop()) / f"AgentReach-selftest-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.gettempdir()) / f"Agent Reach selftest {stamp}"
    base.mkdir(parents=True, exist_ok=True)
    report = Report(out)
    real = DataPaths.resolve(default_root())
    prefs = load_prefs(real)[0] if real.settings.exists() else DailyPrefs()
    prefs = prefs.model_copy(update={"contact_email": ""})
    global WORLD
    if args.world:
        from tests.daily_world import world_settings_entries

        WORLD = {}
        prefs = DailyPrefs(enabled_sources=["news_rss", "google_news", "hackernews"],
                           news_rss_feeds=world_settings_entries(), podcast_auto=False)
    args.ollama_host = (args.ollama_host or prefs.ollama_host).rstrip("/")
    from agent_reach.daily.refresh import watchdog_limit_s

    args.limit_s = watchdog_limit_s(prefs) + 120
    print(f"Agent Reach Daily {__version__} self-test\nresults: {out}\nscratch data: {base}\n"
          f"(your real data folder {real.root} is only read)", flush=True)

    try:
        return _run_parts(report, args, base, prefs, out)
    except KeyboardInterrupt:  # Ctrl+C or a closed window: keep what was found so far
        report.add(report.running or "self-test", "stopped by the user (Ctrl+C)", "FAIL")
        zipped = collect_zip(out)
        print(f"\nStopped. Send this file back anyway: {zipped}", flush=True)
        return 1


def _run_parts(report: Report, args, base: Path, prefs: DailyPrefs, out: Path) -> int:
    guarded(report, "1. environment")(part_environment)(report, args)
    guarded(report, "2. launchers")(part_launchers)(report, args, base)
    ready = False
    if args.world:
        ready = True
        report.add("3. ollama", "real Ollama checks", "SKIP", "--world dry run")
    elif not args.offline:
        ready = bool(guarded(report, "3. ollama")(part_ollama)(report, args, base, prefs))
    if not args.skip_pytest:
        guarded(report, "4. offline test suite")(part_pytest)(report, args)
    if not args.offline and ready:
        guarded(report, "5. real refresh: cancel")(part_refresh_ux)(report, args, base, prefs)
        paths = guarded(report, "5. real refresh: full")(part_full_refresh)(report, args, base, prefs)
        guarded(report, "6. Ollama goes away during a refresh")(part_model_drop)(report, args, base, prefs)
        if paths is not None and not args.quick:
            guarded(report, "7. repeated use")(part_repeat)(report, args, paths)
        if args.interactive:
            guarded(report, "8. by hand: Ollama quit")(part_interactive)(report, args, base, prefs)
    elif not args.offline:
        report.add("5. real refresh", "real refresh parts", "SKIP", "Ollama is not ready (see part 3)")
    report.finished = True
    report.write()
    if not args.keep_scratch:
        shutil.rmtree(base, ignore_errors=True)
    zipped = collect_zip(out)
    failed = sum(c.status == "FAIL" for c in report.checks)
    print(f"\n{'ALL PASSED' if not failed else f'{failed} FAILED'} - send this file back: {zipped}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
