# Handoff: Agent Reach Daily (state after 1.0.0rc10)

For a new Claude session picking up this project. Read `CLAUDE.md` first (commands, invariants,
conventions), then this file. `README.md` is the user guide; `docs/architecture.md` the internals.

## Where things stand

- **Branch:** rc10 was developed on `claude/loving-darwin-a7rqvs`; the review pass below is on
  `claude/affectionate-galileo-isxik1` (no PR has been opened, and none should be unless the user asks). Version `agent_reach/daily/__init__.py` = `1.0.0rc10`.
- **CI:** `tests.yml` is green on rc10 (Python 3.10 and 3.12; the 15 GUI tests skip there without a
  display). On the user's Windows PC: 371 tests, 370 pass and 1 skips (SIGKILL semantics; a Reddit
  pacing test can fail by milliseconds when the PC is busy); the GUI
  tests run against the real display, and Tk start-up there occasionally fails and skips one of them.
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

## Review pass after rc10d (bugs found by reading the Daily code, no new features)

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

A cloud sandbox has no Ollama and no news access. Three ways to see real output:

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
- GUI tests need Xvfb: `Xvfb :99 &` then `DISPLAY=:99 python -m pytest ...` (restart Xvfb if GUI tests
  suddenly skip). `/opt/pwsh/pwsh` can parse-check `.ps1` files.
- On the user's Windows PC: Python 3.9/3.11/3.12 only (no 3.10; CI covers 3.10). PowerShell 5.1:
  `[IO.File]` calls resolve relative paths against the process folder (the user's install), not the
  shell location, so always pass absolute paths.
- Read large files by line range (`gui.py` is ~2,000 lines, `edition.py` ~1,100, `clusterer.py` ~1,300);
  use `grep -n` to find the place first.
- Screenshots are expensive: take one only to check a visual change, at a modest size.
- Keep a Python 3.10 check in the loop: `python3.10 -m venv` and run the suite there before a
  release (3.10 rejects backslashes inside f-string expressions; rc9 nearly shipped one).
