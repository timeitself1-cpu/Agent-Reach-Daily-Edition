# Findings from real editions (input for the next phase)

Real editions are the test material for the intelligence / event layer. Each finding names the edition and
the story, and the regression test that holds it (`tests/test_real_editions.py`; `xfail` = not fixed yet).
Fixtures: `tests/fixtures/real/` (edition JSON as the app wrote it; public news only).

## October 8, 2026, 2:48 PM: the first edition published from the PC (rc15, website commit 90e605c)

The public copy only (`editions/2026-10-08.json` on the website; the full edition is not in this repository yet).
53 stories, 1,512 reports read, 10 of 10 sources. Backend audit round 2 (`docs/BACKEND-AUDIT.md`):
- #6 "Margaret Hamilton Dies at 90": The Guardian, The New York Times and BBC News appear as kind "signal" (their
  links came through Mastodon posts), so the site shows a newspaper as "social/search signal" (N3).
- 40 of 53 stories badged New against revision 1, which never reached the site (N2).
- 37 of 53 single-report stories; 1 of 53 "why it matters" (#34, "The call affected the outcome of the game.").
- Category: #2 OpenAI's revenue under Science & AI; #11 Anne Carson's literature Nobel under Entertainment.
- Promotional/evergreen: #50 "Physical Media and IRL Experiences Are Booming" (a Variety summit takeaway), #52 "The
  Triple-i Initiative October 2026". #34 (one source) summary drifts to other games ("The Dodgers reached the NLCS").

## October 7, 2026: rc11 self-test on the user's Windows PC

Two editions 9 minutes apart (`2026-10-07-selftest-r1.json`, `-r2.json`; r2 after setting sections to 8).
llama3.1:8b on an RTX 4070 Super: a full refresh took 330 s (ingest 30 s, 260 article pages 17 s, grouping and
21 label batches 261 s, brief pass 10 s; the 5.4-minute podcast was recorded with the Windows voice).

The edition reads well: 48 stories, Top Stories all corroborated (2-8 independent reports), and every Top
Story's summary agrees with the headlines and excerpts it cites (Paramount/Warner $111B merger, French student protests, the
physics Nobel to Francis Halzen, OpenAI agents on Wikimedia, the Siberian plague death, the German ex-spy
chief, Eva Marie Saint, Kenya's first Ebola case, Sally Yates at Cornell, Dodgers-Braves).

Fixed in rc11 (after this run):

| Story | Problem | Fix |
|---|---|---|
| #36 Meta's Muse, #26 NASA contractors | "..., but the context / reason is not specified." (the model describing its input) | `edition.without_unstated` |
| #17 Mistral Large 4 | "It was trained on 3,800 NVIDIA Grac." (a context cut inside a word, copied by the model) | `clusterer.clip_words` for the model's context |
| notes | "21 of 150 feeds returned nothing: BBC News, Reuters, Associated Press..." were YouTube channels (YouTube answered 1 of 22) while the BBC's article feeds worked | one note per channel outage; the feed doctor does not count an outage |
| model drop | after Ollama went away every remaining batch retried 3 times at ~2 s per refused connect: the refresh ended 112 s later | the first refused connection ends the model calls of that run |

Not fixed (next phase; `xfail` tests):

1. **One event twice.** Messi's farewell is #15 "Lionel Messi Bids Farewell to Argentina Fans in Emotional
   International Finale" (Sports) and #37 "Messi Signs Off in Tears After One Last Argentina Master Class"
   (Entertainment). The density step kept them apart and `same_topic` compares headline words only.
2. **Editions minutes apart disagree.** r2, 9 minutes after r1 on the same news: 15 new, 28 no longer listed,
   only 3 identical headlines; "Eva Marie Saint Dies at 102" (3 reports) and "Kenya Confirms First Ebola
   Case and Death" (2 reports) dropped out. The smaller sections explain part of it; the rest is run-to-run
   variation in which 260 of ~1,450 items are grouped and how the groups come out. A stable event identity
   across refreshes is the fix (the user's folder holds an `events.py` / `identity.py` from other work on it).
3. **Category from the outlet.** "Paramount Completes $111B Warner Merger" (#1) and "Drones Sink Ships in NATO
   Countries" (#23) are under Tech because Ars Technica / Hacker News reported them.
4. **'Why it matters' is rare.** 2 notes for the 18 stories of the brief pass; the grounding gates reject
   most model output. Worth measuring which gate rejects what before loosening anything.
5. **Weak leads.** #30 Padres ("Right-hander Michael King ... is slated to start": not what happened), #42
   Overwatch ("Earlier this week, Blizzard released a new trailer": not the news), #8 Kenya ("The disease
   continues to spread rapidly through the north-east of the country": the country is DR Congo, not Kenya).
6. **Evergreen and promotional items in Entertainment.** #44 "13 Record Store Day Releases Actually Worth
   Getting on Black Friday", #46 "The 10 Greatest Sci-Fi Cyberpunk Movies of All Time, Ranked", #47 "This One
   Crucial Narnia Detail ..." fill the section on a quiet day.

## October 7, 2026, 5:30 AM CDT: the user's real morning edition (HTML export)

Refresh 5:30-5:36 AM. 51 stories in 7 sections. Better than the night before: one event per story (Messi once,
under Sports), the Paramount merger and Eva Marie Saint filed under Entertainment, a 9-report chemistry Nobel
on top, and YouTube answered again (the October 7 night outage was transient).

1. **"What changed" says 43 new, 41 no longer listed, 1 unchanged** against the October 6, 8:03 AM edition, and
   nearly every card carries NEW. Stories that were in yesterday's edition (the Siberian plague death, the
   physics Nobel) come back as "new" because their reports, ids and headline words changed overnight. The
   NEW tag is only useful once stories have an identity across editions (event layer).
2. **No Hot or Rising labels** ("the sources or settings changed since the refresh used for comparison"): the
   settings v8 feed change after the 8:03 AM refresh. Momentum is lost for a day after any feed change because
   the scorer compares the whole configuration (docs/HISTORY.md open item).
3. **Thin single-outlet filler in the category sections**: 8 of 9 Tech stories, 5 of 6 Science & AI and 6 of 7
   Entertainment stories are one outlet each, including a shopping deal ("LG Evo B6 4K 120Hz OLED TV Drops to
   Under $1,000 for Prime Day" passed the promotional filter), a TV listing ("MLB Playoff Games on TV Today:
   Schedule, Times, TV Channels, Live Streams"), a survey page ("State of Devs 2026"), a library changelog
   ("Tapo (Rust/Python Library) Now Speaks TP-Link's TPAP Protocol"), an anniversary piece ("9 Years Later,
   Margot Robbie's Cult Classic ...") and a listicle ("Five Ways New NBA Lottery Rules Could Impact ...").
4. **Leads that do not say what happened**: "Drones Used to Seed Clouds in Cloud Seeding Experiment" -> "On 23
   August, Cooper Freeman had no idea clouds above his head were being filled with a silver compound." (a
   feature's opening line); "PS5 Modders Using AI Tools ..." -> "Recent games requiring newer firmware are
   inaccessible."; "'Chipflation' Drives up Cost of Video Games and Consoles" -> "Prices show no signs of easing."
5. **A claim to verify against its source**: "Trump Worries Iran Could Target U.S. Cities" -> "... and as a
   result, some places are getting extra nuclear protection." (Axios, CNBC, The Hill).
6. **Headline names**: "Claire, Ex-Dodgers GM, Dies at 91" (Fred Claire).
7. **Category by keyword**: "PS5 Modders Using AI Tools ..." and "Billions Pour into OpenAI, DeepSeek Ahead of
   IPOs" under Science & AI.

## October 7, 2026, 9:29 AM: second self-test run (`2026-10-07-selftest2-r1.json`, `-r2.json`)

46 stories; the two Nobel prizes (physics, chemistry) correctly separate; 0 'why it matters' (17 rejected).

- Fixed: "Biologist James D." / "Watson appears to have ..." (#30): a middle initial ended the sentence.
- Not fixed (xfail): the #1 Top Story "US Woman Who Survived Botched Execution Is Conscious, Speaking"
  (Christa Pike, 3 reports) is absent from the edition made 6 minutes later; 21 of 46 stories "no longer
  listed" again.

## October 7, 2026, 9:35 AM: HTML export of the refreshed edition (`2026-10-07-0935-export.json`)

Turned into a fixture with `python -m tests.html_fixture <export.html> <out.json>`; every published report of
this and the four other October 7 editions is labelled with its real event in `tests/fixtures/real/event_gold.json`
(`tests/event_corpus.py` scores any grouping). rc11 published **52 false merges in 13 stories** over the five
editions. All fixed in rc12 (identity gate; `tests/test_identity_gate.py`, `docs/eval/identity-eval.md`):

- Tech #1 "Privacy Watchdog Launches Investigation into China-Based Company" (Australia's privacy regulator vs
  Shenzhen Qingcheng, maker of the HeyCyan app in Kmart's smartglasses) carried WSJ's "The Mulleted,
  Meme-Loving Billionaire Behind Meta's Hit AI App". Shared only broad concepts ('app', 'AI', 'behind').
- #6 "Collins Distances Herself from Trump in Maine Senate Debate" carried the Washington Post's Cornell
  sexual-violence charts, PBS's "News Wrap: Cornell says Sally Yates will review ..." and NBC's Morning
  Rundown ("Battleground candidates clash over Trump and Cornell allegations ..."): a roundup bridged them.
- #3 "James Webb Space Telescope Investigates Planetary Collisions" carried Mashable's "NASA's Prima space
  telescope would aim to see what James Webb can't" ('James Webb Space Telescope' is one name, not two facts).
- #10 "NASA Features Supernova Remnant Pa 30 and Satellite Puzzler" joined APOD "2026 October 7", The
  Atlantic's Fauda review, the "#October7" hashtag and "October 2026 Satellite Puzzler": a date as evidence.
- Selftest editions: "Star Moles Signs to Dead Oceans" in "Dead Star Likely Birthed a New Planet"; Claude's
  Google Docs integration in "Google Releases EmbeddingGemma 2"; ABC/FCC court fight in the 500 detained
  US citizens story; Google's 'virtual cell' investment in Google's gaming platform.

Text:

- Science #3 summary was only "By studying 21 rare." (source: 'By studying 21 rare "extreme debris disks" ...':
  the model's JSON string ended at the inner quote). Fixed: truncated-copy and intro-only gates, real lead as
  fallback (`test_a_summary_cut_at_a_quotation_mark_is_not_published`).
- Selftest2 r2 #9 "Prime Minister Benjamin Netanyahu faces a reckoning over the Oct.": split after a month
  abbreviation. Fixed (`MONTH_DAY_GUARD`).
- #2 "Stock Markets Hit Record High Despite Inflation, High Fuel Prices" said "record high Tuesday" on
  Wednesday while its newest report said U.S. equities fell on Wednesday. Fixed: the newest dated source
  sentence leads, card labelled "Developing" (`test_the_newest_report_controls_the_current_state`). The
  headline itself still comes from the model and can stay stale: open.
- The same story was "Strong evidence" partly because a Google Trends query added a channel. Fixed (rc12 D).

## October 7, 2026, 6:16 PM: self-test on the user's PC (round 4, still rc12d)

Self-test `AgentReach-selftest-20261007-1816.zip`: 28 PASS, 1 FAIL, 11 INFO in 26 min. The two real editions
(`2026-10-07-rc12d2-r1.json` 18:26, 51 stories; `-r2.json` 18:34, 44 stories) are fixtures with gold events: the
labelled corpus now has 13 editions.

- **Still rc12d.** The rc12e zip arrived two minutes before this run: the zip has no `edition-2-semantic-*.json`
  (rc12e adds it) and Nature's three-prize "Nobel Prizes 2026" round-up is still in the chemistry story in both
  editions (rc12e makes it a round-up). The rc12e fixes are still untested live.
- **Stray tests gone:** the Windows suite loads cleanly, 476 passed, 1 skipped, 6 xfailed.
- **The one FAIL: AgentReachDaily.cmd, 250 s.** The check waits 90 s for the window, but `os.startfile` itself
  did not return for about 250 s: Windows' "Open File - Security Warning" dialog for a `.cmd` extracted from a
  downloaded zip (the shortcuts and the `.pyw` opened in 5 s). Fix: Setup clears the Zone.Identifier mark from
  the project's own files; the self-test explains a launch Windows held for 20 s or more.
- **One new false merge:** r1 #19 "NASA Releases Artemis II Lunar Science Data" carried "From Pitt State to lunar
  research at NASA Johnson Space Center" (a university alumnus profile). 'NASA' + 'lunar' counted as two
  distinctive phrases (NASA in under 2% of the run), cosine 0.788 just under the strong 0.8. Fix: with vectors, a
  scarce name plus one phrase is accepted only at the strong cosine; without vectors it still links (lexical
  fallback recall unchanged). Real nomic replay: recall 0.679 unchanged, and the Warner Bros deal / Skydance film
  heads pair (different events) now stays apart too. Test: `test_a_rare_name_and_one_word_need_the_embedding_when_there_is_one`.
- Golf 'retreat' and US forces were two stories this time (the golf report was not alone). Texas's next
  execution is labelled related to Christa Pike's. Real refresh 429 s, 51 stories, 2 'why it matters' of 21.

## October 7, 2026, 4:29 PM: rc12d self-test on the user's PC (round 3)

Self-test `AgentReach-selftest-20261007-1629.zip`: 29 PASS, 1 FAIL, 11 INFO in 21 min. The two real editions
(`2026-10-07-rc12d-r1.json` 16:42, 51 stories; `-r2.json` 16:50, 42 stories) are fixtures with gold events: the
labelled corpus now has 11 editions.

- **The one FAIL** is the stray `tests/test_event_contract.py` and `tests/test_event_identity.py` (they import
  `agent_reach/daily/events.py` and `agent_reach/pipeline/identity.py`, other work in the user's folder that does
  not load against this release). The user says they are no longer needed and deletes them.
- **Windows suite:** 476 passed, 1 skipped, 6 xfailed; the `progress.json` retry from rc12d passes on Windows. The
  grouping row is INFO for the expected fallback, as intended. Real refresh 432 s, 51 stories, 28 label batches
  (0 failed); 0 'why it matters' of 19 (16 rejected), 3 in the second edition. Model drop ends in 10 s.
- **Live rc12d editions: 12 false merges in 5 stories** (r1 5 in 2, r2 7 in 3):
  - r1 #8 / r2 #9 "Trump's Retreat": the golf club's "presidential retreat" with US forces pulling back, again. The
    gate kept the pair NEUTRAL as rc12d intended ('a common name and one distinctive phrase', cosine 0.70 and 0.76),
    but the lone-report attach rule still counted 'Trump' as a rare name (6% of the run, 1,323 reports) and attached
    it through 'Trump' + 'retreat'. Fix: that clause needs a scarce name (2%, `name_cap`), as the pair rule does.
    In the 72-report r2 replay 'Trump' is genuinely scarce and replayed cosines are 0.96, so the pair stays merged
    there (`SMALL_RUN_MERGES`); `test_a_common_name_and_one_word_never_attach_a_lone_report` rebuilds the real run.
  - r2 #1 "Israelis Mourn Oct. 7 Attack" carried "Gaza child's autoimmune condition triggered amid Israel's war":
    'Gaza' + 'war' were two distinctive phrases (a shared name lifts the word cap to 6%, and 'war' is in about 4% of
    titles). A war is a topic that runs for years, not one event. Fix: 'war' is an everyday word. Traced from the
    replay only: the self-test kept the first refresh's gate decisions alone; it now keeps the second's too.
  - r1 #5 / r2 #5 the chemistry Nobel carried Nature's "Nobel Prizes 2026: brain switches, 'ghost' particle hunter,
    and 'the chemistry of life'" (its lead names the medicine and physics prizes). Fix: a report whose title and lead
    name three prize fields of one kind is a multi-story round-up.
  - Labelled related, not counted: Texas's next execution and lawyers trying to block it, in Christa Pike's story.
  - Looked at and left alone: Kirby Smart's Georgia preparations and an 'escambia county school district' trend in the
    Isaias story (the same storm); the French mayor's clash with student protesters in the French PM's protest story.
  - The two RTX Spark devices were two stories this time (Surface Laptop Ultra, Surface RTX Spark Dev Box).
  Offline after the fixes: replayed neighbourhoods 1 false merge on 11 editions outside the small-run pair (the open
  laptops), no edition lost recall; real nomic vectors replayed: 0 false merges, R 0.679 (unchanged). Tests:
  `test_rc12d_refresh_cases_stay_apart`, `test_a_common_name_and_one_word_never_attach_a_lone_report`.

## October 7, 2026, 1:36 PM: rc12c self-test and benchmark on the user's PC (round 2)

Self-test `AgentReach-selftest-20261007-1336.zip` (28 PASS, 3 FAIL, 10 INFO) and
`AgentReach-embedding-benchmark-20261007-1336.zip`, Ollama 0.40.0. The two real editions
(`2026-10-07-rc12c-r1.json` 13:41, 46 stories; `-r2.json` 13:50, 42 stories) are fixtures with gold events: the
labelled corpus now has 9 editions.

- **No Gemma numbers yet.** EmbeddingGemma 2: "requires MLX support" (as expected since rc12c). `embeddinggemma:300m`
  downloaded (`pull-log.txt`: downloaded) but every embed call failed: "CreateFile ...\.ollama\models\manifests-v2\
  ollama.com\library\embeddinggemma\300m: The path cannot be traversed because it contains an untrusted mount
  point", and `ollama list` does not show it. This is an Ollama 0.40.0 bug on Windows (ollama/ollama issue 18847,
  open: the 0.40 manifest is written as a symbolic link that Windows refuses to follow; the reporter suspects
  Windows Developer Mode, not verified). Nothing to fix in Agent Reach; the benchmark now says so in plain words
  instead of "Pull it". All numbers below are nomic-embed-text.
- **Benchmark (nomic, real vectors, 7 editions):** identity gate 0 false merges, P 1.000, R 0.694 (rc12b fixed the
  two from round 1). Replayed here with the rc12d gate: 0 false merges, R 0.679.
- **Live rc12c editions: 26 false merges, 8 mixed stories** (r1 19 in 6 stories, r2 7 in 2), all from rules the
  offline corpus did not exercise:
  - r1 #12 "Eva Marie Saint and Frank G. Mancuso Sr. Die": Saint's obituary joined Mancuso's through 'dies' in the
    titles plus a name only the pages write. r1/r2 "Trump Announces Automatic Enrollment for Trump Accounts" carried
    Jimmy Kimmel's monologue on Trump's Iran joke ('president' with one member, 'hosts' in another's page). Cause:
    a lone report attached to a story when it shared one specific word with ANY member. Fix: every member must be
    linked by a specific title word or a rare name both TITLES write (`_attach_supported`).
  - r1 #19 "US Voters Concerned About AI Risks": a Reuters/Ipsos AI poll, research on congressional term limits and
    a poll on taxpayer-funded campaign ads. "don't" + 'poll' counted as two distinctive phrases; 'Congress' counted
    as a rare shared name. Fix: negation contractions are everyday words; legislature names are not shared names.
  - r1/r2 "Trump's Retreat": US forces pulling back from the Gulf and Trump's golf club as a "presidential retreat"
    ('Trump' + 'retreat', cosine 0.69). At 6% of a real run (79 of 1,329 reports) 'Trump' was a rare name. Fix: a name
    in more than 2% of the run plus one specific word is accepted only when the embedding agrees strongly (0.8); the
    corpus runs are too small to show it, so a 634-report test rebuilds the real proportions.
  - r1 #3 France's stun-grenade ban carried Belgium's student protests again, this time through "Photos: The Student
    Protests in France" ('student protests' as two shared words). Fix: two shared words that both titles write as
    one phrase are one piece of evidence, unless they are the whole title (the trend 'Christa Pike').
  - r1 #11 Microsoft's Surface Laptop Ultra launch with an HP price leak (five shared words: 'Nvidia RTX Spark laptop
    launch'). **Open** (`test_two_laptops_with_one_chip_are_two_stories`, strict xfail): no rule yet tells a product
    name from what happened.
  - Not counted: the France summons of Iran's ambassador over protest "disinformation" (related), LIV Golf's
    financing with Rahm quitting (related), the Nobel overview in the chemistry story.
  Offline after the fixes: 1 false merge on 9 editions (the laptops) with replayed neighbourhoods and lexically, recall
  0.620 (was 0.627 with the false merges). Tests: `test_rc12c_refresh_cases_stay_apart`,
  `test_a_common_name_and_one_word_need_the_embedding_too`, replay/identical tests over all 9 editions.
- **Windows test failure:** `test_repeated_daily_use_stays_coherent` found `progress.json` after the refresh ended.
  The window reads that file every 100 ms; Windows refuses to delete a file another process has open, and the delete
  was tried once. Harmless in the app (the window trusts the OS lock, not the file), but the file outlived its
  refresh. Fix: the delete is retried for up to 2 s (`fsutil.unlink_with_retry`; Windows-only test holds the file).
- **Self-test:** "stories grouped by the configured embedding model" was a FAIL for the Mac-only model even though
  part 3 called the same situation INFO. Now INFO when the fallback was used for that reason.
- Real refresh 365 s, 46 stories, 24 label batches (0 failed), 1 'why it matters' of 20; podcast 5.2 min; model drop
  ends in 13 s; cancel works; all four launchers open the window (the `.pyw` double-click too, for the first time).
- The stray `tests/test_event_contract.py` and `tests/test_event_identity.py` are still in the user's folder.

## October 7, 2026, afternoon: EmbeddingGemma 2 cannot run in Ollama on Windows (yet)

After updating Ollama to the newest release, the user ran `ollama pull embeddinggemma-2:270m` in PowerShell:

    pulling manifest
    Error: this model requires MLX support, but the MLX runtime is not available

So the earlier 404 was not only an old Ollama: Ollama publishes EmbeddingGemma 2 for Apple's MLX runtime only,
and the standard Windows build has no MLX (the same error on Linux: ollama/ollama issue 18825, open, no reply yet).
Ollama's experimental `ollama-windows-amd64-mlx` zip build exists, but its catalog access is gated by OS
(issue 16265); not something to ask the user to install. llama.cpp added the architecture on October 6 (PR 30054,
GGUF files at ggml-org/embeddinggemma-2-GGUF), so a GGML build of Ollama may follow; nothing to do until then.
Also seen: the Ollama app's model picker lists chat models only, so embedding models never appear there.

rc12c: setup, benchmark, the app's model check and the self-test say this in plain words ("only on Mac computers
so far", no "update Ollama" advice, an INFO row instead of a FAIL); the benchmark compares the first EmbeddingGemma
(`embeddinggemma:300m`, GGML, runs on Windows, same task prompts) with nomic instead. The app's default stays
`embeddinggemma-2:270m` -> nomic fallback; whether `embeddinggemma:300m` joins the chain is decided by its numbers.

## October 7, 2026, 12:07 PM: rc12 self-test and embedding benchmark on the user's PC

Self-test `AgentReach-selftest-20261007-1207.zip` (28 PASS, 3 FAIL) and `AgentReach-embedding-benchmark-20261007-1207.zip`.
Two real rc12 editions (`2026-10-07-rc12-r1.json` 12:13, 53 stories; `-r2.json` 12:23, 44 stories) are fixtures with
gold events; the labelled corpus now has 7 editions.

- **EmbeddingGemma 2 was never used.** Ollama 0.40.0 answered 404 "model not found" for `embeddinggemma-2:270m` and
  `embeddinggemma-2`; `ollama list` shows neither. The library lists the tags (270m, 440m, 570m, 740m/latest),
  but Ollama 0.40.0's release notes mention embeddinggemma-2 only for MLX (Apple Silicon); the multimodal-embedding
  support for the other runners was merged on October 6 (ollama/ollama PR 18820), after 0.40.0. Not verified on the
  PC: rc12b's setup/benchmark record Ollama's own error text (`pull-log.txt`). Every number below is nomic-embed-text.
- **Benchmark (nomic, real vectors, 5 rc11 editions):** identity gate 2 false merges (Asos hacked notification + the
  Wikimedia/OpenAI rogue-agents reports: 'confirms' in both titles, 'sent' and 'third-party' in both leads), P 0.993,
  R 0.740. nomic cosines: same-event p5 0.781 / p50 0.897; different-event p95 0.668 / p99 0.734 / max 0.863; kNN
  candidates hold every same-event pair; 22 different-event pairs reach 0.8. Thresholds unchanged (not enough data).
  Fixed in rc12b (`test_hacked_shop_notification_is_not_wikimedias_rogue_agents`).
- **Live rc12 editions: 26 false merges in 6 stories** (all fixed in rc12b; `test_first_rc12_refresh_cases_stay_apart`,
  `test_merge_pass_never_grows_a_story_one_lone_report_at_a_time`, replay/identical tests over all 7 editions):
  - r1 #2 "Paxton Privately Blames Campaign Woes on Iran War, Gas Prices" carried "Hegseth's handling of Iran war"
    (Bluesky), NPR's DIY-fertilizer story and Politico's Mike Rogers on Canada. Cause: the merge pass after labelling
    tried every story with every single report and accepted any lone report that 'fitted' that one story, bypassing
    the grouping rule that exactly one story must qualify; the pair log showed every one of those pairs as undecided
    with weak support (cosine 0.63-0.72).
  - r1/r2 #1 "France Halts Use of Stun Grenades" carried Reuters' "Belgian students rally ... in protests echoing
    France" ('France' + 'protests' counted as two distinctive phrases).
  - r1 #24 / r2 #20 "OpenAI Agents Tried to Hack Wikipedia Tools" carried Reuters' "South Korea says AI agents appear
    to have been used to hack the country's banks" ('agents' + 'hack').
  - r1 #9 "Tropical Storm Isaias" carried Space.com's "G2 geomagnetic storm watch" ('storm' + 'possible').
  - Offline only: Michigan's Mike Rogers + a trade group on US-made tech ('trade' + a Trump named only in one lead;
    'trump' looked rare because titles write "Trump's").
- **Labelling cut off:** 218 groups (19 multi-report) -> 14 + 3 label batches of up to 20 stories; three answers hit
  the 2,048-token output limit (invalid JSON, retried identically, 25 s each); one relabel batch fell back to report
  titles. Grouping + labelling took 421 s of a 494 s refresh. Fixed: at most 12 stories per call, a cut-off answer is
  split in two (`test_a_cut_off_label_answer_is_split_not_retried`).
- **Diagnostics:** the semantic pair log (4,000 pairs) contained no accepted pair (accepted sorted last), and the gate
  counts included the coherence re-checks ('33670 candidate pairs', 18,573 merges for 2,116 candidates). Fixed.
- **Self-test said PASS for '1 failed'** (Reddit pacing 0.282 s < 0.29 s on Windows: asyncio.sleep wakes up to one
  16 ms tick early). Fixed: pacing re-checks after sleeping; pytest runs with -rfEs and the count line is checked.
- One window test was skipped inside pytest ("Can't find a usable tk.tcl") while every other window test and all
  launchers worked: treated as a file briefly held by another program; the fixture retries once.
- Still on the PC: `tests/test_event_contract.py`, `tests/test_event_identity.py` (import `story_from_event`,
  `ABBREVIATION_GUARD`, which this repository does not have): PLAN 0.5.
- Read-through: possible duplicates #37/#48 (Google's AI game platform, two stories: a false split, acceptable) and
  #41/#44 (Cam Jurgens trade vs concussion: two events). 0 of 20 'why it matters' accepted (23 rejected): Phase 4.

