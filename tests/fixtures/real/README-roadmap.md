# October 8 roadmap replay

`2026-10-08-roadmap.json` freezes revision 6's 54 stories from the saved local edition generated at
21:49:17 UTC. Only edition date, revision, generation time and story/evidence data are retained; settings,
tokens, logs and machine paths are excluded. Tests use this recorded evidence offline, without fetching
current pages or invoking the user's Ollama installation. The evidence list was already capped at eight
links per story, so stored strength is normalized without losing publishers assessed before that cap.

`tests/test_roadmap.py` checks all seven publisher items. The lead changes from 9 to 7 outlets, all 21
unresolved Google News links are labelled, the listed factual/subject/headline errors trigger extraction,
quotes and abbreviation case repair, and the Iran headlines pass the deterministic merge gate while
opposite claims, other days and roundups remain separate. Regeneration JSON gets only one model attempt.

The recorded selection has 31 stories, including 15 single-source stories (48.4%), compared with
38 of 54 (70.4%). The same-day feed-loss replay retains all 31 eligible incumbents (0% dropped); the
separate replacement fixture tests the exact 119/120 boundary against a score of 100. This is not a
claim about future production days: stale stories, reduced settings and substantially stronger incoming
coverage can change the drop rate. An initial upgrade may remove previously admitted filler.

The implementation also replayed all 1,355 stored post-enrichment inputs with the original database
opened read-only and with network and Ollama disabled. The Reuters (41), NYT (304), and Guardian (411)
Iran reports form one story. `2026-10-08-iran-inputs.json` freezes those actual feed titles plus the
different-day financial report and the broader Saudi/Iran headline; only publisher/publication metadata
is retained. The regression includes U.S. punctuation, a trailing background clause, different actors
and opposite time bounds. This offline lexical replay tests grouping, not fresh local-model summaries.

The four added hashes in `../reviewed_claims.json` were inspected against `../reliability_replay.json`:
they contain the cited Packers label, two Acme event titles, and the cited vulnerability title, followed
by the existing factual channel-presence sentence. No additional event claims appear. The benchmark
reports zero unsupported claims and zero unreviewed summaries for these offline cases. Hashes are
specific to those texts; this is not automatic approval of newly generated summaries.

Summary verification uses conservative word, quantity/noun, entity and sentence-context checks. Valid
paraphrases may fall back to extraction; these checks cannot establish the truth of publisher reporting.
No categories, stable event IDs, runtime dependencies or deployment settings are changed.
