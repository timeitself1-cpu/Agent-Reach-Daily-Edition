# Taxonomy, headlines and header follow-up

These patches supersede the earlier exports from stale checkouts. They were regenerated from GitHub's advertised default-branch HEADs, fetched and checked again during this task:

| Repository | Default branch advertised by GitHub | Base commit |
| --- | --- | --- |
| Agent-Reach-Daily-Edition | `claude/loving-darwin-a7rqvs` | `072e61c1d7f00e90931dea9a5b2929432608f972` |
| Agent-Reach-Website | `main` | `7b9286e748d5b0c5ff245e850f2bd195aa23d75e` |

The app base includes merged PR #19 and its shared `daily/render.py`, `daily/sections.py`, and `daily/sections.json`. This change extends those existing paths. It does not replace `render_html.py`, add another taxonomy module, or add `sections.json` as a new app file. The publisher already copies the taxonomy to `editions/sections.json` in the same commit as the edition; that mechanism is retained.

Internet Culture retires into Technology at render time. Existing edition JSON remains readable, including editions and embedded website taxonomies that listed Internet Culture separately. Below `AGENT_REACH_MIN_SECTION_STORIES` (default 3), categories fold into one final Also today section; at the threshold they remain independent. Published and offline HTML share the same grouping function. The app's Top Stories section remains, with already-shown cards linked from their categories; category counts match full cards plus those references. Homepage featured previews link to unique full cards under their sections. Original source categories and story IDs are retained.

RSS membership comes from the taxonomy independently of folding. Technology includes the merged Internet Culture stories, and the legacy Internet Culture feed and HTML route remain available. The legacy route reads the merged Technology section. No code or templates were deleted or archived.

`tests/fixtures/taxonomy-2026-10-10.json` selects unchanged stories from the earlier checked-in October 10 edition to reproduce the request's counts. It contains no invented reporting.

| Section | Before | After |
| --- | ---: | ---: |
| World & Nation | 9 | 9 |
| Technology | 2 | 3 |
| Science & AI | 9 | 9 |
| Sports | 3 | 3 |
| Entertainment | 1 | — |
| Internet Culture | 1 | — |
| Also today | — | 1 |

Headline normalization extends the ordinary-words list with generic headline usages. The four exact requested transformations are golden cases; their empty summaries are explicitly quarantined so these style fixtures cannot imply reporting. Existing golden expectations are unchanged. Acronyms, mixed case, quotes, allowlisted words, story names and uncertain names retain their prior handling.

The website header has Today, Latest, Archive and About. Its single status row contains date, update, story count, relative generation time and Details. Details retains the diff, dropped-story explanations and source health. Folded category pages remain reachable through View all links in Also today. The latest river retains its separate flat renderer. Existing evidence, disclosures, issue-report links, static HTML and reader-timezone controls remain.

Verify from the app repository with `requirements-dev.txt` installed:

```sh
python -m pytest
python -m pyflakes agent_reach tests
python -c "from agent_reach.daily.golden import run_golden; r=run_golden(); print(r.summary()); assert r.ok"
```

Focused checks: `python -m pytest tests/test_render.py tests/test_taxonomy.py tests/test_headline_followup.py tests/test_gates.py`.

Verify from the website repository:

```sh
npm ci
npm test
npm run build
npm run check:built
npm run test:browser
```

Where Chromium is installed by the operating system, use `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm run test:browser`. Otherwise install it with `npx playwright install chromium`. Mobile screenshots are written to `test-results/home-360-enhanced-closed.png` and `test-results/home-360-static-closed.png`.

Each exported patch includes its base SHA in the header. From a clean checkout of that exact repository base, run `git apply --check /path/to/app.patch` or `git apply --check /path/to/website.patch`, then apply with `git apply`. The export includes all modified files and new tests, fixtures and this notes file. Neither patch was pushed, merged or used to create a PR.
