> **Status, October 9, 2026:** items 1, 2, 3, 6 and 7 were done directly (see "Round 3" in `roadmap.md`), and headlines
> now open the publisher's article. Still open from this prompt: item 4's per-page embeds and render skipping,
> item 5 (strong-coverage filter) and item 8 (UI checks in CI).

You are improving the frontend of Agent Reach Daily (https://getagentreach.dev), in the repository `timeitself1-cpu/Agent-Reach-Website`. It is a static news site with no runtime dependencies:

- `scripts/build.cjs` pre-renders the HTML shells with jsdom and embeds the edition JSON in each page.
- `assets/site.js` renders the UI with a small `h()` DOM helper.
- `assets/site.css` holds the styles. The site is dark-only today.
- `_headers` sets a strict CSP: `script-src 'self'`, so inline scripts are blocked.
- Cloudflare Workers Assets serves `dist/`.

A separate Windows app publishes the news data into this repository.

Read `README.md`, `docs/roadmap.md`, `docs/frontend-audit-round-2.md` and `docs/backend-coordination.md` before starting. Phases 1 and 2 of the roadmap are merged. This round is about how the site reads and performs, mostly on phones.

## Evidence (main at `834d5b4`, October 8 edition revision 6, Chromium 390×844 unless noted)

- **Home is 22 phone screens long.** It is 18,674px tall, with 55 story cards and 50 source disclosures.
  - At 640px and below, `site.css` removes the summary line clamp (`.card .dek{-webkit-line-clamp:unset}`), so every card shows its full summary.
  - Each band shows 5 full cards; some bands are about 2,100px tall.
  - Latest is 20,788px tall.
- **The top story starts low.** The masthead, a nav that wraps onto 2 rows, the edition line and 3 rows of section chips come first. The first headline starts at y=534px.
- **Story pages start low too.** The h1 starts at 323px, because the edition strip and breadcrumb are two separate rows. Round 2 set a target of 260px or less, which hasn't been met.
- **Three sections have no page.** Sports (10 stories), Entertainment (10) and Internet Culture (4) are reachable only through Home bands, Latest or search. The nav lists 3 of the 6 sections.
- **Home has a lot of main-thread work.** Under simulated slow 4G with 4× CPU slowdown:
  - Home: FCP and LCP 1,268ms; total blocking time 455ms; 1,288 DOM nodes; 412KB transferred uncompressed.
  - Each page embeds the whole edition. `dist/index.html` is 155KB and `dist/world/index.html` is 89KB, although World shows only 10 stories.
  - On load, the client re-renders the pre-rendered markup (`mount()` calls `replaceChildren`).
  - Search shows a layout shift (CLS) of 0.061.
- **Accessibility.**
  - axe-core 4.10 reports 1 moderate `landmark-unique` violation on Home. The other routes are clean.
  - Some visible targets are under 44px: `.band-link`, `.readmore` and the skip link.
- **Other gaps.**
  - There is no light theme.
  - There is no way to see only well-covered stories, though coverage counts are now reliable.
  - There is no automated check of page height, layout or accessibility budgets, so these regressions go unnoticed.

## Rules

- Keep the public JSON contract (schema_version 1). Don't edit files the app writes: `editions/`, `search/`, `daily/YYYY-MM-DD/index.html`, `feed.xml`, `sitemap.xml`.
- Keep every URL working: `/daily/YYYY-MM-DD/#story-<id>`, the `headline` hint, `/world/`, `/technology/`, `/science/`, `/latest/`, `/archive/`, `/search/`, `/about/`.
- Insert all story text as plain text (`textContent`), never as HTML.
- No runtime dependencies, frameworks, analytics, trackers, third-party requests or inline scripts (the CSP must stay as it is). Dev dependencies for tests are fine.
- Keep the self-hosted fonts, reduced-motion support, the print stylesheet, `og:` and Twitter metadata, and the no-JavaScript content the build pre-renders.
- Tests stay hermetic: they read only `tests/fixtures/`. `tests/fixtures/roadmap-2026-10-08.json` is the revision 6 edition.
- Use Node 24. Before you finish, all of these must pass: `npm ci`, `node --check assets/site.js`, `npm test`, `npm run check:editions`, `npm run build` and the new UI check from item 8.

## Work items, in priority order

1. **A shorter, faster-to-scan Home and Latest on phones (≤640px).**
   - Put the nav on one row that scrolls sideways inside itself, with the active item scrolled into view and a fade at the cut-off edge. The page itself must not scroll sideways.
   - Turn the section chips into a single row in the same style, or merge them into the nav. Either way, keep 44px targets and keep them working without JavaScript.
   - In section bands, show compact items: headline, outlet byline and coverage meter, with the summary clamped to 2 lines. Drop the per-card source disclosure from band cards; the story page already has the sources.
   - Show the first 3 items per band, then a "Show all N" control. Use `<details>` or plain links so every story stays reachable without JavaScript.
   - Keep the lead and the top-stories rail as they are.
   - On Latest, use the same compact item style.
   - Done when:
     - Home is no more than 8,000px tall at 390px;
     - the lead headline starts at 320px or less;
     - Latest is no more than 9,000px tall;
     - all 54 stories are still linked from Home, with or without JavaScript;
     - no page scrolls sideways at 320px.
2. **A compact story header.**
   - On story pages, merge the edition strip and breadcrumb into one line, such as "Oct 8 · Update 6 · Technology · Top story 1 of 10 · Latest". Keep the Details disclosure.
   - Keep the stale and archived notices unchanged.
   - Done when the h1 starts at 240px or less at 390px, and the edition date, revision, latest/archived state and section are all still visible.
3. **Pages for every section.**
   - Add `/sports/`, `/entertainment/` and `/internet-culture/` shells. Generate them from the existing section shell in `build.cjs`, with title, description, canonical and `og:` tags.
   - The nav lists all six sections. On phones it uses the scrolling row from item 1.
   - Point the "All …" band links at the new pages.
   - The sitemap belongs to the app. Add a request to `docs/backend-coordination.md` asking it to list the three new paths.
4. **Less work on load.**
   - Each section page embeds only its own stories plus the fields the masthead and edition strip need (roadmap item B7). The home and daily pages keep the full edition.
   - When the pre-rendered markup already matches the embedded edition, don't rebuild the page: attach behaviour to the existing nodes. Alternatively, render only what is above the fold first and build the rest in an idle callback. Either way, focus handling, `#story-` routing and the headline hint must keep working.
   - Add `content-visibility: auto` with a sensible `contain-intrinsic-size` to bands below the fold.
   - Reserve the search status line's height so the layout doesn't shift.
   - Done when, under slow 4G (150ms latency, 1.6Mbps) with 4× CPU slowdown:
     - Home's total blocking time is 150ms or less, and LCP is no worse than 1,268ms;
     - `dist/world/index.html` is 50KB or less;
     - search CLS is 0.01 or less.
5. **A "Strong coverage only" filter.**
   - Add a toggle on Home, Latest and the section pages, plus a matching filter on Search.
   - The state lives in the URL (`?coverage=strong`) so it can be shared.
   - Show how many stories match, and show a clear empty state with a link to switch the filter off.
   - Without JavaScript the toggle may be missing, but the page must still work.
6. **A light theme.**
   - Follow `prefers-color-scheme` by default. Add an Auto/Light/Dark control in the masthead or footer.
   - Store the choice in `localStorage`, wrapping reads and writes in try/catch.
   - Apply it before the first paint with a tiny external `assets/theme.js` loaded in `<head>`, because inline scripts are blocked by the CSP. There must be no flash of the wrong theme.
   - Define all colours as tokens.
   - Done when every text and UI colour pair measures at least 4.5:1 (3:1 for large text and UI parts) in both themes, and print output is unchanged.
7. **Accessibility clean-up.**
   - Fix `landmark-unique` on Home.
   - Make `.band-link`, `.readmore` and the skip link at least 44px tall, without making the layout look heavier.
   - Done when axe-core 4.10 (WCAG 2.0/2.1/2.2 A and AA plus best-practice) reports 0 violations of any impact on every route, at 390 and 1440px, in both themes. Keyboard order and visible focus must still work for the scrolling nav, the "Show all" controls, the filter and the theme control.
8. **Automated UI checks in CI.**
   - Add `scripts/ui-check.cjs`, using Playwright as a dev dependency, and run it in `.github/workflows/ci.yml`.
   - It builds the site from `tests/fixtures/` (add a root option to `build.cjs` if needed), serves `dist/` locally and visits every route at 320, 390 and 1440px.
   - It asserts the budgets above: page heights, h1 and lead positions, no sideways scrolling, 0 axe violations, no console errors, and that no-JS Home links every story.
   - A failure names the route, the width and the measured value.

## Out of scope

- Per-story pages, per-story `og:` metadata and per-story RSS items. These wait on stable story IDs from the app.
- Changes to the app repository.
- A redesign of the lead or the brand.
- Images in cards.
- New routes beyond the three section pages.
- Analytics.

## Deliverables

- One pull request against `main`, with small commits (roughly one per item). Don't merge it, and don't change deployment settings.
- The pull request description must include:
  - a checklist of items 1–8, each marked done, or not done with the reason;
  - every command you ran, with its pass/fail result;
  - a before/after table for the numbers above (Home and Latest height, lead and h1 positions, TBT, LCP, CLS, World HTML size, axe counts), measured the same way both times;
  - 390px screenshots of Home and a story page, in both themes.
- Update `docs/roadmap.md`: mark the Phase 3 items this completes (per-page embeds, the strong-coverage filter, the light theme), and add a short section recording this round.
