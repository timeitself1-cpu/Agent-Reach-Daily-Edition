# History: Agent Reach Daily up to 1.0.0rc12 (October 1-7, 2026)

**Historical, not current.** This was the session handoff until rc12; "Where things stand" and "Open items"
below describe October 7. The current state is in `HANDOFF.md` (repository root), the roadmap in `BUILD.md`,
the step-by-step plan in `docs/PLAN.md`. Kept for the release history, the rc9-rc12 accuracy work, the open
quality items (still valid unless PLAN.md ticks them) and the working tips.

## Where things stand

- **Branch:** rc10 was developed on `claude/loving-darwin-a7rqvs`; rc11 is on
  `claude/affectionate-galileo-isxik1` (no PR has been opened, and none should be unless the user asks).
  rc12 continues there. Version `agent_reach/daily/__init__.py` = `1.0.0rc12`. Release notes:
  `docs/RELEASE-NOTES.md`.
- **CI:** `tests.yml` is green on rc11 (Python 3.10 and 3.12, pytest under `xvfb-run` so the GUI tests
  really run, plus a dry run of the self-test harness). Up to rc10 the GUI tests silently skipped in CI.
- **Windows:** rc11 has been validated on the user's PC with two self-test rounds (October 7): the offline
  suite passes there (404 passed, 1 skipped, 4 xfailed), shortcuts and `.cmd` open the window, real Ollama
  checks, cancel, a full real refresh (~6 min), the model drop (ends in 9 s) and repeated use all pass.
  Details: "Open items" item 0 below and `docs/RELEASE-NOTES.md`.
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
rc9 second accuracy pass from the real October 5 evening edition. rc10 third accuracy pass from the
real October 6 morning edition, and a cloud runner that fits a Daily refresh (below).
rc11 stabilization pass (six robustness fixes from a code review; see below). rc12 story identity:
EmbeddingGemma 2 neighbours + an explicit same-event gate (below).

## rc12 in short (event identity; the user's priority over Phase 1)

- **Why:** five real October 7 editions published 52 false merges (13 mixed stories). HDBSCAN plus
  single-link `LinkIndex.components` chained A~B, B~C into A=C through roundups, dates and broad words.
- **Measured on:** `tests/event_corpus.py` + `tests/fixtures/real/event_gold.json` (427 reports, 225 gold
  events). `python -m tests.embedding_benchmark` writes `docs/eval/identity-eval.md`: rc11 52 false merges;
  rc12 0 with no embeddings (recall 0.635), 0 with replayed rc11 neighbourhoods (0.762), 0 with every
  cosine forced to 1. Real-model numbers (nomic vs `embeddinggemma-2:270m` vs the full model) need the
  user's PC: `Benchmark-Embeddings.ps1 -PullModels`. NOT run yet; no Ollama in the cloud sandbox.
- **Design:** `pipeline/embeddings.py` (event representation `event_repr_v2`, task prompts, model+digest
  aware SQLite cache, fallback chain) proposes kNN candidates; `pipeline/event_identity.py`
  (`IdentityGate`: ACCEPT/REJECT/NEUTRAL with reasons; `cohesive_groups`: accepted edge + no conflict +
  strict majority support) decides. `LinkIndex.components` uses the same gate. `cluster_method=density`
  keeps HDBSCAN as the candidate source if ever needed. Pair log: `diagnostics\semantic\`.
- **Thresholds** (`identity_candidate_cosine=0.45`, `identity_strong_cosine=0.80`) are untuned guesses
  for EmbeddingGemma: read the benchmark's cosine distributions from the user's PC before changing them.
- Also: summary gates (quote-truncated copies, intro-only phrases, month abbreviations), newest report
  sets the current state ("Developing"), attention signals never raise strength, what-changed by best
  URL overlap with split-aware continuity, prefs v9.
- **rc12b (first PC round, Oct 7 12:07):** EmbeddingGemma 2 could not be pulled on Ollama 0.40.0 (404), so
  everything ran on nomic. The benchmark had 2 false merges, the two live editions 26 (the merge pass after
  labelling grew stories one lone report at a time; 'agents'+'hack', 'France'+'protests', 'storm'+'possible').
  All fixed; both live editions are fixtures (`RC12_EDITIONS`, 7 labelled editions, 0 false merges offline,
  recall 0.620 lexical / 0.688 replay). Also: label calls of <= 12 stories with cut-off answers split, pair log
  keeps accepted pairs, grouping model optional in the model check, pull errors shown, self-test FAIL rule.
  Details: `docs/REAL-EDITION-FINDINGS.md`. Next: the user updates Ollama and reruns the benchmark (PLAN H7).
- **rc12c (same afternoon):** with the newest Ollama, the pull says "this model requires MLX support, but the MLX
  runtime is not available": EmbeddingGemma 2 is Mac-only in Ollama for now. Messages say so (no "update Ollama"),
  the self-test reports it as INFO, and the benchmark compares `embeddinggemma:300m` (runs on Windows) with nomic.
- **rc12d (round 2, 13:36):** `embeddinggemma:300m` downloads but Ollama 0.40.0 cannot open it on Windows (manifest
  written as a symlink, "untrusted mount point", ollama/ollama#18847), so still no Gemma numbers. The two live
  editions had 26 false merges in 8 stories (Saint/Mancuso obituaries, Kimmel in Trump Accounts, three polls, two
  'retreats', Belgium/France, two RTX Spark laptops). Five gate rules tightened (lone-report attachment needs a title
  link to every member; "don't"; legislature names; a common name + one word needs strong embedding agreement; a
  two-word phrase is one piece of evidence); laptops open as a strict xfail. Corpus 9 editions (`RC12C_EDITIONS`):
  1 false merge, R 0.620; real nomic vectors replayed: 0 false merges, R 0.679. Also the Windows-only
  `progress.json` delete race (retried now) and the self-test FAIL for the expected fallback.
- **rc12e (round 3, 16:29):** 29 PASS, 1 FAIL (stray test files, which the user deletes: no longer needed). Live editions
  12 false merges in 5 stories: the golf 'retreat' again (the lone-report attach rule still called 'Trump' rare at
  6%; now 2% as in the pair rule), 'Gaza' + 'war' (now an everyday word), Nature's three-prize Nobel round-up (now
  a round-up). Corpus 11 editions (`RC12D_EDITIONS`), no recall lost; the self-test keeps both grouping files.
- **rc12f (round 4, 18:16, run on rc12d):** the .cmd launcher was held 250 s by Windows' security prompt for
  downloaded files (Setup now unblocks the project's files); 'NASA' + 'lunar' joined a Pitt State profile to the
  Artemis II story (a scarce name + one word now needs the strong cosine when vectors exist). Corpus 13 editions.
  MIT license and a rebuilt getagentreach.dev the same day.

## rc11 stabilization pass (bugs found by reading the Daily code, no new features)

- The window trusted the pid in `state/progress.json` / `refresh.lock.json`. After a crash or power
  loss that pid can belong to another process: the window showed "Refreshing" forever, Refresh was
  blocked, and Cancel would terminate the unrelated process. `AppController.activity` now confirms with
  a non-blocking probe of the OS refresh lock (skipped while the worker is the window's own child).
- A run stopped by the Daily time limit stayed `running` in SQLite (cancellation is not an
  `Exception`); `run_once` marks it invalid.
- A cache-repair `OSError` (Windows refusing to move a damaged file a scanner holds open) escaped the
  worker before the attempt was recorded; it is now logged and the refresh continues.
- `check_ollama` crashed on another program answering on port 11434; a negative or NaN `Retry-After`
  is clamped; Follow / Mute from the story menu is validated like the Topics tab.
- Line endings: 22 files were stored with CRLF, which made the two `.ps1` files show as modified in
  every fresh clone. `.gitattributes` now has `* text=auto` and the repository stores LF (CRLF is still
  checked out for `.ps1`, `.cmd`, `.bat`).

## rc10 in short (see the commit message and `tests/test_accuracy3.py`)

- `pipeline/clusterer.py` `LinkIndex`: everyday words (`COMMON_WORDS`: "adding", "national", ...)
  are never the "what happened" unit (`_event_unit`, `linked`). Fixes "ChatGPT/OpenAI + adding"
  (watermarks + cartoons + Apple lawsuit) and "Trump + national" (AI czar + cable lobby).
  `_guard_category`: within Tech / Science & AI, report keywords decide when they favour one 2:1.
  Headlines: up to 18 words kept whole when there is no clause break (`HEADLINE_STRETCH_WORDS`);
  live blogs never give the title.
- `pipeline/cleaner.py`: `strip_bare_urls` keeps a domain that is the subject ("Example.com just
  launched ..."); `LIVE_BLOG_RX` / `is_live_blog`; "- as it happened" removed from headlines.
- `daily/edition.py`: no "Uncertain trend" on cards (one note when the whole edition is uncertain;
  old stored labels dropped on load). `select_stories`: corroborated stories beyond the category
  cap come before single-outlet ones; sections list corroborated stories first; live-blog-only
  stories are left out. `body_sentences`: numbers must be in the sources, no page voice
  (you/your/we/our outside quotes), no verbless subordinate fragments, no sentence that only
  restates the headline, no near-repeat of earlier sentences together (`NOVEL_SHARE` 0.7), a clause
  that repeats the sentence is cut. `lead_sentence` fallback reads the members' own text (not live
  blogs). Notes are in `edition_notes` ("it had", "its section").
- `daily/brief.py`: `_novel` compares with everything already said (0.7) and rejects self-repeats;
  `WHY_RESTATE_SHARE` 0.8 -> 0.7; "why it matters" needs a consequence (`CONSEQUENCE_RX` or an
  affected group), not names or numbers alone.
- `daily/changes.py`: UPDATED only for new publishers or a headline change backed by new reports;
  growing/fading only against an edition of the same day; `keep_previous_categories` (called in
  `refresh.py` before selection) keeps a carried-over story's section unless a new publisher arrived.
- Found in four real rc10 runs on the user's PC the same morning (also in `test_accuracy3.py`): the
  medicine and physics Nobel Prizes merged (`EXCLUSIVE_QUALIFIERS` in `event_compatible`; Nobel week
  runs to October 12); "games" + "consoles" joined two unrelated items (no shared name: shared words
  must be in at most 1% of the run, `nameless_cap`); a purpose passed as "why it matters"
  (`PURPOSE_RX`); "hit" + "cuts" (FBI budget cuts + SSD price cuts) and "NASA" + "space" (Crew-12 +
  a telescope) linked unrelated items (more `COMMON_WORDS`); a model headline named the wrong game
  ("Thursday Night Football"; `headline_supported`, 50% of its words in the reports: 2 of 227
  headlines in five runs fell below it); "U.S." ended a sentence; a pronoun-led sentence lost the
  sentence it refers to; a
  1-report story rated 9 took a Top Stories place from a 5-report story, so single-outlet stories now
  always come after corroborated news (rated 9+ first among them; this replaces rc9's "rated 9
  competes" rule); "ahead", "costs" and "midterm(s)" joined a diesel order to midterm items (more
  `COMMON_WORDS`); a headline word the old reports already used is not "news"; a single shared
  key name matched unrelated stories in "what changed" and dedupe (`edition.same_entities`); brief
  details that restate a sentence and add a bit now replace it (`place_sentence`); sentences cut
  short are dropped (`ends_dangling`); a title opening with a quotation keeps its opening quote.
- From the user's first rc10 edition (October 6, 6:49 AM): "Gov." was shown as a sentence (more
  abbreviations in the splitters; a sentence needs 3+ words); "- US politics live" / "Ukraine war live:"
  are live blogs too; "why it matters" may not be a cause ("is a response to"), a detail ("as
  required by") or repeat five words of the summary; "the '80s" gets no stray closing quote; "free...
  and" in a title becomes "free, and"; summary casing is restored only for real names (the reports'
  prose writes "the brain", not "Brain").
- From the user's 7:24 AM edition (revision 3): a number attached to the wrong thing ("Over 67 million
  Wikipedia hosts expose sensitive data"; the page counts articles) is dropped by
  `edition.numbers_anchored` (also in the brief pass); 1 of 153 published number sentences in eight
  real editions fails it, the false one. "The author provides their picks" is not news. Also from
  the same morning's runs: shopping-event roundups are promotional, "games" is an everyday word,
  currency signs survive ASCII folding.
- From the user's 8:03 AM edition (revision 4) and two runs after it:
  - Roundups never link to other reports (`cleaner.is_roundup`, `LinkIndex.roundups`): live blogs,
    newsletter digests ("First Thing: ..."), and two headlines in one title ("Yankees staring at
    sweep ... | Falcons run roughshod over Saints"). A Guardian live blog whose title changed during
    the day had joined a "San Diego" trend to the Trump-ads story.
  - More everyday words: "historic", "raised", "million", "really", "night", "safety".
  - Price drops for a shopping event ("Lowest Price Since June for Prime Day") are promotional.
  - A summary may not open with a word that needs an earlier sentence ("It is ...", "But ...",
    "The move ...") or end in "..." (a clipped excerpt).
  - Titles of up to 18 words stay whole unless they contain a sentence break: a clause cut had
    dropped the main verb ("Jim Bakker, who lost ... scandals, dies at 86").
  - "Bros.", "Inc.", "Corp.", "Co.", "Ltd." never end a sentence ("Warner Bros. have merged").
  - Trend fragments no longer link through an everyday word ("National Taco Day" had joined the AI
    czar); "This model is ..." no longer opens a summary ("This year's ..." still may); summary casing
    also checks sentence-case titles when the page text is silent ("Creators", "Mental Health").
  - Settings v8: The Independent - World answers every automated reader with HTTP 429 (it works only
    in a browser: a TLS-level block, not something to work around), replaced by CBS News - World.
- Reddit health notes name the subreddits without URLs, grouped by cause. Settings v7: Yahoo
  Finance (HTTP 404) -> Bloomberg Markets (`REPLACED_IN_V7`).
- `cloud-runner.yml`: the Daily run writes its own settings.json (80 articles via input
  `daily_articles`, 100-minute limit, no podcast). Run 37421270778 failed because 260 articles
  needed 14 label calls of 4-12 min each at ~4 tok/s and hit the 90-minute refresh limit; the
  workflow's `AGENT_REACH_MAX_ITEMS_FOR_LLM=150` never applied to the Daily app (it passes its own
  `max_items_for_llm`).

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

A cloud sandbox has no Ollama and no news access. Four ways to see real output:

0. **The self-test zip (rc11+).** `Test-AgentReachDaily.ps1` on the user's PC writes
   `AgentReach-selftest-<time>.zip`: `report.txt` (PASS/FAIL per check), the real editions
   (`edition.json`, `edition.txt`, `edition-2.*`), an automatic read-through of them (candidate
   duplicates, odd text, old reports: regression-fixture material), the scratch `refresh.log`s, the
   model-drop run, `pytest-output.txt` from Windows, and the launcher checks. Read `report.txt` first.

1. **The user's export.** They send `AgentReachDaily-YYYY-MM-DD.html` (the ... menu > Export) and
   `logs\refresh.log`. Convert the HTML to text (strip tags) and read it story by story: mixed
   stories, invented sentences, wrong headlines, ranking.
2. **GitHub Actions.** `cloud-runner.yml` (workflow_dispatch) with input
   `entrypoint=agent_reach.daily` runs one real Daily refresh on a CPU runner and uploads
   `edition-<run>.html`, `report.txt`, `pipeline.log`, `daily-logs/`, `daily-diagnostics/` and
   `status.json`. Exit 0 = published, 20 = too little news, 31 = Ollama/model missing. The Daily
   data folder is cached under `state/daily`, so later runs have history. CPU runs are slow
   (expect 30-90 min); the job timeout is 120 min. `entrypoint=agent_reach` (default) runs the
   classic CLI report instead. Run 37421270778 (rc9) failed on the 90-minute limit; rc10 runs the
   Daily refresh with 80 articles (input `daily_articles`) and a 100-minute limit. Run 37446999111
   (rc10, commit 2625d47) published 24 stories: refresh 45 min (7 label calls of 1-11 min at ~4 tok/s,
   brief pass 6 min), job 47 min.
3. **A local run on the user's PC** (only when the session itself runs there, as the rc10 session
   did; Ollama with a GPU, ~6 min). Never touch their data folder: copy `settings.json`, `cache\`,
   `data\` and `state\` from `%LOCALAPPDATA%\AgentReachDaily` to a scratch folder, set
   `podcast_auto` false in the copy, then `python -m agent_reach.daily --refresh-now --data-dir <copy>`
   and `--export-html`. The copy keeps the real previous edition, so "what changed", category
   stability and the settings migration (their settings.json is still version 1) are exercised too.

## Open items, in the order I would take them

0. **rc11 Windows validation.** Round 1 (October 7, self-test zip on the user's PC: Windows 11, Python 3.12,
   Ollama 0.35.1, 2560x1440 at 100%): 24 pass, 3 fail; all three fixed (`docs/RELEASE-NOTES.md` items 17-22).
   Round 2 (Ollama 0.40.0): the offline suite runs on Windows (404 passed, 1 skipped, 4 xfailed; real file
   locks, TerminateProcess), shortcuts and `.cmd` open the window, the model drop ends in 9 s. Still open:
   the `.pyw` double-click (the harness now records the `.pyw` association), the by-hand checklist answers,
   a morning with the scheduled task.
   The user's project folder holds `agent_reach/daily/events.py`, `agent_reach/pipeline/identity.py`,
   `tests/test_event_contract.py` and `tests/test_event_identity.py`, which are NOT in this repository (an
   event-registry / story-identity layer from other work; they import `edition.story_from_event` and
   `cleaner.ABBREVIATION_GUARD`, which rc11 does not have). Ask the user where that work lives before the
   event-layer phase. Real-edition findings for that phase: `docs/REAL-EDITION-FINDINGS.md`.
   Known residual risks: the window's lock probe can, in a millisecond window, make a scheduled worker that
   starts at that instant exit as "busy" (it retries at the next hourly check; only when a stale progress
   file exists); a worker killed while publishing can leave a newer edition with an older pointer (repaired
   at the next refresh).

1. **Seen in the rc10 real runs, not fixed yet:**
   - A shared phrase that is itself generic still links two items: "Trump Rallies for Republicans Ahead
     of Midterm Elections" + "Trump announces $90 payments ... ahead of midterm elections" (the unit
     "midterm elections" counts as an event because of "elections"). `test_accuracy3` keeps only the
     diesel order apart from them.
   - Topic nouns shared by unrelated reports can still link them when a name is shared too ("Trump" +
     a moderately common word); `nameless_cap` only covers titles with no name in common. Each real
     run so far showed one or two such pairs; `COMMON_WORDS` grew from them. Borderline and left as
     is: "NASA's Prima space telescope would aim to see what James Webb can't" + "James Webb Space
     Telescope investigates what happens when planets crash together" (shared "James Webb" and
     "space telescope"). A frequency ceiling on single event words was rejected: on a big day the
     key word is frequent ("plague" was in 1.2% of the run) and real stories would split.
   - The same event can still appear twice when one report was not grouped with the rest ("WHO
     Comments on Russian Plague Lab Death" next to the plague story, 8:20 AM run; and: "US Closely
     Monitoring Case of Lab Worker Who Possibly Died of Plague in Siberia" (Hacker News, filed under
     Tech) next to the plague story in News (user's 6:49 edition). `same_topic` compares headlines
     only.
   - The model can misattribute a quoted source's own comment (seen twice, Altman/Boing Boing): "This is an incredible bargain to offer
     humanity, according to Altman" (Boing Boing's sarcasm, not Altman). Every word is in the sources,
     so the support check cannot see it.
   - A "why it matters" whose only concrete element is a group noun passes ("This Nobel Prize is
     overdue, as scientists have anticipated the recognition for years.": "scientists").
   - A "why it matters" that restates the summary in other words passes (Pentagon: "The US Department
     of Defence is no longer using Anthropic's AI tools ..." after "The Pentagon stopped using ...").
   - Publisher category hints still win outside Tech / Science & AI: "Sam Altman Calls for Regulatory
     Light Touch on AI" landed in Internet Culture (Boing Boing). Gizmodo's Antarctica story (rc9) in Tech.
   - Label batches can hit `num_predict` 2048 (`clusterer.py`, label call): the JSON is cut, and the
     call is retried up to three times. Harmless on a GPU (~26 s each), expensive on the CPU runner
     (~8 min each). Smaller batches when a batch's groups are large, or a higher cap, would fix it.
2. **Momentum after a settings change:** any change of the feed list (including the v7 migration)
   makes every story's momentum uncertain for about a day, because the scorer's comparable config
   includes `news_rss_feeds`. rc10 shows that once in the notes instead of on every card.
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
- GUI tests need Tk AND a display: the cloud image's default Python 3.13 has no tkinter, so the GUI file is
  skipped as a whole ("1 skipped"). `apt-get install -y python3-tk`, then a venv from `/usr/bin/python3.12`
  (or `uv python install 3.10`, which has Tk) and `xvfb-run -a <venv>/bin/python -m pytest -rs`.
  Screenshots: `xvfb-run -a -s "-screen 0 1366x768x24"` and ImageMagick `import -window root shot.png`.
  `.ps1` files can be parse-checked with PowerShell 7 (download the linux-x64 tarball from the PowerShell
  GitHub releases into /opt/pwsh) and `[System.Management.Automation.Language.Parser]::ParseFile`.
- On the user's Windows PC: Python 3.9/3.11/3.12 only (no 3.10; CI covers 3.10). PowerShell 5.1:
  `[IO.File]` calls resolve relative paths against the process folder (the user's install), not the
  shell location, so always pass absolute paths.
- Read large files by line range (`gui.py` is ~2,000 lines, `edition.py` ~1,100, `clusterer.py` ~1,300);
  use `grep -n` to find the place first.
- Screenshots are expensive: take one only to check a visual change, at a modest size.
- Keep a Python 3.10 check in the loop: `python3.10 -m venv` and run the suite there before a
  release (3.10 rejects backslashes inside f-string expressions; rc9 nearly shipped one).
