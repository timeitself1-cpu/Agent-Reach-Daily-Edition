# Agent Reach website

The daily publisher commits edition JSON, the archive index, monthly search data, dated HTML shells, RSS and sitemap. The website builds these into static Cloudflare assets; it does not change the publisher or its JSON contract.

Use Node 24:

```sh
npm ci
npm test
npm run check:editions
npm run build
```

`npm test` uses the frozen October 7 publication under `tests/fixtures/`. It remains independent of daily additions, revisions and withdrawals. `check:editions` validates the current published files: dates/revisions/counts, unique IDs/ranks, section/top membership, source fields, exact monthly search membership/headlines, dated shell identity, RSS and sitemap links. The build runs this validation before creating output. A bad publication fails the build rather than silently deploying mismatched files. CI runs unit tests and the build on every PR and `main` push.

The build renders Home, Daily, dated editions, Latest, category pages and Archive with the same frontend code used by the browser. It embeds the existing public edition and index JSON and writes escaped story text into HTML. Readers see content before JavaScript or JSON requests, and the client uses that embedded data for initial rendering. Default Cloudflare cache revalidation keeps HTML and embedded data together. Source shells without an embed still work; a dated edition and the index load concurrently. No new backend fields or stable story IDs are assumed.

The static Home and Daily pages include **every** story, with full summaries, optional context and native source disclosures. Dated story fragments resolve to real HTML articles, including stories beyond the home page's five-card previews. Latest and category pages expose the same evidence. Static timestamps use explicit UTC dates; edition metadata and revision history use a native disclosure. The `data-rendered="static"` styles remain active if scripts are disabled or fail to load, and are removed only when the browser mounts its enhanced view. Mobile category and dated pages keep every story visible. Search still requires JavaScript; its fallback links to the pre-rendered archive.

Preview **the built directory**, not the repository root:

```sh
python -m http.server 8873 --bind 127.0.0.1 --directory dist
```

For Cloudflare behavior (headers and custom 404 handling):

```sh
npx wrangler@4.148.0 dev --config wrangler.jsonc --local
```

Wrangler runs `npm run build` automatically for the existing deploy/preview commands. Its assets directory is `./dist`. Only explicit public routes, assets, edition/search JSON, feeds, robots and `_headers` are copied there. Development tests, fixtures, docs, scripts, dependencies and Wrangler configuration are excluded. Cloudflare's repository build must install the locked development dependencies (`npm ci`); no browser runtime dependency is added.

`_headers` supplies CSP, MIME sniffing and framing protection, referrer and permissions policies, and HSTS. After a production deployment, verify these on the live site and confirm `/docs/frontend-audit.md`, `/tests/frontend.cjs` and `/wrangler.jsonc` return 404. Local Wrangler verification cannot confirm production deployment.

Share/Copy links include the dated story ID and a headline hint for conservative recovery after revisions. Native sharing falls back to copying, then a selectable URL when clipboard access fails. Social metadata uses the generic `assets/social-card.png`; its editable design source is `scripts/social-card.html` (capture at 1200 × 630). Story-specific crawler previews remain deferred until backend IDs are stable; changing a client document title cannot make a hash URL a separate social preview.
