# Agent Reach

Agent Reach is a local-first daily intelligence app for Windows. It gathers public news and
trend signals, filters out noise, groups related reports into stories, measures which stories are
new or rising, and writes a short daily briefing with a local AI model. You read it as an ordinary
desktop window: what happened, why it matters, whether it is new or continuing, and where each
fact came from.

- **Local AI, no subscriptions.** Summaries are written by [Ollama](https://ollama.com) on your
  own PC (`llama3.1:8b` + `nomic-embed-text`). No paid or cloud AI API is used or needed.
- **Evidence first.** The model only words what the collected sources say. Every "why it
  matters" note is checked against the evidence: invented names, numbers or vague filler are
  dropped rather than shown.
- **Quality over quantity.** Stale articles, weak one-off trends and repeats of the same story
  are left out. If there is not enough good material, no edition is published and yesterday's
  stays on screen.

Agent Reach Daily is the desktop product; the original command-line trend report
(`python -m agent_reach`) is still available for power users.

## Quick start (Windows)

Requirements: Windows 10/11, Python 3.10 or newer (3.12 recommended, with "tcl/tk" ticked in the
installer), [Ollama](https://ollama.com/download), about 6 GB of disk space for the models.

Open PowerShell and run, from the project folder:

```powershell
cd "C:\Users\downt\Downloads\Agent Reach\src\Agent-Reach"
powershell -ExecutionPolicy Bypass -File .\Setup-AgentReachDaily.ps1 -PullModels -RegisterTask
```

The setup script creates the project environment (`.venv`), installs the requirements, checks
Ollama and downloads the two models when `-PullModels` is given, creates your data folder,
puts an **Agent Reach** shortcut on the Desktop and in the Start menu, and (with `-RegisterTask`)
registers the background refresh task. It never deletes anything. Add `-DryRun` to see every step
first. Leave out `-PullModels` if you already ran `ollama pull llama3.1:8b` and
`ollama pull nomic-embed-text`.

Then **double-click "Agent Reach"** on the Desktop. The first time, choose
**Collect today's news now**; on a PC without a graphics card the first edition takes roughly
10-40 minutes. You can keep the window open or close it: the refresh continues in the background.

## Using it every day

| What | How |
|---|---|
| Open the app | Desktop / Start-menu shortcut **Agent Reach**, or double-click `AgentReachDaily.pyw` (fallback: `AgentReachDaily.cmd`) |
| Refresh now | the **Refresh** button, F5 or Ctrl+R |
| Read the sources of a story | click a publisher name, or **Source details** under the story |
| Older editions | the **Edition** list (30 days are kept) |
| Search / filter | **Category** list, **Search** box (Ctrl+F, Esc clears) |
| Source health, timings, run details | **Details** (Ctrl+D) |
| Save today's edition as a web page | **Export** (Ctrl+E) |
| Preview the layout with sample stories | View > Demo edition (clearly marked DEMO, not real news) |

Command line (from the project folder):

```powershell
.\.venv\Scripts\python.exe -m agent_reach.daily                 # open the window (same as the shortcut)
.\.venv\Scripts\python.exe -m agent_reach.daily --refresh-now   # collect a new edition now
.\.venv\Scripts\python.exe -m agent_reach.daily --status        # due / last success / backoff, as JSON
.\.venv\Scripts\python.exe -m agent_reach.daily --check         # is Ollama running with both models?
.\.venv\Scripts\python.exe -m agent_reach.daily --export-html today.html
.\.venv\Scripts\python.exe -m agent_reach.daily --help          # everything else (task, reset, exit codes)
```

## How refreshing works

- **Daily cadence.** A new edition is due 24 hours after the *start* of the last successful
  refresh (Settings > Schedule can switch to a fixed US Central time such as 7:00 AM instead).
- **Background task (optional).** The scheduled task `AgentReachDaily-Refresh` runs hourly and
  at logon. It exits within a second when nothing is due, so news sites and your PC are not
  hammered. It runs only while you are logged on, never wakes the PC, and uses no administrator
  rights. A PC that is off or asleep cannot collect news; the refresh happens at the next chance
  (one refresh, not a catch-up burst).
- **When the window opens**, a due refresh starts automatically in the background.
- **Manual refresh** (button or `--refresh-now`) runs immediately, even if not due.
- **Only one refresh at a time.** Scheduled, automatic and manual refreshes share one
  cross-process lock; a crashed refresh can never leave it stuck.
- **Failures keep your edition.** If Ollama is down, the internet is out, too few sources answer
  or too few good stories are found, nothing is published, the previous edition stays on
  screen with a plain-language note, and automatic retries back off (30 min, 1 h, 2 h, ... up to
  6 h). Ollama is started automatically when it is installed but not running.
- **Editions are dated** by the US Central (CST/CDT) day on which the refresh started. A second
  successful refresh on the same day replaces that day's edition as a new revision.

## Your data

Everything lives in `%LOCALAPPDATA%\AgentReachDaily` (for example
`C:\Users\downt\AppData\Local\AgentReachDaily`), never in the project folder:

| Path | Contents |
|---|---|
| `cache\editions\YYYY-MM-DD.json` | the daily editions (kept 30 days; the newest is never deleted) |
| `cache\latest.json` | pointer to the newest edition |
| `settings.json` | your settings (Settings dialog) |
| `state\` | refresh history (last attempt vs. last success, backoff), the refresh lock, window size |
| `data\agent_reach.db` | SQLite history used to tell new / rising / continuing stories |
| `logs\` | `gui.log`, `refresh.log`, `scheduler.log` (rotating, about 6 MB each at most) |
| `diagnostics\` | details of the last 30 failed or unpublished refreshes |
| `exports\` | default folder for exported HTML editions |

## Privacy and cost

- All AI work runs locally through Ollama. Nothing is sent to OpenAI, Anthropic, Google or any
  other AI service, and no API key or subscription is needed.
- The internet is used to read public sources: publisher RSS feeds (BBC, NPR, The Guardian,
  ESPN by default), Google News and Google Trends RSS, Wikipedia's most-read list, Hacker News,
  and optionally Reddit, X trends (trends24.in), TikTok, GitHub Trending, Product Hunt and arXiv.
  Article pages are fetched to give the model context. Model downloads come from Ollama.
- Exported HTML files are self-contained (no scripts, no remote assets); only the article links
  need the internet.

## Troubleshooting

| Symptom | What to do |
|---|---|
| "Ollama is not running" | Start **Ollama** from the Start menu (the app also tries to start it). Check with `--check`. |
| "model(s) ... are missing" | `ollama pull llama3.1:8b` and `ollama pull nomic-embed-text`, or re-run setup with `-PullModels`. |
| "No news source responded" | You are offline or a firewall blocks the feeds. The previous edition is kept; it retries automatically. |
| A source shows PARTIAL or FAILED (Details) | Normal from time to time (Reddit and X often block automated readers). The edition is built from the rest and says what was missing. |
| "found too little news to publish" | Fewer than 3 good stories or fewer than 2 working sources. Wait for the automatic retry or press Refresh later. |
| Wrong date or time zone | Times are US Central (CST/CDT) on purpose. If times look wrong by hours, re-run setup: it installs `tzdata`, which Windows needs. |
| Background refresh never happens | Settings > Schedule shows the task status; **Enable / update** re-registers it. Check `logs\scheduler.log`. The task only runs while you are logged on. |
| "saved edition files are damaged" | Nothing to do: damaged files are skipped and moved to `cache\quarantine` at the next refresh; the newest good edition is shown. |
| The window does not open | Run `.\.venv\Scripts\python.exe -m agent_reach.daily` in PowerShell to see the error, and check `logs\gui.log`. |
| Start completely fresh | Settings > Storage > **Delete all cached editions**, or `--reset-cache --yes`. |

To remove the scheduled task and shortcuts (your editions and settings are kept):

```powershell
powershell -ExecutionPolicy Bypass -File .\Uninstall-AgentReachDaily.ps1           # add -DryRun to preview
powershell -ExecutionPolicy Bypass -File .\Uninstall-AgentReachDaily.ps1 -RemoveVenv -DeleteUserData   # everything
```

## Classic command-line report

The original pipeline still runs on its own and writes an ASCII executive report:

```powershell
.\.venv\Scripts\python.exe -m agent_reach                # one run with Ollama
.\.venv\Scripts\python.exe -m agent_reach --no-llm       # deterministic grouping, no Ollama
.\.venv\Scripts\python.exe -m agent_reach --loop --interval 30
```

It uses `agent_reach.db` in the current folder (or `AGENT_REACH_DB_PATH`) and `.env` settings,
independent of the Daily app. `run_agent_reach.ps1` is its one-shot setup + run script.

## How it works

```
public sources -> ingest -> clean / filter -> enrich (page context) -> embed + group (HDBSCAN)
  -> label (local model) -> score relevance + momentum -> daily selection (balanced, fresh, no repeats)
  -> grounded "why it matters" (local model + evidence check) -> edition store -> desktop reader
```

The model never decides which reports belong together (embeddings and deterministic evidence
checks do), never sees the web, and its output is checked before it is shown. Details:
[docs/architecture.md](docs/architecture.md) and [docs/reliability-v2.1.md](docs/reliability-v2.1.md).

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q                      # offline: fake feeds + fake model, no Ollama/network
.\.venv\Scripts\python.exe -m pyflakes agent_reach tests
.\.venv\Scripts\python.exe -m tests.replay_benchmark
```

Tests never touch the network or a real Ollama. `tests/daily_fakes.py` holds synthetic publisher
feeds (fictional places on `.test` hosts) and a deterministic fake model; `samples/DEMO-edition.json`
is the clearly labelled demo edition. Version: Agent Reach Daily 1.0 release candidate 1
(`python -m agent_reach.daily --version`).
