# Agent Reach: guide for Claude

Agent Reach has two product surfaces: **Agent Reach Daily** (`agent_reach/daily`), a Windows desktop daily-news reader built on the pipeline, and the classic CLI report (`python -m agent_reach`). Read `README.md` (product, Windows quick start) and `docs/architecture.md` (internals). `docs/HANDOFF.md` has the current state, history and open items for a new session.

The pipeline is **Module 1** of a modular trend-intelligence system. It ingests trend signals from 10 sources, filters noise, enriches items with page content, groups them by embedding density, has a local LLM (`llama3.1:8b` via Ollama) label the groups, scores relevance and velocity, and writes an ASCII executive report plus SQLite history.

## Commands

```bash
pip install -r requirements-dev.txt     # runtime deps + pytest + pyflakes
python -m pytest                        # offline suite (~1 min): mock HTTP + fake Ollama, real HDBSCAN/trafilatura/SQLite
python -m pyflakes agent_reach tests    # must be clean
python -m agent_reach --no-llm --help   # CLI smoke test
python -m agent_reach.daily --help      # Daily CLI smoke test
python -m tests.replay_benchmark        # offline reliability replay
```

GUI tests (`tests/test_daily_gui.py`) need a display and skip without one; run them with `xvfb-run -a python -m pytest` on Linux. Daily end-to-end tests use `tests/daily_fakes.py` (synthetic feeds on `.test` hosts + a deterministic fake model) through the real pipeline.

Every change must leave `pytest` green and `pyflakes` clean. `.github/workflows/tests.yml` runs both (plus the CLI smoke test) on every push and pull request. Add or extend tests in `tests/` for any behaviour you change. `tests/fakes.py` holds the mock sources and the fake Ollama.

## Environment limits (cloud sessions)

- **No Ollama or live data here.** The cloud sandbox has no Ollama and cannot reach most source sites, so never try a live run. Verify with the offline tests.
- **Real-data runs happen in GitHub Actions.** The `.github/workflows/cloud-runner.yml` workflow is started manually (`workflow_dispatch`). It installs Ollama with `llama3.1:8b` and `nomic-embed-text` on a CPU runner and uploads `report.txt`, the JSON report and `pipeline.log` as an artifact. With input `entrypoint=agent_reach.daily` it runs one real Daily refresh instead and uploads the edition as HTML plus the Daily logs. When a change needs real-data validation, say so in the PR description. The user will run the workflow and share the artifact.
- **`.ps1` scripts run on Windows PowerShell 5.1** and must stay ASCII-only with CRLF line endings (`.gitattributes`). Keep `$ErrorActionPreference = "Continue"` with explicit `$LASTEXITCODE` checks, because 5.1 turns native stderr into terminating errors. Avoid PowerShell 7-only syntax (`??`, ternary `? :`, `&&`).

## Invariants: do not break these

1. **Item ledger balances.** `ingested == sum(discarded[reason]) + clustered`, in raw-item units (`CleanedTrendItem.raw_weight`). Every dropped item goes into exactly one named bucket (`models.DISCARD_STAGES`). `ClusterOutcome.assert_partition` and `PipelineAccounting` enforce this; tests assert it.
2. **The LLM never decides grouping.** Grouping comes from embeddings + HDBSCAN (`pipeline/density.py`), or the lexical fallback. The LLM only labels groups.
3. **Outliers are noise.** They are dropped, never forced into a mixed cluster.
4. **Entity isolation.** A cluster must be connected by distinctive shared tokens, a literally shared entity, or entities that co-occur in another item of the run (`LinkIndex`), and every member must mention one of the cluster's key names (`_key_name_gate`, names learned from the run's text). A phrase both titles share ("Supreme Court") counts once (`LinkIndex.shared_units`), and names alone never link two full titles. An LLM entity list or headline alone is never evidence.
5. **No filler.** `[INSUFFICIENT_DATA]`, placeholder summaries (`FILLER_RX`) and relevance <= 3 are dropped before the report. In the Daily app every summary sentence must be supported by the story's own sources (`edition.support`, 60% of content words) and be English.
6. **Ingesters never raise.** `BaseIngester.run()` returns `([], SourceStat(ok=False, ...))` on any failure. Reddit and TikTok use a 5 s timeout, 403/429 backoff retries and at least 2 s pacing.
7. **Output contract.** `PipelineReport` (`schema_version`) is consumed by future modules. Changing or removing fields requires bumping `schema_version`; adding optional fields does not.

## Daily app invariants

8. **No edition beats a bad edition.** A refresh that fails, finds too few sources/stories, or has an invalid ledger never touches the last published edition; it records the attempt, backs off and writes a diagnostics file.
9. **Attempt is not success.** `last_attempt_*` and `last_success_*` are separate; due times anchor on the last successful refresh START. Publication time is shown only when a source stated it (`published_at_utc`); retrieval time is never presented as publication time.
10. **One refresh at a time** via the OS byte-range lock in `daily/lock.py`; never a boolean flag.
11. **Model text is grounded or omitted.** Brief-pass output must pass `daily/brief.grounded`; failures leave the story with its validated summary. The model never sees the web and never decides membership.
12. **The GUI renders plain text.** Source/model text goes into Tk Text as text; only `safe_url` (absolute http/https) links open. HTML export escapes everything and loads no remote assets.
13. **User data lives outside the repo** (`%LOCALAPPDATA%\AgentReachDaily`); the demo edition is never written to the news cache.
14. Keep business logic in `daily/app.py` (testable without Tk); `daily/gui.py` is the view.

## Conventions

- Python 3.10+ with `from __future__ import annotations`, Pydantic v2 and `httpx` (the only HTTP client). No LangGraph, aiohttp or other new frameworks without a clear need.
- Surgical, targeted changes over rewrites. Keep the module layout. Complete code only: no placeholders or TODOs.
- Report output is ASCII only. Titles and summaries go through `normalize_text`, `sanitize_summary` and `sanitize_headline`.
- Every behaviour-changing setting lives in `config.py` (`AGENT_REACH_*` env vars) with a safe default.
- Never commit `.env`, `*.db`, `.venv/`, `reports/` or `state/` (see `.gitignore`).

## Known open items

- Similarity thresholds (`density_member_min_cosine=0.62`, `hdbscan_selection="leaf"`) are defaults for `nomic-embed-text`. 0.55 let unrelated reports into stories in a real edition (October 5, 2026); 0.62 plus the key-name gate (`clusterer._key_name_gate`) is the current setting. Use the `stage 3a density` log line from a real run to tune further.
- Google News links are `news.google.com` redirect pages with no article text, so those items get no context.
- Reddit is usually blocked from data-centre IPs (CI). The robust fix is Reddit's OAuth API, with credentials as GitHub secrets.

## Roadmap

- **Module 2, Agent Depth:** reads `PipelineReport` JSON (the contract above), fetches 3-5 sources per top trend, checks cross-source agreement, and writes cited `TrendBrief` records. It must depend on the JSON contract only, never on Agent Reach imports.
- **Module 3:** delivery and watchlists (digest, velocity alerts).
- **Module 4:** actions.
