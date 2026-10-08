# Agent Reach frontend audit and improvement plan

Baseline reviewed October 8, 2026 against `main` at `8161be5` and https://getagentreach.dev/. The focused polish merged in [PR #1](https://github.com/timeitself1-cpu/Agent-Reach-Website/pull/1) at `a2fc699`. The post-merge review and its follow-up are recorded below.

## Architecture and boundaries

This is a dependency-free static site deployed with Cloudflare Workers Assets (`wrangler.jsonc`). Route directories contain HTML shells; `assets/site.js` renders the public pages with DOM APIs and `assets/site.css` supplies the shared design system. About contains static prose. Newsreader and Inter are self-hosted. There is no build step, package manifest, or publishing implementation in this repository. The polish pass added development-only regression checks using Node's test runner and an externally installed jsdom dependency.

The renderer reads the existing `agent_reach.public_index` and `agent_reach.public_edition` v1 documents from `/editions/`. It derives ordered stories in memory. Story URLs use an edition path plus `#story-{id}`. Search loads monthly `/search/YYYY-MM.json` files, six months at a time, with forty results per page. It supports prefix and quoted-phrase matching, section filtering, relevance/date ordering, highlighting, and URL state. RSS, robots, sitemap and edition HTML are committed artifacts.

The fixture is one October 7 edition (revision 2, 44 stories) and one monthly search file. It is sufficient for the main reading journeys, but does not by itself exercise multi-month history or older-edition states. Source content and coverage classifications belong to the publisher; this work evaluates their presentation, not their accuracy.

Preserve JSON and HTML publishing contracts, source grouping, ranking, URLs, RSS discovery and feed, search batching and semantics, categories, revision/date/stale-edition indicators, safe text rendering, self-hosted fonts, and reduced-motion support. No backend, event matching, registry, production timeline, or publishing changes.

## Five highest-impact improvements, in priority order

| Priority | Finding and reader impact | Focused first pass | Acceptance / later work |
| --- | --- | --- | --- |
| **1. Mobile navigation and reflow — complete** | The original navigation hid later section links. Edition details and long publisher text competed for limited width. | Section links wrap with 44px tap targets; the phone/tablet masthead reflows; edition details remain readable; long labels, publisher names, archive text and source timestamps wrap. | All section links visible at 320–640px; no horizontal page overflow; freshness text retained. Verified below. Optional future work: assess navigation with reader feedback before considering a menu. |
| 2. Search clarity and recovery | The search page has no visible submit control or persistent visible field labels. The query and category selector share a narrow capsule. Failed monthly loads are cached and can end in “Nothing found,” conflating unavailable data with zero matches. | Separate and label query/filter controls, retain live search and add submit; expose retry for failed months and distinguish partial/unavailable results from empty results. Preserve query, category, sort, batching and deep links. | Keyboard and touch search, phrase/prefix matching, filters, sorting, empty results and failed-load retry work. Later: date-range controls using the existing index, after archive growth warrants them. |
| 3. Keyboard continuity and status | Every hash change invokes the story router, including `#main` from the skip link. Story-to-story navigation replaces focused nodes without moving focus to the new content. Search forcibly blurs on submit and autofocus can move mobile readers past the heading. Inputs/selects are missing from the shared focus rule. | Route only story hash transitions; focus the new article title after in-page story navigation; make main a focusable skip target; keep search focus on submit, remove forced autofocus, and provide loading/result semantics and visible field focus. | Skip link does not remount content; previous/next and browser history retain correct story content and focus; all controls have visible focus. Later: full assistive-technology audit. |
| 4. Editorial hierarchy and reading comfort | The lead is a large bottom-aligned gradient panel with decorative rings; four-column cards compress headlines and summaries. Some secondary text uses `#5f6775`, too dim on the dark surfaces. | Keep the dark identity and serif headlines, simplify the lead, reduce desktop grid density to three columns, improve paragraph/headline spacing and secondary-text contrast. | Desktop lead and supporting stories remain distinct; summaries are comfortable to scan; mobile story copy stays readable. Later: consider a reader-selected light theme after the core layout is validated. |
| 5. Evidence and edition context | Evidence exists and is detailed, but small source disclosures and implicit metadata make it harder to reach. The source section jumps from the article heading to h3 group labels. Generation time is labelled “made” and is bundled into a long text run. | Give source disclosures larger targets and clearer labels, add a Sources heading and article jump link, use semantic edition/publication times and retain revision, source totals and stale notices. | Independent reports, repeats, signals and external source URLs remain intact; freshness still distinguishes current/archived/stale states. Later: assess concise coverage explanations near cards. Event timelines remain deferred pending Claude’s registry validation. |

## Review sequence

1. Commit this audit and scope before implementation.
2. Commit responsive/editorial CSS and edition/evidence presentation.
3. Commit search recovery and keyboard routing fixes, with regression verification recorded here.

Review the existing fixture on Home, Latest News, all category routes, Archive, Search, dated/current Daily, story detail, About and 404. Check desktop and 320/390/768px layouts, keyboard skip/source/previous-next paths, RSS links, and unchanged published artifacts. Simulate network failure and time-dependent states locally without modifying fixtures. No merge or production deployment is part of this pass.

## Priority #1 — completed October 8, 2026

Finished the mobile navigation and reflow acceptance criteria on the frontend branch:

- All seven existing section links are visible without horizontal scrolling. Navigation wraps at every width and each link has a target at least 44px wide and tall. Active-section indication and link destinations are preserved.
- At phone widths the brand and Search action remain available, including 320px. At 641–880px the edition date occupies its own row above the brand/actions, avoiding the cramped date column at the tablet boundary.
- Edition date, generation time, revision, story/report totals and freshness state remain in the existing wrapping strip.
- Long unbroken publisher names, labels, archive headlines, coverage text and source metadata wrap inside their containers. Section titles and their navigation links can use separate rows. No content is hidden to suppress horizontal overflow.

Validation: 88 browser layout checks across all eleven public page shells at actual viewport widths of 320, 360, 390, 480, 640, 641, 768 and 1440px. Every check passed page reflow, navigation visibility, navigation reflow and minimum navigation target size. All 44 fixture stories also passed a 320px page-overflow check, and each section link was followed at 320px to confirm its destination and current-section indication.

Eighteen additional layout checks covered Home, Latest, Technology, Archive, Search and story detail at 320, 640 and 1440px with long publisher names, source titles, summaries and labels. Expanded source disclosures were included. These checks used a temporary local server that adapted copies of the existing JSON fixture in memory; committed fixtures and schemas were untouched. No page overflow remained. The mobile screenshot and machine-readable measurement reports accompany the audit handoff.

The 11 DOM regression tests and syntax/whitespace checks also pass. PR #1 has since merged, and the deployed mobile implementation passed the post-merge checks below.

## Focused polish pass — completed

Implemented the first-pass work in all five priorities. The visible navigation wraps through tablet widths, and the masthead reflows at 320px. Edition dates, revision and generation time retain their values in separate semantic elements. The simplified lead keeps the serif typography and dark palette; desktop cards use three columns. Source disclosures have larger targets, source titles are visibly linked, and the article has a Sources heading and focusable jump control that preserves its permanent URL.

Search has visible labels, a submit button, responsive field layout and query guidance. Failed monthly requests can be retried without a page reload, partial results are explicitly identified, and zero results have a browse-by-date recovery link. Search still runs locally with the same matching, sorting, highlighting, monthly batching, pagination and URL parameters. Keyboard submission keeps focus. Skip links retain the mounted content and story hash, story transitions focus the new title, and ordinary anchors do not trigger the story router.

### Verification

- `node --check assets/site.js` and `git diff --check`: pass.
- `tests/frontend.cjs`: 11 passing DOM regression tests using the committed JSON fixture. Includes eleven route shells; all 44 stories and their source URLs; complete category/latest lists; source jump and skip behavior; story focus; phrase/prefix/outlet queries; filters/sort/clear/submit; unavailable-month retry; stale and archived notices; safe text rendering; delayed-query races; and load failure recovery.
- Multi-month batching, partial failure and pagination use copies of the existing fixture with dates adapted **in memory**. No fixture files or data contracts were edited.
- Browser layout checks at 320, 390, 768 and 1440px on Home, Search, Archive, Technology, story detail and About. Additional 641px boundary checks after fixing clipped tablet navigation. Final checks found no horizontal page overflow and no clipped section navigation on the tested widths. Desktop and mobile screenshots are included in the handoff.
- Browser keyboard checks: skip to main retains the story; Sources moves focus to evidence without changing its URL; next-story and browser Back focus the correct article title. Browser search section and relevance controls preserve URL state and return expected fixture results.
- `editions/`, monthly search JSON, every existing HTML shell, RSS, sitemap, robots and fonts are unchanged. The frontend polish introduced no runtime dependency, build step or publishing change. A later preview-hosting correction is documented below.

This is a focused browser/DOM review, not a full screen-reader certification or Safari/Firefox/device lab audit. Only one real edition is available; long-history behavior was simulated locally. Production event timelines and the cross-edition registry remain deferred.

### Reproduce the regression checks

Use Node 24 and install the test-only dependency **outside the served repository**. From the repository root in PowerShell:

```powershell
npm install --prefix ../agent-reach-qa --no-audit --no-fund jsdom@30.1.2
$env:NODE_PATH = (Resolve-Path ../agent-reach-qa/node_modules).Path
node --test tests/frontend.cjs
node --check assets/site.js
git diff --check
```

For visual review, run `python -m http.server 8765 --bind 127.0.0.1` from the repository root and visit `http://127.0.0.1:8765/`. The test harness is development-only; it neither runs on the website nor writes data.

## Cloudflare preview check — diagnosed October 8, 2026

The supplied build log identifies a command-line error before deployment: `wrangler preview` in version 4.148.0 rejects `--assets`. Assets are already declared at the top level of `wrangler.jsonc`. The documented preview configuration also requires a `previews` block, so this branch adds `"previews": {}`. Existing production settings, asset directory, 404 handling, and all Daily publishing/data contracts remain unchanged.

In Cloudflare's non-production/preview deploy command setting, replace the failing command with:

```sh
npx wrangler@4.148.0 preview --config wrangler.jsonc --worker-name agent-reach-website
```

The CLI version is pinned to the version shown in the supplied log. This command creates a branch Preview and leaves production deployment to its existing command.

Verified against the installed Wrangler 4.148.0 help and [Cloudflare's preview configuration documentation](https://developers.cloudflare.com/workers/previews/configuration/). After PR #1 merged, Cloudflare reported a successful production build for `a2fc699`. The deployed frontend and JSON/feed content match that merge. The dashboard's saved non-production command was not inspected during the post-merge review; production success does not independently confirm a branch Preview deployment.

## Post-merge review — October 8, 2026

The merge tree matches the reviewed frontend branch. Only shared CSS/JavaScript, this audit, development tests, and the empty Cloudflare preview configuration block changed from the baseline. Edition/search fixtures, existing HTML shells, RSS, sitemap, robots and fonts remain unchanged. No backend or publishing code was added, and production event timelines remain deferred.

The deployed site passed 55 layout checks: all eleven public shells at actual viewport widths of 320, 390, 641, 768 and 1440px. Every check retained seven visible section links with at least 44px targets and no horizontal page overflow. Production JavaScript, CSS, edition index, edition fixture, monthly search fixture and RSS match the merged content after normalizing Windows checkout line endings.

Live search checks confirmed prefix and quoted-phrase matching, Technology filtering, Best match URL state, retained input focus on keyboard submission, and the zero-result archive recovery link. Live article keyboard checks confirmed Sources focus with the permanent story hash intact, skip-to-main without replacing the article, next-story focus, and browser Back restoring the correct article title and focus.

One presentation accuracy correction is prepared on the follow-up branch: the strip now labels `generated_utc` as **Generated**, rather than **Published**. The existing JSON provides generation time, not a separate confirmed publication timestamp. The underlying value, time zone, revision and freshness calculations are unchanged. The regression check now verifies this label; evidence checks also verify exact source URLs within each report/repeat/signal group for all 44 stories.

Priority #1 meets its acceptance criteria. Priorities #2–#5 have their focused first passes complete; their explicitly listed later work remains open. The review does not certify article factual accuracy, assistive-technology compatibility across screen readers, or untested browser/device combinations.
