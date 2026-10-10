# Agent Reach Daily: plan

The live step-by-step plan and progress log. **A new session reads `CLAUDE.md`, `HANDOFF.md` (current state) and
`BUILD.md` (the four-phase roadmap: its Phase 1 = Phase W here, Phase 2 = Phase 2 here) first**, then takes the
first unchecked sub-task of the current phase here, does it, and updates this file.

## How to use and update this file

- Work one sub-task at a time, in order, unless the user re-prioritises (then reorder here first).
- When a sub-task is done: change `[ ]` to `[x]`, and add a line to **Progress log** at the bottom:
  `YYYY-MM-DD | sub-task id | commit | result in one sentence | next`. Commit this file with the work (or
  right after it) and push. Never leave a finished sub-task unticked: the next session cannot see the chat.
- A sub-task that turns out bigger: split it here into lettered steps before starting them.
- A sub-task blocked on the user (their PC, a decision): mark `[~]` with what is needed, and move on to the
  next unblocked one. Put the question in the final message to the user.
- Acceptance criteria are tests or measurements, not impressions. "Measured on fixtures" means the real
  editions in `tests/fixtures/real/` (add the newest ones the user sends).
- Do not tune semantic accuracy blindly: every quality rule starts from a real edition quote in
  `docs/REAL-EDITION-FINDINGS.md`.

## Where we are (October 8, 2026)

- **Oct 8 (later): PR #4 merged rc13c into the default branch (9674c46).** rc14 on `claude/sweet-ramanujan-xj36o5`
  (restarted from the default branch): event registry, observing only, and the self-test's 14-day history.
  User's Phase 2 order (Oct 8): identity before timelines; answer key over >= 7 real days; matching measured
  apart from selection/publishing churn; diagnose before choosing; registry with stable ids, first/last seen,
  evidence, confidence, safe ambiguity; benchmark on a held-out multi-day set (targets, not guarantees);
  timelines only after that. No UI redesign, no installer. Design and results: `docs/EVENT-IDENTITY.md`.
- **rc13 (zip rc13), branch `claude/sweet-ramanujan-xj36o5`: website + automatic publishing (Phase W below),
  re-prioritised by the user on October 8** ("UX first, ship early"). getagentreach.dev is a news site rendered
  from published editions; the app publishes each validated edition by itself once the user saves a GitHub access
  key. **User's order (Oct 8, second message):** (1) PR of rc13 into the default branch, (2) archive search
  (done, W9c), (3) **cross-edition event identity = Phase 2, next**, (4) story timelines once matching is reliable.
  No Windows installer yet. "Keep changes modular; avoid repeated testing or redesigning working features."
  Also open: the one-time key setup on the PC (W6).

- **Oct 8 (evening): backend audit** (`docs/BACKEND-AUDIT.md`, shared as a Claude doc). The user has ChatGPT on the
  website front end (mobile layout, search clarity and recovery). Phase B below = the audit's plan; B1-B7 are
  unblocked while Phase 2 waits for the rc14 self-test zip. Start Phase B only when the user says so.

## Where we were (October 7, 2026)

- Version **1.0.0rc12** (zip rc12f) on branch `claude/affectionate-galileo-isxik1`: EmbeddingGemma 2 + event
  identity. PC round 1 (Oct 7 12:07) fixed in rc12b (H1-H6), round 2 (13:36) in rc12d (H7b), round 3 (16:29) in
  rc12e (H7c): live false merges 26, 26, then 12 in 5 stories (golf 'retreat' again, Gaza/anniversary, a Nobel
  round-up); round 4 (18:16, still rc12d: rc12e was not installed yet) in rc12f (H7d): a Pitt State profile in
  NASA's Artemis II story, the .cmd launcher held by Windows' security prompt. 1 open false merge (two RTX Spark
  laptops) on the 13-edition labelled corpus offline. No Gemma model has run on the PC: EmbeddingGemma 2 is MLX-only in Ollama, and Ollama
  0.40.0 cannot open `embeddinggemma:300m` after downloading it (Windows symlink bug, ollama/ollama#18847).
  **Next:** the user installs rc12f and runs the self-test (H7e), then Phase 1; H7 waits for an Ollama that can run a Gemma
  embedding model on Windows. rc11 was zip rc11d.
- Reliability is proven on the user's Windows PC (self-test round 2): offline suite 404 passed on Windows,
  launchers (shortcuts, .cmd), real Ollama checks, cancel at once/halfway, full real refresh (~6 min, 46-51
  stories, podcast), model drop ends in 9 s, repeated use coherent.
- The remaining problems are editorial quality: story churn between refreshes, NEW/"what changed" noise,
  thin single-outlet section filler, weak leads, rare "why it matters".
- **Re-prioritised by the user on October 7 (rc12):** EmbeddingGemma 2 + story/event identity comes BEFORE
  Phase 1 (Report a problem). Scope: Agent Reach Daily only (no Research/Connections agents, no Project Scout).
  Work the **rc12 phase** below first; Phase 1 follows it.

---

## Phase 0: close rc11 Windows validation

- [x] 0.1 Code review + six stabilization fixes (stale pid, cancelled runs, repair errors, Ollama check,
      Retry-After, topic validation). Commits 4082efd, fceca40.
- [x] 0.2 Real-process scenario tests in a fake world; watchdog; honest model-failure handling; cancel fixes
      (97b3578). File-lock durability, launcher smoke hook, self-test harness, Windows tests, CI under Xvfb
      (87acfa2).
- [x] 0.3 Self-test round 1 on the user's PC; fixes (afc82a9). Round 2; fixes (0f246d6). Real editions saved
      as fixtures; findings in `docs/REAL-EDITION-FINDINGS.md`.
- [~] 0.4 `.pyw` double-click: rc11d's self-test records the `.pyw` file association. NEEDS: the next self-test
      zip (or the user saying what a double-click on AgentReachDaily.pyw does). If `.pyw` opens an editor or
      nothing: change nothing in code; document "use the Desktop shortcut" in README and the setup summary.
- [~] 0.5 Stray files on the user's PC (`agent_reach/daily/events.py`, `agent_reach/pipeline/identity.py`,
      `tests/test_event_contract.py`, `tests/test_event_identity.py`). NEEDS: the user to say where that
      work comes from (another session/branch/zip?). If it exists somewhere, bring it into the repo before
      Phase 2 (ask for the files or the branch name; check `mcp__claude-code-remote__list_repos` / branches).
- [~] 0.6 By-hand checklist (`docs/WINDOWS-TEST-RC11.md` section 2) and one real morning with the scheduled
      task. NEEDS: the user's answers. Fix anything they report before Phase 2.

## Phase rc12: EmbeddingGemma 2 + event identity (priority, before Phase 1)

Goal: one story = one real-world event. The October 7 editions published 52 false merges (13 mixed stories,
e.g. the smart-glasses privacy probe with WSJ's Meta-AI-app billionaire profile, the Maine Senate debate with
Cornell, the Webb planetary collisions with NASA's PRIMA, "October 7" as a date joining four stories). The
cause is structural: HDBSCAN + single-link `LinkIndex.components` chain A~B, B~C into A=C. Embeddings must only
propose candidate neighbours; an explicit event-identity layer decides membership; a false split is better
than a false merge. Model: `embeddinggemma-2:270m` first (768 dims, no 256d), the full model benchmarked on the
user's PC; every exact model id (+ digest) is its own embedding space in the cache. Acceptance: zero false
merges on the labelled corpus under replayed rc11 neighbourhoods AND under "every pair looks identical";
recall >= 0.6; fallback tested; evaluation artifact; real benchmark command for the user's PC.

- [x] A. Baseline + regression corpus: `tests/html_fixture.py` (HTML export -> fixture), the 9:35 export as
      `tests/fixtures/real/2026-10-07-0935-export.json`, gold events (`event_gold.json`), `tests/event_corpus.py`
      (pairwise P/R/F1 + raw false merges). Baseline: rc11 published 52 false merges.
- [x] B. Embeddings: `pipeline/embeddings.py` (deterministic event representation `event_repr_v2`, model task
      prefix, L2 normalisation, SQLite cache keyed by provider|model@digest|dims|norm|repr|text hash, never
      mixes dimensions or models, fallback chain `embed_model` -> `embed_fallback_models` -> lexical).
- [x] C. Identity layer: `pipeline/event_identity.py` (kNN candidates, `IdentityGate` ACCEPT/REJECT/NEUTRAL with
      reasons: roundup, date-only, names/everyday words only, event family, time apart, exclusive qualifiers;
      `cohesive_groups`: merge only through an accepted edge with no rejected cross pair and a strict majority
      of supporting cross pairs; ambiguous fragments join nothing). `LinkIndex.components` uses it (no
      single-link chaining). Roundups by digest names (Morning Rundown, News Wrap). Date words never link.
- [x] D. Evidence vs attention: trend/social signals (Google Trends, X, Bluesky, fragments) never count as
      factual corroboration; strength (Strong/Moderate/Limited) recomputed from the cleaned membership;
      syndication logic kept.
- [x] E. Continuity: NEW/UPDATED only for continuing events matched by identity; the newest reliable evidence
      controls current-state wording (stock market: Tuesday record high -> Wednesday decline).
- [x] F. Summary quality: malformed/truncated sentences rejected ("By studying 21 rare." = JSON string cut at an
      inner double quote), month abbreviations never end a sentence ("Oct. 7"), deterministic extractive
      fallback.
- [x] G. Evaluation + release: `docs/eval/identity-eval.{json,md}` (rc11 recorded vs lexical vs replay vs
      identical), `tests/embedding_benchmark.py` + `Benchmark-Embeddings.ps1` for the user's PC (nomic vs
      gemma 270m vs full model; old density vs identity), compact semantic diagnostics in the HTML + full
      pair log in diagnostics, prefs migration to the Gemma model, setup pulls it, rc12 release + zip.
- [~] H. Real-model benchmark on the user's PC (`Benchmark-Embeddings.ps1 -PullModels`). Round 1 (Oct 7 12:07,
      zips in REAL-EDITION-FINDINGS): only nomic ran (gemma 404 on Ollama 0.40.0); 2 false merges in the
      benchmark, 26 in the two live editions. Split into:
  - [x] H1. Asos/Wikimedia merge: reporting verbs everyday words; page-text support needs page-text rarity.
  - [x] H2. Diagnostics: pair log keeps accepted pairs first; gate counts snapshot after stage 3a; benchmark
        saves real vectors (`vectors-<model>.json.gz`) and replays them offline (`--replay`).
  - [x] H3. Label calls: <= 12 stories, a cut-off answer (done_reason length) is split, not retried.
  - [x] H4. Missing grouping model is optional and explained (`prereqs.check_prefs`); setup/benchmark show
        Ollama's own pull error + version, `pull-log.txt`, UTF-8 output; Windows pacing; self-test FAIL rule.
  - [x] H6. Live merges: merge pass merges drafts only through accepted pairs (no attach); 'agents',
        'possible' everyday words; protest/hack kind-of-event words; strong-path names in both titles and rare
        in any written form. Both live editions are fixtures (`RC12_EDITIONS`) with gold events.
  - [x] H7a. EmbeddingGemma 2 is MLX-only in Ollama (newest Ollama on the PC: "requires MLX support"): setup,
        benchmark, model check and self-test say so plainly; benchmark adds `embeddinggemma:300m` (rc12c).
  - [x] H7b. Round 2 on the PC (13:36, rc12c): live editions 26 false merges in 8 stories (Saint/Mancuso, Kimmel/Trump
        Accounts, three polls, two 'retreats', Belgium/France, two laptops). Fixed: lone reports need a title link
        to EVERY member; "don't" is an everyday word; legislature names are not shared names; a common name + one
        word needs strong embedding agreement; a two-word phrase is one piece of evidence. Laptops open (strict
        xfail). Also: progress.json delete retried on Windows; self-test INFO for the expected fallback; benchmark
        explains Ollama's Windows symlink error. Corpus 9 editions, 1 false merge, R 0.620; real nomic replay 0/0.679.
  - [x] H7c. Round 3 on the PC (16:29, rc12d): 29 PASS, 1 FAIL (the stray test files; the user deletes them, no
        longer needed); Windows suite 476 passed. Live editions 12 false merges in 5 stories. Fixed: the lone-report
        attach rule now needs a scarce name (2%, as the pair rule) - the golf 'retreat' joined through it; 'war' is an
        everyday word (Gaza child in the October 7 anniversary); a report whose title + lead name three prize fields
        is a round-up (Nature's 'Nobel Prizes 2026'). Texas's next execution with Christa Pike's labelled related.
        Self-test keeps the second refresh's gate decisions. Corpus 11 editions; no recall lost on any edition;
        real nomic replay 0/0.679.
  - [x] H7d. Round 4 on the PC (18:16): the stray tests are gone (Windows suite 476 passed), but the run was still
        rc12d (no second grouping file, Nature's round-up still in the chemistry story). 1 FAIL: AgentReachDaily.cmd,
        os.startfile held 250 s by Windows' security prompt for a file from a downloaded zip; Setup now clears the
        Zone.Identifier mark and the self-test explains a held launch. One new false merge: 'NASA' + 'lunar' (scarce
        name + one word, cosine 0.79) joined a Pitt State profile to NASA's Artemis II data; with vectors that now
        needs the strong cosine. Real nomic replay unchanged (0/0.679), lexical unchanged (0.568). Corpus 13 editions.
  - [ ] H7e. The user extracts rc12f over the folder, runs Setup, then `Test-AgentReachDaily.ps1`: expect ALL PASSED
        and a second grouping file in the zip (proof rc12e/f is installed); check both editions for mixed stories.
  - [ ] H7. **Blocked on Ollama:** nomic vs a Gemma embedding model on the PC (`embeddinggemma:300m` downloads but
        Ollama 0.40.0 cannot open it, ollama/ollama#18847; EmbeddingGemma 2 is MLX-only). When a later Ollama runs
        one: `Benchmark-Embeddings.ps1 -PullModels`, replay here with `--replay <vectors-*.json.gz>`, put it in the
        fallback chain only if it beats nomic; set `identity_strong_cosine` only if the different-event p99 says so.

## Phase W: the website and automatic publishing (user's priority, October 8)

Goal: getagentreach.dev is a news-first site that updates itself from the app's real editions. Out of scope:
new agents, new LLM infrastructure, accounts, databases, pipeline changes.

- [x] W1. Inspect: site = static repo `timeitself1-cpu/Agent-Reach-Website`, Cloudflare Workers static assets
      deployed from `main` on every push; the app's public-safe export (`sample.py`) is the starting point.
- [x] W2. `daily/publish.py`: public edition (no excerpts/paths; independent vs repeat vs signal per source),
      edition page + archive index, FolderTarget/GitHubTarget (one fast-forward commit, re-read on conflict,
      no commit when unchanged), DPAPI key, status, withdraw, hide_story, refresh hook, CLI flags. 10 tests +
      a refresh test + a window test.
- [x] W3. Window: **...** > Website publishing (on/off, status, last published, live check, publish now, withdraw,
      key save/test/forget); story menu "Remove from the website...".
- [x] W4. Website redesign (dark, editorial): front page, story pages with sources and coverage, Latest News,
      Technology / Science & AI / World, archive, about (method, coverage, corrections, privacy, app), 404;
      checked at 1440 and 390 px with Playwright (no errors, no horizontal scroll).
- [x] W5. Seed the site with the newest real edition (Oct 7 r2, 44 stories) through the folder target; site commit 91d14bc on main.
- [x] W6. Key setup on the PC (Oct 8, rc15): key saved (DPAPI, Windows), the first publication by hand
      ("Publish latest edition") reached the site repo as commit 90e605c (Oct 8 r2, 53 stories, index + feed +
      sitemap + search). Automatic publishing is now ticked; the first AUTOMATIC publication after a refresh is
      still to be seen. (Before the key, refreshes published nothing: automatic publishing was off.)
- [ ] W7. Later (not blocking): an og:image per edition; show the publishing state in the main window's status
      line; Windows test of DPAPI on the PC (`test_access_key_is_stored_outside_the_repo_and_forgotten` runs
      there in the self-test's pytest).
- [x] W8. Outside review of the site (user, Oct 8; it described the OLD rc12 landing page, so it was written before
      91d14bc went live or the deploy did not run): RSS `feed.xml` + `sitemap.xml` written by the publisher in the
      same commit as the index (`index_files`), `robots.txt`, feed links; source counts made consistent (strip
      "10 of 10 kinds of source", About lists them; README 114 -> 112 feeds); README's personal paths made generic.
- [~] W9. From the same review, ordered by the user on Oct 8: (a) [x] PR #4 merged (Oct 8, 9674c46) (GitHub
      visitors still see the rc12 README); (b) [ ] story timelines on the site, AFTER Phase 2 makes event matching
      across editions reliable; (c) [x] archive search (monthly search files written by the publisher, `/search/`);
      (d) NOT NOW (user): a one-click Windows installer and GitHub Releases.

## Phase B: backend audit fixes (audit of October 8; `docs/BACKEND-AUDIT.md`)

Goal: the step that feeds the live site is as safe as the rest. One commit and one test per item; no new services.

- [x] B1. Removed stories stay removed (F1): `hidden_stories` also keeps each removed story's report keys (URL,
      normalized title); a story is left out when more than half of its reports were removed (the registry's rule).
      Acceptance: fixture test (remove every r1 story, publish r2): 0 come back (today 28 of 144).
- [x] B2. Retry publication on the hourly check (F2): when not due, `--refresh-if-due` publishes the latest edition
      if publishing is on and the site lacks it (status failed or older revision), at most once an hour.
      Acceptance: fake-world process test: first upload 503, next tick publishes, third makes no commit.
- [x] B3. Publish before the podcast (F6). Acceptance: refresh test asserts the stage order.
- [x] B4. Access-key expiry warning (F5) from GitHub's `github-authentication-token-expiration` header, 7 days ahead.
- [x] B5. One bad story, not the whole day (F10): `assert_public` per story; the status names what was left out.
- [x] B6. Validate dates in publish/withdraw/hide (F13); read each file once per pinned head, close clients (F11).
- [x] B7. Release rc15 = Step 1 (B1-B4), zip to the user (Oct 8). B5-B6 (Step 2) go into the next build.
      B2's test runs the real `--refresh-if-due` command in-process with a fake GitHub (not a separate process).
- [ ] B8. `docs/PUBLIC-DATA.md` + `docs/schema/` (edition, index, search month) + a real example; a test validates
      the publisher's output for all fixtures (F4). Share with the front end; F9/F12 only if it agrees.
- [-] B8b. (dropped Oct 8: the website revalidates search files instead) Search entries carry their edition's revision (`v`, optional field) so the site can refetch a stale
      cached month (search recovery, docs/BACKEND-AUDIT.md). Acceptance: publish test expects `v`; a revision rewrites it.
- [ ] B9. With Phase 2.5/3: publish the registry's event id per story + an `aliases` map from old story ids (F3).
- [x] B11. The window's Test connection replaces the last failure's reason with "Connected..." while the headline
      still says "Publication failed" (seen on the PC, Oct 8): keep the reason visible (or say it is an old result).
- [x] B12. (audit round 2, N1, HIGH) A later same-day refresh with fewer than half the sources answered or half the
      stories of the day's current revision is "no new edition" (locally and on the site); a manual refresh may still
      publish it. Acceptance: the 44-story fixture is not replaced by a 3-story revision from 2 of 10 sources.
- [x] B13. (N5) The hourly catch-up pauses after 401/403/"newer revision" until a new key or a new edition.
- [ ] B14. (N3) A signal source names its platform ("Mastodon (link to theguardian.com)"), never a news outlet as
      a signal. Counting linked articles as reports is a separate decision for the user (rc12 D kept them out).
- [ ] B15. (N2) The publisher keeps New/Updated only when `compared_with` is the edition on the site.
- [ ] B16. (N4) Dated pages from a template file the website owns; then F9 (pre-rendered story text).
- [ ] B17. (N6) Scheduled task limit = refresh limit + 25 min (or cap the setting at 95 min).
- [ ] B10. `windows-latest` CI job (F7); `constraints.txt` with the CI-tested versions for Setup and CI (F8).

## Phase U: the app updates itself (user's request, Oct 8)

- [x] U1. `daily/updater.py` + `release.json` + `build.txt` (export-subst); window launch and hourly check; banner,
      Details line; tests and self-test never update (rc17).
- [~] U2. `stable` = aaef839 (rc17, CI green), pushed Oct 8. Real round trip from the sandbox against GitHub: an
      installed copy with another build updated itself (GitHub's zip carried build.txt = aaef839; 2 files changed, a
      user file kept, new version started, notice). NEEDS: the user installs the rc17 zip (made from aaef839) by hand.
- [ ] U3. First real update on the PC: the next release (rc18) arrives by itself; check `updates\status.json` and the
      "Updated to" banner. Until then the round trip has only run here against GitHub.

## Phase 1: "Report a problem with this story" (the feedback loop)

Goal: every morning can produce precise test material with one click, so Phases 2-4 are driven by real
cases. Small, local, no network. (After the rc12 phase, by the user's decision of October 7.)

- [ ] 1.1 Design (write it into this file first): right-click menu item "Report a problem..." on a story ->
      a small dialog: problem type (Wrong/merged stories, Duplicate, Wrong headline, Summary does not say
      what happened, Wrong fact, Wrong section, Not news / advert, Other) + optional note. Saves
      `%LOCALAPPDATA%\AgentReachDaily\feedback\YYYY-MM-DD\<time>-<story_id[:8]>.json` with: app version,
      edition date/revision/run_id, the full Story JSON (as stored), the problem type, the note, and the
      ranks/headlines of the 3 neighbouring stories (for duplicates).
- [ ] 1.2 `daily/feedback.py` (no Tk): `save_report(paths, edition, story, kind, note) -> Path`,
      `list_reports(paths)`, atomic writes, never raises into the window (returns an error message).
      Tests in `tests/test_daily_feedback.py`.
- [ ] 1.3 GUI: menu item in `DailyWindow.story_menu_items`, dialog (`FeedbackDialog`), a confirmation in the
      status line ("Saved. Thank you."), "... menu > Open feedback folder". Test in `test_daily_gui.py`.
- [ ] 1.4 Self-test zip includes the feedback folder (read-only copy) and the latest 3 real editions of the
      data folder (JSON) so fixtures can be made from them. Update `docs/WINDOWS-TEST-RC11.md`.
- [ ] 1.5 `tests/fixtures/real/` tooling: `python -m tests.make_fixture <feedback.json>` turns a report into
      a fixture entry + a strict-xfail test skeleton with the user's words as the docstring.
- [ ] 1.6 Release (rc12 or rc11e), zip to the user with a one-paragraph "how to report a story" note.

## Phase 2: story identity across refreshes (the event layer)

Goal: the same news event keeps one identity from refresh to refresh and day to day. This fixes churn,
NEW/UPDATED noise, "what changed", duplicates across sections, Day N, per-story momentum, and lets unchanged
stories reuse their labels (faster refreshes). Acceptance: the strict xfails
`test_one_event_appears_once`, `test_a_refresh_minutes_later_keeps_the_corroborated_news`,
`test_the_lead_story_survives_the_next_refresh` pass (remove their marks), and churn metrics below improve
on every fixture pair.

- [x] 2.0 Resolve 0.5 (the existing events.py/identity.py work): not in this repository; the user deleted it on
      Oct 7 ("no longer needed"). Phase 2 builds on rc12's within-run gate (`pipeline/event_identity.py`) instead.
- [x] 2.1 Measure first (Oct 8): `tests/cross_edition.py` + `fixtures/real/cross_edition_gold.json`, an answer key
      for the 12 Oct 7 editions (536 stories, 256 events, 108 in more than one edition; built from shared reports
      on top of the per-edition gold, plus 9 hand-checked splits, 12 joins, 16 'related' pairs).
      `python -m tests.cross_edition` scores a matcher. **Baseline, today's `changes._match`:** consecutive
      editions P 0.967 R 0.954 (7 false continuations, e.g. Trump's golf-club "retreat" continued as the forces'
      "retreat"; Cornell/Yates as the Maine debate); **6 h+ apart P 0.966 R 0.752** (56 missed: the same event
      with all-new articles and new wording, e.g. Apple + LG, Decisions API, French protests); Top Stories still
      listed in the next edition 73/100, 6 h+ apart 111/288 (selection churn: 2.2/2.6).
      `tests/test_cross_edition.py`: floor test + strict xfail target (6 h+ apart P >= 0.99, R >= 0.90).
      Gap: all 12 editions are one day; day-to-day pairs need real editions from consecutive days (2.1b).
- [~] 2.1b Real editions from several consecutive days. Done in rc14: the self-test copies the newest 14 dated
      editions + `state/events.json` into `history/`. NEEDS the user's next self-test zip; then extend the answer
      key to >= 7 calendar days (hand-checked positives, negatives, related pairs), hold out the last days.
- [~] 2.2 (Oct 8: churn measured apart from matching, docs/EVENT-IDENTITY.md: carry-over 44% consecutive,
      16% 6 h+ apart; Top Stories again top 48% / 15%.) Find the cause of churn on the fixtures before designing: how much comes from (a) which ~260 of
      ~1,450 items are selected for clustering (`cleaner.select_for_llm` budget, per-feed floors), (b)
      HDBSCAN grouping differences, (c) story selection caps/ranking (`edition.select_stories`), (d) model
      relevance scores varying run to run. Use the logs in the self-test zips. Write the findings here.
- [x] 2.3 (Oct 8, rc14) `daily/registry.py`, `state/events.json`, recorded by the refresh worker after the edition
      is saved, OBSERVING ONLY (no edition uses it yet; never fails a refresh). Stable ids, first/last seen, report
      keys, key names, fading word profile, appearances with tier/confidence/reason/undecided candidates; no
      embedding centroid yet (vectors are not kept per story; wording tf-idf instead). Original text: a persistent store (`state/events.json` or a SQLite table in `data/agent_reach.db`)
      of events: id, first_seen, last_seen, headline history, key names, URL set, embedding centroid
      (from the run's vectors), category, last story text. Owned by the refresh worker (lock holder).
- [~] 2.4 (Oct 8) Matching implemented on stories (not clusters) against events of the last 7 days: shared
      reports as a SHARE of the story's reports (> 50%) + wording agreement; else tf-idf wording with a rare
      non-name word; names never alone; undecided within 90% -> kept apart. Oct 7 held-out pairs 6 h+ apart:
      P 0.991 R 0.898 (today's matcher 0.989 / 0.703); target P >= 0.99 R >= 0.90 still a strict xfail. Remaining
      false continuations come from stories already mixed inside a run. Re-check on the multi-day held-out set
      (2.1b) before 2.5. Original text: Matching a new run's clusters to registry events: shared article URLs; then key-name + event-word
      fingerprint; then embedding cosine of centroids with a strict threshold; never merge two clusters of
      the same run into one event unless they share URLs (invariant 2: the LLM never decides). Unit tests
      from the fixture pairs (Messi farewell #15/#37; plague story day to day; the Nobel prizes must stay
      separate).
- [ ] 2.5 Use the identity: `story_id`/`event_id` stable across editions; `changes.py` compares by event id
      (NEW only for a first-seen event; UPDATED for new publishers/facts); `reading.developing_since` uses
      first_seen (Day N); dedupe across sections by event id.
- [ ] 2.6 Stability of selection: an event that was in the previous edition's Top Stories and still has
      fresh reports keeps a place unless clearly outranked (hysteresis), so the #1 story cannot vanish
      because of sampling noise. Acceptance: the xfails above pass.
- [ ] 2.7 Label reuse: an event whose member URLs did not change since the last refresh reuses its headline,
      summary and category without a model call. Measure refresh time before/after on the user's PC.
- [ ] 2.8 Momentum per event (velocity from the registry's history instead of the whole-config comparison),
      which also fixes "momentum lost for a day after any feed change" (see Phase 5).
- [ ] 2.9 Release, self-test round, read two real editions a day apart; update findings.

## Phase 3: fewer, better stories in the sections

Each rule starts from quotes in `docs/REAL-EDITION-FINDINGS.md`; each gets a fixture test.

- [ ] 3.1 Non-news filter: shopping deals ("Drops to Under $1,000 for Prime Day"), TV/stream listings
      ("MLB Playoff Games on TV Today: Schedule, Times, TV Channels, Live Streams"), listicles/rankings
      ("The 10 Greatest ... Ranked", "Five Ways ..."), anniversary/evergreen pieces ("9 Years Later, ..."),
      changelogs/survey pages. Extend `cleaner` promotional/roundup rules; keep a "secondary" bucket rather
      than dropping when unsure.
- [ ] 3.2 Section quality gate: in category sections, single-outlet stories need relevance >= N (measure N on
      fixtures) or move to a compact "Also noted" list of one-line links under the section.
- [ ] 3.3 Leads that state the event: reject feature openings ("On 23 August, Cooper Freeman had no idea ..."),
      fragments that do not mention the headline's subject ("Recent games requiring newer firmware are
      inaccessible.", "Prices show no signs of easing."), and a sentence whose place name contradicts the
      story's ("the north-east of the country" = DR Congo in a Kenya story). Fall back to `lead_sentence`.
- [ ] 3.4 Category: outlet hints must not override content for business/finance stories (Paramount merger,
      "Billions Pour into OpenAI, DeepSeek Ahead of IPOs"); keyword "AI" alone is not Science & AI.
      Acceptance: `test_media_merger_is_news_not_tech` passes (or the category the user prefers).
- [ ] 3.5 Headline names: keep a person's first name when the reports have it ("Claire, Ex-Dodgers GM" ->
      "Fred Claire").

## Phase 4: trustworthy text

- [ ] 4.1 Measure the brief pass: log which gate rejects each "why it matters"/detail (grounded, numbers,
      support, concrete_effect, novelty, restates). Get counts from one real run (self-test log) before
      changing anything. Acceptance for later: `test_why_it_matters_for_most_top_stories` passes without
      loosening grounding (invariant 11).
- [ ] 4.2 Improve what the model is given (evidence lines with consequence words first, a better prompt,
      one story per call if needed on the GPU) rather than loosening the gates.
- [ ] 4.3 Optional local claim check: for each summary sentence, ask the local model a yes/no "is this
      stated by these excerpts?" (temperature 0); drop "no". Only if the GPU time stays small (measure).
      Motivating case: "some places are getting extra nuclear protection" (Iran story, Oct 7).

## Phase 5: momentum that survives settings changes

- [ ] 5.1 Compare runs on the feeds/sources both runs share instead of requiring an identical configuration
      (`scorer._reference_runs`, `comparable_config`); keep "uncertain" only when the shared part is too
      small. Tests in `test_reliability.py`-style with two runs and a changed feed list.
      (May be absorbed by 2.8.)

## Phase 6: daily-use comforts (all local)

- [ ] 6.1 "Since you last read": open on the stories that are new since the last time the window was used.
- [ ] 6.2 Windows notification when the edition is ready or a followed topic appears (no service; a toast
      via PowerShell or `win10toast`-free code).
- [ ] 6.3 Optional: copy each morning's HTML export to a folder the user picks (e.g. their OneDrive) so it
      reaches the phone. Off by default.
- [ ] 6.4 Podcast voice: optional local Piper TTS if installed; the Windows voice stays the default.
- [ ] 6.5 `.pyw` / launcher polish from 0.4; installer polish (Start-menu icon, uninstall entry).

## Phase 7: Module 2, Agent Depth (later)

- [ ] 7.1 Reads `PipelineReport` JSON only (schema contract), fetches 3-5 sources per top trend, checks
      cross-source agreement, writes cited `TrendBrief` records. Never imports Agent Reach.

---

## Progress log

`date | sub-task | commit | result | next`

- 2026-10-07 | 0.1 | 4082efd | six stabilization fixes, tests | real-process scenarios
- 2026-10-07 | 0.2 | 97b3578, 87acfa2 | watchdog, honest model drop, lock-file durability, self-test kit | self-test on Windows
- 2026-10-07 | 0.3 | afc82a9, d1792e3, 0f246d6 | rounds 1-2 on Windows: 404 tests pass there; 8 more fixes; 4 real editions as fixtures | 0.4-0.6 (user), then Phase 1
- 2026-10-07 | rc12 A | (this commit) | labelled corpus of the 5 real Oct 7 editions: rc11 published 52 false merges in 13 stories | B + C
- 2026-10-07 | rc12 B+C | (this commit) | EmbeddingGemma 2 backend + model-aware cache + fallback; identity gate + cohesive groups: 0 false merges on the corpus under replayed rc11 neighbourhoods and identical vectors, replay recall 0.73 | F (summary gate), then D, E
- 2026-10-07 | rc12 F | (this commit) | 'By studying 21 rare.' rejected (truncated copy + intro-only gates) with the real lead as fallback; 'Oct. 7' no longer ends a sentence | D, E
- 2026-10-07 | rc12 D | (this commit) | trend/social signals no longer add channel diversity or recency; strength comes from the gated membership (evidence is never changed after build_story); syndication unchanged | E
- 2026-10-07 | rc12 E | (this commit) | newest dated report leads when the summary only describes an earlier day (stock market: Wednesday fall before Tuesday record, 'Developing'); what-changed matches by the most shared URLs and a story split from an old false merge is neither new nor fading | G
- 2026-10-07 | rc12 G (eval) | (this commit) | tests/embedding_benchmark.py + docs/eval/identity-eval.{md,json}: rc11 52 false merges; gate 0 with no embeddings (R 0.635), replayed neighbourhoods (R 0.762) and all-identical vectors | Windows benchmark script, HTML diagnostics, prefs migration, release
- 2026-10-07 | rc12 G (app) | (this commit) | prefs v9 (EmbeddingGemma 2 default, nomic fallback), model actually used + compact 'How stories were grouped' in the HTML/details, pair log in diagnostics\semantic, setup checks the model, Benchmark-Embeddings.ps1, self-test checks the grouping model | docs + release
- 2026-10-07 | rc12 G (release) | (this commit) | 1.0.0rc12: docs (README, RELEASE-NOTES, HANDOFF, CLAUDE.md, architecture, findings) | H (user's PC benchmark), then Phase 1
- 2026-10-07 | rc12 H1-H6 | 9b76d41..d20c8de | first PC round fixed: Asos/Wikimedia (verbs, page-text rarity), pair log + counts, label calls split when cut off, grouping model optional + pull errors explained, self-test FAIL rule + Windows pacing, merge pass no longer grows stories one report at a time + 4 gate word rules; 7-edition corpus: 0 false merges offline (R 0.620 lexical, 0.688 replay) | H7: user updates Ollama, reruns the benchmark
- 2026-10-07 | rc12 H7a | 413785a | newest Ollama on the PC: embeddinggemma-2 "requires MLX support" (Mac only); plain messages in setup/benchmark/model check/self-test, benchmark adds embeddinggemma:300m | H7: user reruns the benchmark (rc12c)
- 2026-10-07 | rc12 H7b | f224575 | round 2 (13:36): 26 false merges in the live rc12c editions; five gate rules fixed, laptops open (xfail); progress.json delete retry; self-test INFO for fallback; Ollama symlink bug explained; corpus 9 editions, 1 false merge, R 0.620 | H7c: user runs the self-test on rc12d
- 2026-10-07 | rc12 H7c | f631426, d9cb362, (this commit) | round 3 (16:29): 12 false merges in the live rc12d editions; attach rule needs a scarce name, 'war' everyday, three-field prize round-ups; self-test keeps the second grouping file; corpus 11 editions, 1 false merge offline, no recall lost | H7d: user deletes the stray tests, runs the self-test on rc12e
- 2026-10-07 | website | (this commit), site a34517e | `--export-sample` (public edition sample, no publisher excerpts); getagentreach.dev demo shows 5 real stories of the Oct 7 rc12d edition instead of fictional events | H7d: user runs the self-test on rc12e
- 2026-10-08 | rc12 H7d | 83d9dd6, 7b93072, (this commit) | round 4 (18:16, rc12d): Setup unblocks downloaded files + self-test explains a held launch; scarce name + one word needs strong cosine with vectors (Pitt State/Artemis II); MIT license and website (Oct 8); corpus 13 editions, no recall lost | H7e: user installs rc12f, runs the self-test
- 2026-10-08 | W1-W5 | (this commit), site 91d14bc | rc13: website redesign + opt-in automatic publishing (one GitHub commit per edition, withdraw, story removal, key in DPAPI); site seeded with the real Oct 7 r2 edition | W6: user saves the key and runs a refresh
- 2026-10-08 | W8 | (this commit), site 5ad9ae3 | 499 passed (Tk, xvfb), pyflakes clean; review follow-ups: RSS feed + sitemap rebuilt with every publication (tests extended), robots.txt, consistent source counts, generic README paths | W6: user saves the key and runs a refresh; W9 waits for the user
- 2026-10-08 | W9c search | (this commit), site 8161be5 | archive search: publisher writes search/YYYY-MM.json in the edition commit (self-repairing, withdraw-aware, 1 new test); /search/ page (newest 6 months first, accents ignored, phrases, section filter); Playwright 1440/390 on a 10-month copy | PR of rc13 to the default branch; then Phase 2 (event identity across editions)
- 2026-10-08 | Phase 2.0-2.1 | (this commit) | cross-edition answer key (12 editions, 256 events) + churn report; baseline changes._match: near P 0.967 R 0.954, 6h+ apart P 0.966 R 0.752, top stories kept 111/288 far apart; floor test + strict xfail target | 2.1b multi-day editions from the self-test; 2.2 causes; 2.4 matcher
- 2026-10-08 | PR #4, Phase 2.1b-2.4 | 9674c46 (merge), (this commit) | rc13c merged; rc14: matching vs carry-over vs Top Stories reported apart; diagnosis (false continuations = URL overlap with mixed stories + entity sets; misses = new articles, one shared name); daily/registry.py observing in the refresh; Oct 7 held-out 6h+: P 0.991 R 0.898 (was 0.989/0.703); self-test brings 14 days + events.json | user runs the self-test on rc14; extend the answer key to >= 7 days
- 2026-10-08 | handoff | (this commit) | BUILD.md (roadmap, 4 phases), HANDOFF.md (state), CLAUDE.md updated; docs/HANDOFF.md -> docs/HISTORY.md; rc14 self-test NOT run yet | user sends the rc14 self-test zip; then 2.1b multi-day answer key
- 2026-10-08 | backend audit | (this commit) | audit of rc14 (pipeline, worker, store, publisher): 510 passed (Tk, xvfb), pyflakes clean; 14 findings, 2 high (removed stories return after a revision: 28/144 on fixtures; failed upload waits a day); Phase B + docs/BACKEND-AUDIT.md | user decides: Phase B (rc15) now, or wait for the rc14 self-test zip (Phase 2.1b)
- 2026-10-08 | B1-B4, B7 | bcf298a, 30cf56e, 8ec5bf0, 0f44921, (this commit) | rc15: removed stories stay off in later revisions (0 of 144 back, was 28), hourly catch-up of a failed upload, website before podcast, key-expiry warning; full suite with Tk green | user installs rc15 (and runs the rc14/rc15 self-test); then B5-B6 or Phase 2.1b
- 2026-10-08 | rc15b | 90eba6d, (this commit) | CI on rc15 failed once on 3.10 (publishing window test busy > 20 s: Tk finalizer in a worker thread); window-test fixture collects garbage on the Tk thread; CI green on 3.10 and 3.12; zip rc15b | user installs rc15b; then B5-B6 or Phase 2.1b
- 2026-10-08 | W6 | site 90e605c | first publication from the user's PC (rc15, by hand after saving the key): Oct 8 r2, 53 stories, one commit with index, feed, sitemap, search; automatic publishing now on | first automatic publication after the next refresh; B11 (window message)
- 2026-10-08 | backend audit round 2 | (this commit) | rc15 + first live edition (site 90e605c): publishing proven; N1 HIGH (thin same-day revision replaces a full one, reproduced), N2 New badges vs unpublished revision (40/53), N3 newspapers as signals, N4-N6 low; B12-B17 | user decides: rc16 (B12, B5-B6, B13, B11) next
- 2026-10-08 | B12, B5-B6, B13, B11 (round 2 Step A) | a3af246, fcd024d, 7d9bb1c, 260a032, (this commit) | rc16: thin same-day refresh refused (fixture: 44-story edition kept), one bad story left out not the day, dates checked, reads once (6 not 8), hopeless failures not retried hourly, connection test keeps the failure reason | user installs rc16; then Step B (B14 signals, B15 badges)
- 2026-10-08 | U1 | 5a0be23, (this commit) | rc17: silent updates from branch stable (verify, copy changed files with backup, rollback if the new version does not start, pip only on new requirements); 16 updater tests; full suite 535 passed | push stable after CI; user installs rc17; U3 with the next release
- 2026-10-08 | U2 | stable -> aaef839 | real update round trip from the sandbox against GitHub's stable branch passed | user installs the rc17 zip; U3 with rc18
- 2026-10-09 | W headline links | (this commit), site branch claude/adoring-clarke-9iynyj 0b3ec0d | public stories carry `url` (primary_url, as the HTML export) and search entries `u`, so a website headline opens the source in one click; sitemap lists /sports/, /entertainment/, /internet-culture/ (site pages on the same site branch); 2 new tests; 563 passed with Tk (xvfb), 5 Windows-only skips, pyflakes clean; NOT released (no version bump, stable not moved) | user merges the site branch first, then a release carries this to the PC
- 2026-10-09 | Local section | (this commit) | Local category for Frisco, TX (rule in pipeline/local.py, never the model); 2 Google News searches + 5 local feeds that answered in the live feed-check workflow (5 candidates failed: 404/429/403/invalid XML); settings v11; site /local/ on its branch; full suite with Tk green; NOT released, no real refresh with it yet | user decides on a release; then check the first real edition's Local section (false positives, missing stories)
- 2026-10-09 | release rc18 | (this commit) | PR #8 (Phase 1/2 quality) + PR #9 (Local section, headline links) released to stable; no Setup needed (Setup only dropped the unused embeddinggemma model; requirements unchanged) | user's app updates itself; check the first rc18 edition: Local section, `changes` and `url` fields on the website
- 2026-10-09 | Local removed (rc19) | b1faf1d, (this commit); site branch claude/sleepy-clarke-abilea 12a6833 | the user asked for the Local section to go: rule, local feeds (settings v12 removes the five v11 added, keeps the user's own), searches, local_area, feed-check workflow removed; LOCAL kept in the enum so rc18 editions still load; site: nav Today/.../About/How it works, Local only in old editions, /local/ says retired (kept, noindex), archive shows update numbers; 575 passed with Tk (xvfb), 5 Windows-only skips, pyflakes clean; site 64 unit + 24 browser tests, build + check:built pass, 360px checked; NOT released (stable not moved), site branch NOT merged | user: merge the site branch, approve moving stable to rc19, decide whether /local/ is deleted
- 2026-10-09 | rc19 released | stable -> 90f6e5a (CI run 115 green); site branch cbb0738, caefeaf | user approved: stable moved (fast-forward), /local/ deleted from the site branch (build, sitemap, tests; 64 unit + 24 browser tests, build + check:built pass) | user: merge the site branch; check that the PC updated to rc19 and the next edition has no Local
- 2026-10-09 | site PR #12 merged | site main 31150b0 | the site branch (nav, Local retired, /local/ deleted, archive update numbers) was merged; Website checks green on the PR head caefeaf and on main; the Oct 9 r1 edition (05:37 UTC, before rc19) still carries one Local story, shown under its old label | user looks at the live site; Phase 1 items 4-10
- 2026-10-09 | Phase 1 items 5/6/9/10 (rc20) | 712dbc9, (this commit); site PR #13 (c488b50) | live site checked from the user's screenshot (nav, no Local); app: public edition gains optional `sources` (kinds + feeds by name/site/counts, never feed URLs or errors), sitemap lists /sources/ and /corrections/, version rc20; site: X/Facebook/Reddit share links and Report an issue mailto per story, per-story RSS + per-section feeds built in dist, /sources/, /corrections/ (policy + empty append-only log), .prose phone gutter fix; app 575 passed with Tk, pyflakes clean; site 70 unit + 24 browser tests, build + check:built pass, 360px checked; stable NOT moved, site PR NOT merged | user: merge PR #13, approve rc20; next: Phase 2 (timezones, canonical URLs, summary quality: summaries repeat the headline, seen on the live Oct 9 page)
- 2026-10-09 | rc20 released | stable -> f1060d2 (CI run 121 green) | user approved; site PR #13 checks green, not merged yet | user merges PR #13; first rc20 edition fills /sources/; next: Phase 2 item 13 (summaries repeat the headline)
- 2026-10-10 | editorial pass (user's review of the live Oct 9 edition) | b3ab8a9, bd36351, 018e5e0, (this commit); site branch claude/sleepy-clarke-abilea 9ad713a | source accuracy: `_subject_gate` splits a story whose titles tell two events (Oct 9 firing squad + Christa Pike; exact PC merge path not reproduced offline; corpus P/R unchanged 0.962/0.634 replay); summaries: no sentence that repeats the headline (Oct 7 real edition 37 -> 0 openings, model summaries kept 12 -> 28, 7 headlines stand alone), per-sentence checks, Title Case names fix, fallback from the reports' own sentences, prompt; `editorial_review` before every publication (blocking + logged problems); site: one coverage line, plural helper, "no longer in this edition", restating sentences hidden for old editions, Time not stated gone, check-editions warnings; app 586 passed with Tk, pyflakes clean; site 78 unit + 24 browser, build + check:built + check:editions pass, 360/1280 light/dark shots; NOT released, PRs opened at the user's request | user: review/merge the PRs, approve rc21; send a self-test zip for the PC's pair log of the Oct 9 merge
- 2026-10-10 | release rc21 | (this commit) | the user asked for rc21: version, release.json ("Summaries no longer repeat their headline, and a story's sources must all be about the same event."), README, RELEASE-NOTES; stable moves after CI is green | user's app updates itself; check the first rc21 edition (summaries, no mixed stories, editorial check lines in the log)
