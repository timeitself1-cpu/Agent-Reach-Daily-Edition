# Frozen publication

The October 7, 2026 edition, index, monthly search file, dated HTML shell, RSS and sitemap were copied from commit `24e4295` before the next daily publish. Unit tests read only this data, never production `editions/` or `search/`. Keep the fixture fixed when the publisher adds, revises or withdraws dates.

`npm run check:editions` separately validates all current published files. The build runs this check before producing deployable files.
