# Agent Reach Daily: source handoff

Open CLAUDE_HANDOFF.md and send it to Claude with this ZIP attached.

This package contains the updated Agent Reach v2.1 source and a detailed implementation brief for a Windows daily news app. The daily GUI, 24-hour scheduler and atomic daily-edition cache requested in the brief are NOT implemented yet.

The source includes local reliability fixes and their tests, not yet committed/published as a PR. Existing CLI/setup scripts remain included. Follow the handoff brief to build the desktop product.

Package prepared for the October 1, 2026 handoff. Original real-data replay fixtures were captured September 25, 2026; their synthetic variants are clearly identified.

Included: Python modules, tests/fixtures, documentation, dependency lists, PowerShell launchers, GitHub workflows and .env.example. Excluded: actual .env secrets, virtual environments, Git internals, databases, runtime reports and caches.

MANIFEST.json lists the SHA-256 and size of every packaged payload file. It intentionally does not hash itself.
