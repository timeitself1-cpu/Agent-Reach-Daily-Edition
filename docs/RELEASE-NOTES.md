# Agent Reach Daily: release notes

Each release candidate is delivered as a zip of the repository. Extract it over the old folder, rerun
`powershell -ExecutionPolicy Bypass -File .\Setup-AgentReachDaily.ps1 -RegisterTask`, and reopen the app.
Your editions, settings and history (`%LOCALAPPDATA%\AgentReachDaily`) are kept. Earlier releases are
summarised in `docs/HANDOFF.md` ("Release history").

## 1.0.0rc11

### Stabilization pass (found by reviewing the code; no new features)

1. **The window could stay on "Refreshing" for good, and Cancel could end the wrong program.** A refresh
   that died (crash, power loss) leaves `progress.json` behind with its process number. After a restart
   that number can belong to any other program; the window trusted it, showed "Refreshing", blocked
   Refresh, and Cancel would have ended that program. The window now checks the refresh lock that the
   operating system releases when a worker dies.
2. **A refresh stopped by the time limit stayed "running" in the history database.** It is now marked
   invalid like any other failed run.
3. **A damaged edition file that Windows refused to move (held open by a virus scanner) stopped the
   refresh** before the attempt was recorded. The refresh now logs it and continues.
4. **The model check crashed when another program answered on Ollama's port.** It now says the program
   there is not Ollama.
5. **A negative or invalid `Retry-After` header from a news site** could produce a negative wait. It is
   clamped.
6. **Follow / Mute from a story's right-click menu skipped the checks of the Topics tab** (length, blank
   topics, duplicates in other capitalisation). Both now use the same checks.

Also in the repository: every text file is stored with LF line endings (`.ps1`, `.cmd` and `.bat` are
still checked out with CRLF), so a fresh copy no longer shows the PowerShell scripts as modified.
