# Agent Reach improvement and fix roadmap — October 8, 2026

Reviewed against `main` at `6bba45e`: the October 8 edition, **revision 6** (54 stories, generated 21:49 UTC). This roadmap follows [frontend-audit.md](frontend-audit.md) and [frontend-audit-round-2.md](frontend-audit-round-2.md). It also compares the website with the Windows app's own HTML export of the same edition (`AgentReachDaily-2026-10-08.html`, revision 6, 4:49 PM CDT).

## How this was checked, and its limits

- **Live site.** https://getagentreach.dev/ could not be reached from the review environment: its network policy denied the host. Cloudflare builds from `main`, and `main` holds revision 6, the same revision as the export. So this review built `main` (`npm run build`) and served `dist/`. Anything that depends on the live host is marked **verify live**.
- **Repository checks.** `npm test` passes all 36 tests. `npm run check:editions` validates both published editions. The build succeeds.
- **Browser.** Chromium (Playwright 1.56) at 390 and 1440px covered Home, Daily, Latest, World, Technology, Science & AI, Archive, Search (`?q=iran`), About, a story page and the October 7 edition. axe-core 4.10 ran with the WCAG A/AA and best-practice rules. Load timing used simulated slow 4G (150ms latency, 1.6Mbps down).
- **Data.** The published `editions/2026-10-08.json` was analysed directly: outlets, coverage counts, source URLs and categories.

## Where things stand

The round 2 plan worked:

- Tests no longer break on publish.
- Pages render before JavaScript runs.
- Sports and Entertainment expand to all 10 stories.
- Sharing, print and security headers are in place.
- On slow 4G the first Home paint now arrives at about **1.1s**, compared with 2.1s in round 2.
- No route overflows horizontally at either width, and the browser logged no script errors.
- axe reports no critical or serious issues.

The biggest problems are now **in the content, not the page**. Coverage counts are inflated. Some events appear twice. Some AI summaries contain factual slips. Sections are padded with low-value items. Revisions change the edition faster than a reader can follow. Most of these belong to the publisher (the Windows app), but the website can guard against some of them and make the rest visible.

## Findings

### A. Publisher and data findings (the Windows app)

| # | Finding | Evidence (revision 6) | Impact |
| --- | --- | --- | --- |
| A1 | **The same outlet is counted twice as "independent".** | Top story 1 lists `AP News` and `apnews.com`, and `Reuters` and `reuters.com`, giving "9 independent reports"; the true count is 7. Crew-12 lists `NASA` and `NASA (.gov)`. Seven outlets appear only as bare domains: apnews.com, reuters.com, cnbc.com, github.com, twitter.com, sheets.works, mathstodon.xyz. | Inflates the strength figure that the site's coverage method relies on. This is the core trust signal. |
| A2 | **One event appears as two stories.** | Top story 4, "Trump Promises Not to Resume Iran Strikes Before Midterm Elections", and News 5, "Trump Says US Will Not Strike Iran Before Midterms" (NYT). A search for `iran` returns both side by side. Story 4 also cites a Reuters video that covers the Microsoft story. The export records "15 merges blocked". | Duplicates make the edition look careless and split the coverage count. |
| A3 | **AI summaries contain factual slips**, even though About says every sentence is checked against the sources. | Crew-12: "Four astronauts and a cosmonaut". The sources say three astronauts and one cosmonaut (four people). Paris protests: "with 6,059 arrests made". Le Monde's figure covers Sept 28 to Oct 5 across France, not this protest. "Trump Misnames Michigan Senate Nominee": the headline does not match the summary. "The People Holding up the Internet": the summary has no subject ("Teaches computer science at UCLA…"). Also `Math 1.0"` has a lost opening quote, "P.T. Has" is wrongly capitalised, and "Israel Promotes Film Miming NAZA Documentary" is garbled. | Factual errors on a site whose whole promise is "check the sources". |
| A4 | **Sections are padded to 10 with low-value items.** | 38 of 54 stories (70%) are single-source "Limited". Fillers include a Warhammer trailer, the 'Heathens' trailer, a First Take debate, "Dak Prescott Breaks Down a Play", an NFL mock draft, a podcast episode (Wired, "Uncanny Valley") and a YouTube explainer (Fireship). Internet Culture already ships with 4 stories, so a short section works. | Dilutes the edition. These items also lead Latest News (positions 2–4 are a lawsuit, SpaceX and a trailer). |
| A5 | **Revisions churn faster than readers can follow.** | Six revisions were published on Oct 8, four of them within 61 minutes (15:48–16:49 CDT). From revision 5 to revision 6 (14 minutes apart): 21 new stories, 19 no longer listed, out of 54. Story IDs change with each revision. | A story a reader saw 15 minutes ago can vanish without explanation. Shared links rely on headline recovery. |
| A6 | **21 of 100 source links are Google News redirects** (`news.google.com/rss/articles/…`). | All 21 come through the "Google News" channel. | Contradicts About › Privacy: "Links to sources take you to the publishers' own sites." Readers are routed through Google. |
| A7 | **Questionable categories.** | The SpaceX spectrum purchase (a telecoms business story) is in Science & AI. The green-card suspension (immigration policy) leads as Technology. | Readers browsing a section miss stories, or find surprising ones. |
| A8 | **"Updated" can make a headline worse.** | "Microsoft's New Surface Laptop Ultra Finally Has a Starting Price" became "Magnetic USB-C Port Introduced". Its newest report is 24 hours old. | The headline lost who and what. |
| A9 | **App export only: diagnostics and scrape debris reach readers.** | The footer prints `embeddinggemma-2:270m … ResponseError: model "embeddinggemma-2:270m" not found, try pulling it first (status code: 404)`. Excerpts include NBC page chrome ("05:12 \| Now Playing…"), a Techmeme ad ("Protecting your Cloud Applications Data…") and "The and its more than 4,500 sailors" (a dropped italic word). Reddit was partial (403/429). | The fallback grouping model is not installed, so grouping has no fallback. Debris reads as broken. |

### B. Website findings

| # | Finding | Evidence | Impact |
| --- | --- | --- | --- |
| B1 | **The same section has three names.** | The data category is `News`. The home band is "World & Nation". The nav, page title and h1 say "World". `/world/` holds mostly US stories: the USS Lincoln, Hurricane Isaias, the Arizona candidate, the Cornell case and Hegseth. | The section label misleads readers. |
| B2 | **Bylines show duplicate outlets, and the counts disagree.** | Lead byline: "apnews.com, AP News +4". The story page says "Read 8 sources". The coverage panel says "9 independent outlets", listing both AP spellings. | Three different numbers for one story. The root fix is A1, but the site can present them consistently. |
| B3 | **No "what changed" context.** | The export shows "21 new, 3 updated, 2 fading, 19 no longer listed", "Fading" with signal deltas, and coverage notes (for example "4 repeats left out"). The site shows only per-card New/Updated badges, although `compared_with` is already in the JSON. | Readers can't tell why a story disappeared or how this update differs. This matters more given A5. |
| B4 | **Mobile Home is very long, with no way to jump.** | At 390px Home is **18,469px** tall (54 cards). The nav links three sections. The export's section chips with counts ("Sports (10)") have no equivalent on the site. | Sports, Entertainment and Internet Culture are reachable only by long scrolling. |
| B5 | **Round 2 minor items are still open.** | axe `region` (the skip link is outside a landmark) on 6 of 7 views at both widths, and `landmark-complementary-is-top-level` on story pages (`aside` inside `main`, `site.js:390`). Missing dates still say "This edition was taken off the site" (`site.js:685`, `site.js:710`). The source times in card disclosures use `stamp()`, which shows no year or zone (`site.js:48`, `site.js:129`). "N min ago" never refreshes. | Small, known, and cheap to close. |
| B6 | **A focus box sits on the headline when a shared story link loads.** | Opening `/daily/…/#story-…` directly draws the 2px accent outline around the h1 (`[tabindex="-1"]:focus-visible`, `site.css:23`). | It looks like a bug to pointer users arriving from a share. Keep the focus move for in-page navigation. |
| B7 | **Every news page carries the whole edition twice.** | Each page has rendered HTML plus the embedded JSON. Home is 152KB (42KB gzipped). `/world/` is 89KB for 10 stories. | Fine today. The size grows with the edition, and section pages pay for stories they don't show. |
| B8 | **Post-deploy checks aren't automated (verify live).** | The README asks for a manual live check of headers and of 404s on `/docs/`, `/tests/` and `/wrangler.jsonc`. No record of that check exists, and both reviews were blocked from the host. | A regression in headers or the asset allowlist would go unnoticed. |

## Roadmap

Owner: **P** = publisher (Windows app), **W** = website (this repository). Sizes: S ≈ under a day, M ≈ 1–3 days, L ≈ a week or more.

### Phase 1 — Trust fixes (this week)

| Item | Owner | Size | Acceptance | Status |
| --- | --- | --- | --- | --- |
| Normalise outlets before counting (A1): map domains and aliases to one outlet (`apnews.com` → AP News, `NASA (.gov)` → NASA), then count independence on the normalised name. | P | S | No story's `coverage.publishers` contains two names for one outlet. Story 1 reports 7, not 9. | Implemented in the companion publisher PR; October 8 recorded tests pass. |
| Resolve Google News redirects to the publisher URL at fetch time (A6). If a link can't be resolved, keep it but label it "via Google News". | P | S–M | 0 `news.google.com` URLs in a published edition, or each one labelled. About › Privacy is accurate. | Implemented in the companion publisher PR; October 8 recorded tests pass. |
| Install `embeddinggemma-2:270m` or remove it as the fallback. Move diagnostics into a collapsed "Run details" in the export (A9). | P | S | No raw exception text in the reader-facing export. | Implemented in the companion publisher PR; October 8 recorded tests pass. |
| Website guardrails in `check-editions` (A1, A2, A6): **non-failing warnings** for duplicate normalised outlets, Google News URLs, and same-edition headline pairs with high word overlap. Print them in the CI log. | W | S | The warnings fire on revision 6 for stories 1 and 8, the Iran pair and the 21 redirect URLs. The build still passes. | Implemented; hermetic tests and browser checks pass. |
| One section name (B1). Use "World & Nation" in the nav, page title, h1 and home band, and keep the `/world/` URL. | W | S | The same label appears everywhere; the test is updated. | Implemented; hermetic tests and browser checks pass. |
| Display-time outlet dedupe and consistent counts (B2). Prefer the named outlet over its domain in bylines. Derive "+N" from the same list as the coverage panel. | W | S | The lead byline shows no duplicate outlet. The byline, the "Read N sources" link and the panel agree, or are labelled as different things. | Implemented; hermetic tests and browser checks pass. |
| Close the round 2 minor items (B5) and the arrival focus box (B6). | W | S | axe shows 0 `region` or `landmark-complementary-is-top-level` violations. Missing-date wording is neutral. Source times show year and zone. Relative times refresh every minute while the tab is visible. | Implemented; hermetic tests and browser checks pass. |

### Phase 2 — Edition quality and reader orientation (next 2–3 weeks)

| Item | Owner | Size | Acceptance | Status |
| --- | --- | --- | --- | --- |
| Summary verification upgrades (A3). Every number and named entity in a summary must appear in a cited source, in the same context. Check that the headline agrees with the summary. Reject subjectless sentences. Repair quotes and title case. | P | M | Re-running revision 6 flags all the A3 examples. | Implemented in the companion publisher PR; October 8 recorded tests pass. |
| A newsworthiness bar for filling sections (A4). Allow sections shorter than 10. Exclude trailers, podcasts, mock drafts and video explainers unless they have a second source or a strong signal. | P | M | Fewer than 50% single-source stories on a typical day. No trailers or mock drafts unless corroborated. | Implemented in the companion publisher PR; October 8 recorded tests pass. Typical-day and week-long targets still need observation after rollout. |
| Stricter same-event merging (A2). Investigate the "merges blocked" cases. Merge same-actor, same-claim, same-day pairs. Keep the multi-topic videos out of single stories. | P | M | The Iran pair becomes one story; spot-check one week. | Implemented in the companion publisher PR; October 8 recorded tests pass. |
| Calmer revisions (A5). Set a minimum interval between revisions (for example 60 minutes, unless breaking news). Keep a story unless a clearly stronger one displaces it. Publish an optional `changes` block (`new`, `updated`, `fading`, `dropped` with headlines) in the edition JSON. Rule 4 of the contract allows new optional fields. | P | M | Fewer than 25% of stories dropped between same-day revisions. `changes` is documented in [backend-coordination.md](backend-coordination.md). | Implemented in the companion publisher PR; October 8 recorded tests pass. Typical-day and week-long targets still need observation after rollout. |
| "Since update N" summary in edition Details (B3). Use `compared_with` and the badges now. Add "No longer listed" headlines that link to search once `changes` ships. | W | S → M | Details shows the counts. Dropped headlines open a search for that headline. | Implemented; hermetic tests and browser checks pass. |
| Section jump chips with counts on Home (B4), following the export's pattern. Make them sticky or place them under the edition line on phones. | W | S | Every section is reachable from the top of Home in one tap at 390px; no overflow at 320px. | Implemented; hermetic tests and browser checks pass. |
| Automated post-deploy smoke check (B8). A GitHub Actions job runs after Cloudflare deploys: it checks the security headers, gets 404s for `/docs/…`, `/tests/…` and `/wrangler.jsonc`, and confirms the live `index.json` revision matches `main`. Also add `getagentreach.dev` to the cloud environment's allowed domains so reviews can test the real host. | W | S | The job is green on `main`; a failure names the missing header or exposed path. | Implemented; current live revision 6 passes. Main workflow run after merge remains pending. No deployment settings changed. |


### Phase 3 — Later, or dependent on other work

| Item | Owner | Size | Depends on |
| --- | --- | --- | --- |
| Category review (A7): a business/markets rule for deals and spectrum purchases, and policy-first categorisation for immigration and regulation stories. | P | M | Phase 2 selection work |
| Per-page embeds (B7): section pages embed only their own stories plus the index. | W | S | — |
| Stable event IDs, then per-story pages, per-story `og:` metadata and per-story RSS items. These were deferred in rounds 1 and 2. | P → W | L | Backend event-matching accuracy targets |
| An optional "Strong coverage only" view or filter, once A1 makes the counts trustworthy. | W | S | A1 |
| A reader-selected light theme (deferred since round 1). **Done October 9** (see below). | W | M | — |

## Preserve

The publishing contract and JSON fields, URLs (including `#story-` addresses and the headline hint), monthly search batching, RSS, sitemap and robots, the coverage method, edition and revision indicators, plain-text rendering, self-hosted fonts, the no-tracking promise and reduced-motion support. Nothing here adds a runtime dependency, analytics or a third-party request.

## Phase 1/2 implementation validation — October 8, 2026

This implementation uses the attached roadmap prompt's acceptance rules. Phase 3 remains deferred.
The website passes Node 24 installation, syntax, all 47 tests, edition validation and build.
The frozen revision 6 fixture produces duplicate outlet warnings for the lead and Crew-12, the Iran
pair's 0.50 overlap warning and exactly 21 Google News URL warnings. Warnings remain non-blocking.

Chromium at 320, 390 and 1440px covers ten routes: no horizontal overflow, and zero axe-core 4.10
`region` or `landmark-complementary-is-top-level` violations. Section links also work without JavaScript,
have 44px minimum tap heights and visible keyboard focus. At 390px the same-browser Home measurement
is 18,494px before and 18,674px after; the new shortcut row adds height while making every section
reachable from the top. The audit's 18,469px came from a different measurement environment.
The lead changes from 9 to 7 independent outlets, with 8 distinct source links labelled separately.

The live checker passed against deployed revision 6 with all six headers and four private-path 404s.
The new main-push/manual workflow will verify future deployment once these changes are merged.
Neither PR is merged by this implementation. Recorded input tests exercise publisher fixes offline;
they do not replace a week of production observation for quality and churn targets.

## Round 3 — October 9, 2026: headlines open the source, and a polish pass

- **One click to the source.** Every story headline (lead, top stories, cards, Latest, section pages, the story
  page itself, and search results when the data names the link) opens the publisher's article in a new tab,
  as the app's HTML export does. A second link on each story ("N sources →") opens the story page. The app
  sends the chosen link as the optional `stories[].url` (see `backend-coordination.md`); until then the site
  picks it from `sources` with the same rule. On revision 7, all 56 headlines open a publisher article and none
  a Google News redirect.
- **Pages for every section.** `/sports/`, `/entertainment/` and `/internet-culture/` join World & Nation,
  Technology and Science & AI. The navigation lists all six in one row that scrolls sideways on phones.
- **Shorter phone pages.** Home bands show up to five stories (three on phones) and link to the full section;
  summaries are clamped; the per-card source lists moved to the story page. At 390px, Home went from 18,674px
  to 11,395px and the top story's headline from 534px to 339px down the page; Latest from 20,788px to
  15,930px (measured after the outlet tags and ticker below). On story pages the breadcrumb and edition line share one row: the headline starts at 232px (was 323px).
- **A light theme.** It follows the system by default; the footer has Auto / Light / Dark. `assets/theme.js`
  applies a saved choice before the first paint (the CSP allows no inline scripts), and the build adds it to the
  app's dated shells too.
- **Accessibility.** axe-core 4.10 (WCAG 2.0–2.2 A/AA and best practice) reports no violations on nine routes at
  320, 390 and 1440px in both themes; Home's `landmark-unique` is fixed and section links are 44px tall.
- **Load.** Same-conditions comparison with `main` (slow 4G, 4× CPU, median of 3): load timing unchanged within
  noise; Home has 803 elements instead of 1,385 and Latest's blocking time fell from 472ms to 373ms.
- **Outlet tags.** Stories reported by several independent outlets show them as tags (widely known national and
  international newsrooms such as AP, Reuters and the BBC first; the story page lists every outlet). A
  single-source story keeps its plain outlet name and the "Single source" coverage label.
- **Edition ticker.** The edition's numbers are no longer behind "Details": one line under the header shows
  freshness, date and update, stories, reports, source types that answered (amber when some did not), what changed
  since the previous update (new, updated and, when the app sends `changes`, dropped) and how long ago it was
  generated, refreshed every minute. On phones it scrolls sideways inside itself; story pages keep the compact
  breadcrumb row instead.
- **Not done: thumbnails.** Lead-story images would load from publishers' servers, which the About page's privacy
  promise ("loads nothing from other servers") and the CSP (`img-src 'self'`) rule out; copying them to this site
  raises copyright questions for news photos. Waiting on the owner's decision.
- **Local news for Frisco, Texas.** A `Local` section ("Frisco & North Texas", `/local/`, after World & Nation in
  the navigation). The app files a story there when its reports name a town of the area, from the City of Frisco,
  four Dallas–Fort Worth newsrooms and two Google News searches, all checked against the live sites in the app's
  feed-check workflow. Editions published before that release have no Local stories, so the page says so.
