# Agent Reach frontend audit and improvement plan

Reviewed October 8, 2026 against `main` at `8161be5` and https://getagentreach.dev/.

## Architecture and boundaries

This is a dependency-free static site deployed with Cloudflare Workers Assets (`wrangler.jsonc`). Route directories contain HTML shells; `assets/site.js` renders the public pages with DOM APIs and `assets/site.css` supplies the shared design system. About contains static prose. Newsreader and Inter are self-hosted. There is no build step, package manifest, test runner, or publishing implementation in this repository.

The renderer reads the existing `agent_reach.public_index` and `agent_reach.public_edition` v1 documents from `/editions/`. It derives ordered stories in memory. Story URLs use an edition path plus `#story-{id}`. Search loads monthly `/search/YYYY-MM.json` files, six months at a time, with forty results per page. It supports prefix and quoted-phrase matching, section filtering, relevance/date ordering, highlighting, and URL state. RSS, robots, sitemap and edition HTML are committed artifacts.

The fixture is one October 7 edition (revision 2, 44 stories) and one monthly search file. It is sufficient for the main reading journeys, but does not by itself exercise multi-month history or older-edition states. Source content and coverage classifications belong to the publisher; this work evaluates their presentation, not their accuracy.

Preserve JSON and HTML publishing contracts, source grouping, ranking, URLs, RSS discovery and feed, search batching and semantics, categories, revision/date/stale-edition indicators, safe text rendering, self-hosted fonts, and reduced-motion support. No backend, event matching, registry, production timeline, or publishing changes.

## Five highest-impact improvements, in priority order

| Priority | Finding and reader impact | Focused first pass | Acceptance / later work |
| --- | --- | --- | --- |
| 1. Mobile navigation and reflow | Section links live in a horizontally clipped bar with its scrollbar hidden. Later sections and Archive are easy to miss. The date/status strip, long outlet names and source timestamps compete for limited width. | Wrap the existing section links on small screens; use generous tap targets; group edition status/date/update details into wrapping elements; allow long text to reflow. | All section links visible at 320–640px, no horizontal page overflow, freshness text retained. Later: assess navigation with reader feedback before adding a menu. |
| 2. Search clarity and recovery | The search page has no visible submit control or persistent visible field labels. The query and category selector share a narrow capsule. Failed monthly loads are cached and can end in “Nothing found,” conflating unavailable data with zero matches. | Separate and label query/filter controls, retain live search and add submit; expose retry for failed months and distinguish partial/unavailable results from empty results. Preserve query, category, sort, batching and deep links. | Keyboard and touch search, phrase/prefix matching, filters, sorting, empty results and failed-load retry work. Later: date-range controls using the existing index, after archive growth warrants them. |
| 3. Keyboard continuity and status | Every hash change invokes the story router, including `#main` from the skip link. Story-to-story navigation replaces focused nodes without moving focus to the new content. Search forcibly blurs on submit and autofocus can move mobile readers past the heading. Inputs/selects are missing from the shared focus rule. | Route only story hash transitions; focus the new article title after in-page story navigation; make main a focusable skip target; keep search focus on submit, remove forced autofocus, and provide loading/result semantics and visible field focus. | Skip link does not remount content; previous/next and browser history retain correct story content and focus; all controls have visible focus. Later: full assistive-technology audit. |
| 4. Editorial hierarchy and reading comfort | The lead is a large bottom-aligned gradient panel with decorative rings; four-column cards compress headlines and summaries. Some secondary text uses `#5f6775`, too dim on the dark surfaces. | Keep the dark identity and serif headlines, simplify the lead, reduce desktop grid density to three columns, improve paragraph/headline spacing and secondary-text contrast. | Desktop lead and supporting stories remain distinct; summaries are comfortable to scan; mobile story copy stays readable. Later: consider a reader-selected light theme after the core layout is validated. |
| 5. Evidence and edition context | Evidence exists and is detailed, but small source disclosures and implicit metadata make it harder to reach. The source section jumps from the article heading to h3 group labels. Generation time is labelled “made” and is bundled into a long text run. | Give source disclosures larger targets and clearer labels, add a Sources heading and article jump link, use semantic edition/publication times and retain revision, source totals and stale notices. | Independent reports, repeats, signals and external source URLs remain intact; freshness still distinguishes current/archived/stale states. Later: assess concise coverage explanations near cards. Event timelines remain deferred pending Claude’s registry validation. |

## Review sequence

1. Commit this audit and scope before implementation.
2. Commit responsive/editorial CSS and edition/evidence presentation.
3. Commit search recovery and keyboard routing fixes, with regression verification recorded here.

Review the existing fixture on Home, Latest News, all category routes, Archive, Search, dated/current Daily, story detail, About and 404. Check desktop and 320/390/768px layouts, keyboard skip/source/previous-next paths, RSS links, and unchanged published artifacts. Simulate network failure and time-dependent states locally without modifying fixtures. No merge or production deployment is part of this pass.
