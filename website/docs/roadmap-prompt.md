You are implementing Phases 1 and 2 of the Agent Reach improvement roadmap. The work spans two repositories. Do every item listed for each repository you have access to. If you can only reach one, finish that one completely and list the other repository's items as not done.

- **Website:** `timeitself1-cpu/Agent-Reach-Website`. A static news site (getagentreach.dev) built by `scripts/build.cjs` and deployed on Cloudflare Workers Assets. The UI is `assets/site.js` and `assets/site.css`. It has no runtime dependencies.
- **App (publisher):** `timeitself1-cpu/Agent-Reach-Daily-Edition`. A Windows Python app that collects news, groups reports into stories with Ollama (`llama3.1:8b` for summaries, `nomic-embed-text` for grouping) and publishes `editions/*.json`, `editions/index.json`, `search/YYYY-MM.json`, dated HTML shells, `feed.xml` and `sitemap.xml` to the website repo.

Read `docs/roadmap.md`, `docs/backend-coordination.md` and `README.md` in the website repo before starting.

## Evidence (October 8, 2026 edition, revision 6, website commit `6bba45e`)

- **Same outlet counted twice.** Story `0317f2df6bc9` (rank 1) has `coverage.publishers` = AP News, BBC News, DW, PBS NewsHour, Reuters, Tom's Hardware, Wired, apnews.com, reuters.com. It reports `independent_reports: 9`; the true count is 7. Crew-12 lists `NASA` and `NASA (.gov)`. Outlets named by bare domain: apnews.com, reuters.com, cnbc.com, github.com, twitter.com, sheets.works, mathstodon.xyz.
- **Counts disagree on the site.** The lead byline reads "apnews.com, AP News +4". The story page says "Read 8 sources". The coverage panel says "9 independent outlets".
- **One event published as two stories.** "Trump Promises Not to Resume Iran Strikes Before Midterm Elections" (top 4) and "Trump Says US Will Not Strike Iran Before Midterms" (News 5, NYT only). The app logged "15 merges blocked".
- **Summary errors.**
  - Crew-12 says "Four astronauts and a cosmonaut"; the sources say three astronauts and one cosmonaut.
  - Paris protests says "with 6,059 arrests made"; Le Monde's figure is France-wide for Sept 28 to Oct 5.
  - Headline "Trump Misnames Michigan Senate Nominee" doesn't match its summary, which says Trump called the nominee a "terrorist sympathizer".
  - "The People Holding up the Internet" has a summary with no subject: "Teaches computer science at UCLA…".
  - A summary lost its opening quote: `Math 1.0"`.
  - "P.T. Has" is wrongly capitalised.
- **Padding.** 38 of 54 stories (70%) are single-source. Fillers include game and film trailers (Warhammer 40,000: Dawn of War 4, 'Heathens'), an NFL mock draft, a First Take debate, "Dak Prescott Breaks Down a Play", a Wired podcast episode and a Fireship YouTube video.
- **Churn.** Revisions 3–6 were published within 61 minutes. Revision 5 → 6, 14 minutes apart: 21 new, 3 updated, 2 fading, 19 no longer listed, out of 54. Story IDs change with every revision.
- **Google News redirects.** 21 of 100 source URLs are `news.google.com/rss/articles/…`. The About page promises "Links to sources take you to the publishers' own sites."
- **Raw errors in the export.** The app's HTML export shows `embeddinggemma-2:270m: ResponseError: model "embeddinggemma-2:270m" not found, try pulling it first (status code: 404)`.
- **Section naming.** The data category is `News`. Home calls it "World & Nation"; the nav, page title and h1 call it "World" (`assets/site.js` lines 12–15).
- **Long phone home page.** Home is 18,469px tall at 390px wide. The nav links only 3 of the 6 sections.
- **Accessibility leftovers.** axe reports `region` (the skip link is outside a landmark) on most views and `landmark-complementary-is-top-level` on story pages (`aside` inside `main`, in `renderStory`).
- **Other leftovers.**
  - A missing date says "This edition was taken off the site" (in `start()`).
  - `stamp()` has no year or time zone, and is used in `sourceList()`.
  - Relative times ("19 min ago") never refresh.
  - Loading a shared `#story-` link draws the focus outline around the h1.

## Rules for both repositories

- Keep the public JSON contract (schema_version 1). Only add new **optional** fields, and document them in the website's `docs/backend-coordination.md`.
- Keep every URL working: `/daily/YYYY-MM-DD/#story-<id>`, the `headline` hint, the section paths `/world/`, `/technology/` and `/science/`, the feed and the sitemap.
- Insert all story text as plain text (textContent), never as HTML.
- Add no runtime dependencies, analytics, trackers or third-party requests.
- Self-hosted fonts and reduced-motion support stay.
- The website must not edit files the app writes: `editions/`, `search/`, `daily/YYYY-MM-DD/index.html`, `feed.xml`, `sitemap.xml`.
- Website tests stay hermetic: use `tests/fixtures/`, never the live `editions/`. Add fixtures for any new case.

## Part 1: Website repository

Use Node 24. Before you finish, all of these must pass: `npm ci`, `node --check assets/site.js`, `npm test`, `npm run check:editions` and `npm run build`. Add or extend tests in `tests/frontend.cjs` and `tests/editions.cjs` for each item.

1. **Data warnings (non-blocking).** In `scripts/check-editions.cjs`, collect warnings without failing the build, and print them as `console.warn` lines prefixed `WARN`. Export the warnings for tests. Warn on:
   - a story whose `coverage.publishers` has two entries for one outlet after normalisation (see item 3);
   - any source URL on `news.google.com`;
   - two stories in one edition with matching headlines: Jaccard similarity of 0.4 or more over lowercase content words. Strip punctuation, drop stop words (a, an, the, of, to, in, on, for, and, or, with, at, by, from, as, is, are, was, be, not, before, after, says, said, us, new), and remove a trailing "s" from each word. On revision 6 this scores the Iran pair 0.50; the next-closest pair scores 0.20.

   Revision 6 must produce warnings for story 1, the Crew-12 story, the Iran pair and the 21 Google News URLs.
2. **One section name.** Use "World & Nation" for the `News` category everywhere: nav label, page `title`, h1, home band and search filter. Update the static `world/index.html` shell's `<title>` and meta too. Keep the `/world/` path.
3. **Show each outlet once, and make the counts agree.** Add a `normOutlet(name)` helper:
   - lowercase the name;
   - strip a leading `www.`, a trailing ` (.gov)` and similar suffixes, and the top-level domain;
   - remove spaces and punctuation;
   - apply a small alias map: apnews → AP News, reuters → Reuters, cnbc → CNBC, twitter or x → X, nytimes → The New York Times, and so on.

   When two names normalise to the same key, show the human-readable one (not the domain). Use it in `outlets()` (bylines), `coveragePanel()` and `sourcesBlock()`. Derive the byline's "+N" from the same deduplicated list. Never show an independent-outlet count higher than the deduplicated publisher list.

   Label the two numbers as different things: "8 source links" and "7 independent outlets".
4. **Accessibility and wording leftovers.**
   - Place the skip link inside a landmark: the header, or its own `nav`.
   - Turn the story page's `aside` into a `section` with a heading.
   - Change the missing-date message to "This edition isn't available. It may have been withdrawn.", keeping the archive link. Apply the same wording in `404.html` if it is there.
   - Make `stamp()` include the year when it isn't the current year, plus `timeZoneName: 'short'`.
   - Refresh relative times every 60 seconds while the page is visible: store the ISO time in `datetime` and re-render `time` text; pause on `visibilitychange`.
   - Move focus to the story headline only after in-app navigation (previous/next, history), not on the first page load. No focus outline should show on a direct load.

   axe-core 4.10 must report 0 `region` and 0 `landmark-complementary-is-top-level` violations.
5. **"Since update N" summary.** In the edition strip's Details disclosure, when `compared_with` exists, show "Compared with update {revision}: X new · Y updated", counted from `story.change`.

   If the optional `changes` field from Part 2 is present, also show "Z no longer listed" with a list of those headlines. Each one links to `/search/?q="<headline>"` so readers can find it in earlier revisions. Render nothing extra when the field is absent.
6. **Section shortcuts on Home and Daily.** Under the edition strip, add a wrapping row of chips, one per entry in `ed.sections`, each showing its label and count, for example "Sports 10". Each chip links to an `id` on its section band.
   - Tap targets are at least 44px tall.
   - No horizontal page overflow at 320px.
   - The chips are keyboard reachable, with visible focus.
   - The chips are also in the static built HTML, so they work without JavaScript.
7. **Live-site check after deploy.**
   - Add `scripts/live-check.cjs`, using Node's built-in `fetch` only. It polls `https://getagentreach.dev/editions/index.json` for up to 10 minutes, until the latest date's revision matches the repository's `editions/index.json`.
   - It then asserts that `/` sends these headers: Content-Security-Policy, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy and Strict-Transport-Security.
   - It also asserts that `/docs/roadmap.md`, `/tests/frontend.cjs`, `/wrangler.jsonc` and `/package.json` each return 404.
   - Add `.github/workflows/live-check.yml`, triggered by `push` to `main` and by `workflow_dispatch`. A failure must name the missing header or the exposed path.

Afterwards, update the item statuses in `docs/roadmap.md`, and record the `changes` field in `docs/backend-coordination.md`.

## Part 2: App repository

Follow the repository's own test and lint setup, and add tests for each item. Re-run the October 8 inputs if they are stored; otherwise use recorded fixtures.

1. **Normalise outlets before counting independence.** Use the registrable domain for URLs, plus an alias map (apnews.com → AP News, reuters.com → Reuters, `NASA (.gov)` → NASA, and so on). Count `independent_reports` and `publishers` on the normalised name, and publish the readable name. Done when story 1 above reports 7 and no story lists one outlet twice.
2. **Resolve Google News redirects** to the publisher's URL when fetching, with a timeout and a cache. If a link can't be resolved, keep it but set `via` to "Google News". Done when no edition contains an unlabelled `news.google.com` URL.
3. **Fix the grouping fallback.** Install `embeddinggemma-2:270m` during setup, or remove it as a fallback. In the HTML export, move run diagnostics (source health, grouping, errors) into a collapsed "Run details" section. No raw exception text should show in the reader-facing part.
4. **Stricter summary checks.** Run these before publishing:
   - every number, and every named person or organisation, in a summary must appear in at least one cited source's title or excerpt, in the same sentence context;
   - the headline's key entities must appear in the summary;
   - reject sentences without a subject;
   - repair unbalanced quotes;
   - fix title case after abbreviations ("P.T. has").

   When a check fails, regenerate once. If it still fails, fall back to the best source title plus an extractive first sentence. Done when every summary error in the evidence above is caught.
5. **A minimum bar for including a story.**
   - Sections may hold fewer than 10 stories.
   - A single-source story needs a strong signal or a news-type source to qualify.
   - Exclude trailers, podcasts, mock drafts, debate-show clips and video explainers unless they have a second independent source.

   Target: under 50% single-source stories on a typical day.
6. **Stricter merging of same-event stories.** Re-check blocked merges: merge stories with the same actor, the same claim or action, the same day, and high title overlap. Keep multi-topic video roundups out of single stories. Done when the Iran pair becomes one story.
7. **Calmer revisions.**
   - Leave at least 60 minutes between same-day revisions, unless a new story reaches Strong coverage and top-3 rank.
   - Add hysteresis: keep a listed story unless a replacement scores at least 20% higher.
   - Publish the optional edition field: `changes: {"compared_with": {"edition_date", "revision"}, "new": [id], "updated": [id], "fading": [id], "dropped": [{"headline", "category"}]}`.

   Target: under 25% of stories dropped between same-day revisions.

## Out of scope

Category rules, per-section data embeds, stable story IDs, per-story pages, previews and RSS items, a strong-coverage filter, and a light theme. These are Phase 3. Don't start them.

## Deliverables

- One pull request per repository, each with small, reviewable commits.
- In each pull request description: a checklist of the items above (done, or not done and why), the commands you ran with their pass/fail output, and before/after numbers for the lead story's outlet count and for page height at 390px.
- Don't merge the pull requests, and don't change deployment settings.
