import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from agent_reach.config import Settings
from agent_reach.daily.render import render_edition_html
from agent_reach.daily.sections import load_sections, section_groups, section_target

FIXTURE = Path(__file__).parent / "fixtures/taxonomy-2026-10-10.json"


def test_current_retirement_overrides_old_edition_taxonomy():
    public = json.loads(FIXTURE.read_text())
    public["taxonomy"] = {"Internet Culture": {"label": "Internet Culture"}}
    assert section_target("Internet Culture") == "Tech"
    row = next(s for s in load_sections()["sections"] if s["id"] == "Internet Culture")
    assert row["merged_into"] == "technology" and row["retired"]
    assert not any(g["category"] == "Internet Culture" for g in section_groups(public))
    assert any(g["category"] == "Tech" for g in section_groups(public, 1))
    for standalone in (False, True):
        page = BeautifulSoup(render_edition_html(public, standalone=standalone), "html.parser")
        assert page.select_one("#sec-internet-culture") is None
        assert page.select_one("#sec-tech .count").text == "3 stories"
        assert page.select_one("#sec-also-today .count").text == "1 story"


@pytest.mark.parametrize("size,folded", [(2, True), (3, False), (4, False)])
@pytest.mark.parametrize("standalone", [False, True])
def test_threshold_counts_and_articles(size, folded, standalone):
    public = json.loads(FIXTURE.read_text())
    public["stories"] = public["stories"][:size]
    public["top"] = [public["stories"][0]["id"]]
    ids = [s["id"] for s in public["stories"]]
    public["sections"] = [{"category": "Sports", "ids": ids}]
    page = BeautifulSoup(render_edition_html(public, standalone=standalone), "html.parser")
    label = "Also today" if folded else "Sports"
    slug = "sec-also-today" if folded else "sec-sports"
    assert page.select_one(f'nav.sections a[href="#{slug}"]').text == f"{label} ({size})"
    section = page.select_one("#" + slug)
    assert section.h2.text == label
    assert section.select_one(".count").text == f"{size} stories"
    # Top stories have complete cards once, then ordinary links in their category group.
    assert len(section.select("article")) + len(section.select("ul.also li")) == size
    assert len(page.select("article[id]")) == size


def test_fixture_before_and_after():
    public = json.loads(FIXTURE.read_text())
    before = {s["category"]: len(s["ids"]) for s in public["sections"]}
    after = {s["category"]: len(s["ids"]) for s in section_groups(public)}
    assert before == {"News": 9, "Tech": 2, "Science & AI": 9, "Sports": 3, "Entertainment": 1, "Internet Culture": 1}
    assert after == {"News": 9, "Tech": 3, "Science & AI": 9, "Sports": 3, "Also today": 1}
    assert sum(after.values()) == len(public["stories"])
    assert Settings().min_section_stories == 3


def test_setting_overrides_default_for_old_editions(monkeypatch):
    public = json.loads(FIXTURE.read_text())
    monkeypatch.setenv("AGENT_REACH_MIN_SECTION_STORIES", "4")
    assert not any(g["category"] in ("Tech", "Sports") for g in section_groups(public))
    public["min_section_stories"] = 3
    assert any(g["category"] == "Tech" for g in section_groups(public))
