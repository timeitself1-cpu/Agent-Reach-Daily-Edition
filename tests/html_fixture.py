"""Turn an exported Daily HTML page (``render_html``) back into a fixture JSON.

The user often sends the HTML export of a real edition (it is what they read). The page carries every
story's headline, summary, "why it matters", evidence-strength line and the full evidence list (source,
title, link, publisher, publication time, excerpt), which is what the clustering and summary regression
tests need. Item ids are not in the page, so every evidence line becomes its own record.

    python -m tests.html_fixture <AgentReachDaily-YYYY-MM-DD.html> tests/fixtures/real/<name>.json

Check the output for personal data before committing (``grep -iE "downt|@gmail"``).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

CATEGORIES = ("Science & AI", "Internet Culture", "Entertainment", "Sports", "Tech", "News", "Local")
_WHEN_RX = re.compile(r"(published|retrieved) ([A-Z][a-z]+ \d{1,2}, \d{4} at \d{1,2}:\d{2} [AP]M) (CDT|CST)")


def central_to_utc(text: str, zone: str) -> str:
    local = datetime.strptime(text, "%B %d, %Y at %I:%M %p")
    offset = timedelta(hours=5 if zone == "CDT" else 6)
    return (local + offset).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stories: list[dict] = []
        self.footer = ""
        self.subtitle = ""
        self.section = ""
        self._stack: list[tuple[str, dict]] = []
        self._story: dict | None = None
        self._ev: dict | None = None
        self._field: str | None = None
        self._buf: list[str] = []

    # a tiny state machine over the renderer's fixed markup
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "") or ""
        if tag == "section" and "sec" in cls.split():
            self.section = ""
            self._begin("section_title_pending")
        if tag == "h2" and self._field == "section_title_pending":
            self._begin("section")
        if tag == "article":
            self._story = {"section": self.section, "anchor": a.get("id", ""), "kicker": "", "headline": "",
                           "url": None, "summary": "", "why_it_matters": None, "strength": "", "evidence": []}
            self._begin("kicker_wait")
        elif self._story is not None:
            if tag == "div" and cls == "kicker":
                self._begin("kicker")
            elif tag == "h3":
                self._begin("headline")
            elif tag == "a" and cls == "hl" and self._field == "headline":
                self._story["url"] = a.get("href")
            elif tag == "p" and not cls and self._field in ("kicker_done", "headline_done"):
                self._begin("summary")
            elif tag == "p" and cls == "why":
                self._begin("why")
            elif tag == "p" and cls == "strength":
                self._begin("strength")
            elif tag == "li" and self._field in ("strength_done", "ev_done"):
                self._ev = {"line": "", "url": None, "title": "", "excerpt": ""}
                self._begin("ev")
            elif tag == "a" and self._field == "ev" and self._ev is not None:
                self._ev["url"] = a.get("href")
                self._flush_into_ev("line")
                self._begin("ev_title")
            elif tag == "span" and cls == "excerpt" and self._ev is not None:
                self._flush_into_ev("line")
                self._begin("ev_excerpt")
        if tag == "footer":
            self._begin("footer")
        if tag == "p" and cls == "sub":
            self._begin("subtitle")

    def handle_endtag(self, tag):
        f = self._field
        if f == "section" and tag == "h2":
            self.section = self._take()
            self._field = None
        elif f == "kicker" and tag == "div":
            self._story["kicker"] = self._take()
            self._field = "kicker_done"
        elif f == "headline" and tag == "h3":
            self._story["headline"] = re.sub(r"^\d+\.\s*", "", self._take())
            self._field = "headline_done"
        elif f == "summary" and tag == "p":
            self._story["summary"] = self._take()
            self._field = "summary_done"
        elif f == "why" and tag == "p":
            self._story["why_it_matters"] = re.sub(r"^Why it matters\s*", "", self._take())
            self._field = "why_done"
        elif f == "strength" and tag == "p":
            self._story["strength"] = self._take()
            self._field = "strength_done"
        elif f == "ev_title" and tag == "a":
            self._ev["title"] = self._take()
            self._field = "ev"
        elif f == "ev_excerpt" and tag == "span":
            self._ev["excerpt"] = self._take()
            self._field = "ev"
        elif f == "ev" and tag == "li":
            self._flush_into_ev("line")
            self._story["evidence"].append(self._ev)
            self._ev = None
            self._field = "ev_done"
        elif tag == "article" and self._story is not None:
            self.stories.append(self._story)
            self._story = None
            self._field = None
        elif f == "footer" and tag == "footer":
            self.footer = self._take()
            self._field = None
        elif f == "subtitle" and tag == "p":
            self.subtitle = self._take()
            self._field = None

    def handle_data(self, data):
        if self._field in ("section", "kicker", "headline", "summary", "why", "strength", "ev", "ev_title",
                           "ev_excerpt", "footer", "subtitle"):
            self._buf.append(data)

    def _begin(self, field: str) -> None:
        self._field = field
        self._buf = []

    def _take(self) -> str:
        text = " ".join("".join(self._buf).split())
        self._buf = []
        return text

    def _flush_into_ev(self, key: str) -> None:
        self._ev[key] = (self._ev[key] + " " + self._take()).strip()


def parse_edition_html(text: str) -> dict:
    page = _Page()
    page.feed(text)
    stories = []
    for n, s in enumerate(page.stories, start=1):
        evidence = []
        for ev in s["evidence"]:
            line = ev.pop("line")
            source_name = line.split(":", 1)[0].strip()
            pub = re.search(r"\(([^()]*)\)\s*·", line)
            when = _WHEN_RX.search(line)
            evidence.append({
                "source_name": source_name, "title": ev["title"], "url": ev["url"],
                "publisher": pub.group(1) if pub else None,
                "published_at_utc": central_to_utc(when.group(2), when.group(3)) if when and when.group(1) == "published" else None,
                "retrieved_at_utc": central_to_utc(when.group(2), when.group(3)) if when and when.group(1) == "retrieved" else None,
                "excerpt": ev["excerpt"] or None,
            })
        kicker = s["kicker"]
        tag = "new" if " new " in f" {kicker} " else "updated" if " updated " in f" {kicker} " else ""
        category = next((c for c in CATEGORIES if kicker.startswith(c + " ")), None)
        stories.append({"card": n, "anchor": s["anchor"], "section": s["section"], "category": category, "tag": tag, "headline": s["headline"], "url": s["url"], "summary": s["summary"],
                        "why_it_matters": s["why_it_matters"], "strength": s["strength"], "evidence": evidence})
    return {"source": "html_export", "subtitle": page.subtitle, "footer": page.footer, "stories": stories}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    data = parse_edition_html(Path(argv[0]).read_text(encoding="utf-8"))
    Path(argv[1]).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(data['stories'])} story cards, {sum(len(s['evidence']) for s in data['stories'])} evidence lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
