"""Local prerequisite checks: Ollama reachability and the two models.

Only localhost-style calls to the configured Ollama host; never pulls models (that belongs to
the interactive setup script, so unattended refreshes never start multi-GB downloads).
``start_ollama`` launches the installed Ollama app hidden when the server is down; it is used
by refreshes when ``start_ollama_if_down`` is enabled.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


@dataclass
class OllamaStatus:
    reachable: bool
    host: str
    version: str | None = None
    models: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ready(self) -> bool:
        return self.reachable and not self.missing

    def describe(self) -> str:
        if not self.reachable and "not like an Ollama server" in (self.error or ""):
            return (f"Another program answers at {self.host}, not Ollama. Check the Ollama address in Settings > "
                    "Model, or close the program that uses that port and start the Ollama app.")
        if not self.reachable:
            return (f"Ollama is not running at {self.host}. Start the Ollama app (Start menu -> Ollama), "
                    "or install it from https://ollama.com/download.")
        if self.missing:
            pulls = " and ".join(f"'ollama pull {m}'" for m in self.missing)
            return f"Ollama is running but model(s) {', '.join(self.missing)} are missing. Run {pulls} in a terminal."
        return f"Ollama {self.version or ''} is running with the required models.".replace("  ", " ")


def model_present(wanted: str, names: list[str]) -> bool:
    if wanted in names or f"{wanted}:latest" in names:
        return True
    return ":" not in wanted and any(n.split(":")[0] == wanted for n in names)


def check_ollama(host: str, required_models: list[str], timeout_s: float = 3.0) -> OllamaStatus:
    host = host.rstrip("/")
    try:
        with httpx.Client(timeout=timeout_s, trust_env=False) as client:
            tags = client.get(f"{host}/api/tags")
            tags.raise_for_status()
            listing = tags.json()
            if not isinstance(listing, dict) or not isinstance(listing.get("models", []), list):
                raise ValueError(f"{host} answered, but not like an Ollama server")
            names = [str(m.get("name") or m.get("model")) for m in listing.get("models", []) if isinstance(m, dict)]
            try:
                answer = client.get(f"{host}/api/version").json()
                version = answer.get("version") if isinstance(answer, dict) else None
            except (httpx.HTTPError, ValueError):
                version = None
    except (httpx.HTTPError, ValueError) as exc:
        return OllamaStatus(False, host, error=f"{type(exc).__name__}: {str(exc)[:160]}")
    missing = [m for m in required_models if not model_present(m, names)]
    return OllamaStatus(True, host, version=version, models=sorted(names), missing=missing)


def find_ollama_executables() -> list[Path]:
    """Installed Ollama binaries, preferring the tray app (it runs the server in the background)."""
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        base = Path(local) / "Programs" / "Ollama"
        candidates += [base / "ollama app.exe", base / "ollama.exe"]
    on_path = shutil.which("ollama")
    if on_path:
        candidates.append(Path(on_path))
    seen, out = set(), []
    for c in candidates:
        key = str(c).lower()
        if key not in seen and c.is_file():
            seen.add(key)
            out.append(c)
    return out


def start_ollama(host: str, required_models: list[str], wait_s: float = 45.0) -> OllamaStatus:
    """Start the local Ollama server hidden if it is down and the host is local. Never pulls models."""
    status = check_ollama(host, required_models)
    if status.reachable:
        return status
    if not any(h in host for h in ("localhost", "127.0.0.1", "[::1]")):
        status.error = (status.error or "") + " (remote host: not starting anything locally)"
        return status
    exes = find_ollama_executables()
    if not exes:
        status.error = "Ollama is not installed (no ollama.exe found)."
        return status
    exe = exes[0]
    args = [str(exe)] if exe.name.lower() == "ollama app.exe" else [str(exe), "serve"]
    flags = (CREATE_NO_WINDOW | DETACHED_PROCESS) if sys.platform == "win32" else 0
    try:
        subprocess.Popen(args, cwd=str(exe.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    except OSError as exc:
        status.error = f"could not start {exe.name}: {exc}"
        return status
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        time.sleep(1.5)
        status = check_ollama(host, required_models)
        if status.reachable:
            return status
    status.error = f"started {exe.name} but the server did not answer within {wait_s:.0f} s"
    return status
