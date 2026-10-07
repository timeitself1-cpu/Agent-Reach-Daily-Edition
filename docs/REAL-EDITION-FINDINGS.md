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
