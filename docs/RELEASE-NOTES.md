# Agent Reach Daily: release notes

Each release candidate is delivered as a zip of the repository. Extract it over the old folder, rerun
`powershell -ExecutionPolicy Bypass -File .\Setup-AgentReachDaily.ps1 -RegisterTask`, and reopen the app.
Your editions, settings and history (`%LOCALAPPDATA%\AgentReachDaily`) are kept. Earlier releases are
summarised in `docs/HISTORY.md` ("Release history").

## 1.0.0rc21 (update): cleaner summaries, one event per story

This version installs itself (no zip, no Setup).

1. **Summaries add something.** A summary no longer starts by repeating its headline. When a sentence fails the
   check against the story's sources, only that sentence is left out (before, the whole summary was replaced by
   a source's headline). When nothing adds to the headline, the story shows the headline alone; nothing is made up.
2. **One event per story.** A story whose sources tell two different events is split in two, so unrelated reports
   no longer count as coverage (October 9: Christa Pike's case had been counted in the Pentagon execution story).
3. **Checked before publishing.** Every edition gets an editorial check before it goes to the website. A broken
   edition is not published and the website keeps the previous one; smaller problems are noted in the log.

## 1.0.0rc20 (update): sources on the website

This version installs itself (no zip, no Setup).

1. **Sources page.** Each edition published to the website now lists the sources it read: each kind of source
   and every news feed by name and website, with how many reports each gave and how many the edition cites. Feed
   addresses and error messages are never published. The website shows them on its new Sources page.
2. **Sitemap.** The website's new Sources and Corrections pages are listed for search engines.

## 1.0.0rc19 (update): no Local section

This version installs itself (no zip, no Setup).

1. **The Local section is gone.** New editions no longer have a Local (Frisco & North Texas) section, and the
   five Dallas-Fort Worth feeds and two Frisco searches that filled it are no longer read. A news feed you added
   yourself stays. Older editions that had a Local section still show it as it was.

## 1.0.0rc18 (update): local news, and a more trustworthy edition

This version installs itself (no zip, no Setup). It brings the website and quality work of October 8 and 9.

1. **Local news for Frisco, Texas.** A new **Local** section collects news from Frisco, Collin and Denton
   counties and North Texas: the City of Frisco's news, NBC DFW, WFAA, FOX 4, CBS News Texas and two Google News
   searches. A story is Local only when its reports name a town of the area; Cowboys and other pro teams stay
   in Sports. To turn the section off, set `"local_area": ""` in `settings.json`.
2. **One click to the source on the website.** Each story tells the website which article its headline opens
   (the same one as in the exported page), and the website now has a page for every section, Local included.
3. **Fairer source counts.** One outlet listed twice (for example "AP News" and "apnews.com") counts once, and
   Google News links are replaced by the publisher's own link whenever it can be found.
4. **Checked summaries.** Numbers and names in a summary must appear in the cited reports, and sentences without a
   subject or with broken quotation marks are fixed or replaced by a checked sentence from a source.
5. **Fewer filler stories and duplicates.** A story from one outlet needs a real news report or a strong signal
   (trailers, podcasts, mock drafts and debate clips need a second outlet), and two reports of the same event
   are merged more often.
6. **Calmer updates.** The website gets a same-day update at most once an hour (sooner only for major new
   stories), stories are not replaced by barely better ones, and each update lists what changed.

## 1.0.0rc17 (zip rc17): the app updates itself

1. **No more zips.** When you open Agent Reach Daily it checks for a newer version and installs it by itself (a
   small "Updating..." window appears for a moment), then opens on the new version and says what changed. While
   the app is closed, the hourly scheduled check does the same. This is the last version you install by hand.
2. **Safe updates.** Only files that changed are replaced; the old ones are kept, and if the new version does not
   start, the old one is put back. Your editions, settings and website key are never touched. Updates come only
   from the app's own GitHub repository (its `stable` branch).
3. **Your choice.** Details show the last update check; `"auto_update": false` in `settings.json` turns it off.

## 1.0.0rc16 (zip rc16): the website never gets thinner

From the second backend audit of October 8 (`docs/BACKEND-AUDIT.md`, round 2, Step A).

1. **A poor refresh no longer replaces a good edition of the same day.** If a later refresh finds much less (for
   example only 2 of 10 news sources answered), today's edition stays as it was, in the app and on the website,
   and the app tries again later. The message says how much each refresh found.
2. **One odd story no longer keeps the whole edition off the website.** A story whose text looks like a file
   path on your PC is left out and named; the rest of the edition goes up.
3. **The hourly retry stops when retrying cannot help** (a refused or expired key, a key without access, or a
   newer edition already on the site). Saving a new key starts it again.
4. **Test connection keeps the reason visible** when the last publication failed, and says to click Publish
   latest edition to try again.
5. Publishing reads less from GitHub and closes its connections; taking an edition off the website accepts only
   a real date.

## 1.0.0rc15 (zip rc15): the website stays correct and up to date on its own

From the backend audit of October 8 (`docs/BACKEND-AUDIT.md`, Step 1).

1. **A story you remove from the website stays removed.** Before, a second refresh on the same day could put
   it back, because the story got a new internal id when it gained or lost an article (on the October 7
   editions this would have happened to 28 of 144 stories). The app now recognises the story by its articles.
2. **A failed upload is tried again within the hour.** If GitHub or your internet connection is down when the
   refresh publishes, the hourly scheduled check sends the edition as soon as it can, instead of waiting for
   the next day's refresh. A date you took off the website is never put back this way.
3. **The website no longer waits for the podcast.** The edition goes to the website first; the spoken edition
   is recorded after it.
4. **A warning before your access key expires.** GitHub keys have an end date. A week before it, the
   publishing window and the refresh message tell you the date, so you can paste a new key in time.

## 1.0.0rc14 (zip rc14): the app starts recognising the same event across days (behind the scenes)

1. **Event registry, observing only.** After each successful refresh the app records which earlier event each
   story continues: the same news told again hours or days later, even with new articles and a new headline.
   Each event keeps a fixed id, when it was first and last seen, its reports, and why every story was matched
   (or kept apart when the evidence was unclear). Nothing you see changes yet: this builds the history that
   story timelines will use once the matching is proven on your real editions. Stored in
   `%LOCALAPPDATA%\AgentReachDaily\state\events.json`; a problem with it never fails a refresh.
2. **The self-test brings back your last 14 days of editions** (and the registry), so the matching can be
   checked against real news from consecutive days. Nothing in your data folder is changed.

## 1.0.0rc13 (zip rc13): your editions on getagentreach.dev, automatically

1. **The website is now a news site.** getagentreach.dev opens on the newest edition: a lead story, the top
   stories, then World, Technology, Science & AI, Sports, Entertainment and Internet Culture. Every story has its
   own page with the summary, how widely it was reported (independent outlets, repeats and syndicated copies
   counted once, social signals shown as attention only) and every source with its date and link. `/daily/` is the
   newest edition, `/daily/2026-10-07/` a fixed date, and `/archive/` lists them all. It works on phones.
2. **Automatic publishing (off until you switch it on).** After a successful refresh the app can put the edition
   on the website by itself. One-time setup: create a GitHub access key for the website repository (README,
   "Publishing to the website"), paste it in **...** > **Website publishing...**, tick **Automatic publishing**.
   The window shows the last published edition, whether it worked, and what the live site shows.
3. **Safe by design.** Only the news goes up (no excerpts, logs, settings or anything about your PC). An edition
   goes up in one piece or not at all: a failed upload leaves yesterday's edition on the website, and the refresh
   itself still succeeds. Retries never duplicate an edition.
4. **Corrections.** Right-click a story > **Remove from the website...**, or take a whole edition off the site from
   the publishing window.
5. **RSS and search engines (zip rc13b).** Each publication also updates the site's RSS feed
   (getagentreach.dev/feed.xml, one item per edition) and its sitemap, so readers can follow the editions in a feed
   reader and search engines can find every dated page.
6. **Archive search (zip rc13c).** getagentreach.dev/search finds any story in any edition by headline, summary,
   outlet or section, in the browser (no server). Each publication updates a small search file for its month;
   editions published by an earlier version are added automatically the next time you publish.

After extracting the zip, run setup once as usual. Nothing changes until you set up publishing.

## 1.0.0rc12 (zip rc12f): the launcher, and one more mixed story

Your test at 6:16 PM ran on the previous version (rc12d): the rc12e fixes were not installed yet. It showed two
new things:

1. **Double-clicking AgentReachDaily.cmd could stall.** Windows shows a security warning for files that came out
   of a downloaded zip, and the launcher waited on it for four minutes. Setup now removes that "downloaded from
   the internet" mark from Agent Reach's own files, so the launcher opens straight away. If it ever happens again,
   the self-test says so in plain words.
2. **A university profile was grouped with NASA's Artemis II news** because both mention NASA and the Moon. A
   name plus one shared word now needs strong agreement from the grouping model before two reports become one
   story. On your saved editions this kept every correct grouping.

This zip also contains everything from rc12e. After extracting it, run setup once.

## 1.0.0rc12 (zip rc12e): fewer mixed stories, from your third test

Your test at 4:29 PM passed everything except the two leftover test files. Its two editions still put different
events into one story in 5 places: Trump's golf-club "presidential retreat" with US forces pulling back (again),
a Gaza child's illness inside the story of Israelis mourning the October 7 attack, and Nature's round-up of all
the Nobel prizes inside the chemistry prize story.

1. **All three are fixed** (checked on the two saved editions; your next test checks a live run). The golf club
   joined through a second rule that still treated "Trump" as a rare name; that rule now agrees with the first.
   "War" no longer counts as proof of one event, because a war runs for years. An article that covers three
   different prizes is now treated as a round-up and joins no story.
2. **The self-test keeps the grouping details of its second refresh too**, so a mixed story in the second
   edition can be traced.
3. **The two leftover test files** (`tests\test_event_contract.py`, `tests\test_event_identity.py`) are not
   part of Agent Reach. Delete them and the self-test has no failure left.

## 1.0.0rc12 (zip rc12d): fewer mixed stories, from your second test

Your test at 1:36 PM showed that the two editions it made still put different events into one story 8 times:
Eva Marie Saint's obituary inside Frank Mancuso's, Jimmy Kimmel's monologue inside the Trump Accounts story,
three different polls as one, US forces "retreating" with Trump's golf-club "presidential retreat", Belgian
student protests inside France's, and two different laptops with the same Nvidia chip.

1. **Five of these six mix-ups are fixed** (checked on the two saved editions; your next test checks a live
   run). A single report now joins a story only when its headline links it to every report already in it.
   Words like "don't", names like "Congress" and a very common name such as "Trump" with one shared word
   no longer count as proof of the same event. The two laptops are still grouped together; that case is
   recorded as open.
2. **The self-test failure on Windows is fixed.** A small progress file sometimes stayed behind after a
   refresh, because Windows will not delete a file while the window is reading it. The refresh now tries
   again for a moment. It never affected what the window showed.
3. **The self-test no longer reports "grouped by the configured model" as a failure** when the app used
   nomic-embed-text because Ollama cannot run EmbeddingGemma 2 on Windows.
4. **About embeddinggemma:300m:** it downloaded, but Ollama 0.40.0 could not open it ("The path cannot be
   traversed because it contains an untrusted mount point"). That is a bug in Ollama on Windows, not in
   Agent Reach; the benchmark now says so in plain words. Nothing to do; the app keeps using nomic-embed-text.

## 1.0.0rc12 (zip rc12c): EmbeddingGemma 2 is Mac-only in Ollama for now

With the newest Ollama, `ollama pull embeddinggemma-2:270m` on your PC answered "this model requires MLX
support, but the MLX runtime is not available". MLX is Apple's engine: Ollama can run EmbeddingGemma 2 only
on Mac computers so far, and updating Ollama does not change that on Windows yet. Nothing is broken: the
app keeps grouping stories with nomic-embed-text, as it did in your test.

1. Setup, the benchmark, the app's model check and the self-test now say this plainly, instead of advising
   you to update Ollama. The self-test reports it as information, not as a failure.
2. The benchmark now also compares the first EmbeddingGemma (`embeddinggemma:300m`), which Ollama does run
   on Windows, against nomic-embed-text. If it groups stories better on your PC, a later version uses it.
3. The Ollama app's chat window lists chat models only; embedding models never appear there.

## 1.0.0rc12 (zip rc12b): fixes from the first test on your PC

Your self-test and benchmark (October 7, 12:07) showed these problems; each is fixed and has a test.

1. **Fewer mixed stories.** Two real editions from that test still put different events together 6 times:
   the leaked Paxton audio carried a Hegseth post, a fertilizer-price story and Michigan's Mike Rogers on
   Canada; France's stun-grenade ban carried Belgian student protests; OpenAI's agents at Wikipedia
   carried AI agents hacking South Korea's banks; Tropical Storm Isaias carried a geomagnetic storm watch;
   an Asos hacking notice joined the Wikimedia story in the benchmark. A clean-up step after labelling
   could add single reports to a story one by one; it no longer can. Broad words ("agents",
   "possible", "confirms", "sent") and kinds of event ("protests", "hack") alone no longer count as a
   shared fact. Both editions are now part of the test material (0 mixed stories in every offline check).
2. **AI headlines no longer cut off.** With many one-report stories, the model was asked to label up to 20
   at once, ran out of room, and the answer was cut off three times in a row (about 75 seconds lost, and
   some stories fell back to plain report titles). At most 12 stories go into one request now, and a
   cut-off answer is split into two smaller requests instead of being repeated.
3. **EmbeddingGemma 2 did not download on your PC.** Your Ollama (0.40.0) answered "not found" for
   `embeddinggemma-2:270m`. The model is in the Ollama library, but Ollama 0.40.0 appears to support it only
   on Apple computers; support for other computers was added to Ollama's code on October 6, after 0.40.0
   (likely, not yet confirmed on your PC). Refreshes kept working with nomic-embed-text. Setup and the
   benchmark now show the reason Ollama gives when a download fails and suggest updating Ollama; the
   app's model check names a missing grouping model separately and never treats it as blocking.
4. **The self-test is stricter.** It said PASS for the offline tests although one test had failed (a
   timing test that Windows' coarse timer could trip: fixed too). Failed tests are now a FAIL, and window
   tests that could not start are reported.
5. **Better troubleshooting files.** The list of same-event decisions now keeps the accepted pairs (it
   had cut all of them), its counts describe the grouping itself, and the benchmark saves each model's
   results so a fix can be re-checked without your PC.

## 1.0.0rc12

### One story = one event (story grouping rebuilt)

The October 7 editions put different events into one story 13 times. Examples: the Australian privacy
investigation of a smart-glasses app maker carried the Wall Street Journal's profile of the billionaire
behind Meta's AI app; the Maine Senate debate carried two Cornell stories and a newsletter roundup; the
Webb telescope's planetary-collision finding carried NASA's PRIMA telescope plan; "October 7" as a date
joined NASA's picture of the day, a TV review and a satellite puzzle. The cause was structural: if A looked
like B and B looked like C, A and C ended up together, so one roundup or one shared word could bridge two
events.

1. **Similar is not the same event.** The embedding model now only suggests which reports might belong
   together. A separate same-event check decides, and it needs specific shared facts. Shared broad words
   (technology, app, AI, privacy, smart devices, model, platform), dates, weekdays and names alone are
   never enough. Newsletter roundups and live blogs ("Morning Rundown", "News Wrap") join no story.
   Reports join a story only when most of its reports agree, so one report can no longer bridge two
   stories. When unsure, two stories are shown instead of one mixed story.
2. **New grouping model: EmbeddingGemma 2** (`embeddinggemma-2:270m`, a few hundred MB). Your settings
   switch to it automatically; `nomic-embed-text` stays as the fallback. If the new model is not
   installed, refreshes keep working with the old one, and the edition says so. Download it with
   `ollama pull embeddinggemma-2:270m`, or rerun setup with `-PullModels`.
3. **Faster repeat refreshes.** Each report's embedding is remembered (a cache next to the history
   database), separately for every model and model version. A second refresh on the same day only
   embeds reports it has not seen.
4. **"How stories were grouped"** at the bottom of the HTML export, plus the footer and the Details
   panel, name the model that actually grouped the stories and why another one was not used, with a few
   counts. The full list of every same-event decision (for troubleshooting) goes to
   `diagnostics\semantic\` in your data folder, never into the edition.

### Text and evidence

5. **A summary cut in half is no longer published.** "By studying 21 rare." (the Webb story): the model
   stopped at a quotation mark. Such a sentence is now refused, and the story uses its source's own
   first sentence instead. "Oct. 7" and "Sept. 30" no longer end a sentence ("Netanyahu faces a
   reckoning over the Oct.").
6. **The newest report sets the current state.** The stock-market story said "record high Tuesday" on
   Wednesday morning, while its newest report said stocks fell on Wednesday. When a summary only
   describes an earlier day and a source states what happened today, that source sentence now comes
   first, the earlier one follows, and the card is labelled **Developing**.
7. **Attention is not evidence.** Google Trends, X, Bluesky, Mastodon and Reddit items show interest,
   not reporting. They no longer raise a story to "Strong evidence" through channel diversity or
   recency.
8. **"What changed" is fairer.** A story is matched to the earlier story it shares the most articles
   with. When an earlier edition had merged two events that are now apart, neither half is called "new"
   or "fading".

### For testing on your PC

- `Benchmark-Embeddings.ps1` compares nomic-embed-text, EmbeddingGemma 2 270M and the full EmbeddingGemma 2
  on the labelled October 7 editions (wrongly merged stories, correctly grouped reports, speed, cache
  reuse), then runs the self-test. Both result zips land on your Desktop.
- The self-test now checks that the configured grouping model was used, and includes the same-event
  decisions in its zip.
- Expect "momentum uncertain" notes for about a day after upgrading: momentum is compared only with
  refreshes made with the same settings, and the grouping model is one of them.

## 1.0.0rc11

### Stabilization pass (found by reviewing the code; no new features)

1. **The window could stay on "Refreshing" for good, and Cancel could end the wrong program.** A refresh
   that died (crash, power loss) leaves `progress.json` behind with its process number. After a restart
   that number can belong to any other program; the window trusted it, showed "Refreshing", blocked
   Refresh, and Cancel would have ended that program. The window now checks the refresh lock that the
   operating system releases when a worker dies.
2. **A refresh stopped by the time limit stayed "running" in the history database.** It is now marked
   invalid like any other failed run.
3. **A damaged edition file that Windows refused to move (held open by a virus scanner) stopped the
   refresh** before the attempt was recorded. The refresh now logs it and continues.
4. **The model check crashed when another program answered on Ollama's port.** It now says the program
   there is not Ollama.
5. **A negative or invalid `Retry-After` header from a news site** could produce a negative wait. It is
   clamped.
6. **Follow / Mute from a story's right-click menu skipped the checks of the Topics tab** (length, blank
   topics, duplicates in other capitalisation). Both now use the same checks.

Also in the repository: every text file is stored with LF line endings (`.ps1`, `.cmd` and `.bat` are
still checked out with CRLF), so a fresh copy no longer shows the PowerShell scripts as modified.

### Windows-readiness pass

Found by running the real refresh worker as its own process (offline, with synthetic news and a fake
model) and cancelling, killing, hanging and starving it, by damaging and locking its files, and by
looking at the window as a reader would. Not yet run on Windows or with a real Ollama: see
`docs/WINDOWS-TEST-RC11.md`.

7. **A hung refresh could keep "Refreshing" forever.** A refresh stuck in a call that ignores the time
   limit (a hung network, disk or driver call) never ended. A watchdog now ends it 25 minutes after the
   time limit, records "stopped responding" in plain words, and writes where it hung to `diagnostics\`.
8. **When Ollama stopped answering partway through a refresh, the edition still said "local model"
   summaries.** The app now counts the model steps that fell back. If half or more fell back, the edition
   counts as extractive: with "AI summaries required" the previous edition is kept, and the reason says
   the model stopped answering. If fewer fell back, the edition says so in its notes.
9. **A refresh killed halfway (Task Manager, crash, power loss) left the window silent.** It now says
   the last refresh stopped before finishing.
10. **Settings or refresh history held open by another program (antivirus, OneDrive, a backup tool)
    were treated as damaged:** `settings.json` was renamed and default settings were used, which lost
    your feeds and topics. Such files are now left alone. The window shows a warning, and refreshes wait
    until the file can be read.
11. **An edition file held open by another program failed the refresh with a raw `PermissionError`.**
    It now says the new edition could not be saved and why.
12. **Cancel right after pressing Refresh** waited 5 seconds for nothing. **The Cancel button's reset**
    went through a background-thread call to Tk that could be lost, which would leave "Refreshing..." on
    for good.
13. **A damaged newest edition was counted twice** ("2 files could not be read").
14. **Saving settings or topics to a read-only settings file** showed "Something went wrong". It now
    says what happened.
15. **Another program on Ollama's port** is now named as such ("Another program answers at ..., not
    Ollama"), not as "Ollama is not running".
16. **"Found too little news to publish"** was shown for every refresh that published nothing, including
    when the model stopped. It now says "did not publish a new edition", and the banner gives the reason.

Daily use:
- The status shows the step a refresh is on ("Refreshing, step 4 of 7: ...").
- Before the first edition, the empty date box and the Listen button are disabled.
- "Clear search" looks like a link.
- A Settings label no longer gets cut off.
- `python -m agent_reach.daily` works from any folder after rerunning Setup.

Testing:
- `Test-AgentReachDaily.ps1` (self-test on your PC with real Ollama and real news; leaves a zip of the
  results on the Desktop).
- `tests/test_daily_processes.py` (real worker processes).
- `tests/test_daily_windows.py` (real Windows file locks).
- The window tests now run in CI on a virtual display. Before this they were silently skipped there.

### First Windows test round (self-test on the reader's PC, October 7)

The self-test ran on Windows 11 with Ollama 0.35.1 (llama3.1:8b, RTX 4070 Super): 24 checks passed and 3
failed. These passed:
- the Desktop and Start-menu shortcuts started from another folder;
- `python -m agent_reach.daily` started from another folder;
- the Ollama checks (running, missing model, nothing listening);
- cancel right after starting and cancel halfway;
- a full real refresh: 330 s, 48 stories, HTML export, a 5.4-minute podcast in the Windows voice;
- Ollama cut off halfway: no edition, explained in plain words;
- a second refresh after changing settings.

Fixed from that run:

17. **Another program on Ollama's port answering with a web page** (not JSON) still read as "Ollama is not
    running". Any answer that is not Ollama's model list now says another program answers there.
18. **After Ollama went away mid-refresh, every remaining model step retried three times.** Each refused
    connection costs about 2 s on Windows, so the refresh ended 112 s after Ollama stopped. The first refused
    connection now ends the model calls for that refresh.
19. **A YouTube outage (1 of 22 channels answered) was listed as 21 broken feeds** named like the
    publishers' working article feeds, and the feed checker would have blamed those addresses after three
    days. A channel where fewer than 1 in 5 feeds answer now counts as one outage, said once.
20. **The model's remarks about its input reached summaries** ("..., but the reason is not specified").
    They are removed.
21. **A summary ended inside a word** ("trained on 3,800 NVIDIA Grac."). The article text the model reads is
    now cut at a word.
22. **Self-test:** the `.cmd` launcher check hung (fixed in the harness), and a test file that does not
    load no longer stops the whole test suite.

The two real editions are now regression fixtures (`tests/fixtures/real/`). What they show for the next
phase is in `docs/REAL-EDITION-FINDINGS.md`.

### Second Windows test round (October 7, 9:29 AM)

The self-test ran with 31 checks passing and 3 failing. Highlights from that run:
- **Offline suite on Windows:** 404 passed, 1 skipped, 4 expected failures. That includes the real Windows
  file-lock tests and the process kill/cancel tests.
- **Launchers:** the Desktop and Start-menu shortcuts and `AgentReachDaily.cmd` all opened the window.
- **Model drop:** the refresh now ends 9 s after Ollama goes away (it took 112 s before).

The three failures:
1. **`AgentReachDaily.pyw` (double-click) did not open the window.** The self-test now records what `.pyw`
   files open with on the PC. The Desktop shortcut is the supported launcher.
2. **Two test files in the reader's folder are not part of this release** (other work); see the handoff.
3. **The "Following" check followed the #1 story, and the next refresh no longer had that story.** That is
   the refresh-to-refresh churn the event layer must fix. The check now follows the best-corroborated story
   and reports churn as churn.

Fixed:

23. **A middle initial ended a sentence.** A summary read "Biologist James D." followed by "Watson appears to
    have ...". The sentence splitters no longer split after a single capital initial.
