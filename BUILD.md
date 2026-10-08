# Agent Reach: master implementation roadmap

The four phases that turn Agent Reach Daily into a public news platform that tracks real-world events over
time. This file is the roadmap only:
- current state and how to resume: `HANDOFF.md`;
- permanent rules: `CLAUDE.md`;
- step-by-step sub-tasks with commit references: `docs/PLAN.md` (its ids are cited below).

Status marks (`[x]` done, `[~]` started or blocked on the user, `[ ]` not started) reflect the repository on
October 8, 2026. Rule: mark `[x]` only for work that is in the repository and tested; anything that needs the
user's PC stays `[~]` until their results are back.

Order: Phase 1 is done except for the user's one-time setup. **Phase 2 is the current work.** Phase 3 starts
only when Phase 2 is done. Phase 4 waits for the user's go-ahead (on Oct 8 the user said: no installer yet).

---

## Phase 1: automated website publishing, RSS, sitemap, archives and search

**Goal.** getagentreach.dev shows the app's real editions, news first, updated by the app itself after each
successful refresh. No manual copying, and no cloud AI. A failed upload never replaces the last good edition.
(PLAN Phase W.)

**Completed (app on the default branch since PR #4, rc13c; website `main` of `timeitself1-cpu/Agent-Reach-Website`):**
- [x] **Publisher** `agent_reach/daily/publish.py`, off by default:
  - the public copy of an edition: no excerpts, paths, logs or settings, and `assert_public` refuses
    local-path text;
  - one fast-forward GitHub commit per edition, with no commit when nothing changed;
  - an older revision never replaces a newer one;
  - withdraw an edition; remove one story;
  - access key stored with DPAPI in the data folder;
  - the refresh hook never fails a refresh;
  - CLI `--publish`, `--publish-to-folder`, `--withdraw`, `--publish-status`. (W2)
- [x] **Window:** **...** > **Website publishing...** (status, publish now, open site, key save/test/forget,
  withdraw), plus a story menu item "Remove from the website...". (W3)
- [x] **Website,** news first:
  - front page;
  - story pages with sources split into independent reports, repeats and signals;
  - Latest News, Technology, Science & AI and World pages;
  - archive (`/archive/`, `/daily/`, `/daily/YYYY-MM-DD/`);
  - About, 404, self-hosted fonts.

  Checked at 1440 and 390 px with Playwright. (W4, W5)
- [x] **RSS** `feed.xml` (one item per edition), **`sitemap.xml`**, `robots.txt`. Feed and sitemap are
  rebuilt from the archive index in the same commit as the edition. (W8)
- [x] **Archive search:** the publisher writes `search/YYYY-MM.json` in the edition commit. A missing month
  repairs itself, and a withdrawn or hidden story is removed. The `/search/` page runs in the browser with
  no server and loads the newest 6 months first. Website commit 8161be5. (W9c)

**Remaining:**
- [~] W6 **(user):** create the fine-grained GitHub key, paste it in the app, tick Automatic publishing, run a
  refresh, and confirm the live site updates. Not confirmed yet. The site currently shows the October 7
  edition, seeded by hand from the same code.
- [~] **DPAPI key storage on real Windows:** its test runs only in the user's self-test (rc14 self-test not
  run yet).
- [ ] W7, not blocking: an og:image per edition; publishing state in the main window's status line.

**Dependencies:** GitHub API reachable from the PC; Cloudflare deploys `main` of the website repository on
every push. This sandbox cannot reach getagentreach.dev, so the user confirms live deploys.

**Acceptance criteria:**
- After one real refresh with publishing on, the site's `/daily/` shows that edition within minutes.
- A retry makes no commit.
- A forced failure leaves the site unchanged.
- Search finds the new edition's stories.

**Definition of done:** W6 confirmed by the user on their PC, and the self-test's DPAPI test passes on Windows.

---

## Phase 2: cross-edition event identity (current phase)

**Goal.** The same real-world event keeps one stable identity across editions and days. It must be measured,
explainable and deterministic, with no model deciding. This is the foundation for Phase 3. (PLAN Phase 2;
design and numbers: `docs/EVENT-IDENTITY.md`.)

**Completed (rc14, branch `claude/sweet-ramanujan-xj36o5`, not yet merged into the default branch):**
- [x] **Answer key** for the 12 real October 7 editions: 536 stories, 256 events, plus hand-checked splits,
  joins and related pairs. Files: `tests/cross_edition.py`, `tests/fixtures/real/cross_edition_gold.json`.
  (2.1)
- [x] **Matching measured apart from churn:** event carry-over and Top Stories kept are scored from the
  answer key alone. `python -m tests.cross_edition` (2.1, 2.2 measurement only)
- [x] **Diagnosis of today's matcher** (`changes._match`):
  - false continuations come from one shared URL with an earlier mixed story, and from entity sets;
  - misses are new articles about the same event.
- [x] **Event registry** `agent_reach/daily/registry.py`, `state/events.json`:
  - stable ids, first and last seen, report keys, names, word profile;
  - every appearance with tier, confidence and reason;
  - undecided matches are kept apart with their candidates;
  - recording the same run twice changes nothing;
  - recorded after each refresh, **observing only**. (2.3)
- [x] **Matcher v1:**
  - shared reports counted as a share of the story's reports (more than 50%), plus wording agreement;
  - otherwise tf-idf wording with a rare word that is not a name;
  - names never match alone.

  Held-out October 7 pairs, 6 hours or more apart: **precision 0.991, recall 0.898** (today's matcher:
  0.989 / 0.703). (2.4)
- [x] **Self-test** copies the newest 14 dated editions and `events.json` into `history/`. (2.1b, code part)

**Remaining, in order:**
1. [~] **2.1b, blocked on the user's rc14 self-test zip (not run yet).** Extend the answer key to **7 or more
   calendar days** of real editions. Keep the hand-checked positives, negatives and related pairs, and hold
   out the last days. Check the fixtures for personal data first.
2. [ ] **Re-benchmark** the registry on that multi-day held-out set. Also compare the registry decisions the
   PC recorded in `events.json` with the answer key.
3. [~] **2.2:** find why events drop out between editions. Carry-over is 16% over 6 hours, and the cause lies
   in collection and selection, not matching.
4. [ ] **Fix only what the multi-day diagnosis shows.** Each change must be scored with
   `python -m tests.cross_edition`. Do not tune on the held-out days.
5. [ ] **2.5:** use event ids in editions, only after the targets hold:
   - "what changed" compares by event;
   - NEW means a first-seen event;
   - Day N from first seen;
   - one event in one section.
6. [ ] **2.6:** selection stability for continuing Top Stories.
7. [ ] **2.7 to 2.8:** label reuse and per-event momentum. Optional within Phase 2.

**Dependencies:**
- real multi-day editions from the user's PC;
- the within-run grouping (rc12 identity gate): the registry's remaining false continuations come from
  stories already mixed inside one run.

**Acceptance criteria (targets, not production guarantees):**
- On a held-out set of 2 or more real days not used for tuning, editions 6 hours or more apart (including
  day to day): **precision ≥ 0.99, recall ≥ 0.90**.
- Consecutive editions are no worse than today's matcher.
- No undecided story is ever merged.
- The strict xfail `tests/test_cross_edition.py::test_events_are_recognised_hours_apart_on_held_out_editions`
  is re-based on the multi-day set and passes.

**Definition of done:**
- The acceptance criteria are met on the multi-day held-out set.
- The registry has run on the user's PC for at least 7 days with no refresh failures attributed to it.
- 2.5 has shipped in a release and the user has run its self-test.

---

## Phase 3: event timelines, history, evidence and JSON exports

**Goal.**
- Each tracked event shows how it developed: first report, later developments, sources per step.
- Downstream agents (Module 2 "Agent Depth" and later) read structured JSON, never the app's internals.

**Completed:** nothing yet. What already exists and Phase 3 builds on:
- the registry's per-event appearances (record-only);
- per-story sources with dates and kinds on the public site;
- the classic pipeline's `PipelineReport` JSON (`python -m agent_reach.main --json-out report.json`,
  `schema_version` 3; a contract: bump the version on breaking changes).

**Remaining:**
- [ ] **Event history model:** from registry appearances to a public, sanitized event record (`public_event`,
  like `public_edition`). It holds: id, first and last seen, headline per day, sources per appearance (outlet,
  title, link, stated time, kind), and coverage per day. No excerpts or paths (`assert_public`).
- [ ] **Publisher:** `events/<event-id>.json` and an event index, in the same atomic commit as the edition.
  Withdraw and story removal must update them.
- [ ] **Website timeline:** on a story page, "How this story developed" lists earlier appearances with dates
  and links to their editions. An event page may follow. Same design system; no redesign.
- [ ] **Structured export for agents:** a versioned JSON schema (events + editions) with a documented
  contract, e.g. `docs/EXPORT-SCHEMA.md` and a `schema_version` field. Written locally (CLI flag) and
  optionally published.
- [ ] **Evidence:** every timeline step cites its sources. Coverage strength stays "not a fact check".

**Dependencies:** Phase 2 done. Timelines must not be built on unproven matching (user, Oct 8).

**Acceptance criteria:**
- A timeline shows only appearances the registry matched at tier `reports` or `wording` with confidence of
  0.5 or more; undecided appearances never join a timeline.
- Every step links to its edition and sources.
- The JSON validates against its schema in a test.
- A withdrawn edition disappears from timelines.

**Definition of done:**
- Timelines live on getagentreach.dev for real events spanning 3 or more days, checked by the user.
- The export schema is documented and tested.
- The publish tests cover the event files (one commit, idempotent, withdraw).

---

## Phase 4: distribution and production readiness

**Goal.** People can install, update and trust Agent Reach Daily without a developer's help.

**Completed (the current, developer-style distribution):**
- [x] `Setup-AgentReachDaily.ps1`: venv, requirements, Ollama models, scheduled task.
- [x] `Uninstall-AgentReachDaily.ps1`.
- [x] Releases delivered as a zip of the repository.
- [x] CI `tests.yml` on Python 3.10 and 3.12 under xvfb, plus the self-test dry run.
- [x] MIT license.

**Remaining (not started; the user said "do not begin the Windows installer yet", Oct 8):**
- [ ] A **Windows installer**: one download, no Python or PowerShell steps, Start-menu entry, uninstall entry.
  Ollama stays a separate, documented prerequisite (local-first).
- [ ] **GitHub Releases** with versioned assets and release notes taken from `docs/RELEASE-NOTES.md`. Tags
  per release candidate, then 1.0.
- [ ] **Production readiness:**
  - Windows checks still open from Phase 0:
    - `.pyw` double-click;
    - one real morning with the scheduled task;
    - the by-hand checklist (`docs/WINDOWS-TEST-RC11.md`);
  - the podcast heard on real Windows;
  - an update path that keeps the data folder;
  - signed binaries if an installer ships.
- [ ] Website: confirm that search engines index it (sitemap submitted). Optional og:images (W7).

**Dependencies:** the user's go-ahead. Phases 2 and 3 should be stable first, so the installer does not ship
moving targets.

**Acceptance criteria:** a fresh Windows 11 PC with only Ollama installed gets from download to first edition
by following one page, with no terminal. Uninstall leaves no files outside the data folder, which is kept
unless the user asks.

**Definition of done:**
- 1.0 is tagged and published as a GitHub Release with an installer.
- The self-test passes on the installed build.
- README install steps are rewritten for the installer.

---

## Not in these four phases (tracked in docs/PLAN.md)

Quality work runs alongside and is taken up when the user asks:
- Phase 1 of PLAN: "Report a problem with this story" feedback loop.
- Phase 3: section quality.
- Phase 4: trustworthy text.
- Phase 5: momentum after settings changes.
- Phase 6: daily-use comforts.
- Phase 7: Module 2, Agent Depth (consumes the Phase 3 exports).

Out of scope unless the user asks: new autonomous agents, cloud LLMs or paid APIs, accounts, billing,
telemetry, Docker, new frameworks.
