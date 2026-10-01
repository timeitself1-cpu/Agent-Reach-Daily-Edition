# Claude handoff: build Agent Reach Daily for Windows

Act as a senior Windows desktop application engineer and AI data engineer. Implement a usable daily news application from the attached Agent Reach source. Deliver working code and a complete updated ZIP, not just a plan, mockup, or code snippets.

## Read first

Read README.md, CLAUDE.md, docs/reliability-v2.1.md and the existing implementation/tests. This ZIP contains the current v2.1 working tree, including reliability changes that are not yet committed or published as a PR. Do not replace it with the older GitHub version. The existing application is a CLI pipeline, not a completed Windows desktop news program.

The latest local validation of this code passed 43 tests, pyflakes, the offline replay benchmark and the CLI help smoke test. That is not a live-source, live-Ollama, Windows GUI, or scheduler acceptance test. Existing cloud-environment restrictions in CLAUDE.md refer to cloud testing; the delivered product must run locally on Windows and use local Ollama. Update stale documentation where it contradicts the v2.1 implementation.

## Product outcome

Name: Agent Reach Daily.

The user opens an ordinary Windows desktop program and immediately reads the most recently cached daily news edition. A successful edition collected on October 1, 2026 in US Central time displays:

Trending news for October 1, 2026
Updated October 1, 2026 at 7:05 AM CDT

These are examples, not hardcoded dates or fabricated news. Compute dates and CDT/CST from America/Chicago with zoneinfo; include tzdata for Windows. Use UTC internally for timestamps, locks and elapsed-time scheduling.

The application refreshes news every 24 elapsed hours using local Ollama. HTTP/RSS ingestion fetches evidence; the local model summarizes and labels that evidence. Do not ask an LLM to invent current news or assume the model itself can access the web. Keep the default model llama3.1:8b and embedding model nomic-embed-text, configurable through settings. Use no required paid API or cloud LLM.

## Desktop experience

Use Python 3.10+ and a lightweight native Windows GUI, preferably tkinter/ttk to minimize dependencies. Preserve the existing pipeline modules. Add a separate GUI entry point and background-refresh entry point. Keep the current CLI working.

Provide:
- A clear dated edition heading, last successful refresh, next due refresh, and status.
- A short daily overview followed by ranked news cards with a title, category, two to four concise factual sentences, why it matters when supported, and clickable evidence links.
- Hot, rising, new and uncertain labels only when supported by the pipeline. A first run is a baseline; a headline is not proof that a topic is rising.
- Category filters, text search, Refresh now, an edition-history date selector, and simple settings for sources, model, cadence and retention.
- General-interest news by default, not an AI-only feed. Avoid allowing the number of enabled tech feeds alone to dominate the edition. Preserve honest coverage indicators if a balanced edition cannot be assembled.
- Source health and understandable errors, including blocked feeds or unavailable Ollama. Partial coverage must be visible.
- A responsive window: fetching, embedding and generation run off the GUI thread. Opening an existing edition does not rerun the model or redownload articles.
- Useful empty, first-run, refreshing, offline, stale-cache, and failure states. Never display fabricated sample stories as real news.

External sources such as X, TikTok and Reddit may be blocked or unavailable. Keep the current supported fetchers, use lawful public feeds/APIs and graceful fallbacks, and show missing coverage. Do not promise that every source always works or try to bypass authentication requirements.

## Daily refresh and caching contract

1. On first use with no cache, guide the user through prerequisites and offer an immediate real refresh.
2. Default refresh eligibility is 24 elapsed UTC hours after the last successful refresh. Manual refresh can run sooner. If you also support a fixed Central-time daily schedule, label it as a distinct setting and handle 23/25-hour DST days explicitly.
3. Install a current-user Windows Task Scheduler task that invokes a lightweight --refresh-if-due command periodically, such as hourly, and at logon. It must exit quickly without ingestion or model work when no refresh is due. Use StartWhenAvailable and prevent overlapping task instances. The GUI also checks eligibility on launch.
4. Be explicit that the computer cannot collect news while powered off. After sleep or a missed run, refresh when the task or GUI next gets a chance. Do not require a continuously open GUI. Document whether the scheduled task requires the user to be logged on and how Ollama is started in that session.
5. Use one cross-process lock for scheduled and manual refreshes, with safe recovery after a crashed worker. Do not use a boolean flag that can remain permanently stuck.
6. Store user data under a stable writable path such as %LOCALAPPDATA%\AgentReachDaily, independent of the install directory and current working directory. Persist settings, SQLite history, logs and dated editions there.
7. Write each validated edition to cache/editions/YYYY-MM-DD.json, with edition_date, timezone, generation start/completion in UTC, source health, configuration fingerprint, schema version, model identity and cited story evidence. Date the edition by refresh start in America/Chicago; a run crossing midnight must remain internally consistent.
8. Publish the dated file and latest-edition pointer atomically after successful validation. Readers must never see partial JSON. A second successful refresh on the same date may replace that date's edition atomically, with revision metadata; make the behavior explicit.
9. Render the GUI and an exportable standalone HTML daily edition from the same cached JSON. Escape all untrusted source/model text before rendering HTML. Offline reading must work without Ollama or network access; external article links still require internet.
10. On a failed or invalid run, preserve the last good edition, show the failure/stale status, and retain diagnostics. Never change yesterday's date to today merely because the user opened the app. All-source failure or an empty/no-useful-story run must not overwrite a useful cached edition; show an explicit no-update status instead.
11. Make cache publication eligibility stricter than accounting validity where necessary: an empty run can have a balanced ledger without being a useful daily edition. Partial successful coverage can publish only when the configured minimum useful-evidence requirement is met, with coverage warnings.
12. Store last attempt separately from last success. Rate-limit failed retries with backoff, so repeated UI opens or scheduler ticks cannot hammer feeds or Ollama. Show when the next retry is due.
13. Default to 30 days of editions with configurable retention. Do not delete the last valid edition merely because refresh has failed. Provide safe explicit controls for resetting the cache or disabling scheduled refresh.

## Preserve the reliability work

- LLM labels must never assign or merge members. Preserve deterministic event-coherence and final partition validation.
- Entity IDs and evidence-based event IDs are different. Existing event IDs are evidence fingerprints, not a complete persistent event-tracking solution; do not silently assume they stay stable when evidence changes.
- Keep duplicate observations and separate platform diversity from known publisher-host diversity. Publisher hosts are a proxy, not proof of editorial independence.
- Momentum comparisons must use compatible successful sources and effective configuration. Preserve UNCERTAIN behavior and the corrected reachable FADING score.
- Keep private/local destination blocking, per-redirect DNS validation, IP pinning, verified TLS and bounded fetches. Do not reintroduce automatic unchecked redirects.
- Invalid membership/accounting cannot produce a delivered edition or historical baseline. No model_construct validation bypass.
- Preserve supporting item IDs, source URLs, excerpts/context, source publication timestamps when known and retrieval timestamps. Summaries must be grounded in that evidence. Unknown publication times must not be presented as verified publication times.
- Preserve the current category enum rather than silently breaking report consumers. Keep a documented versioned DailyEdition wrapper if the GUI needs a different presentation schema.

Daily refresh produces roughly daily history, so existing 1h/6h momentum windows will often have no comparable run. Adapt the scoring configuration for the daily product, for example 24h/48h/7d windows with suitable tolerances and retention, and add tests. Do not invent hourly momentum from once-daily observations or label missing history as flat growth.

## Windows installation and operation

Deliver a PowerShell 5.1-compatible setup script and a double-click launcher/desktop shortcut. Quote paths containing spaces and use explicit working directories/interpreters. Do not rely on a globally activated Python environment. Install Python requirements in a project-owned environment. Check for Python, Ollama and both model downloads; provide clear remediation and progress instead of silently failing. Keep all runtime processing local except source fetching and prerequisite/model downloads.

Separate interactive setup from unattended refresh: scheduled runs must never wait for input, reinstall packages or pull models unexpectedly. Log to a rotating user-data log file and return meaningful exit codes. Register/update the scheduled task idempotently; provide an uninstall/disable script that removes the task and shortcut without deleting cached news unless explicitly requested. Avoid administrator privileges where possible. No visible console windows for normal GUI use or scheduled background jobs.

Prefer a simple maintainable launcher first. A packaged EXE is optional only if you can build and validate it; do not supply a broken executable or claim an installer was tested on Windows when it was not.

## Validation and deliverables

Extend offline tests for:
- First launch, cached startup, repeated opens with zero fetch/model calls, manual refresh and exactly-24-hour eligibility.
- Central-time date formatting, midnight boundaries and both daylight-saving transitions.
- Scheduled task command quoting, paths with spaces, missed schedules and an unavailable Ollama service.
- Simultaneous refresh attempts, worker crashes, corrupt cache recovery and atomic publication.
- Source outages, invalid accounting, empty-but-balanced runs, retry backoff, and preservation of the last good edition.
- Daily-cadence momentum, unavailable baselines and source/configuration changes.
- HTML escaping, archived editions, retention and exported evidence links.

Run the existing pytest, pyflakes, replay benchmark and CLI smoke checks. Test actual Windows GUI launch, cached offline reading and task registration where the environment permits; otherwise explicitly list these as unverified and provide exact Windows acceptance steps. Use fake HTTP/model responses for deterministic unit tests. Never label fixture news as a live edition.

Deliver the implemented application, complete updated source ZIP, setup/launch/uninstall scripts, a concise Windows quick-start, architecture notes, test results and known limitations. Include a sample edition only if prominently labeled DEMO and segregated from real cached news. Do not register tasks or install prerequisites merely to inspect this ZIP; registration belongs to the user's explicit setup action.

Start by inspecting the attached code, then implement the complete application. Make routine engineering decisions and finish the deliverable rather than stopping after a proposed plan.
