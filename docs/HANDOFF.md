# Handoff: Agent Reach Daily (state after 1.0.0rc9)

For a new Claude session picking up this project. Read `CLAUDE.md` first (commands, invariants,
conventions), then this file. `README.md` is the user guide; `docs/architecture.md` the internals.

## Where things stand

- **Branch:** `claude/loving-darwin-a7rqvs` (all work is pushed there; no PR has been opened, and
  none should be unless the user asks). Version `agent_reach/daily/__init__.py` = `1.0.0rc9`.
- **CI:** `tests.yml` is green on rc9 (320 tests with a display, 305 on Python 3.10, pyflakes clean).
- **The user** runs the app on Windows from `C:\Users\downt\Downloads\Agent Reach\src\Agent-Reach`,
  with Ollama (`llama3.1:8b`, `nomic-embed-text`) on their PC. A refresh takes about 5 minutes there.
  They receive each release as a zip (`git archive --format=zip --prefix=Agent-Reach/ HEAD`),
  extract it over the old folder, rerun
  `powershell -ExecutionPolicy Bypass -File .\Setup-AgentReachDaily.ps1 -RegisterTask`, and press F5.
  Their data folder is `%LOCALAPPDATA%\AgentReachDaily` (logs: `... menu > Open logs folder`).
- **User's standing constraints:** no paid APIs, cloud LLMs, Docker or new frameworks; local Ollama
  only; "finish the application we already have, do not turn it into a research project"; never
  claim untested results; commit and push to the branch above (authorized), nothing else remote
  without asking.

## Release history (one line each)

rc3 top 10 + per-category sections, macOS-like look. rc4 YouTube/TikTok, code review. rc5 Mastodon,
Bluesky, Wikipedia "In the news", 114 feeds. rc6 accuracy pass from a real edition (key-name gate,
filler, headlines, feed doctor, TikTok off). rc7 In brief, NEW/UPDATED/DAY tags, read state,
follow/mute. rc8 daily podcast (Windows System.Speech via PowerShell, espeak-ng fallback).
rc9 second accuracy pass from the real October 5 evening edition (below).

## rc9 in short (see the commit message and `tests/test_accuracy2.py`)

- `pipeline/clusterer.py` `LinkIndex`: a shared phrase counts once (`shared_units`); a rare-word link
  needs two units, one not just names/numbers (`_event_unit`); inner-capital words are names;
  trend fragments may not name another person (`fragment_fits`); headline amounts must appear in
  the reports (`quantities_grounded`).
- `daily/edition.py`: summary sentences need 60% source support (`support`, `member_text`), must be
  English (`looks_english`), "Sources:" prefixes stripped, better sentence splitting; Top Stories
  take corroborated stories first (`is_corroborated`, single-outlet needs relevance 9); `plural()`.
- `daily/brief.py`: details need support; "why it matters" may not restate (80%) or be vague.
- `pipeline/cleaner.py`: headlines keep their first sentence and balanced quotes.
- Settings v6 removes MIT News (both of its URLs failed). Feed errors show "HTTP 404 Not Found".
- HTML export numbers section stories consecutively, "Also in Top Stories" list.

## Validating with real data

The sandbox has no Ollama and no news access. Two ways to see real output:

1. **The user's export.** They send `AgentReachDaily-YYYY-MM-DD.html` (the ... menu > Export) and
   `logs\refresh.log`. Convert the HTML to text (strip tags) and read it story by story: mixed
   stories, invented sentences, wrong headlines, ranking.
2. **GitHub Actions.** `cloud-runner.yml` (workflow_dispatch) with input
   `entrypoint=agent_reach.daily` runs one real Daily refresh on a CPU runner and uploads
   `edition-<run>.html`, `report.txt`, `pipeline.log`, `daily-logs/`, `daily-diagnostics/` and
   `status.json`. Exit 0 = published, 20 = too little news, 31 = Ollama/model missing. The Daily
   data folder is cached under `state/daily`, so later runs have history. CPU runs are slow
   (expect 30-90 min); the job timeout is 120 min. `entrypoint=agent_reach` (default) runs the
   classic CLI report instead.

## Open items, in the order I would take them

1. **Check rc9 against real data** (an export from the user or a cloud-runner Daily run): did the
   phrase-unit rule split too much (real stories now single-source)? Did the 60% support rule drop
   good sentences (stories falling back to the excerpt lead)? Tune `SUPPORT_SHARE` /
   `rare_units` only with real examples, and add them to `tests/test_accuracy2.py`.
2. **Category mistakes:** Gizmodo's Antarctica sea-level story landed in Tech (publisher default).
   `clusterer._guard_category` could let strong science keywords override a publisher hint.
3. **Refresh speed:** about 5 min on the user's PC. Idea: reuse labels for stories whose membership
   did not change since the previous revision (skip the LLM call).
4. **Podcast:** never heard on real Windows yet; ask the user how it sounds. Ideas: Piper neural TTS
   (local), MP3, two voices.
5. Later ideas the user has seen: phone delivery (OneDrive folder / LAN page), deep briefs
   (Module 2, reads `PipelineReport` JSON only), notifications, archive search, weekly recap,
   mute publisher, installer.

## Working tips for this repo (to keep the context small)

- Run tests quietly: `python -m pytest -o addopts="" -q 2>&1 | tail -2` (pytest.ini adds `-q`;
  the refresh tests print INFO logs on failure, so always `tail`/`grep` the output).
- GUI tests need Xvfb: `Xvfb :99 &` then `DISPLAY=:99 python -m pytest ...` (restart Xvfb if GUI tests
  suddenly skip). `/opt/pwsh/pwsh` can parse-check `.ps1` files.
- Read large files by line range (`gui.py` is ~2,000 lines, `edition.py` ~900, `clusterer.py` ~1,300);
  use `grep -n` to find the place first.
- Screenshots are expensive: take one only to check a visual change, at a modest size.
- Keep a Python 3.10 check in the loop: `python3.10 -m venv` and run the suite there before a
  release (3.10 rejects backslashes inside f-string expressions; rc9 nearly shipped one).
