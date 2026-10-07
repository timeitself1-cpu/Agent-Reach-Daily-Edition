# Agent Reach Daily: plan

The live roadmap. **A new session starts here** (after `CLAUDE.md`): find the current phase, take the first
unchecked sub-task, do it, then update this file.

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

## Where we are (October 7, 2026)

- Version **1.0.0rc12** (zip rc12d) on branch `claude/affectionate-galileo-isxik1`: EmbeddingGemma 2 + event
  identity. PC round 1 (Oct 7 12:07) fixed in rc12b (H1-H6), round 2 (13:36) in rc12d (H7b): the live editions still
  had 26 false merges from rules the corpus did not exercise; now 1 open (two RTX Spark laptops) on the 9-edition
  labelled corpus offline. No Gemma model has run on the PC: EmbeddingGemma 2 is MLX-only in Ollama, and Ollama
  0.40.0 cannot open `embeddinggemma:300m` after downloading it (Windows symlink bug, ollama/ollama#18847).
  **Next:** the user runs the self-test on rc12d (H7c), then Phase 1; H7 waits for an Ollama that can run a Gemma
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
  - [ ] H7c. The user runs `Test-AgentReachDaily.ps1` on rc12d: expect 0 FAIL besides the stray test files, and
        check the live editions for mixed stories again.
  - [ ] H7. **Blocked on Ollama:** nomic vs a Gemma embedding model on the PC (`embeddinggemma:300m` downloads but
        Ollama 0.40.0 cannot open it, ollama/ollama#18847; EmbeddingGemma 2 is MLX-only). When a later Ollama runs
        one: `Benchmark-Embeddings.ps1 -PullModels`, replay here with `--replay <vectors-*.json.gz>`, put it in the
        fallback chain only if it beats nomic; set `identity_strong_cosine` only if the different-event p99 says so.

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

- [ ] 2.0 Resolve 0.5 (the existing events.py/identity.py work). If it is available, review it against this
      plan and adopt what fits; do not build a second, parallel design.
- [ ] 2.1 Measure first: `tests/churn_report.py` (or a test helper) computes for each fixture pair:
      stories matched by URL overlap, by `changes._match`, "new"/"gone" counts, and whether each Top Story
      survives. Record the baseline numbers in the Progress log (r1->r2 on Oct 7: 20 of 35 matched, 3
      identical headlines; selftest2: the #1 story vanished).
- [ ] 2.2 Find the cause of churn on the fixtures before designing: how much comes from (a) which ~260 of
      ~1,450 items are selected for clustering (`cleaner.select_for_llm` budget, per-feed floors), (b)
      HDBSCAN grouping differences, (c) story selection caps/ranking (`edition.select_stories`), (d) model
      relevance scores varying run to run. Use the logs in the self-test zips. Write the findings here.
- [ ] 2.3 Event registry: a persistent store (`state/events.json` or a SQLite table in `data/agent_reach.db`)
      of events: id, first_seen, last_seen, headline history, key names, URL set, embedding centroid
      (from the run's vectors), category, last story text. Owned by the refresh worker (lock holder).
- [ ] 2.4 Matching a new run's clusters to registry events: shared article URLs; then key-name + event-word
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
- 2026-10-07 | rc12 H7b | (this commit) | round 2 (13:36): 26 false merges in the live rc12c editions; five gate rules fixed, laptops open (xfail); progress.json delete retry; self-test INFO for fallback; Ollama symlink bug explained; corpus 9 editions, 1 false merge, R 0.620 | H7c: user runs the self-test on rc12d
