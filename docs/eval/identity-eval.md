# Event identity evaluation (rc12)

Generated 2026-10-07T18:21:57+00:00 on the labelled October 7 corpus (593 reports, 332 gold events, 7 real editions). Pairwise scores over all reports; **false merges** = report pairs from different events published in one story.

| Grouping | False merges | Mixed stories | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| rc11 published (nomic + HDBSCAN + single-link; 5 rc11 editions) | 52 | 13 | 0.885 | 0.976 | 0.928 |
| rc12 published on the PC (nomic + identity gate before rc12b; 2 rc12 editions) | 26 | 6 | 0.816 | 1.000 | 0.898 |
| identity gate, no embeddings (fallback) | 0 | 0 | 1.000 | 0.620 | 0.765 |
| identity gate, replayed rc11 neighbourhoods | 0 | 0 | 1.000 | 0.688 | 0.815 |
| identity gate, every pair cosine 1 | 0 | 0 | 1.000 | 0.167 | 0.287 |

Settings: identity_neighbors=12, identity_candidate_cosine=0.45, identity_strong_cosine=0.8, event_max_age_hours=72.0

Real embedding models were not run here (no Ollama). On a PC with Ollama:

    python -m tests.embedding_benchmark --ollama --models nomic-embed-text,embeddinggemma:300m,embeddinggemma-2:270m,embeddinggemma-2:latest

## False merges left (first 5 per edition)

**rc11 published (nomic + HDBSCAN + single-link; 5 rc11 editions)**
- 2026-10-07-selftest-r2.json: "Federal Agents Have Detained More Than 500 American Citizens in Trump's Immigrat" + "ABC and Trump's FCC battle in federal court over free speech and jurisdiction is"
- 2026-10-07-selftest-r2.json: "Federal Agents Have Detained More Than 500 American Citizens in Trump's Immigrat" + "Disney, ABC battle Trump's FCC in court over free speech protections"
- 2026-10-07-selftest-r2.json: "EmbeddingGemma 2: An open, lightweight multimodal embedding model" + "Claude launches Google Docs, Sheets, and Slides integration with sidebar and mor"
- 2026-10-07-selftest-r2.json: "Google claims EmbeddingGemma 2 outperforms rival embedding models twice its size" + "Claude launches Google Docs, Sheets, and Slides integration with sidebar and mor"
- 2026-10-07-selftest-r2.json: "Claude launches Google Docs, Sheets, and Slides integration with sidebar and mor" + "Google DeepMind Releases EmbeddingGemma 2, a 740M Open Multimodal Embedding Mode"
- 2026-10-07-selftest2-r1.json: "Star Moles Signs to Dead Oceans, Readies 2027 Tour" + "Dead star likely birthed a new planet, in astronomical first"
- 2026-10-07-selftest2-r1.json: "Worlds collide! James Webb Space Telescope investigates what happens when planet" + "NASA's Prima space telescope would aim to see what James Webb can't"
- 2026-10-07-selftest2-r1.json: "NASA's Webb finds signs of Mars-sized worlds smashing together" + "NASA's Prima space telescope would aim to see what James Webb can't"
- 2026-10-07-selftest2-r1.json: "What happened in the first Maine Senate debate between Collins and Jackson" + "Battleground candidates clash over Trump and Cornell allegations reignite debate"
- 2026-10-07-selftest2-r1.json: "What happened in the first Maine Senate debate between Collins and Jackson" + "News Wrap: Cornell says Sally Yates will review handling of sexual assault repor"
- 2026-10-07-selftest2-r2.json: "Worlds collide! James Webb Space Telescope investigates what happens when planet" + "NASA's Prima space telescope would aim to see what James Webb can't"
- 2026-10-07-selftest2-r2.json: "NASA's Webb finds signs of Mars-sized worlds smashing together" + "NASA's Prima space telescope would aim to see what James Webb can't"
- 2026-10-07-selftest2-r2.json: "Google launches platform to create video games from text prompts" + "Google invests millions in Mark Zuckerberg's efforts to create a 'virtual cell'"
- 2026-10-07-selftest2-r2.json: "Google launches platform to create video games from text prompts" + ""The beginning of a new scientific paradigm": Zuckerberg's Biohub, U.S. and Goog"
- 2026-10-07-selftest2-r2.json: "Google invests millions in Mark Zuckerberg's efforts to create a 'virtual cell'" + "Google, Unity Launch Platform to Create Video Games From Prompts"
- 2026-10-07-0935-export.json: "Worlds collide! James Webb Space Telescope investigates what happens when planet" + "NASA's Prima space telescope would aim to see what James Webb can't"
- 2026-10-07-0935-export.json: "NASA's Webb finds signs of Mars-sized worlds smashing together" + "NASA's Prima space telescope would aim to see what James Webb can't"
- 2026-10-07-0935-export.json: "What happened in the first Maine Senate debate between Collins and Jackson" + "Reports of sexual violence are up. Data from Cornell and other colleges in 8 cha"
- 2026-10-07-0935-export.json: "What happened in the first Maine Senate debate between Collins and Jackson" + "Battleground candidates clash over Trump and Cornell allegations reignite debate"
- 2026-10-07-0935-export.json: "What happened in the first Maine Senate debate between Collins and Jackson" + "News Wrap: Cornell says Sally Yates will review handling of sexual assault repor"

**rc12 published on the PC (nomic + identity gate before rc12b; 2 rc12 editions)**
- 2026-10-07-rc12-r1.json: "France halts use of stun grenades after boy's hand blown off in student protests" + "Belgian students rally over education costs in protests echoing France"
- 2026-10-07-rc12-r1.json: "France suspends the use of stun grenades after student protester loses hand" + "Belgian students rally over education costs in protests echoing France"
- 2026-10-07-rc12-r1.json: "Photos: The Student Protests in France" + "Belgian students rally over education costs in protests echoing France"
- 2026-10-07-rc12-r1.json: "Belgian students rally over education costs in protests echoing France" + "French government defends handling of high school protests as controversies grow"
- 2026-10-07-rc12-r1.json: "Belgian students rally over education costs in protests echoing France" + "What France's student protesters want - and what the government is offering"
- 2026-10-07-rc12-r2.json: "France halts use of stun grenades after boy's hand blown off in student protests" + "Belgian students rally over education costs in protests echoing France"
- 2026-10-07-rc12-r2.json: "France suspends the use of stun grenades after student protester loses hand" + "Belgian students rally over education costs in protests echoing France"
- 2026-10-07-rc12-r2.json: "Photos: The Student Protests in France" + "Belgian students rally over education costs in protests echoing France"
- 2026-10-07-rc12-r2.json: "French government defends handling of high school protests as controversies grow" + "Belgian students rally over education costs in protests echoing France"
- 2026-10-07-rc12-r2.json: "What France's student protesters want - and what the government is offering" + "Belgian students rally over education costs in protests echoing France"
