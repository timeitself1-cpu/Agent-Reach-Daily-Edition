# Agent Reach

Agent Reach is a local-first daily intelligence app for Windows. It gathers public news and
trend signals, filters out noise, groups related reports into stories, measures which stories are
new or rising, and writes a short daily briefing with a local AI model. You read it as an ordinary
desktop window: what happened, why it matters, whether it is new or continuing, and where each
fact came from.

- **Local AI, no subscriptions.** Summaries are written by [Ollama](https://ollama.com) on your
  own PC (`llama3.1:8b` writes; `nomic-embed-text` groups reports into stories). No paid or cloud AI API is used or needed.
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

Open PowerShell in the folder you extracted (the one that contains `Setup-AgentReachDaily.ps1`) and run:

```powershell
cd "$HOME\Downloads\Agent-Reach"   # your folder
powershell -ExecutionPolicy Bypass -File .\Setup-AgentReachDaily.ps1 -PullModels -RegisterTask
```

The setup script creates the project environment (`.venv`), installs the requirements, checks
Ollama and downloads the models when `-PullModels` is given, creates your data folder,
puts an **Agent Reach** shortcut on the Desktop and in the Start menu, and (with `-RegisterTask`)
registers the background refresh task. It never deletes anything. Add `-DryRun` to see every step
first. Leave out `-PullModels` if you already ran `ollama pull llama3.1:8b` and
`ollama pull nomic-embed-text`. Both models work with the Windows setup. Older default settings
migrate to `nomic-embed-text`; a custom grouping model remains your choice. Embedding models
do not appear in the Ollama app's chat model list.

Then **double-click "Agent Reach"** on the Desktop. The first time, choose
**Collect today's news now**; on a PC without a graphics card the first edition takes roughly
10-40 minutes. You can keep the window open or close it: the refresh continues in the background.

## Using it every day

| What | How |
|---|---|
| Open the app | Desktop / Start-menu shortcut **Agent Reach**, or double-click `AgentReachDaily.pyw` (fallback: `AgentReachDaily.cmd`) |
| Refresh now | the **Refresh** button, F5 or Ctrl+R |
| Read the sources of a story | click **Sources (N)** under the story to expand its articles |
| Older editions | the edition date list next to Search (30 days are kept) |
| Top 10 overall, then the top 10 of each category | the **Sections** sidebar: Top Stories, News, Tech, Science & AI, Sports, Entertainment, Internet Culture (Ctrl+1 to Ctrl+7) |
| Everything else (demo, data folder, model check, help) | the **...** button at the right of the toolbar |
| Listen to the news | **Listen** in the toolbar (or P): a 5-8 minute podcast of the top stories, recorded after every refresh. Settings > **Podcast** sets the voice, speed and length or turns it off |
| The day in ten seconds | **In brief** at the top of Top Stories: the lead sentence of the first five stories (click one to jump to it) |
| What is new | **NEW** and **UPDATED** tags (compared with the previous edition) and **DAY 3** on stories that have run for several days |
| Open a story's main article | click its headline (or press O); the story then shows as read (dimmed) |
| Move between stories | J (next) and K (previous), S shows the sources; every shortcut is under **...** > Keyboard shortcuts |
| Unread counts | the numbers in the sidebar count stories you have not opened yet; **...** > Mark all as read clears them |
| Follow or mute a topic | right-click a story > Follow / Mute a name in it, or Settings > **Topics** (one per line). Followed stories get a star and a **Following** section; muted ones are hidden everywhere |
| Search | **Search** box (Ctrl+F, Esc clears and returns to Top Stories) |
| What changed since the last refresh | **Details** > Changes (kept out of the reading view) |
| Source health, timings, run details | **Details** (Ctrl+D) |
| Save today's edition as a web page | **Export** (Ctrl+E) |
| Preview the layout with sample stories | **...** > Demo edition (clearly marked DEMO, not real news) |
| Choose publishers or YouTube channels, add a local outlet, test a feed | Settings (Ctrl+,) > **Publisher feeds** (Add feed, Edit, Turn on/off, Test, Restore defaults). For a YouTube channel, paste its `youtube.com/channel/UC...` address |
| Turn sources on or off (YouTube, TikTok, Reddit, X, ...) | Settings > **Sources** |
| Dark mode | Settings > **Appearance** (Match Windows, Light or Dark) |
| See which feeds and publishers fed today's edition | **Details** > Sources (per-feed health, collected, used) and Publishers |

Command line (from the project folder):

```powershell
.\.venv\Scripts\python.exe -m agent_reach.daily                 # open the window (same as the shortcut)
.\.venv\Scripts\python.exe -m agent_reach.daily --refresh-now   # collect a new edition now
.\.venv\Scripts\python.exe -m agent_reach.daily --status        # due / last success / backoff, as JSON
.\.venv\Scripts\python.exe -m agent_reach.daily --check         # is Ollama running with both models?
.\.venv\Scripts\python.exe -m agent_reach.daily --export-html today.html
.\.venv\Scripts\python.exe -m agent_reach.daily --export-sample daily-sample.json --stories 1,2,3,4,9
.\.venv\Scripts\python.exe -m agent_reach.daily --help          # everything else (task, reset, exit codes)
```

`--export-sample` writes a few stories of an edition (headlines, the app's summaries, source names and links,
no publisher article text) for the demo on getagentreach.dev: replace `daily-sample.json` in the website's
repository with it. Read the chosen stories first; only stories grouped correctly belong on the site.

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
  successful refresh on the same day replaces that day's edition as a new revision. Publication
  waits at least 60 minutes after the previous revision, except for a new Strong story in Top Stories' first
  three positions. A manual refresh still collects immediately, but cannot bypass this publication gate.
- **Calmer selection.** Eligible listed stories stay unless a replacement in their section scores at least
  20% higher. Stale, unsupported or newly excluded filler stories may leave. Sections can be shorter than
  ten; trailers, podcasts, mock drafts, debate clips and explainers need two independent publishers.
- **Summary checks.** Names and quantities must share a cited sentence context. A failed summary gets
  one regeneration, then a source title and extractive first sentence. These conservative text checks
  can reject valid paraphrases; they do not prove every statement true. Unresolved Google News links
  remain labelled via Google News. Export diagnostics are under the collapsed **Run details** section.

## Your data

Everything lives in `%LOCALAPPDATA%\AgentReachDaily` (for example
`C:\Users\<you>\AppData\Local\AgentReachDaily`), never in the project folder:

| Path | Contents |
|---|---|
| `cache\editions\YYYY-MM-DD.json` | the daily editions (kept 30 days; the newest is never deleted) |
| `cache\latest.json` | pointer to the newest edition |
| `settings.json` | your settings (Settings dialog) |
| `state\` | refresh history (last attempt vs. last success, backoff), the refresh lock, window size, and `events.json`: the event registry (which earlier event each story continues, kept 30 days; it only observes for now) |
| `data\agent_reach.db` | SQLite history used to tell new / rising / continuing stories |
| `logs\` | `gui.log`, `refresh.log`, `scheduler.log` (rotating, about 6 MB each at most) |
| `diagnostics\` | details of the last 30 failed or unpublished refreshes |
| `exports\` | default folder for exported HTML editions |
| `publish\` | website publishing: settings, last result, the encrypted access key (only if you set it up) |
| `updates\` | automatic updates: what the last check found, the files of the installed version, a backup of the files the last update replaced |

## Updates

From version 1.0 rc17 the app keeps itself up to date. When you open it, it asks GitHub whether a newer version
is out (a second or two; offline it simply opens). If there is one, a small window says "Updating Agent Reach
Daily..." while it installs, and the app opens on the new version with a line saying what changed. While the app
is closed, the hourly scheduled check does the same. Your editions, settings and website key are never touched.

- Only changed files are replaced; the previous ones are kept in the data folder's `updates\backup` until the next
  update. If the new version does not start, the old one is put back and the app opens as before.
- Python packages are installed only when a version needs new ones; if a version needs Setup to run once (for
  example a new local model), the app says so.
- **Turn it off:** set `"auto_update": false` in `settings.json` (or the environment variable
  `AGENT_REACH_NO_UPDATE=1`). Details (**...** > **Details**) show when the last check ran and what it found.
- Updates come from the `stable` branch of the app's GitHub repository, which moves only to releases that passed
  their tests.

## The daily podcast

After every successful refresh the app records a spoken edition: an introduction, the top stories
(headline, summary, "why it matters" and who reported them), a quick round of headlines from each
section and the topics you follow, then a sign-off. It reads only the edition's own text, so it says
exactly what the window shows, and it is spoken by the voices built into Windows: no download,
account or cloud service. Each podcast is saved as `podcasts\YYYY-MM-DD.wav` with a transcript
(`.txt`) in the data folder and kept for 7 days.

- **Listen** (toolbar, P, or **...** > Listen to the podcast) plays it in your default audio player.
- **...** > Record the podcast again re-records it (after changing the voice, for example).
- Settings > **Podcast**: on/off, voice, speed, how many stories are told in full, how long to keep them.
  More voices: Windows Settings > Time & language > Speech > Add voices.
- From PowerShell: `.\.venv\Scripts\python.exe -m agent_reach.daily --podcast` (add `--date 2026-10-05`
  for an older edition).

## Publishing to the website (optional)

Agent Reach Daily can put each new edition on [getagentreach.dev](https://getagentreach.dev) by itself: the
home page shows the newest edition, `/daily/2026-10-08/` keeps each date, and `/archive/` lists them all. It is
off until you switch it on, and it needs one GitHub access key, once:

1. On github.com: **Settings > Developer settings > Personal access tokens > Fine-grained tokens > Generate new
   token**. Repository access: **Only select repositories > timeitself1-cpu/Agent-Reach-Website**. Permissions:
   **Contents: Read and write** (nothing else). Pick an expiry you are comfortable with (a year, for example).
2. In the app: **...** > **Website publishing...**, paste the key, **Save key** (it tests the connection).
3. Tick **Automatic publishing**. From then on every successful refresh publishes its edition; nothing to copy
   or upload. **Publish latest edition** sends the current one now.

The window shows the last published edition, the last result ("Published successfully", "Publication failed:
previous edition preserved") and what the live site shows. Details: [docs/PUBLISHING.md](docs/PUBLISHING.md).

- **Only the news goes up:** headlines, the app's summaries, categories, coverage strength, New/Updated labels
  and each source's outlet, headline, link and time. Never publisher excerpts, logs, settings, file paths or
  anything about your PC. The PC only makes outgoing requests to GitHub; nothing listens for connections.
- **A failed upload changes nothing on the site**: an edition goes up as one commit or not at all, and the
  website keeps the previous edition. Retrying never creates duplicates. The app tries again by itself at its
  next hourly check (the scheduled task), so a short outage does not leave the site a day behind.
- **Corrections:** right-click a story > **Remove from the website...** (it stays off when a later refresh the
  same day finds that story again); or **Take this edition off the website...** in the publishing window.
- **The day's edition never gets thinner:** a later refresh of the same day replaces the edition (in the app and
  on the website) only if at least half as many sources answered and half as many stories came through; otherwise
  the edition stays and the app tries again later.
- **Key expiry:** a week before the access key expires, the publishing window and the refresh message say so;
  make a new key the same way and paste it.
- The key is stored encrypted for your Windows account in `publish\access-key.dat` in the data folder (never in
  the project folder). **Forget key** deletes it; revoke it on github.com if it may have leaked.

## Privacy and cost

- All AI work runs locally through Ollama. Nothing is sent to OpenAI, Anthropic, Google or any
  other AI service, and no API key or subscription is needed.
- The internet is used to read public sources, with no account or API key:
  - **112 publisher feeds from about 100 organisations**: world and US news (BBC, NPR, The
    Guardian, PBS, CBS, NBC, ABC, Fox News, New York Times, Washington Post, Al Jazeera, Le Monde,
    France 24, DW, Sky News, The Independent, Euronews, CBC, ABC Australia, South China Morning
    Post, The Japan Times, Times of India, Politico, The Hill, Axios, Vox, The Atlantic,
    ProPublica), business (CNBC, MarketWatch, Business Insider, Fortune, Yahoo Finance), technology
    and security (Ars Technica, The Verge, TechCrunch, Wired, Engadget, The Register, ZDNET,
    Gizmodo, 9to5Mac, MacRumors, Tom's Hardware, Android Authority, Techmeme, The Next Web, Fast
    Company, BleepingComputer, Krebs on Security, Lobsters), science and AI (NASA, ScienceDaily,
    Science, Nature, New Scientist, Phys.org, ScienceAlert, Space.com, Quanta, MIT Technology
    Review, MIT News AI, VentureBeat AI, Ars Technica AI, The Decoder, MarkTechPost, Simon
    Willison, Google AI, Google DeepMind, OpenAI, Hugging Face), sports (ESPN with NFL, NBA, MLB and
    soccer, BBC Sport and BBC Football, CBS Sports, Yahoo Sports, Sky Sports, Guardian Sport,
    Sporting News), entertainment and games (Variety, The Hollywood Reporter, Deadline, Billboard,
    Rolling Stone, Pitchfork, Collider, Screen Rant, IGN, Polygon, Kotaku, Eurogamer) and internet
    culture (The Daily Dot, Mashable, Tubefilter, Social Media Today, Boing Boing);
  - **22 YouTube channels** (BBC News, Reuters, AP, NBC, ABC, CBS, PBS, Al Jazeera, Sky News, CNBC,
    Bloomberg Technology, CNET, The Verge, Linus Tech Tips, Marques Brownlee, Fireship, NASA, ESPN,
    NFL, NBA, IGN, Entertainment Tonight) through their public channel feeds. YouTube retired its
    Trending page in 2025, so "trending" here means each channel's most-watched uploads of the
    last 72 hours, ranked by views per hour;
  - **Google News** top stories plus one section per category (World, U.S., Business, Health,
    Technology, Science, Sports, Entertainment), searches for artificial intelligence, space, video
    games and "TikTok / viral", and the AP and Reuters wires (which publish no RSS of their own);
  - **What people are sharing:** news links trending on Mastodon (mastodon.social), Bluesky
    trending topics, Reddit and X trends (trends24.in). TikTok trending hashtags are available but
    off: TikTok blocks automated readers, and viral news still arrives through Google News;
  - **Attention and curation:** Wikipedia's most-read articles and its curated "In the news"
    list, Google Trends and Hacker News. GitHub Trending, Product Hunt and arXiv are available but
    off.

  Each feed and channel has its own allowance and its own health line in Details, so adding feeds
  never squeezes the others, and you can add local outlets in Settings > Publisher feeds. Settings
  saved by an older version keep your own choices and gain the new feeds and sources once.
  Article pages are fetched to give the model context. Model downloads come from Ollama.
- Exported HTML files are self-contained (no scripts, no remote assets); only the article links
  need the internet.
- Website publishing is off unless you switch it on; then the public copy of each edition goes to GitHub
  (see "Publishing to the website").

## Troubleshooting

| Symptom | What to do |
|---|---|
| "Ollama is not running" | Start **Ollama** from the Start menu (the app also tries to start it). Check with `--check`. |
| "model(s) ... are missing" | `ollama pull llama3.1:8b` and `ollama pull nomic-embed-text`, or re-run setup with `-PullModels`. |
| "No news source responded" | You are offline or a firewall blocks the feeds. The previous edition is kept; it retries automatically. |
| A source shows PARTIAL or FAILED (Details) | Normal from time to time (Reddit and X often rate-limit automated readers). The edition is built from the rest and says what was missing. Expand "News feeds", "YouTube" or "Google News" in Details to see which feed, channel or section failed and why. |
| A publisher feed keeps failing | Feed addresses move. Settings > Publisher feeds > select it > **Test**; then Edit the address or turn the feed off. |
| TikTok, Bluesky or Mastodon shows FAILED | TikTok blocks many automated readers (it is off by default; turn it on in Settings > Sources to try); the Bluesky and Mastodon public APIs occasionally change or rate-limit. Nothing is lost: viral and TikTok news still arrives through the Google News "TikTok / viral" section. |
| "N feeds have not worked for 3 days or more" | The feed doctor noticed feeds that failed in every refresh for 3+ days. Open Settings > Publisher feeds: failing feeds say "Failing since ..."; **Test** one, Edit its address, or press **Turn off failing feeds**. |
| A refresh takes too long | Each refresh groups and summarizes up to 260 articles. On a PC without a graphics card, lower "Articles grouped and summarized per refresh" in Settings > Sources (for example to 150), or turn off feeds you do not read. |
| "did not publish a new edition" | The banner says why: fewer than 3 good stories, fewer than 2 working sources, or the local model stopped answering partway. The previous edition is kept; wait for the automatic retry or press Refresh later. |
| "stopped responding and was ended" | A refresh hung (for example a stuck network or disk call) and was ended after the time limit plus 25 minutes. `diagnostics\*-watchdog.json` shows where it hung; send it with `logs\refresh.log`. |
| Wrong date or time zone | Times are US Central (CST/CDT) on purpose. If times look wrong by hours, re-run setup: it installs `tzdata`, which Windows needs. |
| Background refresh never happens | Settings > Schedule shows the task status; **Enable / update** re-registers it. Check `logs\scheduler.log`. The task only runs while you are logged on. |
| "saved edition files could not be read" | Usually nothing to do: damaged files are skipped and moved to `cache\quarantine` at the next refresh, and the newest good edition is shown. A file that is only open in another program (a backup or sync tool) is left alone and read again later. |
| "settings could not be read just now" | Another program (OneDrive, a backup tool, an editor) holds `settings.json`. Nothing was changed; close that program or wait a minute. Refreshes wait until the file can be read. |
| The window does not open | Run `.\.venv\Scripts\python.exe -m agent_reach.daily` in PowerShell to see the error, and check `logs\gui.log`. |
| Where are the logs? | In the app: **...** menu > **Open logs folder**. Or paste `%LOCALAPPDATA%\AgentReachDaily\logs` into the File Explorer address bar (the AppData folder is hidden by default). Refreshes write `refresh.log`; the window writes `gui.log`. |
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
.\.venv\Scripts\python.exe -m agent_reach --sources youtube google_news hackernews   # pick sources
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

On your own PC, `powershell -ExecutionPolicy Bypass -File .\Test-AgentReachDaily.ps1` runs the self-test
with the real Ollama and real news in a scratch folder (your data folder is only read) and leaves a zip of
the results on the Desktop; see [docs/WINDOWS-TEST-RC11.md](docs/WINDOWS-TEST-RC11.md).
`powershell -ExecutionPolicy Bypass -File .\Benchmark-Embeddings.ps1 -PullModels` first compares the embedding
models for story grouping (nomic-embed-text, EmbeddingGemma 2 270M and the full model) on labelled real
editions, then runs the same self-test; send back both zips from the Desktop.

Tests never touch the network or a real Ollama. `tests/daily_fakes.py` holds synthetic publisher
feeds (fictional places on `.test` hosts) and a deterministic fake model; `samples/DEMO-edition.json`
is the clearly labelled demo edition. Version: Agent Reach Daily 1.0 release candidate 17
(`python -m agent_reach.daily --version`). What changed in each release: `docs/RELEASE-NOTES.md`.

## License and contact

Agent Reach is open source under the MIT License (see `LICENSE`). Website: https://getagentreach.dev.
Questions: hello@getagentreach.dev or GitHub issues.
