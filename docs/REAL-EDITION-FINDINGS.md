# Findings from real editions (input for the next phase)

Real editions are the test material for the intelligence / event layer. Each finding names the edition and
the story, and the regression test that holds it (`tests/test_real_editions.py`; `xfail` = not fixed yet).
Fixtures: `tests/fixtures/real/` (edition JSON as the app wrote it; public news only).

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
   the scorer compares the whole configuration (HANDOFF open item).
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
