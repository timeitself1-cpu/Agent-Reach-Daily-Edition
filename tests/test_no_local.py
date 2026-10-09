"""The Local section is gone (rc19, Oct 9, 2026): rc18 added it for Frisco, Texas the same day and the user
asked for it to be removed entirely. New editions never file a story under Local, settings drop the local
feeds and the area, and editions saved with a Local section (rc18) still load and show it as it was."""

from __future__ import annotations

import json

from agent_reach.daily import publish as P
from agent_reach.daily.edition import SECTION_ORDER, DailyEdition, all_categories, category_sections
from agent_reach.daily.feeds import REMOVED_IN_V12, default_feeds
from agent_reach.daily.prefs import PREFS_VERSION, DailyPrefs, build_settings, load_prefs
from agent_reach.models import CategoryEnum
from agent_reach.pipeline.clusterer import _relabel_schema, coerce_category, ordinary
from tests.daily_fakes import make_edition, make_story

NEWS, SPORTS, LOCAL = CategoryEnum.NEWS, CategoryEnum.SPORTS, CategoryEnum.LOCAL
RC18_LOCAL_FEEDS = [
    {"name": "City of Frisco - News", "url": REMOVED_IN_V12[0], "category": "Local"},
    {"name": "NBC DFW - Local", "url": REMOVED_IN_V12[1], "category": "Local"},
    {"name": "WFAA - Local", "url": REMOVED_IN_V12[2], "category": "Local"},
    {"name": "FOX 4 Dallas-Fort Worth - Local", "url": REMOVED_IN_V12[3], "category": "Local"},
    {"name": "CBS News Texas", "url": REMOVED_IN_V12[4], "category": "Local"},
]


def test_no_new_story_can_be_filed_under_local():
    assert "Local" not in SECTION_ORDER and "Local" not in all_categories()
    assert _relabel_schema()["properties"]["groups"]["items"]["properties"]["category"]["enum"] == CategoryEnum.model_values()
    assert "Local" not in CategoryEnum.model_values()
    assert coerce_category("Local", NEWS) is NEWS and coerce_category("local", SPORTS) is SPORTS
    # a feed the user still has with category Local counts as general news
    assert ordinary(LOCAL) is NEWS and ordinary(SPORTS) is SPORTS and ordinary(None) is None


def test_no_default_feed_or_search_exists_only_for_local(daily_paths):
    assert not [f for f in default_feeds() if f.category == "Local"]
    assert not {u.lower() for u in REMOVED_IN_V12} & {f.url.lower() for f in default_feeds()}
    s = build_settings(DailyPrefs(), daily_paths)
    assert not [e for e in s.google_news_sections if e.startswith("Local|")]
    assert not hasattr(s, "local_area")


def test_version_11_settings_lose_the_local_feeds_and_area_but_keep_the_users_own(daily_paths):
    mine = {"name": "My Town Paper", "url": "https://paper.test/rss", "category": "Local"}
    news = [f.model_dump() for f in default_feeds()[:3]]
    old = {"prefs_version": 11, "local_area": "frisco-tx", "feeds": news + RC18_LOCAL_FEEDS + [mine]}
    daily_paths.settings.write_text(json.dumps(old))
    prefs, warning = load_prefs(daily_paths)
    assert warning is None and prefs.prefs_version == PREFS_VERSION == 12
    assert [f.url for f in prefs.feeds] == [f["url"] for f in news] + [mine["url"]]
    assert "local_area" not in prefs.model_dump()
    # the rc18 setting that turned the section off is dropped too
    daily_paths.settings.write_text(json.dumps({**old, "local_area": ""}))
    assert "local_area" not in load_prefs(daily_paths)[0].model_dump()


def test_an_rc18_edition_with_a_local_section_still_loads_and_shows_it_last():
    ed = make_edition([make_story(1), make_story(2, headline="Frisco Council Approves Library Branch", category="Local"),
                       make_story(3, headline="Riverton Hawks Win Final", category="Sports")])
    again = DailyEdition.model_validate_json(ed.model_dump_json())
    assert [cat for cat, _ in category_sections(again)] == ["News", "Sports", "Local"]
    pub = P.public_edition(again)
    assert [s["category"] for s in pub["stories"]].count("Local") == 1  # history is published as it was


def test_the_sitemap_no_longer_lists_a_local_page():
    assert "/local/" not in P.sitemap_xml({"editions": []}).decode()
