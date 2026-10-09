"""The Local section: which stories file under Local (agent_reach/pipeline/local.py), and how it reaches the
settings, the model's choices and the edition's section order."""

from __future__ import annotations

import json
from types import SimpleNamespace

from agent_reach.daily.edition import SECTION_ORDER
from agent_reach.daily.feeds import ADDED_IN_V11, DEFAULT_FEEDS, LOCAL_CANDIDATES
from agent_reach.models import CategoryEnum
from agent_reach.pipeline.clusterer import coerce_category
from agent_reach.pipeline.local import FRISCO_TX, area, google_news_sections, is_local, ordinary

LOCAL, NEWS, SPORTS = CategoryEnum.LOCAL, CategoryEnum.NEWS, CategoryEnum.SPORTS


def item(title: str, description: str = "", hint: CategoryEnum | None = None):
    return SimpleNamespace(normalized_title=title, description=description, category_hint=hint)


def test_a_title_naming_a_town_of_the_area_is_local_from_any_outlet():
    for title in ("Frisco City Council Approves New Library Branch",
                  "Collin County Commissioners Set Tax Rate",
                  "Frisco ISD Trustees Approve Budget",
                  "Plano Police Investigate Overnight Shooting",
                  "McKinney, Texas, Opens New Airport Terminal"):
        assert is_local(NEWS, [item(title)], FRISCO_TX), title


def test_other_friscos_surnames_and_plain_words_are_not_local():
    for title, description in (
            ("Frisco, Colorado Ski Resorts Open Early", ""),
            ("Snow Closes Roads Near Frisco", "Summit County deputies closed Highway 9 toward Breckenridge."),
            ("Former Rep. Cynthia McKinney Speaks at Rally", ""),
            ("How Small Businesses Can Prosper in 2027", ""),
            ("Attorney General Garland Testifies", "")):
        assert not is_local(NEWS, [item(title, description)], FRISCO_TX), title


def test_a_local_feed_report_naming_the_region_is_local_but_its_national_story_is_not():
    assert is_local(NEWS, [item("Storms Knock Out Power Across North Texas", hint=LOCAL)], FRISCO_TX)
    assert is_local(NEWS, [item("DART Board Votes on Rail Plan", "Dallas commuters would ...", LOCAL)], FRISCO_TX)
    # a TV station's national story: no local place, so it is categorised as usual
    assert not is_local(NEWS, [item("Senate Passes Spending Bill", "Washington lawmakers ...", LOCAL)], FRISCO_TX)
    # the region alone counts only from a local feed
    assert not is_local(NEWS, [item("Dallas Fed Raises Growth Forecast")], FRISCO_TX)


def test_pro_sports_stay_in_sports_and_school_sports_are_local():
    cowboys = item("Cowboys Activate Linebacker From Injured Reserve",
                   "FRISCO, Texas (AP) - The Dallas Cowboys activated ...")
    assert not is_local(SPORTS, [cowboys], FRISCO_TX)
    assert is_local(SPORTS, [item("Frisco ISD Football Moves to New Stadium Schedule")], FRISCO_TX)


def test_without_an_area_nothing_is_local_and_a_local_hint_counts_as_news():
    assert not is_local(NEWS, [item("Frisco City Council Approves New Library Branch")], area(""))
    assert ordinary(LOCAL) is NEWS and ordinary(SPORTS) is SPORTS and ordinary(None) is None


def test_the_model_never_chooses_local():
    assert "Local" not in CategoryEnum.model_values() and "Local" in CategoryEnum.values()
    assert coerce_category("Local", NEWS) is NEWS and coerce_category("local", SPORTS) is SPORTS
    from agent_reach.pipeline.clusterer import _relabel_schema
    category = _relabel_schema()["properties"]["groups"]["items"]["properties"]["category"]
    assert category["enum"] == CategoryEnum.model_values()


def test_the_area_brings_its_google_news_searches_and_a_section_after_world_news():
    sections = google_news_sections("frisco-tx")
    assert sections and all(s.startswith("Local|") for s in sections)
    assert google_news_sections("") == [] and google_news_sections("nowhere") == []
    assert SECTION_ORDER.index("Local") == SECTION_ORDER.index("News") + 1


def test_local_feeds_are_local_and_only_checked_ones_are_defaults():
    assert all(f.category == "Local" for f in LOCAL_CANDIDATES + ADDED_IN_V11)
    assert {f.url for f in ADDED_IN_V11} <= {f.url for f in LOCAL_CANDIDATES}
    assert all(f in DEFAULT_FEEDS for f in ADDED_IN_V11)


def test_version_10_settings_gain_the_local_section(daily_paths):
    from agent_reach.daily.feeds import default_feeds
    from agent_reach.daily.prefs import PREFS_VERSION, load_prefs

    old = {"prefs_version": 10, "feeds": [f.model_dump() for f in default_feeds() if f.category != "Local"]}
    daily_paths.settings.write_text(json.dumps(old))
    prefs, warning = load_prefs(daily_paths)
    assert warning is None and prefs.prefs_version == PREFS_VERSION == 11
    assert prefs.local_area == "frisco-tx"
    assert {f.url for f in ADDED_IN_V11} <= {f.url for f in prefs.feeds}
    # a reader who turned the Local section off keeps it off
    daily_paths.settings.write_text(json.dumps({**old, "prefs_version": 11, "local_area": ""}))
    assert load_prefs(daily_paths)[0].local_area == ""
