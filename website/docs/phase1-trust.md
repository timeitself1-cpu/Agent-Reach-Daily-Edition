# Trust and navigation contract

All in-document controls preserve fragment-only URLs. Browser regression tests click every section shortcut on the frozen October 7 archive at 390 and 1280 pixels, and keyboard-activate Skip to content on Home, Daily, the dated edition, Technology, Latest and Archive. The same checks run with JavaScript enabled, disabled and script requests aborted; they assert the resulting URL and focus. CI installs Chromium. Locally, `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` may select an installed Chrome executable.

The publisher assigns `outlet_id` to a newsroom and `reporting_origin` to contributions grouped within a story. Repeated newsroom contributions and identical syndicated titles share an origin. The website derives these for older editions; supplied origin IDs also connect copies. Reviewed NBC DFW and Al Jazeera aliases are shared with the publisher. Ownership alone is not a grouping rule.

`coverage.independent_reports`, `publishers`, `repeats`, `channels` and optional `points` describe all evidence assessed by the publisher, before its eight-source display limit. Alias corrections reduce the count, adjust corroboration points and reclassify strength together. Legacy exports without points conservatively downgrade a strong rating when alias removal leaves fewer than four origins; they cannot establish whether the original recency point applied. They never gain a stronger rating from normalization.

`source_links`, `linked_outlets` and `linked_reporting_origins` count the displayed evidence separately. Links include background/signals; newsroom and reporting-origin totals exclude signals. These displayed totals need not equal the all-evidence independent count. Source panels explicitly label this scope. Canonical names are representative newsroom names, not corporate ownership groups.

The build applies normalization to every edition in `dist/`, embeds the same normalized story in HTML, and joins each monthly search entry by date and story ID to copy its coverage and primary destination. Checked-in publisher files remain unchanged. New publisher exports include coverage in search entries; older search files are enriched during the build.

A headline links only to a resolved HTTP(S) report whose title matches that headline. Exact matching reports take precedence over loosely related reports; unresolved exact matches keep the internal evidence destination. A conservative title-overlap fallback supports paraphrases. Wikipedia and signal platforms are never primary destinations. Google News redirect links remain in evidence with a visible label in both enhanced and static views. This is a deterministic title heuristic, not a semantic guarantee; uncertain matches should stay internal. The existing publisher resolver still resolves URLs during ingestion.

Summary quality and mobile hierarchy changes are outside Phase 1.
