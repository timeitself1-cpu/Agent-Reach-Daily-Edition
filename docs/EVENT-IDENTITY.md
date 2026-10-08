# Event identity across editions

How Agent Reach recognises that stories in different editions report the same real-world event. This is the
foundation for "what changed", for Day N, and later for story timelines. Status on October 8, 2026: measured,
diagnosed, and a registry built. The registry is **observing only**: it records its decisions after each refresh,
and no edition uses them yet.

## Words used here

- **Story:** one edition's account of an event. Its `story_id` fingerprints the evidence, so it changes when
  reports are added.
- **Event:** the real-world occurrence. The registry gives it a stable id (`ev-YYYYMMDD-xxxxxxxx`).
- **Same event:** the same occurrence, including later coverage of it (for example, experts' reaction to
  OpenAI's math proofs).
- **Related:** a different occurrence in one ongoing topic. France's stun-grenade ban is related to the
  school-funding protests, not the same event. Related pairs are never scored as right or wrong.

## The answer key (`tests/cross_edition.py`, `tests/fixtures/real/cross_edition_gold.json`)

Twelve real editions from October 7, 05:05 to 23:34 UTC (rc11 to rc12d): 536 stories, 256 events, 108 of them
in more than one edition. It is built in three steps:

1. **Per-edition labels.** The labels in `event_gold.json` already give every report an event within its
   edition. A story's event is the event of most of its reports.
2. **Shared reports.** Events in different editions are the same when they share a report (the same article
   URL, or the same normalized title).
3. **Hand-checked rules:**
   - 9 forced splits, where one shared report had joined two different events (HP's RTX Spark leak and
     Microsoft's Surface launch).
   - 12 joins of events with no shared report (Apple + LG smart home, worded differently).
   - 16 related pairs.

   To find these, I reviewed every shared-report cluster and every pair of events with two or more shared
   headline words.

**Limits:**
- It covers **one day**, so it cannot measure day-to-day matching. The self-test now brings back the last 14
  days of real editions (PLAN 2.1b). The key must be extended to at least 7 calendar days, with the same kinds
  of hand-checked positives, negatives and related pairs.
- A missed link between two differently-worded events that share fewer than two headline words is possible.

## Three separate measurements

`python -m tests.cross_edition` reports these independently:

| Measure | What it depends on | Oct 7, consecutive editions | Oct 7, 6 h or more apart |
|---|---|---|---|
| **Matching** (precision / recall of "which earlier story continues") | the matcher only | see below | see below |
| **Event carry-over** (earlier events still in the later edition) | collection and selection, not the matcher | 44% | 16% |
| **Top Stories** (earlier Top Stories still Top Stories; still listed at all) | selection only | 48%; 73% | 15%; 39% |

Even a perfect matcher cannot fix carry-over or Top Stories. Those are PLAN 2.2 (why stories drop out) and 2.6
(keeping a place for an event that is still developing).

## Diagnosis of today's matcher (`changes._match`)

**False continuations (13, all pairs):**
- **7: one shared article URL with an earlier story that was itself two events.** Examples: Cornell's Sally
  Yates review inside the Maine Senate debate; Trump's golf-club "retreat" inside the forces' "retreat"; the
  French PM inside a mayor's clash. One shared report out of six was enough to continue the wrong story.
- **6: "same entity set".** Prolific names (OpenAI + ChatGPT, NASA + SpaceX, Meta + Muse) joined different
  occurrences: the EU watermark and the teen usage report; Crew-12's return and the next resupply launch.

**Misses (65), mostly in editions hours apart:**
- **Nearly all have no shared report:** the later edition cites new articles about the same event, with a new
  headline.
- Usually exactly one key name is shared, so the entity-set rule cannot help.
- Typical cases: Apple + LG smart home, OpenAI's Decisions API, the plague death at a Russian lab, the
  Physics Nobel, Messi's farewell.

## The registry (`agent_reach/daily/registry.py`)

Persistent, in `state/events.json`, written by the refresh worker after the edition is saved. Each event keeps:
- a stable id;
- first-seen and last-seen times;
- headline and category;
- report keys (URLs and normalized titles);
- key names with counts;
- a word profile in which older wording fades;
- every appearance: edition, story, tier, confidence, the reason in words, and the candidates when undecided.

**Matching** (deterministic; no model involved; invariant 2 holds). Every event seen in the last 7 days is a
candidate. Evidence comes in three kinds:
- **Shared reports, as a share of the story's reports.** More than half must be the event's, and the wording
  must not disagree (cosine 0.12 or more). This is tier `reports`, confidence 0.95.
- **Wording.** Tf-idf cosine over headline, summary and report titles, using 5-letter stems so that rare words
  weigh most. It requires at least one rare shared word that is **not part of a shared name**, plus either
  cosine 0.45 with a shared name or two rare words, or cosine 0.32 with both. This is tier `wording`, with
  confidence 0.5 to 0.9.
- **Key names.** They count only alongside wording, never alone.

**Safeguards:**
- **Ambiguity:** when a second candidate in the same tier scores within 90% of the best, the story is not
  matched. It becomes a new event and lists the candidates. A false split is preferred to a false merge.
- **One story per event per edition**, except that a second story may join the same event through its reports.
  This is for the same event told twice in one edition, like Messi's farewell as #15 and #37.
- **Recording the same edition twice** (the same run id) changes nothing.
- **Clean-up:** events not seen for 30 days are dropped.

**Thresholds** were chosen on the development pairs (later edition among the first eight, 05:05 to 18:49). The
pairs ending in the four evening editions (21:34 to 23:34) were held out and scored once.

## Results (October 7 editions)

| Pairs | Matcher | Consecutive P / R | 6 h+ apart P / R |
|---|---|---|---|
| development | today's | 0.967 / 0.937 | 0.941 / 0.816 |
| development | registry | 0.984 / 0.976 | 1.000 / 0.939 |
| **held out** | today's | 0.967 / 0.978 | 0.989 / 0.703 |
| **held out** | registry | 0.966 / 0.956 | **0.991 / 0.898** |
| all | today's | 0.967 / 0.954 | 0.966 / 0.752 |
| all | registry | 0.977 / 0.968 | 0.995 / 0.916 |

**Hours apart,** recall rises from 0.70 to 0.90 on the held-out pairs and precision stays at 0.99. That is just
under the 0.99 / 0.90 target; the strict xfail in `tests/test_cross_edition.py` stays until it is met.

**On consecutive editions,** the registry is no better than today's matcher on the held-out pairs.

**Remaining false continuations** all come from stories that were already two events inside one run (golf club
vs. forces' retreat; French PM vs. mayor). Cross-edition precision is therefore now limited by grouping
mistakes **within** a run, which is the rc12 identity gate's job.

**Remaining misses:**
- one event worded entirely differently (Microsoft's "Nvidia-chip AI PCs" vs. "Surface Laptop Ultra");
- an event told twice in one edition, where the second copy has no shared reports.

**On ambiguity:** no story was undecided on these editions, so the ambiguity rule is tested only with
constructed data.

**These are targets on one day of news, not a production guarantee.** The held-out set holds out stories, not
events (one day's news overlaps). The real test is a held-out multi-day set.

## Next steps (docs/PLAN.md, Phase 2)

1. **2.1b:** collect 7 or more consecutive days of real editions (the self-test's `history/`), extend the
   answer key to them with the same hand-checked positives, negatives and related pairs, and hold out the last
   days.
2. **2.2:** find why events drop out between editions (carry-over 16% over 6 h), separately from matching.
3. **Re-check the matcher on the multi-day held-out set.** Compare the registry's own decisions from the PC
   (`events.json` in the self-test zip) with the answer key. Lower confidence for wording-only matches across
   days if needed.
4. **Only then 2.5:** use event ids in the editions ("what changed", Day N, one event in one section). Then
   timelines on the website.
