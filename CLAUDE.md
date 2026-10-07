# Agent Reach: guide for Claude

This file is the project's long-term memory: conventions, file map, workflow and the user's standing
instructions. It is loaded automatically in every session, so keep it current and do not rely on chat
history. When a convention or instruction changes, change it HERE in the same commit.

## Start of every session (do this first)

1. Read **`docs/PLAN.md`**: the roadmap, the current phase and the first unchecked sub-task. Continue
   from there unless the user asks for something else.
2. Skim `docs/HANDOFF.md` ("Where things stand") for history and context, and `docs/REAL-EDITION-FINDINGS.md`
   when the work touches edition quality.
3. Work one sub-task at a time. **After each sub-task: tick it in `docs/PLAN.md`, add a line to its Progress
   log (date, commit, result, what is next), then commit and push.** A new session must be able to resume
   from PLAN.md alone.
4. If the user sends files (a self-test zip, an HTML export, logs), unzip into the scratchpad, read the
   report first, and record real-data findings in `docs/REAL-EDITION-FINDINGS.md` + fixtures (below).

## The product

Agent Reach has two surfaces: **Agent Reach Daily** (`agent_reach/daily`), a Windows desktop daily-news
reader built on the pipeline, and the classic CLI report (`python -m agent_reach`). `README.md` is the user
guide, `docs/architecture.md` the internals, `docs/RELEASE-NOTES.md` what changed per release.

The pipeline is **Module 1** of a modular trend-intelligence system. It ingests trend signals from 10+
sources, filters noise, enriches items with page content, groups them into events (embedding neighbours +
an explicit same-event gate), has a local LLM
(`llama3.1:8b` via Ollama) label the groups, scores relevance and velocity, and writes an ASCII executive
report plus SQLite history. The Daily app turns one validated run into a dated edition (Top Stories +
category sections), a grounded "why it matters" pass, an HTML export and a spoken podcast.

## The user, delivery and standing instructions

- Runs the app on **Windows 11** (RTX 4070 Super, 2560x1440 at 100%) from
  `C:\Users\downt\Downloads\Agent Reach\src\Agent-Reach`, Python 3.12 venv in `.venv`, Ollama 0.40 with
  `llama3.1:8b` and `nomic-embed-text` (rc12 asks for `embeddinggemma-2:270m` too; nomic is its fallback; Ollama
  runs EmbeddingGemma 2 on Macs only so far: "requires MLX support" on Windows, Oct 7; `embeddinggemma:300m`
  downloads but Ollama 0.40.0 cannot open it there, symlink bug ollama/ollama#18847). Data folder: `%LOCALAPPDATA%\AgentReachDaily` (never touch it from
  tests; the self-test only reads it). A real refresh takes about 6 minutes there.
- **Constraints:** local-model-first; no paid APIs, cloud LLMs, hosted services, telemetry, accounts,
  Docker or new frameworks. "Finish the application we already have, do not turn it into a research
  project." **Never claim untested results**: say what ran where (sandbox, CI, the user's PC). Never
  simulate success for something that needs their machine; prepare the harness, give the exact command.
- **Branch:** `claude/affectionate-galileo-isxik1` (rc11+). Committing and pushing there is authorized.
  No pull requests unless asked; nothing else remote without asking.
- **Delivery:** each release goes to the user as a zip of the repository:
  `git archive --format=zip --prefix=Agent-Reach/ -o <scratchpad>/Agent-Reach-Daily-v1.0rcNN<letter>.zip HEAD`
  sent with SendUserFile (display "attach"). Letters (rc11b, rc11c, rc11d) mark rebuilds of the same
  version; bump `agent_reach/daily/__init__.py` (`__version__`, `VERSION_LABEL`), README and
  RELEASE-NOTES for a new rc. The user extracts it over the folder and runs
  `powershell -ExecutionPolicy Bypass -File .\Setup-AgentReachDaily.ps1 -RegisterTask`.
- **Real-data validation on the user's PC:** `powershell -ExecutionPolicy Bypass -File .\Test-AgentReachDaily.ps1`
  (`tests/daily_selftest.py`) leaves `AgentReach-selftest-<time>.zip` on their Desktop: `report.txt`
  (PASS/FAIL per check, written after every check), real editions (`edition.json`, `edition-2.json`, `.txt`,
  `.html`), refresh logs, the model-drop log, `pytest-output.txt` from Windows. Guide and by-hand checklist:
  `docs/WINDOWS-TEST-RC11.md`.
- **Real editions are the test material.** Do not tune thresholds blindly. Each problem seen in a real
  edition goes into `docs/REAL-EDITION-FINDINGS.md` (edition, story number, quote) and, when concrete, into
  `tests/fixtures/real/*.json` + `tests/test_real_editions.py` (a regression test when fixed, a
  `pytest.mark.xfail(strict=True)` test when open, so a fix flips it). Strip nothing but check fixtures for
  personal data first (`grep -iE "downt|@gmail"`).
- User-facing text (banners, notes, release notes) is plain English for a non-developer: what happened and
  what to do, no stack traces, no internal names.

## Commands

```bash
pip install -r requirements-dev.txt     # runtime deps + pytest + pyflakes
python -m pytest                        # offline suite (~2.5 min): mock HTTP + fake Ollama, real HDBSCAN/trafilatura/SQLite
python -m pyflakes agent_reach tests    # must be clean
python -m agent_reach --no-llm --help   # CLI smoke test
python -m agent_reach.daily --help      # Daily CLI smoke test
python -m tests.replay_benchmark        # offline reliability replay
python -m tests.embedding_benchmark     # event-identity scores on the labelled Oct 7 corpus -> docs/eval/ (--ollama: real models)
python -m tests.html_fixture <export.html> <out.json>   # an exported edition page -> fixture
python -m tests.daily_selftest --world --skip-pytest  # dry run of the Windows self-test harness (fake world)
```

**Cloud-sandbox setup for the full suite** (the default Python 3.13 here has NO tkinter, so the GUI test
file is skipped silently as "1 skipped"; always run with `-rs` and check):
```bash
apt-get install -y python3-tk                         # gives /usr/bin/python3.12 with Tk 8.6
/usr/bin/python3.12 -m venv <scratchpad>/venv312 && <scratchpad>/venv312/bin/pip install -q -r requirements-dev.txt
xvfb-run -a <scratchpad>/venv312/bin/python -m pytest -q -o addopts="" -rs   # expect 0 GUI skips
uv python install 3.10   # CI also runs 3.10 (it has Tk): $(uv python find 3.10) -m venv ...
```
Screenshots: `xvfb-run -a -s "-screen 0 1366x768x24" python script.py` + ImageMagick
`import -window root shot.png` (a script that builds `DailyWindow` with a no-op spawner). PowerShell parse
check: download PowerShell 7 (linux-x64 tarball from the PowerShell GitHub releases) to `/opt/pwsh` and use
`[System.Management.Automation.Language.Parser]::ParseFile`.

Every change must leave `pytest` green (with Tk) and `pyflakes` clean. `.github/workflows/tests.yml` runs
both on Python 3.10 and 3.12 under `xvfb-run`, plus the replay, the CLI smoke tests and the self-test dry
run, on every push. Check CI after pushing (GitHub MCP `actions_list` / `get_job_logs`).

## File map

```
agent_reach/
  config.py            Settings (AGENT_REACH_* env vars, safe defaults)       models.py  PipelineReport contract
  main.py              run_once(): ingest -> clean -> enrich -> cluster -> score -> persist (invalidates on any stop)
  ingestion/           base.py (BaseIngester.run never raises, retries, pacing) + news, search, social, tech, video
  pipeline/            cleaner.py (filters, normalize/sanitize, SENTENCE_RX, roundups/live blogs)
                       embeddings.py (event representation, Ollama embeddings, model+digest-aware cache, fallback)
                       event_identity.py (IdentityGate ACCEPT/REJECT/NEUTRAL + reasons, cohesive_groups, kNN)
                       density.py (HDBSCAN, legacy cluster_method=density)  clusterer.py (LinkIndex evidence,
                       coherence, key-name gate, model labels, connection_lost circuit breaker, clip_words)  scorer.py (relevance, momentum)
                       enricher.py (page context, SSRF guard)  evidence.py
  storage/db.py        SQLite history (runs valid/invalid/running, items, clusters, snapshots)
  daily/
    app.py             AppController: everything the window shows, no Tk (activity via OS-lock probe, snapshot,
                       banners, cancel). Business logic goes here.        gui.py  Tk view only (DailyWindow,
                       Details, Settings, FeedDialog; SMOKE_ENV hook for the self-test)
    refresh.py         the worker: due check -> lock -> repair -> attempt -> publish; Watchdog; FileUnavailable
    edition.py         DailyEdition schema, story building, sentence gates (support, numbers, unstated remarks),
                       selection (Top Stories/sections), coverage notes, publication decision
    brief.py           grounded "why it matters"/details pass    changes.py  what changed vs previous edition
    store.py           atomic dated editions + latest pointer, repair/quarantine   state.py  attempt vs success, backoff
    prefs.py           settings.json (migrations v1..v8, load strict/non-strict)   feeds.py  default feeds, feed test
    lock.py            OS byte-range refresh lock   fsutil.py atomic writes, read retry   paths.py data layout
    feedhealth.py      feed doctor (channel_outage)  reading.py  read state, follow/mute, In brief, Day N
    strength.py        evidence strength   podcast.py  Windows System.Speech / espeak   render_html.py  export
    prereqs.py         Ollama checks/start   scheduler.py  Task Scheduler XML   timeutil.py  Central time, DST
tests/
  fakes.py, daily_fakes.py   mock sources + fake Ollama; synthetic feeds on .test hosts + fake daily model
  daily_world.py       the REAL worker command in that fake world as its own process (AR_WORLD_* switches:
                       model delay, model dies after N calls, model down, run limit, hang at stage, watchdog)
  test_daily_processes.py   real processes: cancel, kill, hang/watchdog, time limit, model drop, stale pid, damage
  test_daily_windows.py     Windows only: real file locks (CreateFileW no-share), read-only, TerminateProcess
  test_real_editions.py     fixtures from the user's real editions (regressions + strict xfails)
  event_corpus.py      labelled real editions (fixtures/real/event_gold.json) + pairwise P/R/F1, false merges
  test_identity_gate.py     no false merges / no bridges on that corpus; named October 7 cases
  embedding_benchmark.py    rc11 vs gate (offline) and nomic vs EmbeddingGemma (--ollama); Benchmark-Embeddings.ps1
  html_fixture.py      exported edition HTML -> fixture JSON
  daily_selftest.py    the self-test the user runs (Test-AgentReachDaily.ps1); --world = dry run here
docs/  PLAN.md (roadmap, live)  HANDOFF.md (history, state)  RELEASE-NOTES.md  REAL-EDITION-FINDINGS.md
       WINDOWS-TEST-RC11.md  architecture.md  reliability-v2.1.md  eval/identity-eval.{md,json}
Setup-AgentReachDaily.ps1  Test-AgentReachDaily.ps1  Benchmark-Embeddings.ps1  Uninstall-AgentReachDaily.ps1
AgentReachDaily.cmd/.pyw
```

## Environment limits (cloud sessions)

- **No Ollama or live data here.** The sandbox has no Ollama and cannot reach most source sites (YouTube is
  blocked by the egress proxy), so never try a live run. Verify with the offline tests and the fake world;
  real data comes from the user's self-test zip or the cloud runner.
- **Cloud runner.** `.github/workflows/cloud-runner.yml` (`workflow_dispatch`) installs Ollama on a CPU
  runner; input `entrypoint=agent_reach.daily` runs one real Daily refresh (80 articles, slow: 30-90 min).
- **`.ps1` scripts run on Windows PowerShell 5.1** and must stay ASCII-only with CRLF line endings
  (`.gitattributes`: `* text=auto`, LF in the repo, CRLF checkout for .ps1/.cmd/.bat). Write them with
  Python `newline=''` and explicit `\r\n`. Keep `$ErrorActionPreference = "Continue"` with explicit
  `$LASTEXITCODE` checks. Avoid PowerShell 7-only syntax (`??`, ternary `? :`, `&&`).
- Windows-only code paths (msvcrt locks, TerminateProcess, os.startfile, winreg, pythonw) cannot run here:
  write a `skipif(sys.platform != "win32")` test and let the self-test run it on the user's PC.

## Invariants: do not break these

1. **Item ledger balances.** `ingested == sum(discarded[reason]) + clustered`, in raw-item units (`CleanedTrendItem.raw_weight`). Every dropped item goes into exactly one named bucket (`models.DISCARD_STAGES`). `ClusterOutcome.assert_partition` and `PipelineAccounting` enforce this; tests assert it.
2. **The LLM never decides grouping.** Embeddings only propose candidate neighbours (`pipeline/embeddings.py`; lexical candidates when no model answers); the same-event gate decides membership (`pipeline/event_identity.py`): never single-link chaining, never a merge across a refused pair, a strict majority of supporting pairs, a false split before a false merge. The LLM only labels groups.
3. **Outliers are noise.** They are dropped, never forced into a mixed cluster.
4. **Entity isolation.** A cluster must be connected by distinctive shared tokens, a literally shared entity, or entities that co-occur in another item of the run (`LinkIndex`), and every member must mention one of the cluster's key names (`_key_name_gate`, names learned from the run's text). A phrase both titles share ("Supreme Court") counts once (`LinkIndex.shared_units`), and names alone never link two full titles. An LLM entity list or headline alone is never evidence.
5. **No filler.** `[INSUFFICIENT_DATA]`, placeholder summaries (`FILLER_RX`), the model's remarks about its input (`edition.UNSTATED_RX`) and relevance <= 3 are dropped before the report. In the Daily app every summary sentence must be supported by the story's own sources (`edition.support`, 60% of content words) and be English.
6. **Ingesters never raise.** `BaseIngester.run()` returns `([], SourceStat(ok=False, ...))` on any failure. Reddit and TikTok use a 5 s timeout, 403/429 backoff retries and at least 2 s pacing.
7. **Output contract.** `PipelineReport` (`schema_version`) is consumed by future modules. Changing or removing fields requires bumping `schema_version`; adding optional fields does not (rc11 added `label_calls`, `label_calls_failed`).

## Daily app invariants

8. **No edition beats a bad edition.** A refresh that fails, finds too few sources/stories, has an invalid ledger, or whose model stopped for half or more of the labelling (summaries become "extractive") never touches the last published edition when AI summaries are required; it records the attempt, backs off and writes a diagnostics file.
9. **Attempt is not success.** `last_attempt_*` and `last_success_*` are separate; due times anchor on the last successful refresh START. Publication time is shown only when a source stated it (`published_at_utc`); retrieval time is never presented as publication time.
10. **One refresh at a time** via the OS byte-range lock in `daily/lock.py`; never a boolean flag. The window decides "a refresh is running" from its own child process or the OS lock, never from a pid in a file alone (a pid can belong to another program after a reboot; Cancel must never stop a non-worker).
11. **Model text is grounded or omitted.** Brief-pass output must pass `daily/brief.grounded`; failures leave the story with its validated summary. The model never sees the web and never decides membership.
12. **The GUI renders plain text.** Source/model text goes into Tk Text as text; only `safe_url` (absolute http/https) links open. HTML export escapes everything and loads no remote assets.
13. **User data lives outside the repo** (`%LOCALAPPDATA%\AgentReachDaily`); the demo edition is never written to the news cache. A file another program holds (antivirus, OneDrive) is never treated as damaged: no rename, no reset to defaults (`fsutil.FileUnavailable`).
14. Keep business logic in `daily/app.py` (testable without Tk); `daily/gui.py` is the view. Tk is only touched from the Tk thread: background work reports through queues or a polled thread, never `root.after` from another thread.
15. **Nothing hangs for ever.** The refresh has a time limit and a watchdog (`refresh.Watchdog`, limit + 25 min) that records the outcome and exits; the first refused model connection ends model calls for that run (`clusterer.connection_lost`).

## Conventions

- Python 3.10+ with `from __future__ import annotations`, Pydantic v2 and `httpx` (the only HTTP client). No LangGraph, aiohttp or other new frameworks without a clear need.
- Surgical, targeted changes over rewrites. Keep the module layout. Complete code only: no placeholders or TODOs. Match the surrounding comment style (comments cite the real case that motivated a rule, with its date).
- Report output is ASCII only. Titles and summaries go through `normalize_text`, `sanitize_summary` and `sanitize_headline`.
- Every behaviour-changing setting lives in `config.py` (`AGENT_REACH_*` env vars) or `daily/prefs.py` (with a settings migration step when a default changes) with a safe default.
- Every behaviour change gets a test; process-level behaviour gets a `test_daily_processes.py` scenario in the fake world; a bug found in a real edition gets a fixture-based test.
- Commits: one topic each, a subject line plus a body that says what was wrong and why the fix is right, ending with the attribution lines the session provides. Keep refactors (e.g. line endings) out of fix commits.
- Never commit `.env`, `*.db`, `.venv/`, `reports/` or `state/` (see `.gitignore`).

## Known open items (details and order: docs/PLAN.md)

- **Within a run, one story = one event since rc12** (rc12d: 1 false merge on the 9-edition labelled corpus offline,
  two RTX Spark laptops, strict xfail; each PC round's live editions had 26, fixed in rc12b and rc12d). The corpus
  runs are small (~90 reports): rarity caps behave differently in a real run of ~1,300, so rebuild real proportions
  in a test when a live false merge does not reproduce offline (`test_a_common_name_and_one_word_need_the_embedding_too`). EmbeddingGemma 2 cannot run on the PC yet:
  Ollama publishes it for Apple's MLX only (newest Ollama on Windows: "this model requires MLX support"). The
  benchmark compares nomic with `embeddinggemma:300m` (first EmbeddingGemma) instead, once Ollama can open it on
  Windows; it joins the fallback chain only if its numbers beat nomic. Real numbers so far are nomic only; thresholds `identity_candidate_cosine` /
  `identity_strong_cosine` stay untuned until gemma's cosines are measured (`--replay` the saved vectors here).
- **Story identity across refreshes** is the biggest quality gap: editions minutes apart disagree (the #1
  story can vanish), NEW/"what changed" is mostly noise, one event can appear in two sections. The user's
  PC has `agent_reach/daily/events.py`, `agent_reach/pipeline/identity.py` and `tests/test_event_*.py` that
  are NOT in this repository (other work on exactly this); ask where it lives before building it.
- Thin single-outlet and promotional/evergreen items fill the category sections; some leads do not say what
  happened; "why it matters" is accepted for 0-2 of ~18 stories.
- Momentum is uncertain for a day after any feed-list change (the scorer compares the whole configuration).
- Each exact embedding model (tag + Ollama digest) is its own space: never reuse or compare vectors across
  models; bump `EVENT_REPR_VERSION` when the embedded text changes.
- Google News links are redirect pages with no article text; Reddit is mostly blocked (429/403); YouTube
  channel feeds have whole-site outages (treated as one outage since rc11).
- `AgentReachDaily.pyw` double-click did not open the window on the user's PC (shortcuts and .cmd do).

## Roadmap

`docs/PLAN.md` is the live, step-by-step plan. Longer term: **Module 2, Agent Depth** (reads `PipelineReport`
JSON only, fetches 3-5 sources per top trend, checks agreement, writes cited `TrendBrief` records; never
imports Agent Reach), **Module 3** delivery and watchlists, **Module 4** actions.
