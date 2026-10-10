#!/usr/bin/env python3
"""Taxonomy contract check.

The ONE taxonomy is agent_reach/daily/sections.json. The website keeps a
fallback table in website/assets/site.js (used when editions/sections.json
cannot be fetched). The two must agree on every section id: same label,
same retired status. Any drift fails the build.

Run from the repo root:  python3 scripts/check_taxonomy_contract.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTIONS_JSON = ROOT / "agent_reach" / "daily" / "sections.json"
SITE_JS = ROOT / "website" / "assets" / "site.js"

ENTRY_RE = re.compile(r"^\s*'((?:[^'\\]|\\.)+)':\s*\{([^}]*)\},?\s*$", re.M)
FIELD_RE = re.compile(r"(\w+):\s*'((?:[^'\\]|\\.)*)'")


def parse_site_js() -> dict[str, dict[str, str]]:
    text = SITE_JS.read_text(encoding="utf-8")
    # Isolate the SECTION table: from "const SECTION = {" to the matching "};"
    m = re.search(r"const SECTION = \{(.*?)\n  \};", text, re.S)
    if not m:
        raise SystemExit("could not locate const SECTION table in site.js")
    entries: dict[str, dict[str, str]] = {}
    for em in ENTRY_RE.finditer(m.group(1)):
        sid, body = em.group(1), em.group(2)
        entries[sid] = dict(FIELD_RE.findall(body))
    if not entries:
        raise SystemExit("parsed zero SECTION entries from site.js")
    return entries


def main() -> int:
    canonical = json.loads(SECTIONS_JSON.read_text(encoding="utf-8"))["sections"]
    fallback = parse_site_js()
    errors: list[str] = []

    for sec in canonical:
        sid = sec["id"]
        if sid not in fallback:
            errors.append(f"site.js missing section id {sid!r}")
            continue
        fb = fallback[sid]
        if fb.get("label") != sec["label"]:
            errors.append(
                f"label mismatch for {sid!r}: sections.json={sec['label']!r} "
                f"site.js={fb.get('label')!r}"
            )
        retired_json = sec.get("retired")
        retired_js = fb.get("retired")
        if bool(retired_json) != bool(retired_js):
            errors.append(
                f"retired-flag mismatch for {sid!r}: sections.json={retired_json!r} "
                f"site.js={retired_js!r}"
            )
        elif retired_json and retired_json != retired_js:
            errors.append(
                f"retired-date mismatch for {sid!r}: sections.json={retired_json!r} "
                f"site.js={retired_js!r}"
            )

    for sid, fb in fallback.items():
        if not fb.get("retired") and not any(s["id"] == sid for s in canonical):
            errors.append(f"site.js has active section {sid!r} absent from sections.json")

    if errors:
        print("TAXONOMY CONTRACT FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(
        f"taxonomy contract OK: {len(canonical)} sections agree "
        f"(sections.json <-> site.js fallback)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
