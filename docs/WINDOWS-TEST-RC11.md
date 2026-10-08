# Testing rc11 on your Windows PC

rc11 has been tested in a Linux cloud sandbox only: offline, with synthetic news and a fake model, but
with real worker processes, real locks and the real window (on a virtual display). Nothing in it has run on
Windows or against a real Ollama yet. This page is how to do that. There are two parts: an automatic
self-test (about 25 minutes, unattended) and ten minutes of using the app by hand.

## 0. Install rc11

1. Extract the rc11 zip over `C:\Users\downt\Downloads\Agent Reach\src\Agent-Reach` (replace files).
2. In PowerShell in that folder:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\Setup-AgentReachDaily.ps1 -RegisterTask
   ```

   rc11's setup also registers the project folder in `.venv`, so
   `.venv\Scripts\python.exe -m agent_reach.daily` works from any folder.

## 1. Automatic self-test (send back the zip)

Make sure Ollama is running (the llama icon by the clock), then in PowerShell in the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\Test-AgentReachDaily.ps1
```

It works in a new scratch folder under `%TEMP%`. Your real data folder is only read: its `settings.json`
is copied so the test uses your own feeds. It:

| Part | What it checks |
|---|---|
| 1 environment | Python, Tk and your display scaling; `python -m agent_reach.daily` started from another folder |
| 2 launchers | The Desktop and Start menu shortcuts, `AgentReachDaily.cmd` and `AgentReachDaily.pyw` each open the window from another folder (it appears for 3 seconds and closes by itself) |
| 3 Ollama | Your real Ollama: running with both models; a missing model; nothing listening; another program on the port; a refresh against each failure stops at once with a plain message |
| 4 offline suite | The whole test suite on Windows: small windows flash for a minute or two (that is the window tests), real Windows file locks, process kill and cancel |
| 5 real refresh | Cancel right after Refresh; cancel halfway; one full real refresh started the way the Refresh button starts it, with its progress steps, HTML export, podcast (Windows voice) and the edition as text |
| 6 model drop | A real refresh whose connection to Ollama is cut halfway: it must end by itself and say what happened |
| 7 repeated use | A second real refresh after changing settings: revision 2, "what changed", coherent state |

At the end Explorer opens on **`AgentReach-selftest-<time>.zip` on your Desktop. Send that file back.**
It contains the report, the scratch logs, the editions (JSON, HTML, text, for regression fixtures), the
podcast transcript (not the audio) and the test-suite output.

Options: `-Quick` skips part 7; `-Interactive` adds a part where you quit Ollama when asked (the app's own
start of Ollama, and a refresh while it is gone); `-SkipTests` skips part 4.

## 2. By hand (about 10 minutes): what only a person can judge

Use the real app as you would every morning. Write a short answer to each item. A phone photo or a
screenshot (Win+Shift+S) of anything odd is the most useful thing you can send.

1. **Start.** Double-click "Agent Reach" on the Desktop. Does a console window flash? How many seconds
   until the window appears? Is anything cut off or squeezed at your display scaling? Try maximising it.
2. **Read.** Does the first screen make sense without knowing how the app works? Is anything confusing
   (a word, a button, a number such as the counts next to the sections)?
3. **Refresh.** Press Refresh. Does the status say which step it is on ("step 4 of 7")? Is the Stop
   button obvious? How long did it take?
4. **Stop.** Press Refresh, then Stop at once. Then press Refresh again and Stop it halfway. What did the
   window say each time? Did Refresh work again right after?
5. **Close during a refresh.** Press Refresh, close the window, open it again from the Desktop. It should
   say the refresh is still running and then show the new edition by itself.
6. **Crash.** Press Refresh. In Task Manager > Details, right-click a column header > Select columns >
   tick "Command line". End the `pythonw.exe` whose command line contains `--refresh-now` (not the one with
   `--gui`, which is the window). The window should say the last refresh stopped before finishing, and
   Refresh should work.
7. **Follow / Mute.** Right-click a story: Follow one of its names. Is the story starred, and is there a
   "Following" section? Right-click it again: Stop following. Mute a name: is the story hidden, and does
   the subtitle say "1 muted"? In Settings > Topics, add `norvale` and `NORVALE` on two lines, a blank line
   and a very long line, then Save. Close the app, open it again: are the topics still there (once each)?
   Remove them again in Settings > Topics.
8. **Listen.** Press Listen. Does the podcast play? How does the voice sound?
9. **Export.** "..." menu > Export: does the page open in your browser and look right?
10. **Next morning.** Open the app the next morning as you normally would. Was today's edition already
    there (the scheduled task refreshes at logon and hourly)? If not, how long until you could read it?

Optional, if you are willing: press Refresh and restart Windows while it runs (Start > Power > Restart).
After logging in, open the app: it should say the last refresh stopped and then refresh on its own.

**Send back:** the self-test zip, your answers, any screenshots, and the logs of your real data folder
("..." menu > Open logs folder: zip the folder) if anything went wrong.

## What rc11 cannot know yet

- How the Windows display scaling of your monitor renders the window (the sandbox screenshots were at 100%).
- Real timings with your RTX 4070 Super (the label and brief steps), and how the Windows voice sounds.
- Whether your antivirus or OneDrive holds files in the data folder (rc11 now waits for such files and
  never resets your settings because of them; the self-test's Windows lock tests show it).
- Real-news accuracy problems (merged stories, wrong headlines): the self-test saves the editions, and its
  "automatic read-through" lists candidates. They become regression fixtures in the next phase; rc11 does
  not tune them blindly.
