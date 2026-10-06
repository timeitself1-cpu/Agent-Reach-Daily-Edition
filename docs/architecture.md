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
address, category, on/off. An RSS/Atom/RDF feed is one channel inside the `news_rss` source; a
YouTube channel address (`/channel/UC...` or its feed URL) is one channel inside the `youtube`
source (`build_settings` splits them into `news_rss_feeds` and `youtube_channels`). Three sources
are made of feeds, each with its own allowance, budget floor and health line (`SourceStat.feeds`):

| Source | Feeds | Allowance per feed | Score inside the source |
|---|---|---|---|
| `news_rss` | publisher feeds (114 by default) | `items_per_feed` (10); total `news_rss_max_total_items` (900) | in-feed rank |
| `youtube` | channels (22 by default) | 3 most-watched uploads of the last `youtube_max_age_hours` (72) | views per hour since upload |
| `google_news` | top stories + `google_news_sections` (14) | 60 top stories, 20 per section | 1.0 for each section's lead story, falling with rank |
| `mastodon` | `mastodon_instances` (mastodon.social) | 20 trending links per server | accounts that shared the link in two days |

YouTube retired its public Trending page in 2025 and its Data API needs a key, so the `youtube`
source reads the public channel feeds (`/feeds/videos.xml?channel_id=`), which carry view counts.
Video descriptions (first substantive lines, no links or calls to subscribe) are the item context;
watch pages are never fetched. A channel's videos count as that publisher's reports: a BBC News
video and a BBC News article are one publisher in evidence strength. A channel with no upload in
the window is EMPTY, not failed, and does not raise a coverage warning. Google News sections are
topics (`/rss/headlines/section/topic/TECHNOLOGY`) or day-limited searches (`q=... when:1d`) and
set the item's category hint. TikTok reads the Creative Center page (pages-router
`__NEXT_DATA__`, app-router escaped JSON, or the rendered cards); a page without data is tried
once more without parameters, a blocked request is not repeated beyond its retries.

**Feed doctor** (`daily/feedhealth.py`): after every refresh each feed's result is recorded in
`state/feed_health.json`. A feed that failed in every refresh for 3+ days (and 2+ refreshes) is
flagged in a notice and in Settings > Publisher feeds ("Failing since ...", "Turn off failing
feeds"). When every feed of a channel fails at once (offline, blocked), that refresh is not
counted against any feed.

Other channels added in settings v4: **Mastodon** trending links (`/api/v1/trends/links`, public)
are publisher articles that many people share, so they count as the publisher's report (a shared
copy of an article already cited is cited once). **Bluesky** trending topics
(`app.bsky.unspecced.getTrends`, falling back to `getTrendingTopics`) are attention signals like X
trends. **Wikipedia "In the news"** (`/api/rest_v1/feed/featured/`, `wikipedia_in_the_news`) adds
the curated one-sentence world-news items ahead of the most-read list; when it is unavailable the
Wikipedia channel is partial, never failed.

- **Intake:** feeds are interleaved by rank, so a cap never drops a whole feed and adding feeds
  never shrinks the others.
- **Processing budget:** `max_items_for_llm` (260) articles are grouped and labelled per refresh.
  Every channel keeps `min_items_per_source_for_llm` (6), every publisher feed keeps
  `min_items_per_feed_for_llm` (2) and every YouTube channel or Google News section keeps
  `min_items_per_channel_feed_for_llm` (1) of that budget; the rest goes to the highest scores.
  Floors are handed out in rounds (every group's best item first, then every group's second) and
  may use at most `FLOOR_SHARE` (75%) of the budget, so with 150+ feeds each still gets its lead
  item and the strongest items keep a quarter of the budget.
- **Single-report stories:** the Daily app runs the clusterer with `outlier_policy="keep_top"`:
  a density outlier stays as its own one-article story (never merged into a mixed cluster) when
  its heuristic score is >= `singleton_keep_score` (0.35, roughly the top 7 of each feed, since
  the score is a percentile within the channel) or its relevance is >= 6. Without this, a niche
  section such as Tech, whose news is often reported by one outlet, came out empty.
- **Health:** `SourceStat.feeds` records every feed (OK / EMPTY / FAILED, articles collected); the
  edition adds how many of each feed's articles were cited ("used"). A channel that answered but hit
  errors (a failing feed, a Reddit 429 with RSS fallback) is PARTIAL, never "healthy".

### Selection rules (quality over quota)

1. Stories whose every stated publication time is older than `max_story_age_hours` (48) are dropped.
   Undated items (trend lists, Wikipedia) are kept but never shown with an age.
2. A single trend/social signal with no publisher article and relevance below 7 is dropped.
   Earlier, at the clean stage: advertising dressed as news ("on sale now for just $14.97 (MSRP
   $159)") is discarded as `promotional`, and YouTube highlight reels, full replays, live streams,
   reactions and recaps as `video_clip`. Summary sentences that say nothing ("is drawing attention
   due to...", "this showcases...", "published in various journals") or repeat what was already said
   are dropped (an earlier sentence at 60%, or all earlier sentences together at 70%,
   `edition.NOVEL_SHARE`); "why it matters" must also state a consequence - who is affected
   ("residents", "patients") or what changes ("forces", "no longer", "prompted") - and avoid vague
   claims ("highlights concerns", "significantly impacted", "severe consequences"); a purpose ("The
   move is to comply with ...", "aims to curb fuel costs", `brief.PURPOSE_RX`), a cause ("is a
   response to intense criticism"), a line repeating five words of the summary, or a further detail
   ("The 39-year-old will bid an emotional farewell") is not a consequence (`brief.concrete_effect`).
   Every summary sentence must also be **supported by the story's own sources**: at least 60% of
   its content words (stemmed) appear in the members' titles, page/feed context and descriptions
   (`edition.support`), so model padding such as "The film is a unique and artistic take on the human
   experience" is dropped, and **every number** in it must appear there too (`edition.numbers_in`;
   "1.4 billion neurons" when the page says "23 billion active" is dropped) and stand next to the same
   words as there (`edition.numbers_anchored`: a word just before it matches a word before it in the
   sources, or a word just after it matches one after it; "Over 67 million Wikipedia hosts expose
   sensitive data" from "Wikipedia hosts over 67 million articles" is dropped; years, dates, labels
   such as "Week 5", scores and a number ending the sentence are not checked). Measured on eight real
   editions: 1 of 153 published sentences with numbers rejected, the false one. A sentence about the
   article ("The author provides their picks") is not news. Also dropped: sentences
   in another language (`looks_english`); the page's own voice outside quotes ("Every time you ask
   ChatGPT ...", "as our industry ...", `page_voice`); a subordinate clause with no main clause
   (`is_fragment`); a sentence cut short ("Clayton will lead the government's new.", `ends_dangling`);
   a sentence that only restates the headline ("The redesign is the biggest in decades."; kept when
   the next sentence opens with a pronoun that needs it: "He was best known for ..."). Sentences never
   end after "U.S.", "U.K.", "No.", "Gov." and similar abbreviations, and a "sentence" of fewer than
   three words is dropped. Model "entities" restore their casing in a summary only when the reports'
   own prose writes them that way ("in the brain" stays lower case). A clause
   that repeats the sentence ("..., found by a team of Claude Opus 5.5 agents") is cut
   (`without_self_repeat`); a sentence that repeats a five-word run of an earlier one replaces it when
   it contains it and says more, and is dropped otherwise (`place_sentence`; also for brief details). Attribution prefixes ("Sources:") are removed, and a "why it
   matters" that restates the headline or summary (70% of its words) is left out. When no summary
   sentence survives, the first sound sentence of the reports' own text is used (`lead_sentence`;
   never from a live blog). A model headline that states an amount ("Thousands in
   Quarantine", "12,000") no member reports is replaced by the best real report title
   (`clusterer.quantities_grounded`).
3. Repeats are dropped: same entity set, a shared article URL, or near-identical headline words.
   The entity-set id hashes only the key names, so a single shared name ("Donald Trump") never
   makes two stories the same, here or in "what changed" (`edition.same_entities`).
   A story told only by live blogs ("... - as it happened": a running page of many events) is left
   out; elsewhere a live blog is never the story's title (`clusterer._best_member_title`) and its
   "- as it happened" suffix is removed (`cleaner.LIVE_BLOG_SUFFIX_RX`).
4. **Sections.** Each category keeps its top `max_stories` (10) stories, corroborated stories
   first (inside a section a single-outlet story never sits above news several outlets report); the
   overflow is counted as held back. **Top Stories** are the `max_stories` best of those, with at
   most `max_per_category` (4) from one category (a strong story - relevance 8+ and corroborated -
   may exceed that by 2) and `max_tech_only_share` (34%) tech-only stories, so the top stays broad.
   Places are filled in passes, each in pipeline rank order: corroborated stories (more than one
   independent report) within the caps; then corroborated stories beyond their category's cap; then
   single-outlet stories within the caps, those the model rated 9+ first. A single outlet's story
   never takes a place while corroborated news waits (in a real run a 1-report story rated 9 had
   taken News's last place from a 5-report story).
   First-person columns ("How I made...") and stories told only through video clips stay in their
   section, after the news, and never enter Top Stories. If the caps leave Top Stories short, the next best stories
   fill it. The edition stores the Top Stories as `top_ranks` (optional; older editions show their
   first ten stories). Sections are shown in a fixed order: News, Tech, Science & AI, Sports,
   Entertainment, Internet Culture.
   The grounded brief pass runs on Top Stories plus the first 3 of each category, which bounds
   model time.
5. The edition is published only with >= `min_ok_sources` (2) responding sources and
   >= `min_useful_stories` (3) stories; otherwise the previous edition stays.

### Reading features (`daily/reading.py`, no Tk)

- **In brief:** the lead sentence of the first five Top Stories (clipped at 170 characters), in the
  window and the HTML export.
- **Tags:** NEW / UPDATED come from the edition's `changes` (no model). DAY n comes from walking back
  through up to 7 earlier cached editions with the same matching rules as "what changed"; the run
  ends at the first edition that does not carry the story (`AppController.developing`, cached per
  edition).
- **Read state:** `state/reading.json` maps `story_id` to when it was opened (written only by the
  window, kept 14 days). A story that gains new evidence gets a new `story_id` and reads as unread.
  Sidebar counts are unread counts.
- **Topics:** `follow_topics` / `mute_topics` in settings (whole words or phrases, any case, matched
  on headline, summary, key names and evidence titles). Followed stories are starred and gathered in
  a Following section; muted stories are left out of every section and search. `Story.entities`
  (optional; the cluster's key names) feeds the right-click Follow / Mute suggestions.

### Daily podcast (`daily/podcast.py`)

Built after a successful publish when `podcast_auto` is on (and on demand from the window or
`--podcast`). The script is deterministic: intro, the first `podcast_stories` Top Stories (headline,
summary sentences, grounded "why it matters", named publishers from evidence strength), followed
topics, two headlines per section, outro; muted topics are skipped. No model text is added. Speech
uses Windows `System.Speech` through Windows PowerShell 5.1 (`-EncodedCommand`, paths passed in
environment variables, SSML with pauses, 22 kHz mono WAV; the SSML language follows the chosen
voice), or `espeak-ng` elsewhere. Audio is written to a `.part.wav` and renamed when complete;
podcasts older than `podcast_keep_days` are deleted. A podcast failure is reported in the refresh
message and never affects the edition.

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
near-identical headline words. Reported: new; materially updated (new independent publishers, or a
different headline with words neither the previous headline nor its reports used, taken from reports
the previous edition did not cite - the model
rewording the same evidence, a new summary or a new "why it matters" is not an update); signals
up/down (raw signals changed by >= 50% and >= 2, or independent reports by >= 2), only against an
edition of the same day, since a story carried over from yesterday naturally has fewer fresh
signals; and stories no longer listed. Before selection, a story already in the previous edition
keeps that edition's category unless it has reporting from a new publisher
(`changes.keep_previous_categories`), so the model's Tech / Science & AI choice cannot flip it
between runs. The first edition has nothing to compare with. The window shows this only in
Details > Changes and the HTML export keeps it in a collapsed block at the bottom, so it never
takes reading space.

### Grounding gate for model text

The brief pass sends the model only the story's headline, summary and evidence lines. A returned
sentence is kept only if every number, spelled-out quantity, capitalised name or acronym (as a
whole word) and hedge word ("could", "may") appears in that evidence, and it contains no generic
filler ("highlights the importance of", "only time will tell"), URL or handle. Rejected text is
omitted; a failed or garbled model call leaves the story with its validated summary.

### Momentum on a daily cadence

The Daily app compares against runs about 24 h, 48 h and 7 days earlier (+/-25%). A run serves at
most one window, so one historical run never counts twice. The first edition is a baseline (no
trend labels). Labels: New, Rising, Hot, Continuing, Cooling, Fading. When sources or configuration
changed too much to compare (the scorer's `UNCERTAIN`; any feed-list change, such as a settings
migration, does this for a day), cards carry no trend label, and when that holds for every story
the edition says so once in its notes. "Uncertain trend" labels stored by older editions are
dropped on load.

## Pipeline modules (classic Agent Reach)

| Module | Role |
|---|---|
| `config.py` | Pydantic Settings; every field overridable via `AGENT_REACH_*` env vars / `.env` |
| `models.py` | `CategoryEnum`, `RawTrendItem`, `CleanedTrendItem` (+ scraped `context`), `MacroCluster`, `PipelineAccounting` (ledger with invariant checks), `PipelineReport` (schema_version 3) |
| `ingestion/base.py` | `BaseIngester`: shared `httpx.AsyncClient`, per-call timeout, exponential backoff + jitter, `Retry-After`, extra retryable statuses, per-ingester request pacing; `run()` never raises |
| `ingestion/social.py` | X (Trends24 scrape), Reddit (JSON with score/comments -> RSS; 5 s timeout, 403/429 retries, 2 s pacing, 30 s budget), TikTok Creative Center (5 s timeout, retries, 2 s pacing; three page shapes), Mastodon trending links, Bluesky trending topics (public APIs, 8 s timeout) |
| `ingestion/search.py` | Google Trends RSS, Google News RSS (top stories + optional per-category sections), Wikipedia top pageviews, ArXiv Atom API |
| `ingestion/video.py` | YouTube channel feeds (`youtube_channels`, `Category|CHANNEL_ID|Name`): recent uploads ranked by views per hour, per-channel health |
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
   - **3d' key names:** chained links can still connect different events through generic words ('accused' + 'woman' joined a spy arrest to an unrelated murder in a real edition). Every member must therefore mention one of the story's key names: proper nouns that at least 40% of its members mention. Which words are names is learned from the run's own text (written capitalised mid-sentence far more often than lower case, or only ever seen opening a headline), never from model output. Members that fail are split off into their own coherent stories (or single-report stories that the singleton rules keep or drop). Single-word links through a short title only work for trend fragments (X, Google Trends, Wikipedia, TikTok, Bluesky), not for article titles such as "Web Search API", and a fragment may not name someone else than the article ("Gavin Williams" does not join "Hayley Williams ...": `LinkIndex.fragment_fits`).
   - **Shared phrases count once:** two titles that share only one phrase ("Supreme Court", "iPhone 18 Pro", "dies aged", "data centres") are not linked through it word by word. Shared tokens that both titles write side by side are one unit (`LinkIndex.shared_units`); a link through rare words needs two such units, and at least one must say what happened rather than only who ("Apple" + "iPhone" is not enough; a number such as "27.2" is not either). Words with a capital inside ("iPhone", "tvOS") count as names. This split three Supreme Court stories, five Apple stories and two obituaries that a real evening edition (October 5, 2026) had merged.
   - **Everyday words are not events:** a fixed list of common English words (`clusterer.COMMON_WORDS`: "adding", "using", "national", "officials", "case", "ahead", "costs", "hit", "cuts", "space", ...) never counts as the "what happened" unit and never alone keeps two titles linked. The list also holds "midterm(s)", a season word in US news before November 2026: it occurs in the run as often as "diesel", so a document-frequency floor cannot separate it from a real event word. In the October 6 morning edition "ChatGPT/OpenAI" + "adding" had joined the EU watermark story, a cartoon story and an Apple lawsuit ("7 independent reports" instead of 4), and "Trump" + "national" had joined the AI czar to a cable lobby lawsuit.
   - **Names or rare words:** two titles that share no name link only through words in at most 1% of the run (`LinkIndex.nameless_cap`; with a shared name the 6% `rare_cap` applies). "games" (17 of 1,352 titles) + "consoles" had joined a PS5-on-Xbox mod to "chipflation" prices.
   - **Exclusive qualifiers:** titles naming different members of a set (`EXCLUSIVE_QUALIFIERS`: physics / chemistry / medicine / literature / peace / economics) are different events (`event_compatible`), so the medicine and physics Nobel Prizes stay apart although both titles say "Nobel Prize".
   - **Tech vs Science & AI:** within this pair the model's choice stands unless the reports' own keywords favour the other side at least 2 to 1 (2+ hits; "Apple Intelligence from macOS 27" is Tech), in `_guard_category`.
   - **3e drop:** clusters flagged `[INSUFFICIENT_DATA]`, with filler summaries ("no specific information", "details are scarce"), or with relevance <= 3 are dropped, as are weak singletons. Headlines keep up to 14 words and are cut at a sentence or clause break; a title with no such break keeps up to 18 words whole (`HEADLINE_STRETCH_WORDS`) rather than being cut mid-clause ("... Exploring Trauma Brought"), and only a longer one is cut before a dangling word. A model headline must use the reports' own words (half of its content words, `headline_supported`), or the best report title replaces it ("Falcons Edge Saints in Thursday Night Football" for a Monday game). A domain that is the subject ("Example.com just launched ...") is kept; one used as attribution ("via techcrunch.com") is removed (`cleaner.strip_bare_urls`). A topic label from the model (a short title with no verb, e.g. "Cornell University Rape Allegations") is replaced by the best real report title when that reads as a headline.
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
- `density_member_min_cosine` (0.62, raised from 0.55 after a real edition) and `hdbscan_selection` (`leaf`) are tuned for `nomic-embed-text`. If you change the embedding model, re-check the `stage 3a density` log line.

### Cloud runner (GitHub Actions)

`run_cloud_handoff.ps1` syncs this folder to `timeitself1-cpu/Agent-Reach`. It excludes secrets, blocks token-looking strings, and keeps remote-only files unless you pass `-Mirror`. It then dispatches `.github/workflows/cloud-runner.yml`, waits until the run is `in_progress`, and streams its logs.

```powershell
powershell -ExecutionPolicy Bypass -File .\run_cloud_handoff.ps1                 # full LLM run
.\run_cloud_handoff.ps1 -NoLLM -ExtraArgs "--top 10"                              # fast deterministic run
```

The workflow installs Ollama on a CPU-only `ubuntu-latest` runner and caches `llama3.1:8b` after the first pull. It also pulls `nomic-embed-text`. It clusters up to 150 candidates, and because grouping is embedding-based, the LLM only labels real clusters. SQLite history is carried between runs in the Actions cache, so velocity works in the cloud as well. The report appears in the run summary and as a downloadable artifact. Optionally, set the repository variable `AGENT_REACH_CONTACT_EMAIL`.

With `entrypoint=agent_reach.daily` the workflow runs one real Daily refresh. The Daily app takes its processing budget from `settings.json`, not from `AGENT_REACH_MAX_ITEMS_FOR_LLM`, so the workflow writes the runner's own settings first: `daily_articles` (input, default 80) articles instead of the Windows default 260, a 100-minute refresh limit (the job allows 120) and no podcast. The runner generates about 4 tokens/s; with 260 articles the first Daily run (37421270778) needed 14 label calls of 4-12 minutes and hit the 90-minute limit before the brief pass.
