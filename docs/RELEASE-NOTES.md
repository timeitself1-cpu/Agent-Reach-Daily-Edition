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

### Windows-readiness pass

Found by running the real refresh worker as its own process (offline, with synthetic news and a fake
model) and cancelling, killing, hanging and starving it, by damaging and locking its files, and by
looking at the window as a reader would. Not yet run on Windows or with a real Ollama: see
`docs/WINDOWS-TEST-RC11.md`.

7. **A hung refresh could keep "Refreshing" forever.** A refresh stuck in a call that ignores the time
   limit (a hung network, disk or driver call) never ended. A watchdog now ends it 25 minutes after the
   time limit, records "stopped responding" in plain words, and writes where it hung to `diagnostics\`.
8. **When Ollama stopped answering partway through a refresh, the edition still said "local model"
   summaries.** The app now counts the model steps that fell back. If half or more fell back, the edition
   counts as extractive: with "AI summaries required" the previous edition is kept, and the reason says
   the model stopped answering. If fewer fell back, the edition says so in its notes.
9. **A refresh killed halfway (Task Manager, crash, power loss) left the window silent.** It now says
   the last refresh stopped before finishing.
10. **Settings or refresh history held open by another program (antivirus, OneDrive, a backup tool)
    were treated as damaged:** `settings.json` was renamed and default settings were used, which lost
    your feeds and topics. Such files are now left alone. The window shows a warning, and refreshes wait
    until the file can be read.
11. **An edition file held open by another program failed the refresh with a raw `PermissionError`.**
    It now says the new edition could not be saved and why.
12. **Cancel right after pressing Refresh** waited 5 seconds for nothing. **The Cancel button's reset**
    went through a background-thread call to Tk that could be lost, which would leave "Refreshing..." on
    for good.
13. **A damaged newest edition was counted twice** ("2 files could not be read").
14. **Saving settings or topics to a read-only settings file** showed "Something went wrong". It now
    says what happened.
15. **Another program on Ollama's port** is now named as such ("Another program answers at ..., not
    Ollama"), not as "Ollama is not running".
16. **"Found too little news to publish"** was shown for every refresh that published nothing, including
    when the model stopped. It now says "did not publish a new edition", and the banner gives the reason.

Daily use:
- The status shows the step a refresh is on ("Refreshing, step 4 of 7: ...").
- Before the first edition, the empty date box and the Listen button are disabled.
- "Clear search" looks like a link.
- A Settings label no longer gets cut off.
- `python -m agent_reach.daily` works from any folder after rerunning Setup.

Testing:
- `Test-AgentReachDaily.ps1` (self-test on your PC with real Ollama and real news; leaves a zip of the
  results on the Desktop).
- `tests/test_daily_processes.py` (real worker processes).
- `tests/test_daily_windows.py` (real Windows file locks).
- The window tests now run in CI on a virtual display. Before this they were silently skipped there.

### First Windows test round (self-test on the reader's PC, October 7)

The self-test ran on Windows 11 with Ollama 0.35.1 (llama3.1:8b, RTX 4070 Super): 24 checks passed and 3
failed. These passed:
- the Desktop and Start-menu shortcuts started from another folder;
- `python -m agent_reach.daily` started from another folder;
- the Ollama checks (running, missing model, nothing listening);
- cancel right after starting and cancel halfway;
- a full real refresh: 330 s, 48 stories, HTML export, a 5.4-minute podcast in the Windows voice;
- Ollama cut off halfway: no edition, explained in plain words;
- a second refresh after changing settings.

Fixed from that run:

17. **Another program on Ollama's port answering with a web page** (not JSON) still read as "Ollama is not
    running". Any answer that is not Ollama's model list now says another program answers there.
18. **After Ollama went away mid-refresh, every remaining model step retried three times.** Each refused
    connection costs about 2 s on Windows, so the refresh ended 112 s after Ollama stopped. The first refused
    connection now ends the model calls for that refresh.
19. **A YouTube outage (1 of 22 channels answered) was listed as 21 broken feeds** named like the
    publishers' working article feeds, and the feed checker would have blamed those addresses after three
    days. A channel where fewer than 1 in 5 feeds answer now counts as one outage, said once.
20. **The model's remarks about its input reached summaries** ("..., but the reason is not specified").
    They are removed.
21. **A summary ended inside a word** ("trained on 3,800 NVIDIA Grac."). The article text the model reads is
    now cut at a word.
22. **Self-test:** the `.cmd` launcher check hung (fixed in the harness), and a test file that does not
    load no longer stops the whole test suite.

The two real editions are now regression fixtures (`tests/fixtures/real/`). What they show for the next
phase is in `docs/REAL-EDITION-FINDINGS.md`.

### Second Windows test round (October 7, 9:29 AM)

The self-test ran with 31 checks passing and 3 failing. Highlights from that run:
- **Offline suite on Windows:** 404 passed, 1 skipped, 4 expected failures. That includes the real Windows
  file-lock tests and the process kill/cancel tests.
- **Launchers:** the Desktop and Start-menu shortcuts and `AgentReachDaily.cmd` all opened the window.
- **Model drop:** the refresh now ends 9 s after Ollama goes away (it took 112 s before).

The three failures:
1. **`AgentReachDaily.pyw` (double-click) did not open the window.** The self-test now records what `.pyw`
   files open with on the PC. The Desktop shortcut is the supported launcher.
2. **Two test files in the reader's folder are not part of this release** (other work); see the handoff.
3. **The "Following" check followed the #1 story, and the next refresh no longer had that story.** That is
   the refresh-to-refresh churn the event layer must fix. The check now follows the best-corroborated story
   and reports churn as churn.

Fixed:

23. **A middle initial ended a sentence.** A summary read "Biologist James D." followed by "Watson appears to
    have ...". The sentence splitters no longer split after a single capital initial.
