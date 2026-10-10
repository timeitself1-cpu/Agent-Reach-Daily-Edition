"""One renderer (render.py): the same content in both frames, one taxonomy, one timestamp policy."""

from __future__ import annotations

import json
import re

from agent_reach.daily import publish as P
from agent_reach.daily.edition import SECTION_ORDER
from agent_reach.daily.render import render_edition_html
from agent_reach.daily.sections import SECTIONS_FILE, load_sections, section_label
from agent_reach.models import CategoryEnum
from tests.test_daily_publish import real_edition


def _public():
    return P.public_edition(real_edition())


def test_sections_json_is_the_taxonomy_of_the_app():
    ids = [s["id"] for s in load_sections()["sections"]]
    assert sorted(ids) == sorted(CategoryEnum.values())  # every category has a label, nothing extra
    assert SECTION_ORDER == [i for i in ids if i != "Local"]
    assert section_label("News") == "World & Nation" and section_label("Tech") == "Technology"
    assert json.loads(P.sections_bytes()) == json.loads(SECTIONS_FILE.read_text(encoding="utf-8"))


def test_both_frames_carry_the_same_content():
    public = _public()
    live, solo = render_edition_html(public), render_edition_html(public, standalone=True)
    for page in (live, solo):
        assert page.count("<article ") == len({i for sec in [public["top"]] + [s["ids"] for s in public["sections"]] for i in sec})
        for story in public["stories"]:
            if f'id="story-{story["id"]}"' not in page:
                continue
            assert "Why it matters</strong>" in page or not story.get("why_it_matters")
        assert "What changed since last refresh" in page and "Sources (" in page
        assert "Single source" in page or "coverage" in page.lower()
        assert "World &amp; Nation" in page and 'href="#sec-top-stories"' in page
    # only the frame differs
    assert "/assets/site.js" in live and "/assets/site.css" in live and "<style>" not in live
    assert "<script" not in solo and "<link" not in solo and " src=" not in solo and "<style>" in solo
    assert "Content-Security-Policy" in solo


def test_every_story_keeps_its_sources_and_why_it_matters():
    public = _public()
    page = render_edition_html(public)
    for story in public["stories"]:
        anchor = f'id="story-{story["id"]}"'
        if anchor not in page:
            continue  # shown once, in its first section
        art = re.search(rf'<article [^>]*{re.escape(anchor)}.*?</article>', page, re.S).group(0)
        assert f"Sources ({len(story['sources'])})" in art
        assert ("Why it matters" in art) == bool(story.get("why_it_matters"))


def test_timestamps_live_is_utc_marked_for_the_reader_and_standalone_is_central():
    public = _public()
    live, solo = render_edition_html(public), render_edition_html(public, standalone=True)
    assert 'data-local="true"' in live and " UTC<" in live and "CDT<" not in live and "CST<" not in live
    assert "data-local" not in solo and re.search(r"(CDT|CST)</time>", solo) and "UTC</time>" not in solo
    assert "America/Chicago" in solo
    assert re.search(r"<time datetime=\"[0-9TZ:-]+\">[A-Z][a-z]+ \d+, \d{4} at \d+:\d\d (AM|PM) CDT</time>", solo)


def test_publication_time_only_when_a_source_stated_it():
    public = _public()
    stated = [x for s in public["stories"] for x in s["sources"] if x["published_utc"]]
    unstated = [x for s in public["stories"] for x in s["sources"] if not x["published_utc"]]
    assert stated and unstated
    page = render_edition_html(public, standalone=True)
    assert page.count("publication time not stated") >= len(unstated) > 0
    assert page.count("published <time") >= 1
    assert "retrieved" not in page.lower()  # a retrieval time is never shown as a publication time


def test_shell_page_falls_back_to_the_previous_template(monkeypatch):
    public = _public()
    assert P.shell_page(public).startswith(b"<!doctype html>")
    monkeypatch.setattr(P, "render_edition_html", lambda *a, **k: 1 / 0)
    assert P.shell_page(public) == P.edition_page(public)  # the old template still works and is kept


def test_rss_stays_utc():
    index = P.merge_index(None, P.index_entry(_public()))
    assert b"GMT</pubDate>" in P.feed_xml(index)


def test_standalone_export_marks_the_demo_and_keeps_notes():
    from tests.daily_fakes import make_edition, make_story

    ed = make_edition([make_story(headline="Demo One"), make_story(headline="Demo Two"), make_story(headline="Demo Three")], demo=True)
    ed.notes = ["Only 3 of 9 feeds answered."]
    page = render_edition_html(P.public_edition(ed, export=True), standalone=True)
    assert "<title>DEMO - " in page and "These are not real news stories" in page
    assert "Only 3 of 9 feeds answered." in page and "<script" not in page
