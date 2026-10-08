# Agent Reach backend audit and improvement plan (October 8, 2026)

Audit of everything behind getagentreach.dev: pipeline, Daily refresh worker, local storage, and the website
publisher. The website's pages and scripts were out of scope (front-end work runs in parallel). The shared
version of this document is a Claude doc; this file is the repository copy, and the sub-tasks are Phase B in
`docs/PLAN.md`.

**What ran where:** cloud sandbox only, on rc14 (`e0a3b07`): offline suite with Tk under Xvfb 510 passed,
5 Windows-only skips, 7 strict xfails; pyflakes clean; CI green on the last 4 runs. Measurements on the 12 real
October 7 editions in `tests/fixtures/real/`. Nothing ran on the Windows PC or against the live site.

## Summary

The backend is sound: a failed run never replaces a good edition, the site only moves by one complete
fast-forward commit, nothing hangs (lock, time limit, watchdog), the page fetcher pins checked public addresses.
The weak spot is the step that feeds the live site:

- **F1** a story removed from the website can come back with a later revision of the same day;
- **F2** a failed upload is not retried until the next refresh (24 h by default).

Next: a written data contract with the front end (F4), stable story links (F3).

## Findings

| # | Sev. | Finding | Evidence |
|---|---|---|---|
| F1 | High | Removed story comes back after a same-day revision: removal is keyed by story id, the id is a hash of the member titles and changes when a report is added or lost. | `publish.hide_story` / `public_edition`, `pipeline/evidence.event_id`. Fixtures: 28 of 144 stories continuing into r2 reappear (19%). |
| F2 | High | A failed upload waits for the next refresh. | `refresh._attempt` is the only caller of `publish_after_refresh`; the hourly `--refresh-if-due` tick exits when not due. |
| F3 | Medium | Public story ids are short-lived: links, bookmarks, search results break on a revision; all change the next day. | 116 of 295 ids (39%) survive a same-day revision. The rc14 registry has stable event ids, unpublished. |
| F4 | Medium | The public data format (edition, index, search month) exists only as code; the front end is built separately. | `docs/PUBLISHING.md` lists files, not fields; no contract test. |
| F5 | Medium | Access-key expiry is noticed only after a refused upload. | 401 handling in `GitHubTarget._call`; GitHub's `github-authentication-token-expiration` header is not read. |
| F6 | Medium | The website waits for the podcast. | Order in `refresh._attempt`: save, registry, podcast, website. |
| F7 | Medium | Windows-only code (DPAPI, file locks, TerminateProcess) never runs in CI. | `tests.yml` is Ubuntu only. |
| F8 | Medium | Dependencies are unpinned (`>=` only); Setup installs the newest of everything. | `requirements.txt`. |
| F9 | Low | Edition pages carry only headlines without JavaScript (slower first paint on phones, weaker for search engines). | `edition_page` `<noscript>` list. |
| F10 | Low | One path-like string (e.g. a headline about "AppData") blocks the whole day. | `assert_public` raises for the edition. |
| F11 | Low | The publisher reads the same files twice per attempt and does not close its HTTP clients. | `_with_target`, `GitHubTarget`, `live_edition`. |
| F12 | Low | Published JSON is indented: compact is 17% smaller (70 -> 58 KB; 15-20 KB gzipped). Search month ~570 KB (~200 KB gzipped). | measured with `public_edition`, `search_entries`. |
| F13 | Low | `withdraw` does not validate the date before building GitHub paths (the folder target has a guard). | `publish.withdraw`. |
| F14 | Low | Very large modules: `clusterer.py` 1,709 lines, `edition.py` 1,351, `gui.py` 2,364. | split only when touched. |

## Plan (sub-tasks: docs/PLAN.md Phase B)

1. **Protect the live website (rc15):** removed stories stay removed by their reports, not only their id (F1);
   the hourly check retries a failed or missing publication of the latest edition (F2); publish before the
   podcast (F6); warn seven days before the access key expires (F5).
2. **Publisher hardening (same release):** leave out one bad story instead of the day (F10); validate dates
   (F13); read each file once, close clients (F11).
3. **Contract with the front end (parallel):** `docs/PUBLIC-DATA.md`, schema files and a real example in
   `docs/schema/`, a test validating the publisher's output on all fixtures (F4); pre-rendered pages (F9) and
   compact JSON (F12) only with the front end's agreement.
4. **Stable story links (with Phase 2/3):** publish the registry's event id per story once Phase 2 meets its
   targets, with an `aliases` map from old story ids (F3).
5. **Hygiene:** `windows-latest` CI job (F7); `constraints.txt` with the versions CI passed (F8); split large
   modules only when touched (F14).

## Rules the front end can rely on (start of docs/PUBLIC-DATA.md)

- All text is plain text (insert as text, never HTML); links are absolute http/https or null.
- Story ids can vanish with a revision (F3): search recovery falls back to the date page, then a headline match.
- A withdrawn date disappears from the index, the search month and its two files in one commit.
- New optional fields can appear at any time; renames/removals bump `schema_version`.
- Often empty: `why_it_matters`, `top_rank` (outside Top Stories), `published_utc`, `compared_with`.
