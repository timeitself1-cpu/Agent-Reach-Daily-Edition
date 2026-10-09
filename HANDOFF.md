# Handoff: where Agent Reach stands (end of session, October 8, 2026)

For a fresh Claude Code session: the current state, and how to resume.
- Permanent rules: `CLAUDE.md`.
- The roadmap: `BUILD.md`.
- Step-by-step sub-tasks: `docs/PLAN.md`.
- History up to rc12: `docs/HISTORY.md`.

## Purpose and vision

Agent Reach Daily is a local-first Windows app. Every day it reads public reporting (112 publisher feeds,
22 YouTube news channels and 8 other source types), groups the reports about each event into one story, and
summarizes it with a local model (Ollama, `llama3.1:8b`; no cloud AI). It then publishes a dated edition.
getagentreach.dev shows those editions publicly.

The long-term aim: Agent Reach tells you **what happened, what changed, and which sources support it**. It
tracks each real-world event over time (timelines), and later feeds structured event data to downstream agents
(Module 2 "Agent Depth").

## Release and repository state

- **Oct 9, branch `claude/sleepy-clarke-abilea` (from the default branch at PR #12):** the user's website
  improvement plan (four phases; Phase 1 items 1-3 done here). The Local section is removed: **rc19 released**
  (stable -> 90f6e5a after CI green, at the user's go-ahead; the PC installs it at the next window start or hourly
  check; no real refresh with rc19 seen yet). The website side is on the site repo's branch
  `claude/sleepy-clarke-abilea` (nav Today / How it works, Local only in old editions, `/local/` deleted at the
  user's request, archive update numbers), **merged** as site PR #12 (31150b0; PR checks and the `main` checks
  green; whether Cloudflare serves the new navigation is for the user to look at). Next: Phase 1 items 4-10,
  mostly already on the site; confirm with the user what the live site shows. Most items of the user's Phase 1 list (archive,
  About, RSS, sitemap, share/copy links, corrections section, theme toggle, search) already exist on the site.
- **Current release: rc18** (`1.0.0rc18`, Oct 9): Local section for Frisco, TX (`pipeline/local.py`), headline
  links in the public edition, and the Phase 1/2 quality work of PR #8; delivered through `stable` (no zip, no
  Setup). Earlier: rc17 (`1.0.0rc17`): the app updates itself from branch `stable` (`daily/updater.py`); the
  user installs this one zip by hand (`Agent-Reach-Daily-v1.0rc17.zip`), later releases arrive by themselves
  (release rule in CLAUDE.md "Delivery"). rc16 = audit round 2 Step A; rc15 runs on the PC since Oct 8.
- **Update channel:** branch `stable` of this repository = the newest released commit (moved only after CI green).
- **Branch:** `claude/great-hawking-t1h2cl` (rc15; fast-forwarded from rc14's `claude/sweet-ramanujan-xj36o5`).
- **Code commit (rc14):** `7cd47e7`, CI green. rc15's commits are on the branch (`git log`).
- **Front end:** the user has ChatGPT changing the website (mobile layout, search clarity and recovery) since
  Oct 8. The data contract it builds on is in `docs/BACKEND-AUDIT.md` (PLAN B8 writes `docs/PUBLIC-DATA.md`).
- **Default branch** `claude/loving-darwin-a7rqvs` (what GitHub visitors download): **PR #4 merged** on
  Oct 8 as `9674c46` (squash). It brought rc13c: publishing, RSS, sitemap, search data, and the Phase 2.1
  answer key.
  - **rc14 and rc15 are NOT on the default branch.** They need a new PR when the user asks. Do not merge
    unreviewed work.
- **Website repo** `timeitself1-cpu/Agent-Reach-Website`, branch `main`, head `8161be5` (archive search). The
  user reported the news-first site live (Oct 8). This sandbox cannot reach getagentreach.dev.

## Architecture in one screen

```
refresh worker (daily/refresh.py, holds the OS lock)
  -> pipeline (agent_reach/main.py: ingest -> clean -> enrich -> group [embeddings + identity gate] -> label [LLM] -> score)
  -> edition (daily/edition.py) -> saved atomically (daily/store.py, one file per date, last revision wins)
  -> registry.record_edition  (daily/registry.py: observe only, never fails the refresh)        [rc14]
  -> publish_after_refresh    (daily/publish.py: opt-in, one GitHub commit, never fails the refresh)
  -> podcast (optional)                                                     [rc15: after the website]
scheduled check every hour (--refresh-if-due): refresh when due, else publish.catch_up        [rc15]
window (daily/gui.py, view only) <- daily/app.py (all logic the window shows)
```

The full file map is in `CLAUDE.md`; the internals are in `docs/architecture.md`.

## What works (in the repository, tested)

**Publishing** (rc13 to rc13c, merged). Each publication is one atomic commit containing:
- `editions/DATE.json` and `daily/DATE/index.html`;
- `editions/index.json`;
- `feed.xml` and `sitemap.xml`;
- `search/YYYY-MM.json`.

Retries make no commit. Withdraw and story removal work. The access key is stored with DPAPI. The guide is
`docs/PUBLISHING.md`.

**Website:** news-first pages, story pages with sources split into independent reports, repeats and signals,
the archive, RSS, the sitemap, and `/search/` (runs in the browser, newest 6 months first).

**Event registry (rc14, record-only):** `state/events.json` in the data folder.
- Per event: a stable id, first and last seen, report keys, key names, a word profile, and appearances with
  tier, confidence and reason.
- Matching:
  - more than 50% of the story's reports shared, plus wording agreement;
  - or tf-idf wording with a rare word that is not a name;
  - names never match alone;
  - a close second candidate means the story is kept apart, with its candidates listed.
- **Nothing the user sees uses it yet.** The design is in `docs/EVENT-IDENTITY.md`.

## Benchmark (October 7 only, one day)

| | Precision | Recall |
|---|---|---|
| Held-out pairs 6 h+ apart (the four evening editions), registry | **0.991** | **0.898** |
| Same pairs, today's `changes._match` | 0.989 | 0.703 |
| Consecutive held-out pairs, registry | 0.966 | 0.956 |
| Consecutive held-out pairs, today's matcher | 0.967 | 0.978 |

- The target (precision ≥ 0.99, recall ≥ 0.90) is not met. It stays a strict xfail in
  `tests/test_cross_edition.py`.
- The held-out set holds out stories, not events. The editions all come from one day.
- **Do not present these as production performance.** Reproduce with `python -m tests.cross_edition`.

## Not done, and not to be claimed

- **The rc14 Windows self-test has NOT been run by the user.** No multi-day data exists in the repository.
- **Multi-day validation is NOT done.** The answer key covers one day (12 editions of October 7).
- Website publishing from the PC works (Oct 8, rc15): key saved, first publication by hand reached the site
  repo (commit 90e605c, Oct 8 r2). The first AUTOMATIC publication after a refresh is not yet confirmed.
- DPAPI key storage is untested on Windows; its test runs in the self-test.

## Known limitations and open issues

**Matching:**
- The registry's remaining false continuations come from stories already mixed inside one run (golf-club vs.
  forces' "retreat"; French PM vs. a mayor). This is within-run grouping, the rc12 gate's job.
- Misses: the same event with entirely different wording; an event told twice in one edition.

**Churn**, independent of matching (October 7):
- events still in the next edition: 44% between consecutive editions, 16% 6 hours or more apart;
- Top Stories again top: 48% and 15%.

The cause is in collection and selection (PLAN 2.2), not yet diagnosed.

**Other:**
- Each date keeps only its last revision on the PC, so intraday history exists only in the registry.
- Older quality items (generic shared phrases, misattributed quotes, weak "why it matters", category hints,
  momentum after feed changes) are listed in `docs/HISTORY.md` "Open items" and `docs/REAL-EDITION-FINDINGS.md`.
- Windows: the `.pyw` double-click does not open the window; one real scheduled morning is unverified; the
  podcast has never been heard on Windows.

## How to resume (next task: multi-day event identity validation)

1. Read `CLAUDE.md`, then this file, `BUILD.md` Phase 2, `docs/PLAN.md` 2.1b to 2.5, and
   `docs/EVENT-IDENTITY.md`.
2. Branch: `git fetch origin && git checkout claude/sweet-ramanujan-xj36o5`. If a PR of rc14 was merged
   meanwhile, restart the branch from the default branch first.
3. Sandbox setup for the full suite (Tk) is in `CLAUDE.md` "Commands". The baseline is 510 passed, 5
   Windows-only skips, 7 xfailed.
4. **When the user sends the rc14 self-test zip:**
   - Unzip it into the scratchpad and read `report.txt` first.
   - Check DPAPI and any FAILs.
   - Then use `history/` (up to 14 dated editions) and `history/events.json` (the registry decisions from
     the PC).
5. Run `grep -iE "downt|@gmail"` on every edition before it becomes a fixture. Copy the editions to
   `tests/fixtures/real/` with dated names.
6. Extend the answer key to 7 or more calendar days:
   - Use the same method as `tests/cross_edition.py`: shared reports, then hand-checked `force`, `join` and
     `related` rules.
   - Generalise `EDITIONS` and the hold-out split so that the **last days are held out**.
   - Do not tune on them.
7. Score both matchers with `python -m tests.cross_edition`. Report matching apart from carry-over and Top
   Stories. Compare `events.json` with the answer key.
8. Diagnose before changing the matcher. Record the findings in `docs/EVENT-IDENTITY.md`, tick
   `docs/PLAN.md`, update `BUILD.md` status marks and this file, then commit and push to the branch.
9. Without the zip, do not invent data. The unblocked work is PLAN 2.2 (why events drop out) on the
   existing fixtures.
10. Also unblocked: the **backend audit** of Oct 8 (`docs/BACKEND-AUDIT.md`, PLAN Phase B). Two high findings on the
    live-site path: a removed story returns after a same-day revision (B1), a failed upload waits for the next
    refresh (B2). Start it when the user says so; the front end (website repo) is being changed by another tool.
