"""Current-user Windows Task Scheduler task for unattended daily refreshes.

The task runs ``pythonw.exe -m agent_reach.daily --refresh-if-due`` from the project folder:

* triggers: at logon of this user (2 minute delay, so the network and the Ollama tray app
  can start) and every hour; the command exits within about a second when nothing is due;
* ``StartWhenAvailable``: a run missed while the PC was asleep or off starts when possible;
* ``MultipleInstancesPolicy=IgnoreNew``: overlapping instances are not started (the refresh
  lock is the second line of defence);
* ``LogonType=InteractiveToken`` / ``LeastPrivilege``: runs only while this user is logged on,
  without administrator rights and without storing a password. The PC cannot collect news
  while it is powered off; it does not wake the computer (``WakeToRun=false``);
* ``pythonw.exe``: no console window; ``ExecutionTimeLimit`` 2 hours bounds a hung run.

Registration uses ``schtasks /Create /XML`` (UTF-16 file) with ``/F`` so re-running setup
updates the task in place. Nothing here runs unless the user asks for it (setup script, GUI
button or ``--install-task``).
"""

from __future__ import annotations

import getpass
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

TASK_NAME = "AgentReachDaily-Refresh"
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
CREATE_NO_WINDOW = 0x08000000


def current_user_id() -> str:
    user = os.environ.get("USERNAME") or getpass.getuser()
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{user}" if domain else user


def gui_python(python_exe: str | Path) -> Path:
    """pythonw.exe next to the given interpreter (no console window), if present."""
    p = Path(python_exe)
    if p.name.lower() == "python.exe":
        w = p.with_name("pythonw.exe")
        if w.exists():
            return w
    return p


def quote_command(path: str | Path) -> str:
    """Task Scheduler <Command>: quoted so paths with spaces work (quotes are not allowed inside)."""
    text = str(path)
    if '"' in text:
        raise ValueError("executable path may not contain double quotes")
    return f'"{text}"'


def task_arguments(data_dir: str | Path | None = None) -> str:
    args = "-m agent_reach.daily --refresh-if-due --trigger scheduled"
    if data_dir:
        text = str(data_dir)
        if '"' in text:
            raise ValueError("data directory may not contain double quotes")
        args += f' --data-dir "{text}"'
    return args


def build_task_xml(python_exe: str | Path, project_dir: str | Path, *, user_id: str | None = None,
                   data_dir: str | Path | None = None, start: datetime | None = None) -> str:
    user = escape(user_id or current_user_id())
    start = (start or datetime.now()).replace(second=0, microsecond=0)
    command = escape(quote_command(python_exe))
    arguments = escape(task_arguments(data_dir))
    workdir = escape(str(project_dir))  # WorkingDirectory must NOT be quoted
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="{TASK_NS}">
  <RegistrationInfo>
    <Description>Agent Reach Daily: checks hourly and at logon whether the 24-hour news refresh is due (exits immediately when not). Runs only while you are logged on.</Description>
    <URI>\\{TASK_NAME}</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{user}</UserId>
      <Delay>PT2M</Delay>
    </LogonTrigger>
    <TimeTrigger>
      <Enabled>true</Enabled>
      <StartBoundary>{start:%Y-%m-%dT%H:%M:%S}</StartBoundary>
      <Repetition>
        <Interval>PT1H</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


@dataclass
class TaskStatus:
    supported: bool
    installed: bool
    command: str | None = None
    arguments: str | None = None
    working_directory: str | None = None
    enabled: bool | None = None
    detail: str = ""

    def matches(self, python_exe: str | Path, project_dir: str | Path) -> bool:
        return (self.command or "").strip('"').lower() == str(python_exe).lower() and \
               (self.working_directory or "").lower() == str(project_dir).lower()


def _run(args: list[str]) -> subprocess.CompletedProcess:
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(args, capture_output=True, text=True, creationflags=flags, timeout=60)


def install_task(python_exe: str | Path, project_dir: str | Path, *, data_dir: str | Path | None = None,
                 runner=_run) -> tuple[bool, str]:
    if sys.platform != "win32" and runner is _run:
        return False, "Task Scheduler is only available on Windows."
    xml = build_task_xml(gui_python(python_exe), project_dir, data_dir=data_dir)
    fd, tmp = tempfile.mkstemp(prefix="agent-reach-task-", suffix=".xml")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(xml.encode("utf-16"))  # schtasks expects UTF-16 (with BOM)
        proc = runner(["schtasks.exe", "/Create", "/TN", TASK_NAME, "/XML", tmp, "/F"])
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    ok = proc.returncode == 0
    message = (proc.stdout or proc.stderr or "").strip()
    return ok, message or ("Scheduled refresh installed." if ok else f"schtasks exited with {proc.returncode}")


def uninstall_task(runner=_run) -> tuple[bool, str]:
    if sys.platform != "win32" and runner is _run:
        return False, "Task Scheduler is only available on Windows."
    status = task_status(runner=runner)
    if not status.installed:
        return True, "Scheduled refresh was not installed."
    proc = runner(["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"])
    message = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode == 0, message


def task_status(runner=_run) -> TaskStatus:
    if sys.platform != "win32" and runner is _run:
        return TaskStatus(supported=False, installed=False, detail="Task Scheduler is only available on Windows.")
    try:
        proc = runner(["schtasks.exe", "/Query", "/TN", TASK_NAME, "/XML"])
    except (OSError, subprocess.SubprocessError) as exc:
        return TaskStatus(supported=False, installed=False, detail=str(exc))
    if proc.returncode != 0:
        return TaskStatus(supported=True, installed=False, detail="not installed")
    return parse_task_xml(proc.stdout)


def parse_task_xml(text: str) -> TaskStatus:
    # schtasks prints a UTF-16 declaration on already-decoded text; drop it before parsing.
    body = re.sub(r"^\s*﻿?\s*<\?xml[^>]*\?>", "", text or "")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        return TaskStatus(supported=True, installed=True, detail=f"unreadable task definition: {exc}")
    ns = {"t": TASK_NS}

    def find(path: str) -> str | None:
        el = root.find(path, ns)
        return el.text if el is not None else None

    enabled = find("t:Settings/t:Enabled")
    return TaskStatus(
        supported=True, installed=True,
        command=find("t:Actions/t:Exec/t:Command"),
        arguments=find("t:Actions/t:Exec/t:Arguments"),
        working_directory=find("t:Actions/t:Exec/t:WorkingDirectory"),
        enabled=None if enabled is None else enabled.strip().lower() == "true",
        detail="installed",
    )
