# Editorial quality benchmark

A read-only, non-blocking report on the **published editions** (`website/editions/*.json`). It
does not touch the publisher, event identity or website rendering.

```
python scripts/edition_quality.py              # text report
python scripts/edition_quality.py --evaluate   # also score the checks against the labeled samples
python scripts/edition_quality.py --json | --markdown
python -m pytest tests/test_edition_quality.py # focused tests of the script itself
```

It is **not a CI gate.** `.github/workflows/editorial-quality.yml` runs it with
`continue-on-error: true` and writes the report to the job summary so it can be watched over several
editions first. `--fail-on-failures` exists for later, and is off by default.

## What it can and cannot say

It reads only the stored headline, summary, source titles and metadata. It never opens the cited
articles, so it cannot verify a fact or a claim of support. Keyword overlap is a prompt for a
person, not evidence.

| Tier | Meaning | Examples |
|---|---|---|
| `failure` | A deterministic fact about the data | empty summary; source with no valid URL/outlet/kind; `independent_reports` larger than `publishers`; invalid `top_rank`; encoding corruption |
| `warning` | Flagged **for human review**; never "wrong" or "duplicate" | summary adds little to the headline; cited title shares little with the headline; two stories look alike; "A. And, B." two-topic title; Top list not 10 |
| `info` | Context | continuity not assessable |

Every warning check name ends in `_review` (or `summary_adds_little`).

## Historical editions and event identity

- **Era.** An edition with a `quality` block (written by the publisher's `editorial_review`) is
  `current`; older ones are `legacy`. Legacy findings are reported separately and never count as
  regressions, so an old edition cannot make a later fix look like a failure.
- **Continuity.** The story `id` is an evidence fingerprint that is expected to change
  (`agent_reach/daily/edition.py`), so it is never compared. Cross-edition continuity is assessed only
  between two editions that both publish `event_id` on every story. As of 2026-10-10 none do, so the
  report says `continuity_not_assessable`. Once editions publish `event_id`, a near-identical
  headline under a different `event_id` becomes a `possible_identity_split_review` warning.
- **Source list cap.** Every published story lists at most 8 sources while `coverage` counts more, so a
  coverage count above the listed sources is not a defect by itself.

## Label samples (auditor-labeled, not independently reviewed)

`tests/fixtures/editorial/`:

- `auditor_labeled_smoke.json`: development examples; the checks were built while looking at
  them. A smoke test only.
- `auditor_labeled_validation.json`: separate sample (editions 2026-10-07 and 2026-10-08; no story
  overlaps the smoke file) with real defects **and** legitimate stories that must not be flagged.
  The labels were written before the checks ran on it, and checks were not tuned afterwards. The
  labeler had earlier run exploratory scans on these editions, so it is **not a blind holdout**.

Both are labeled by one auditor from the stored text and need independent review. Labels are pinned to
an edition revision (`edition_revisions`); if an edition is republished, its labels are reported as
stale and skipped. Defects whose `expected_checks` is empty have no implemented check and count against
recall by design.

Metrics (`--evaluate`): per-sample recall (all defects, and only those with an implemented check),
precision (detected defects / (detected defects + clean stories that received a failure or warning)),
and the clean stories that were flagged.

## Adding or changing a check

1. Reproduce the defect from a real edition and add it to a label file as `defect` with the check it should
   trigger, and a nearby legitimate story as `clean`.
2. Tune on the smoke file only. Do not edit checks to improve the validation numbers; grow the validation
   sample instead.
3. Prefer a deterministic `failure` only when the property is true or false without editorial judgment.

## Automated Operational Protocol (Continuous Editorial Monitoring)

When new editions are published, `.github/workflows/editorial-quality.yml` runs automatically on pushes to `website/editions/**`. Operational monitoring agents (e.g., Meta Muse on 30-minute heartbeats) and reviewers follow this workflow:

1. **Verify Workflow Run**: Confirm that the `editorial-quality` CI workflow completed on the publish commit.
2. **Delta Analysis**: Read the job summary and compare new findings against previous editions to identify regressions.
3. **Deduplication**: Filter out known legacy-era items and previously reviewed warnings.
4. **Escalate Structural Failures**: Escalate confirmed data failures (`empty_summary`, `signal_only_no_report`, `duplicate_source_url`) as immediate P0/P1 defects.
5. **Surface High-Impact Warnings**: Identify editorial warnings requiring human review (`two_topics_review`, `similar_story_review`, major summary tautologies).
6. **Concise Tracking**: Create a single, concise GitHub issue for unowned, confirmed defects instead of repeating alerts.
7. **Sonnet Handoff**: Assign difficult editorial-quality investigations to Claude Sonnet using the `AGENT HANDOFF` format defined in `AGENTS.md`.
8. **Asynchronous Discipline**: Do not assume GitHub comments immediately activate Sonnet; handoffs are picked up via configured runs.
9. **Holdout Privacy**: Never post or commit hidden holdout evaluation labels to public GitHub threads or commits.
10. **Non-Blocking Rule**: Never block daily publishing or deployments based on unverified heuristic warnings.

