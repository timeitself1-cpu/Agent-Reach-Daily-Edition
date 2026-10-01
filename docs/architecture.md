# Architecture

```
public sources (RSS / APIs / pages)
      |  ingest          ingestion/*        one SourceStat per source: OK / PARTIAL / EMPTY / FAILED
      v
  clean / filter         pipeline/cleaner   noise rules, de-duplication, heuristic score, item ledger
      v
  enrich                 pipeline/enricher  page title + description + lead paragraphs (SSRF-safe)
      v
  embed / group          pipeline/density   nomic-embed-text + HDBSCAN; outliers are noise
      v
  label + coherence      pipeline/clusterer local model NAMES groups only; evidence decides membership
      v
  score                  pipeline/scorer    relevance 1-10, momentum vs comparable earlier runs
      v
  daily selection        daily/edition      fresh, not weak, no repeats, category/tech balance
      v
  grounded brief         daily/brief        optional detail + "why it matters", deterministic gate
      v
  edition store          daily/store        versioned JSON, atomic write, latest pointer, retention
      v
  desktop reader         daily/gui (+ app)  tkinter window; HTML export via daily/render_html
```

## Agent Reach Daily (`agent_reach/daily`)

| Module | Role |
|---|---|
| `paths.py` | Data folder layout under `%LOCALAPPDATA%\AgentReachDaily` (`AGENT_REACH_DAILY_HOME` or `--data-dir` override it) |
| `timeutil.py` | UTC internally; America/Chicago dates and CDT/CST display; DST gap/fold handling for fixed-time schedules |
| `prefs.py` | `settings.json` (validated, per-field reset on bad values) mapped onto pipeline `Settings`; daily momentum windows |
| `state.py` | Last attempt vs. last success, due check, exponential failure backoff, interrupted-attempt recovery |
| `lock.py` | One OS byte-range lock for every refresh; released by the OS when a worker dies |
| `edition.py` | Versioned `DailyEdition` schema, evidence links, balanced selection, publication gate |
| `brief.py` | Optional local-model pass; every sentence must pass the grounding gate |
| `store.py` | Dated editions, atomic publish + checksummed `latest.json`, same-day revisions, quarantine, retention |
| `render_html.py` | Standalone escaped HTML (no scripts, no remote assets, CSP) |
| `prereqs.py` | Ollama/model checks and optional hidden start (never pulls models) |
| `refresh.py` | The one refresh path for scheduled, launch-time and manual refreshes |
| `scheduler.py` | Current-user Task Scheduler XML (hourly + logon, IgnoreNew, StartWhenAvailable) |
| `app.py` | GUI controller: everything the window shows, computed without Tk (unit-tested) |
| `gui.py` | tkinter view; refreshes run in a separate background process |
| `logs.py` | Rotating `gui.log` / `refresh.log` / `scheduler.log` (1 MB x 6 each) |

Launch and install files in the project root: `AgentReachDaily.pyw` (double-click; re-launches
itself with `.venv`), `AgentReachDaily.cmd` (fallback), `Setup-AgentReachDaily.ps1`,
`Uninstall-AgentReachDaily.ps1`. `samples/DEMO-edition.json` is the synthetic demo edition.

### Time semantics

| Field | Meaning |
|---|---|
| `EvidenceLink.published_at_utc` | publication time **only when the source stated one**; otherwise `null`, shown as "publication time not stated" |
| `EvidenceLink.retrieved_at_utc` | when Agent Reach fetched the item |
| `DailyEdition.generation_started_utc` | refresh (attempt) start; the edition date is its Central calendar date |
| `DailyEdition.generation_completed_utc` | when the edition was generated ("Updated ..." line, export) |
| `RefreshState.last_attempt_*` | the latest attempt, whatever its outcome |
| `RefreshState.last_success_*` | the latest *published* edition; the next due time is anchored on its start |

Stored timestamps are UTC (ISO 8601). Everything shown to the user is US Central with the correct
CST/CDT abbreviation (`tzdata` provides the zone database on Windows).

### Refresh worker

```
due check (no lock, no network; about 1 s)  ->  lock  ->  repair cache, recover a dead attempt
  ->  re-check due under the lock  ->  mark attempt running
  ->  Ollama check (start it if installed; never pull models); model missing -> fail before fetching
  ->  pipeline run_once (validated ledger)  ->  stories from validated clusters + cited evidence
  ->  selection (stale > 48 h, weak signals, repeats, caps)  ->  grounded brief pass (optional)
  ->  DailyEdition  ->  publication gate (>= 2 sources, >= 3 stories, model summaries unless allowed)
  ->  atomic publish + retention        or: no_update / failed + backoff + diagnostics file
```

Exit codes: 0 published, 10 not due, 11 another refresh running, 12 waiting for backoff,
20 nothing publishable, 30 failed, 31 Ollama/model unavailable, 2 usage error.

An attempt that dies (crash, power loss) is found by the next lock holder and recorded as
`interrupted`; its backoff is counted from when it *started*, so a PC that was off overnight
retries immediately while a crash loop stays rate-limited.

### Publisher feeds and fair limits

Publisher feeds are configured per feed (`daily/feeds.py`, Settings > Publisher feeds): name,
address, category, on/off. Each feed is one channel inside the `news_rss` source:

- **Intake:** each feed contributes up to `items_per_feed` (10) articles; the source cap is
  `items_per_feed x feeds`, bounded by `news_rss_max_total_items` (300), and feeds are interleaved
  by rank, so a cap never drops a whole feed and adding feeds never shrinks the others.
- **Processing budget:** `max_items_for_llm` (150) articles are grouped and labelled per refresh.
  Every channel keeps `min_items_per_source_for_llm` (6) and every publisher feed keeps
  `min_items_per_feed_for_llm` (3) of that budget; the rest goes to the highest scores.
- **Health:** `SourceStat.feeds` records every feed (OK / EMPTY / FAILED, articles collected); the
  edition adds how many of each feed's articles were cited ("used"). A channel that answered but hit
  errors (a failing feed, a Reddit 429 with RSS fallback) is PARTIAL, never "healthy".

### Selection rules (quality over quota)

1. Stories whose every stated publication time is older than `max_story_age_hours` (48) are dropped.
   Undated items (trend lists, Wikipedia) are kept but never shown with an age.
2. A single trend/social signal with no publisher article and relevance below 7 is dropped.
3. Repeats are dropped: same entity set, a shared article URL, or near-identical headline words.
4. At most `max_per_category` (5) stories per category and `max_tech_only_share` (34%) tech-only
   stories, in pipeline rank order. A capped story fills a free slot only if it is strong
   (relevance >= 7) and not tech-only. Free slots otherwise stay empty.
5. The edition is published only with >= `min_ok_sources` (2) responding sources and
   >= `min_useful_stories` (3) stories; otherwise the previous edition stays.

### Publication-time validation

`ingestion/base.py` parses RFC-822 and ISO-8601 times and normalises every offset or zone name to
UTC. Unparseable values, date-only values (no time of day) and RFC-822 year rewrites (`0001` read
as `2001`) become "unknown", never "now". A stated time later than retrieval by more than 15 minutes
("in the future") or earlier than 1995 is discarded and noted in `metadata["published_at_note"]`;
up to 15 minutes ahead is clock skew and is clamped to the retrieval time. Bad Unix epochs (Hacker
News, Reddit) are unknown instead of failing the source. When an edition loads, any evidence time
after the edition's generation time is dropped, so a cached edition with an impossible date still
opens and shows "publication time not stated".

### Evidence strength (`daily/strength.py`)

Rule-based, per story, from the full evidence list and the edition's generation time; no model
and no percentages. Independent reports = distinct origin publishers (Google News items count as
their publisher; repeats from one publisher and syndicated copies of the same headline count once).
Trend/social items (Google Trends, X, Reddit, Wikipedia, TikTok) add channel diversity but never
corroboration. Points: corroboration (2 reports 2, 3 reports 3, 4+ 4), +1 for two or more channels,
+1 for a stated report within 24 h. Fewer than 2 independent reports is always **limited**;
otherwise 5+ points is **strong**, else **moderate**. Every level comes with its reasons.

### What changed since last refresh (`daily/changes.py`)

Before publishing, the new edition is compared with the last persisted edition (a same-day
revision compares with the revision it replaces) and the result is stored in the edition
(`changes`). Stories are matched by story_id, then a shared article URL, then the entity set, then
near-identical headline words. Reported: new; materially updated (new independent publishers, a
substantially rewritten summary or headline, a category change, a new "why it matters"); signals
up/down (raw signals changed by >= 50% and >= 2, or independent reports by >= 2); and stories no
longer listed. The first edition has nothing to compare with.

### Grounding gate for model text

The brief pass sends the model only the story's headline, summary and evidence lines. A returned
sentence is kept only if every number, spelled-out quantity, capitalised name or acronym (as a
whole word) and hedge word ("could", "may") appears in that evidence, and it contains no generic
filler ("highlights the importance of", "only time will tell"), URL or handle. Rejected text is
omitted; a failed or garbled model call leaves the story with its validated summary.

### Momentum on a daily cadence

The Daily app compares against runs about 24 h, 48 h and 7 days earlier (+/-25%). A run serves at
most one window, so one historical run never counts twice. The first edition is a baseline (no
trend labels). Labels: New, Rising, Hot, Continuing, Cooling, Fading, or "Uncertain trend" when
sources or configuration changed too much to compare.

## Pipeline modules (classic Agent Reach)

| Module | Role |
|---|---|
| `config.py` | Pydantic Settings; every field overridable via `AGENT_REACH_*` env vars / `.env` |
| `models.py` | `CategoryEnum`, `RawTrendItem`, `CleanedTrendItem` (+ scraped `context`), `MacroCluster`, `PipelineAccounting` (ledger with invariant checks), `PipelineReport` (schema_version 3) |
| `ingestion/base.py` | `BaseIngester`: shared `httpx.AsyncClient`, per-call timeout, exponential backoff + jitter, `Retry-After`, extra retryable statuses, per-ingester request pacing; `run()` never raises |
| `ingestion/social.py` | X (Trends24 scrape), Reddit (JSON with score/comments -> RSS; 5 s timeout, 403/429 retries, 2 s pacing, 30 s budget), TikTok Creative Center (5 s timeout, retries, 2 s pacing) |
| `ingestion/search.py` | Google Trends RSS, Google News RSS, Wikipedia top pageviews, ArXiv Atom API |
| `ingestion/tech.py` | Hacker News (Algolia), GitHub Trending scrape, Product Hunt feed |
| `ingestion/news.py` | Publisher RSS/Atom feeds (`news_rss_feeds`, `Category|URL`); a failing feed is reported as partial coverage |
| `pipeline/cleaner.py` | ASCII normalisation, hashtag splitting, engagement thresholds, noise regexes, de-dup, heuristic score, output sanitisers |
| `pipeline/enricher.py` | Stage 2b: fetches each candidate's page (or Wikipedia summary API) and keeps title + meta description + 1-2 lead paragraphs (trafilatura, BeautifulSoup fallback) |
| `pipeline/density.py` | Stage 3a: `nomic-embed-text` embeddings -> HDBSCAN (leaf selection) -> cosine-to-centroid gate; outliers are noise |
| `pipeline/clusterer.py` | Stage 3b-e: LLM labelling only (never grouping), `[INSUFFICIENT_DATA]` flag, entity isolation + orphan re-homing, merge, drop rules, guardrails |
| `pipeline/scorer.py` | Relevance 1-10 (LLM + heuristics), velocity 0-100 vs earlier runs (CLI 1h/6h/24h, Daily 24h/48h/7d) |
| `storage/db.py` | SQLite WAL: `runs` (health/config/validity), `raw_items`, `cleaned_evidence`, `clusters`, `entity_snapshots` |
| `main.py` | Stage orchestration (1 ingest, 2 clean/select, 2b enrich, 3 cluster, 4 score, 5 persist), accounting ledger, report renderer, loop mode |

### Reliability release

See [the v2.1 contract and replay benchmark](reliability-v2.1.md) for membership guarantees, provenance, source-aware momentum, safe page fetching, schema migration and known limits. Invalid runs retain diagnostics but never produce a completed report or historical baseline.

### Pipeline stages

1. **Ingest.** Ten sources are fetched concurrently. A failing source returns no items; it never fails the run.
2. **Clean and select.** Engagement thresholds, noise regexes and de-duplication run first. Then the top `MAX_ITEMS_FOR_LLM` items, with a floor per source, become clustering candidates.
3. **Enrich (2b).** Each candidate gets `context`: page title, meta description and 1-2 lead paragraphs.
   - Wikipedia uses its summary API.
   - arXiv and Product Hunt use their feed text.
   - X and TikTok have no article page, so their items get no context.
4. **Cluster (3a-3e).**
   - **3a density:** embed `title + context`, run HDBSCAN (`min_cluster_size=2`, leaf selection), then apply a cosine-to-centroid gate. Outliers are noise and are dropped. They are never forced into a mixed bucket.
   - **3b label:** the LLM only names groups (headline, category, entities, two sentences, relevance). Groups whose signals can't explain what happened and why get `[INSUFFICIENT_DATA]`.
   - **3c event coherence:** groups require event evidence and compatible timestamps. Model labels never create membership edges. Ambiguous fragments remain unassigned; deterministic reassignment requires exactly one coherent home.
   - **3d merge:** combined membership must pass event coherence; entity or cluster ID equality never triggers a merge.
   - **3e drop:** clusters flagged `[INSUFFICIENT_DATA]`, with filler summaries ("no specific information", "details are scarce"), or with relevance <= 3 are dropped, as are weak singletons.
5. **Score and persist.** Relevance and velocity are computed, then everything is saved to SQLite.

With no embedding model, grouping falls back to lexical union-find under the same noise rule. With no Ollama, labels are heuristic, and summaries use the scraped lead sentence or are flagged insufficient.

### Item accounting

Every run prints and stores a raw-item ledger (`PipelineReport.accounting`). The invariant is:

    ingested == sum(discarded[reason]) + clustered        (clustered == sum(raw_item_count) over clusters)

- **filtered:** noise-filter reasons, such as `reddit_low_engagement`, `generic_hashtag` or `pet_post`.
- **budget:** `not_selected_budget` counts items that passed filters but ranked below the clustering cap.
- **clustering:** `density_noise`, `unsupported_grouping`, `insufficient_data`, `low_relevance` and `weak_singleton`.

A de-duplicated item stands for all its duplicates (`raw_weight`), so de-duplication is never a discard. The ledger validates stage by stage, and an imbalance is logged as an error.

### Noise defences (pre-LLM)

- **Source thresholds:** Reddit score < 20 or comments < 5, HN points < 10, GitHub stars-today < 20, and low-signal subreddits are all dropped. Reddit RSS items are kept only when they rank in the top `REDDIT_RSS_MAX_RANK` of a subreddit's top-of-day listing.
- **Regex rules:** clickbait prefixes are stripped. Personal anecdotes, meme/photo and pet posts, betting/box-score chatter and generic hashtags are dropped.

### Reddit and TikTok resilience

- **Reddit:** every request uses fixed browser headers, a 5 s timeout and exponential-backoff retries on 403/429/5xx/timeouts, honouring `Retry-After`. Requests are paced at least 2 s apart. After the first definitive JSON 403/429, the remaining subreddits use RSS, and a 30 s budget stops new subreddits from starting.
- **TikTok:** 5 s timeout, 2 retries on 403/429/5xx, paced 2 s apart. It is often bot-gated and then reports `FAIL` cleanly.

### Velocity

For each entity: `rate = mean(% of kept observations mentioning it per comparable source)`. Only valid runs and compatible configurations enter historical comparisons. Large coverage changes produce neutral `UNCERTAIN` momentum. For each lookback window, the completed run closest to `now - w` (within ±50%) is found, and the rate is recomputed from that run's stored titles. `growth = (now - then) / max(then, one_item_floor)`. `velocity = 50 + 50 * weighted_mean(tanh(2 * growth))`, with weights 0.5, 0.3 and 0.2 for 1h, 6h and 24h. 50 means flat. Momentum labels: NEW, SURGING (75+), RISING (60+), STEADY, COOLING (25+), FADING. Until history exists, the score is a cold-start estimate labelled `BASELINE`. Run in `--loop` mode to fill the 1h, 6h and 24h windows.

### Notes

- Titles are folded to ASCII (as specified), so non-Latin-script trends are discarded. For another region, change `AGENT_REACH_GEO`, `TRENDS24_REGION` and `WIKIPEDIA_PROJECT`.
- Trends24, GitHub Trending and TikTok are HTML scrapes. When their markup changes, the ingester reports `FAIL` in SOURCE HEALTH and the run continues.
- TikTok Creative Center often bot-gates unauthenticated requests. Expect intermittent `FAIL` from that source.
- Unreachable Ollama, a missing model or invalid JSON all fall back to deterministic grouping and heuristic labels. The engine and the grouping method are shown in the report header.
- `density_member_min_cosine` (0.55) and `hdbscan_selection` (`leaf`) are tuned for `nomic-embed-text`. If you change the embedding model, re-check the `stage 3a density` log line.

### Cloud runner (GitHub Actions)

`run_cloud_handoff.ps1` syncs this folder to `timeitself1-cpu/Agent-Reach`. It excludes secrets, blocks token-looking strings, and keeps remote-only files unless you pass `-Mirror`. It then dispatches `.github/workflows/cloud-runner.yml`, waits until the run is `in_progress`, and streams its logs.

```powershell
powershell -ExecutionPolicy Bypass -File .\run_cloud_handoff.ps1                 # full LLM run
.\run_cloud_handoff.ps1 -NoLLM -ExtraArgs "--top 10"                              # fast deterministic run
```

The workflow installs Ollama on a CPU-only `ubuntu-latest` runner and caches `llama3.1:8b` after the first pull. It also pulls `nomic-embed-text`. It clusters up to 150 candidates, and because grouping is embedding-based, the LLM only labels real clusters. SQLite history is carried between runs in the Actions cache, so velocity works in the cloud as well. The report appears in the run summary and as a downloadable artifact. Optionally, set the repository variable `AGENT_REACH_CONTACT_EMAIL`.
