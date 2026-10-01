"""Daily app: the cross-process refresh lock and the Windows Task Scheduler definition."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from agent_reach.daily import scheduler as SCH
from agent_reach.daily.lock import LockBusy, RefreshLock, pid_alive, read_holder_info
from agent_reach.daily.refresh import EXIT_BUSY, refresh

ROOT = Path(__file__).resolve().parents[1]
NS = {"t": SCH.TASK_NS}


# ------------------------------------------------------------------ lock
def test_acquire_release_and_holder_info(daily_paths):
    lock = RefreshLock(daily_paths.lock_file, daily_paths.lock_info)
    lock.acquire({"trigger": "manual"})
    assert lock.held
    info = read_holder_info(daily_paths.lock_info)
    assert info["pid"] == os.getpid() and info["trigger"] == "manual"
    lock.release()
    assert not lock.held and read_holder_info(daily_paths.lock_info) is None
    with RefreshLock(daily_paths.lock_file) as again:  # reusable after release
        assert again.held


def test_second_holder_is_refused_even_in_the_same_process(daily_paths):
    first = RefreshLock(daily_paths.lock_file)
    first.acquire()
    try:
        with pytest.raises(LockBusy):
            RefreshLock(daily_paths.lock_file).acquire()
        with pytest.raises(LockBusy):
            first.acquire()
    finally:
        first.release()


def _hold_lock_in_child(lock_file: Path) -> subprocess.Popen:
    code = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(ROOT)!r})
        from agent_reach.daily.lock import RefreshLock
        lock = RefreshLock({str(lock_file)!r})
        lock.acquire()
        print("held", flush=True)
        time.sleep(60)
    """)
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


def test_lock_held_by_another_process_blocks_a_refresh(daily_paths):
    proc = _hold_lock_in_child(daily_paths.lock_file)
    try:
        out = refresh(daily_paths, trigger="manual", force=True, ollama_probe=lambda p: pytest.fail("must not run"))
        assert out.code == EXIT_BUSY and out.outcome == "busy"
    finally:
        proc.kill()
        proc.wait()


@pytest.mark.skipif(sys.platform == "win32", reason="SIGKILL semantics; Windows releases on TerminateProcess too")
def test_crashed_holder_never_leaves_a_stuck_lock(daily_paths):
    proc = _hold_lock_in_child(daily_paths.lock_file)
    with pytest.raises(LockBusy):
        RefreshLock(daily_paths.lock_file).acquire()
    os.kill(proc.pid, signal.SIGKILL)  # crash: no cleanup code runs
    proc.wait()
    deadline = time.monotonic() + 5
    while True:
        try:
            RefreshLock(daily_paths.lock_file).acquire()
            break
        except LockBusy:
            assert time.monotonic() < deadline, "the OS should release a dead holder's lock"
            time.sleep(0.05)
    assert not pid_alive(proc.pid)


# ------------------------------------------------------------------ scheduler definition
def windows_argv(cmdline: str) -> list[str]:
    """CommandLineToArgvW / MSVCRT rules (backslashes before quotes, quoted spaces)."""
    args, cur, in_q, i, have = [], [], False, 0, False
    while i < len(cmdline):
        c = cmdline[i]
        if c == "\\":
            n = 0
            while i < len(cmdline) and cmdline[i] == "\\":
                n += 1
                i += 1
            if i < len(cmdline) and cmdline[i] == '"':
                cur.append("\\" * (n // 2))
                if n % 2:
                    cur.append('"')
                    i += 1
            else:
                cur.append("\\" * n)
            have = True
            continue
        if c == '"':
            in_q = not in_q
            have = True
        elif c in " \t" and not in_q:
            if have:
                args.append("".join(cur))
                cur, have = [], False
        else:
            cur.append(c)
            have = True
        i += 1
    if have:
        args.append("".join(cur))
    return args


def _parse(xml_text: str) -> ET.Element:
    return SCH.ET.fromstring(xml_text.split("?>", 1)[1])


@pytest.mark.parametrize("data_dir", [
    r"C:\Users\Jane Doe\AppData\Local\Agent Reach Daily",
    "C:\\Users\\Jane Doe\\Daily data\\",  # trailing backslash must not swallow the closing quote
    "D:\\",
])
def test_task_arguments_survive_windows_argv_parsing(data_dir):
    args = windows_argv(SCH.task_arguments(data_dir))
    assert args[:5] == ["-m", "agent_reach.daily", "--refresh-if-due", "--trigger", "scheduled"]
    assert args[5:] == ["--data-dir", data_dir]


def test_task_xml_quotes_paths_with_spaces_and_escapes_markup():
    exe = r"C:\Users\Jane Doe\Downloads\Agent Reach\src\Agent-Reach\.venv\Scripts\pythonw.exe"
    project = r"C:\Users\Jane Doe\Downloads\Agent Reach & Co\src\Agent-Reach"
    xml = SCH.build_task_xml(exe, project, user_id="PC\\Jane")
    root = _parse(xml)
    command = root.find("t:Actions/t:Exec/t:Command", NS).text
    assert command == f'"{exe}"' and windows_argv(command) == [exe]
    assert root.find("t:Actions/t:Exec/t:WorkingDirectory", NS).text == project  # unquoted, & round-trips
    assert root.find("t:Actions/t:Exec/t:Arguments", NS).text == "-m agent_reach.daily --refresh-if-due --trigger scheduled"
    s = root.find("t:Settings", NS)
    assert s.find("t:MultipleInstancesPolicy", NS).text == "IgnoreNew"
    assert s.find("t:StartWhenAvailable", NS).text == "true"
    assert s.find("t:WakeToRun", NS).text == "false"
    assert root.find("t:Principals/t:Principal/t:LogonType", NS).text == "InteractiveToken"
    assert root.find("t:Principals/t:Principal/t:RunLevel", NS).text == "LeastPrivilege"
    assert root.find("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", NS).text == "PT1H"
    assert root.find("t:Triggers/t:LogonTrigger/t:UserId", NS).text == "PC\\Jane"
    with pytest.raises(ValueError):
        SCH.build_task_xml('C:\\bad"name\\pythonw.exe', project)


def test_status_parser_reads_back_the_generated_definition():
    exe, project = r"C:\A B\pythonw.exe", r"C:\A B\src"
    st = SCH.parse_task_xml(SCH.build_task_xml(exe, project, user_id="u"))
    assert st.installed and st.enabled is True and st.matches(exe, project)
    assert not st.matches(r"C:\Other\pythonw.exe", project)


class FakeRunner:
    def __init__(self, installed: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.installed = installed
        self.xml_bytes: bytes | None = None

    def __call__(self, args):
        self.calls.append(args)
        if "/Create" in args:
            self.xml_bytes = Path(args[args.index("/XML") + 1]).read_bytes()
            return subprocess.CompletedProcess(args, 0, "SUCCESS: created", "")
        if "/Query" in args:
            if not self.installed:
                return subprocess.CompletedProcess(args, 1, "", "ERROR: not found")
            return subprocess.CompletedProcess(args, 0, SCH.build_task_xml(r"C:\p\pythonw.exe", r"C:\p", user_id="u"), "")
        return subprocess.CompletedProcess(args, 0, "SUCCESS: deleted", "")


def test_install_writes_utf16_xml_and_updates_in_place(tmp_path):
    runner = FakeRunner()
    ok, msg = SCH.install_task(tmp_path / "python.exe", tmp_path / "proj dir", runner=runner)
    assert ok and "SUCCESS" in msg
    args = runner.calls[0]
    assert args[:4] == ["schtasks.exe", "/Create", "/TN", SCH.TASK_NAME] and args[-1] == "/F"
    assert runner.xml_bytes[:2] in (b"\xff\xfe", b"\xfe\xff")  # UTF-16 with BOM
    assert "<Task" in runner.xml_bytes.decode("utf-16")
    assert not Path(args[args.index("/XML") + 1]).exists()  # temp file removed


def test_dry_runs_never_call_schtasks():
    runner = FakeRunner(installed=True)
    ok, msg = SCH.install_task(r"C:\p\python.exe", r"C:\p", runner=runner, dry_run=True)
    assert ok and msg.startswith("DRY RUN") and "<Task" in msg
    ok, msg = SCH.uninstall_task(runner=runner, dry_run=True)
    assert ok and msg.startswith("DRY RUN")
    assert runner.calls == []


def test_uninstall_is_idempotent():
    runner = FakeRunner(installed=False)
    ok, msg = SCH.uninstall_task(runner=runner)
    assert ok and "not installed" in msg and all("/Delete" not in c for c in runner.calls)
    runner = FakeRunner(installed=True)
    ok, _ = SCH.uninstall_task(runner=runner)
    assert ok and any("/Delete" in c for c in runner.calls)


def test_gui_python_prefers_pythonw(tmp_path):
    (tmp_path / "python.exe").write_text("")
    assert SCH.gui_python(tmp_path / "python.exe") == tmp_path / "python.exe"
    (tmp_path / "pythonw.exe").write_text("")
    assert SCH.gui_python(tmp_path / "python.exe") == tmp_path / "pythonw.exe"


def test_install_task_cli_dry_run_with_spaces(tmp_path):
    data = tmp_path / "my data dir"
    proc = subprocess.run([sys.executable, "-m", "agent_reach.daily", "--install-task", "--dry-run", "--data-dir",
                           str(data)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("DRY RUN") and f'--data-dir "{data.resolve()}"' in proc.stdout
