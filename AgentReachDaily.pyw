"""Double-click launcher for Agent Reach Daily (opens the window, no console).

Windows runs ``.pyw`` files with whichever ``pythonw.exe`` is associated with them, which is
usually NOT this project's environment. This launcher therefore re-starts itself with the
project's own ``.venv`` (created by Setup-AgentReachDaily.ps1) when that exists, so the right
Python and dependencies are always used. Any extra arguments (e.g. ``--data-dir``) are passed on.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
RELAUNCHED = "AGENT_REACH_DAILY_LAUNCHED"


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "pythonw.exe"
    return VENV / "bin" / "python"


def in_project_venv() -> bool:
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def show_error(message: str) -> None:
    """Visible error without a console: Tk dialog, else the native Windows message box."""
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("Agent Reach Daily", message)
        root.destroy()
        return
    except Exception:  # noqa: BLE001 - fall through to the next way of telling the user
        pass
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Agent Reach Daily", 0x10)
    else:
        print(message, file=sys.stderr)


def main() -> int:
    target = venv_python()
    if not in_project_venv() and target.exists() and not os.environ.get(RELAUNCHED):
        env = dict(os.environ, **{RELAUNCHED: "1"})
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        subprocess.Popen([str(target), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=str(ROOT), env=env,
                         creationflags=flags, close_fds=True)
        return 0
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from agent_reach.daily.__main__ import main as daily_main
    except ImportError as exc:
        show_error(f"Agent Reach Daily is not set up yet ({exc}).\n\n"
                   f"Open PowerShell in\n{ROOT}\nand run:\n\n"
                   "powershell -ExecutionPolicy Bypass -File .\\Setup-AgentReachDaily.ps1")
        return 1
    return daily_main(["--gui", *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
