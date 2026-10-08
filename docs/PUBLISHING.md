# Website publishing

Agent Reach Daily can publish each validated edition to the website, getagentreach.dev, without anyone copying
files. This page explains the one-time setup, what happens on every refresh, how to correct or withdraw an
edition, and how to preview the site locally. Code: `agent_reach/daily/publish.py` (no Tk), window:
`PublishDialog` in `agent_reach/daily/gui.py`, tests: `tests/test_daily_publish.py`.

## How the website is hosted

- Repository `timeitself1-cpu/Agent-Reach-Website`, branch `main`. It is a static site: HTML shells, one script
  (`assets/site.js`) and one stylesheet (`assets/site.css`), self-hosted fonts, and the published editions as JSON.
- Cloudflare serves the repository as a Workers static-assets site (`wrangler.jsonc`, `assets.directory = "."`,
  `not_found_handling = "404-page"`) and deploys every push to `main` automatically. Cloudflare keeps serving the
  previous deployment until a new one is ready, so a deployment is all-or-nothing too.
- Pages: `/` (newest edition, front page), `/daily/` (newest edition), `/daily/YYYY-MM-DD/` (one date,
  permanent), `/daily/YYYY-MM-DD/#story-<id>` (one story with its sources), `/latest/`, `/technology/`,
  `/science/`, `/world/` (category views of the newest edition), `/archive/`, `/about/`.

## One-time setup (the user, about 3 minutes)

1. github.com > Settings > Developer settings > Personal access tokens > **Fine-grained tokens** > Generate new
   token. Resource owner: timeitself1-cpu. Repository access: **Only select repositories**,
   `Agent-Reach-Website`. Repository permissions: **Contents: Read and write** (Metadata: Read is added by
   GitHub). Expiry: your choice. From rc15 the app reads the expiry date GitHub sends with every answer and, a
   week before, says when the key expires (in Website publishing and in the refresh message); make a new key the
   same way and paste it. An expired key shows "GitHub did not accept the access key".
2. In the app: **...** > **Website publishing...** > paste the key > **Save key**. It is tested at once.
3. Tick **Automatic publishing**.

The key is stored in `%LOCALAPPDATA%\AgentReachDaily\publish\access-key.dat`, encrypted with Windows DPAPI for
your Windows account (another account or another PC cannot read it). It is never written to the project folder
or the logs. `AGENT_REACH_PUBLISH_TOKEN` (environment variable) overrides it, for a portable install.

## What happens on every refresh

1. The refresh makes and validates the edition as before ("no edition beats a bad edition": a failed or thin
   run publishes nothing, here or on the website).
2. The edition is saved on the PC and the podcast is recorded.
3. If automatic publishing is on, `publish_after_refresh` builds the public copy (`public_edition`): headlines,
   the validated summaries, "why it matters", categories, Top Stories and sections, New/Updated, coverage
   strength, and for each source its outlet, headline, link, stated publication time and whether it is an
   independent report, a repeat/syndicated copy or a social/search signal. Not included: publisher excerpts,
   run ids, settings, feed lists, model diagnostics, notes, file paths. `assert_public` refuses to publish any
   text that looks like a path on the PC.
4. Six files go up in **one commit** through GitHub's API: `editions/YYYY-MM-DD.json`,
   `daily/YYYY-MM-DD/index.html`, `editions/index.json` (the archive list, merged with what is already on the
   site), `feed.xml` (RSS, one item per edition) and `sitemap.xml`, both rebuilt from that archive list, and
   `search/YYYY-MM.json`, the archive search data of that month (headline, a short summary, category, outlets
   and coverage level per story). A month whose search file is missing is rebuilt from the edition files
   already on the site, so editions published by an older version become searchable on the next publication. The branch only moves by fast-forward: if it changed meanwhile, the files are re-read and the commit
   rebuilt (3 tries). If anything fails, no commit lands and the website keeps the previous edition.
5. The result is recorded in `publish\status.json` and shown in the window and in the refresh message. A website
   problem never makes the refresh fail.

Safety rules: the files are a pure function of the edition, so a retry finds them already there and makes no
commit (no duplicates); one file per date, so a later revision of the same day replaces the earlier one; an
older revision never replaces a newer one; a demo edition is never published; a date you withdrew is not
published again automatically unless a newer revision of that day is made.

## Corrections and withdrawal

- **One story:** right-click it in the app > **Remove from the website...** The story is removed from that date's
  public copy and the date is republished (the story stays in the app). Recorded in `publish\publish.json`
  (`hidden_stories`), so it stays off if the edition is published again.
- **A whole date:** Website publishing > **Take this edition off the website...** (for the edition on screen).
  The date's page and archive entry are removed; `/` and `/daily/` then show the next newest date.
  From a terminal: `python -m agent_reach.daily --withdraw 2026-10-07`.
- Anything else (a wording fix, the site design): edit the website repository directly; editions are plain JSON.

## Preview locally

```bash
git clone https://github.com/timeitself1-cpu/Agent-Reach-Website site
python -m agent_reach.daily --publish-to-folder site          # writes the newest edition into the copy
python -m http.server 8080 --directory site                   # then open http://localhost:8080/
```

`--publish-to-folder` uses the same code path as the real publication, without GitHub (no key needed).
`--publish` publishes from a terminal, `--publish-status` prints the state the window shows.

## Status messages

| Window shows | Meaning |
|---|---|
| Not set up | No access key saved yet. |
| Ready to publish | A key is saved; nothing published from this PC yet. |
| Publishing | A publication is running (one at a time, `publish\publish.lock`). |
| Published successfully | The site has the edition; Cloudflare shows it within a few minutes. "Live website now shows" confirms it. |
| Publication failed: previous edition preserved | Nothing changed on the site. The message says why (offline, key expired, no write permission). |
| Edition taken off the website | The last action was a withdrawal. |
