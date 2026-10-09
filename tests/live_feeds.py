"""Check feeds against the live sites (needs internet: CI workflow feed-check, never the offline suite).

    python -m tests.live_feeds              # the Local candidates and the Local Google News searches
    python -m tests.live_feeds --defaults   # every default Local feed

Prints one line per feed and a Markdown table to $GITHUB_STEP_SUMMARY when it is set. Exits 1 only when
no feed at all answered (the network is down), so one dead feed never blocks a push.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

from agent_reach.config import Settings
from agent_reach.daily.feeds import DEFAULT_FEEDS, LOCAL_CANDIDATES, check_feed
from agent_reach.ingestion.search import GoogleNewsIngester
from agent_reach.pipeline.local import google_news_sections


def google_sections(area: str) -> list[tuple[str, bool, str]]:
    settings = Settings(google_news_sections=google_news_sections(area), http_max_retries=1)

    async def run():
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            ing = GoogleNewsIngester(client, settings, asyncio.Semaphore(2))
            await ing.run()
            return ing.feed_stats or []

    stats = asyncio.run(run())
    return [(s.name, s.ok, f"{s.item_count} articles" if s.ok else (s.error or "failed")) for s in stats]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--defaults", action="store_true", help="check the default Local feeds instead of the candidates")
    p.add_argument("--area", default="frisco-tx")
    args = p.parse_args(argv)
    feeds = [f for f in DEFAULT_FEEDS if f.category == "Local"] if args.defaults else LOCAL_CANDIDATES
    rows = []
    for f in feeds:
        r = check_feed(f)
        rows.append((f.name, r.ok, f"{r.message} ({f.url})"))
    rows += google_sections(args.area)
    for name, ok, msg in rows:
        print(f"{'OK  ' if ok else 'FAIL'} {name}: {msg}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("| Feed | Result |\n| --- | --- |\n")
            fh.writelines(f"| {name} | {'OK' if ok else 'FAIL'}: {msg.replace('|', '/')} |\n" for name, ok, msg in rows)
    return 0 if any(ok for _, ok, _ in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
