# v2.1 reliability contract

LLM responses contain labels only. Assignment fields are ignored even if a model
returns them. Membership uses title evidence, event wording and publication time;
labels and extracted entity lists cannot create graph edges. Every reassignment,
merge and final partition is validated. Ambiguous fragments remain unassigned.
This conservative lexical gate can miss paraphrases; it is not a complete event resolver.

`entity_id` identifies the entity set. `event_id` (also `cluster_id`) fingerprints
the normalized member titles and their UTC dates. An ID collision never merges
clusters. Identical evidence has an identical ID; changed evidence can change it.
Persistent event continuation across runs remains work for the future change digest.
`AGENT_REACH_EVENT_MAX_AGE_HOURS` defaults to 72; timestamps defaulting to retrieval
time cannot establish the original publication time.

Each cleaned item retains every contributing `observations` record. Cluster
`sources` includes every observed platform. `publisher_hosts` separately records
known origin hosts, including Google News publisher URLs. Unknown origins do not
earn publisher credit. Host diversity is a proxy: it cannot establish editorial
independence or detect unattributed syndication across different domains.
Repeated identical copies do not increase the relevance size component.

Runs retain source health and effective configuration. Each historical window
uses the intersection of successful sources, excludes sources without filtered
observations, and averages mention shares equally across comparable sources.
Changing a feed's volume alone therefore cannot change its weight. Missing
configuration, incompatible configuration, empty denominators, no comparable
cluster evidence, or coverage loss above 25% marks momentum `UNCERTAIN` and gives
it a neutral ranking contribution. The threshold is configurable through
`AGENT_REACH_VELOCITY_MAX_COVERAGE_CHANGE`. Smaller changes still restrict comparison
to shared sources. Health describes what the ingesters report; undetected partial
feed failures remain a limitation. Momentum still measures entity mentions,
not independently verified event popularity.

Velocity now uses `50 + 50 * weighted_mean(tanh(2 * growth))`. Flat growth scores
50; a 50% decline scores about 11.9 and can reach `FADING`. These are calibrated
heuristic labels, not statistical significance tests.

Enrichment validates the initial URL and every redirect, checks all resolved IP
addresses, and connects to a pinned public IP. Host and TLS SNI retain the original
hostname, certificate verification remains enabled, and connections close after
each response to avoid cross-host IP connection reuse. The enrichment client does
not use environment proxies. Redirect count, total fetch time and response size
are bounded. HTTP failures leave the item without page context.

SQLite and JSON report schema versions are now 3. Migration adds columns and an
evidence table without removing existing records. Legacy runs have unknown
validity and cannot become historical baselines. Run states are `running`, `valid`
or `invalid`; an invariant failure retains diagnostics and available evidence,
raises an error, and withholds delivery. Only valid runs enter history queries.
`cleaned_evidence` stores context and observations, `clusters.payload` stores the
full cluster including `member_item_ids`, and source context lives on `runs`.

## Replay benchmark

```powershell
python -m pytest
python -m pyflakes agent_reach tests
python -m tests.replay_benchmark --output reports/reliability-replay.json
python -m agent_reach --no-llm --help
```

The fixture includes five public X chart entries from the saved September 25,
2026 snapshot. It deliberately contains no game facts. Additional event evidence,
same-company launch/outage stories and a valuable single-source disclosure are
explicitly synthetic. Separate replay checks exercise source outages, syndicated
duplicates and hostile model assignments. Replay starts after enrichment; it does
not benchmark ingestion, extraction quality or real-world recall.

The benchmark measures incorrect cross-event member pairs, missed annotated
stories, missing expected pairs, false alerts in the outage scenario, and runtime.
It repeats cases to count repeated label/embedding requests. Fetch time and cache
hits are zero because fetching is excluded and no cache is implemented. Grouping
time includes embedding time. `--llm` opts into local Ollama for model timing and
quality evaluation; default and CI runs are offline and use heuristic labels.

`reviewed_claims.json` contains fixture-author annotations for the four exact
deterministic summaries: their factual lead sentences match the fixture evidence,
and their platform/item counts match membership. Counts refer to unsupported claims
relative to that evidence, not verification of synthetic events in the real world.
Any changed or LLM-generated summary needs a fresh evidence review; unknown
summaries report `null`, never a fabricated zero. To annotate, review every claim
against the case evidence and map the emitted summary SHA-256 to the number of
unsupported claims. Offline CI rejects changed unreviewed summaries.

An early-signals queue, persistent event continuation, personalized relevance,
claim-level citations and extraction/embedding/label caches are outside this release.
