# Agent Reach website: the data contract with the back end

The back end (the Agent Reach Daily app on the Windows PC) writes every file the website reads. It pushes them to
GitHub as ONE commit per edition, and Cloudflare deploys it. Please build against the fields and rules below.
Tell me before the site relies on anything not listed here.

## Files the site reads (all schema_version 1)

| File | Written when | Fields the site can rely on |
|---|---|---|
| `editions/YYYY-MM-DD.json` | each publication; a later revision of the same day REPLACES it | `edition_date`, `revision`, `generated_utc`, `timezone`, `summaries`, `models`, `reports_read`, `sources_answered`, `sources_tried`, `compared_with`, `top` (story ids), `sections` (`category`, `ids`), `stories` (`id`, `rank`, `top_rank`, `category`, `headline`, `summary` = list of sentences, `why_it_matters`, `change`, `labels`, `newest_published_utc`, `coverage`, `sources` = list of {`outlet`, `via`, `title`, `url`, `published_utc`, `kind`}) |
| `editions/index.json` | each publication and withdrawal | `latest`, `editions` = list of {`date`, `revision`, `generated_utc`, `stories`, `lead`, `headlines`, `sections` (counts)}, newest first |
| `search/YYYY-MM.json` | each publication and withdrawal, in the same commit as the edition | `month`, `stories` = list of {`d` date, `id`, `r` rank, `t` top rank, `c` category, `h` headline, `s` summary (max 280 chars), `o` up to 5 outlets, `l` coverage level}, newest date first |
| `daily/YYYY-MM-DD/index.html` | each publication | page shell: `<body data-page="edition" data-date="...">`, `#app`, title/description/canonical tags; headlines only inside `<noscript>` |
| `feed.xml`, `sitemap.xml` | with the index | built from the index only |

## Rules

1. **All text is plain text.** Headlines, summaries and source titles come from news sites and a local AI model.
   Insert them as text (textContent), never as HTML. `url` is an absolute http/https link or `null`.
2. **Story ids are NOT stable today.** An id is a fingerprint of the story's articles. When the day gets a second
   edition (a new revision), only 39% of story ids survive: on the real October 7 editions, 116 of 295 did. No
   id carries over to the next day. Stable event ids are planned, but only after the back end's event matching
   passes its accuracy targets.
3. **Dates can disappear.** A withdrawn date is removed from the index, its search month and its own two files
   in one commit. A 404 for an old date link is normal.
4. **New optional fields can appear at any time.** Ignore fields you don't know. A rename or removal comes with a
   new `schema_version`.
5. **Empty values are normal:** `why_it_matters` (often empty), `top_rank` (empty outside Top Stories),
   `published_utc` (the source gave no time), `compared_with` (the first edition), `summary` can be short.

## Search recovery: when a story link points to a missing id

The search file and the edition file are written in the same commit, so on a fresh deploy they agree. Mismatches
come from (a) a cached old search month, (b) a revision published after the result was shown, (c) external links
and bookmarks. Suggested fallback, in order:

1. Load `editions/<date>.json`. A 404 means the date was withdrawn: say "This edition isn't available. It may have been withdrawn." and
   link the archive.
2. Find the story by `id`. If it is found, show it.
3. If the id is missing, match by headline: an exact match after lowercasing and stripping punctuation, then the
   story on that date with the most shared headline words (require a clear winner; on a tie, don't guess).
4. If nothing matches, open that date's page with a short note: "This story was updated in a later edition of
   the day; here is the full edition."
5. Treat `revision` in the index as a cache key: if the index's revision for a date is newer than the one a
   cached search month was built from, refetch that month.

## Questions back to you

1. Does any page or search result link to a story by its `id` today? If yes, stable ids become a higher priority
   on the back end.
2. Would it conflict with `site.js` if the publisher wrote the full story text (escaped HTML) inside `#app` for
   no-JavaScript readers and search engines, with the script replacing it as it does now?
3. Is a "last updated" note planned, so readers can see when the PC hasn't published for a while?

---

## Frontend coordination response — October 8, 2026

- Yes: headline/card, category, latest, previous/next and search links use edition date plus `#story-{id}`. These are current story addresses, not stable event identifiers. The frontend does not assume IDs survive revisions or carry across days.
- Escaped server-rendered story HTML inside `#app` is compatible with the current renderer, which replaces its children after loading JSON. It would remain visible without JavaScript. Preserve the shell's `#app`, `data-page`, `data-date` and metadata; avoid inserting an additional outer `main` or duplicate element IDs outside `#app`. This is a backend publishing decision; the frontend pass does not alter the publisher.
- Generation time, edition revision, archived/latest state and a stale notice already exist. Priority #5 makes generation time include its date and time zone, and exposes edition context on article/category/latest pages. Generation time is labelled as generation, not an independently confirmed publication timestamp.
- Search month JSON has no built-from-revision field. The frontend continues requesting index, edition and monthly files with HTTP cache revalidation (`cache: 'no-cache'`) rather than claiming a revision comparison it cannot perform. No new JSON field is required. A revision signature for each month would need a separate agreed contract addition before the frontend could compare it reliably.
- Search links can carry the existing `h` headline as a frontend URL hint for recovery, consumed when the edition loads and removed from the current address. This introduces no backend field or stable event ID. Matching is confined to the requested edition; ties and weak word matches fall back to its full page.

The supplied contract above is preserved as the coordination record. The response describes frontend decisions; it does not change the publishing contract or certify the backend's ID-match accuracy.

## Website build integration — October 8, 2026

The website now adds a deployment build step that consumes only the files and fields above. It writes escaped story HTML into `dist/` and embeds the existing public edition/index JSON for immediate browser rendering. This works with the publisher's current one-commit publication and withdrawal behavior, without requiring a publisher change or a new JSON field. The source dated shells remain publisher-owned; generated HTML is never committed back over them. Every deploy validates the index, editions, search months, dated shells, RSS and sitemap before building.

Native Share and Copy link carry the existing headline hint. Stable IDs and dedicated per-story preview pages remain backend follow-up work.

## Optional Phase 2 changes block — October 8, 2026

Public editions retain `schema_version: 1`. A publisher may add this optional top-level field:

```json
"changes": {
  "compared_with": {"edition_date": "2026-10-08", "revision": 5},
  "new": ["12hexstoryid0"],
  "updated": [],
  "fading": [],
  "dropped": [{"headline": "Earlier headline", "category": "News"}]
}
```

The ID arrays use the same public IDs as `stories[].id`. The comparison pointer matches top-level
`compared_with`. Dropped entries contain plain-text headlines and the previous category, never private
IDs or evidence. Hidden website stories are excluded from the changes block too. Old cached changes
may have an empty category; readers tolerate that. Omit the block when no comparison exists.
This is revision context, not stable event identity or a promise to keep earlier revisions searchable.
The frontend counts `story.change` for New/Updated, and renders optional dropped headlines as quoted
search links. Without `changes`, only the existing comparison and badges are used.

`sources[].via` already exists: unresolved `news.google.com` URLs now use `"Google News"`, which the
frontend labels explicitly. Successful resolution retains the publisher URL. No required field changes.
Publisher names and aliases normalize before independence counts; source-link count and independent
publisher count are different measurements, and the reader labels each one. Schema 1 URLs, headline
hints, feed and sitemap remain compatible.
