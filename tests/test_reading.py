"""Reading features: In brief, NEW / UPDATED / DAY n tags, follow and mute, read state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent_reach.daily import reading as RD
from agent_reach.daily.changes import compare_editions
from agent_reach.daily.store import EditionStore
from tests.daily_fakes import make_edition, make_story

T0 = datetime(2026, 10, 3, 12, 5, tzinfo=timezone.utc)


def _story(headline, **kw):
    return make_story(headline=headline, **kw)


def test_in_brief_takes_the_lead_sentence_of_the_top_stories():
    long = "A " + "very " * 60 + "long sentence."
    stories = [_story(f"Story {i}", sentences=[f"Lead sentence {i}.", "Second."]) for i in range(1, 8)]
    stories[1].sentences = [long]
    brief = RD.in_brief(stories)
    assert len(brief) == 5 and brief[0][1] == "Lead sentence 1."
    assert len(brief[1][1]) <= RD.BRIEF_CHARS + 3 and brief[1][1].endswith("...")


def test_follow_and_mute_match_whole_words_in_any_case():
    a = _story("Packers Beat Falcons", sentences=["Jordan Love threw three touchdowns."])
    b = _story("Apple Unveils Vision Headset")
    c = _story("Pineapple Prices Rise")
    assert RD.matching_topics(a, ["jordan love", "Falcons", "Lions"]) == ["jordan love", "Falcons"]
    kept, muted = RD.without_muted([a, b, c], ["apple"])
    assert [s.headline for s in kept] == ["Packers Beat Falcons", "Pineapple Prices Rise"] and muted == 1
    assert RD.followed([a, b, c], ["packers"]) == [a]
    assert RD.followed([a, b, c], []) == []


def test_topic_suggestions_prefer_key_names():
    s = _story("Spanish PM Sanchez Calls Snap Election")
    s.entities = ["Pedro Sanchez", "Spain"]
    assert RD.topic_suggestions(s) == ["Pedro Sanchez", "Spain"]
    s.entities = []
    assert "Sanchez" in " ".join(RD.topic_suggestions(s))


def test_new_updated_and_day_tags_across_editions(daily_paths):
    store = EditionStore(daily_paths)
    ferry = dict(headline="Norvale Ferry Strike Halts Island Service", url="https://wire-one.test/ferry")
    day1 = make_edition([_story(now=T0, **ferry), _story("Old Story Fades Away", now=T0,
                                                         url="https://wire-one.test/old")], started=T0, run_id="r1")
    t1, t2 = T0 + timedelta(days=1), T0 + timedelta(days=2)
    day2 = make_edition([_story(now=t1, **ferry)], started=t1, run_id="r2")
    day3 = make_edition([_story(now=t2, **ferry), _story("Quake Strikes Port Calder", now=t2,
                                                         url="https://wire-one.test/quake")], started=t2, run_id="r3")
    day3.changes = compare_editions(day2, day3)
    for ed in (day1, day2, day3):
        store.publish(ed)
    tags = RD.change_tags(day3)
    assert tags == {2: "new"}
    from agent_reach.daily.app import AppController

    ctrl = AppController(daily_paths)
    since = ctrl.developing(store.load_latest().edition)
    assert since == {1: day1.edition_date}  # the ferry strike has run for three days
    assert RD.day_label(since[1], day3.edition_date) == "Day 3"


def test_read_state_round_trip_and_pruning(daily_paths):
    now = T0
    RD.set_read(daily_paths, ["a", "b"], now)
    assert set(RD.load_reading(daily_paths).read) == {"a", "b"}
    RD.set_read(daily_paths, ["a"], now, read=False)
    assert set(RD.load_reading(daily_paths).read) == {"b"}
    RD.set_read(daily_paths, ["c"], now + timedelta(days=RD.READ_KEEP_DAYS + 1))
    assert set(RD.load_reading(daily_paths).read) == {"c"}  # old marks are forgotten
    (daily_paths.state_dir / "reading.json").write_text("{broken")
    assert RD.load_reading(daily_paths).read == {}


def test_topics_settings_are_cleaned(daily_paths):
    from agent_reach.daily.prefs import DailyPrefs

    p = DailyPrefs(follow_topics=["  Packers ", "packers", "x", "Jordan   Love"], mute_topics=["Crypto"])
    assert p.follow_topics == ["Packers", "Jordan Love"] and p.mute_topics == ["Crypto"]


def test_export_has_in_brief_and_new_tags():
    from agent_reach.daily.render_html import render_edition_html

    t1 = T0 + timedelta(days=1)
    old = make_edition([_story("Norvale Ferry Strike Halts Island Service", now=T0, url="https://wire-one.test/a")],
                       started=T0)
    new = make_edition([_story("Norvale Ferry Strike Halts Island Service", now=t1, url="https://wire-one.test/a"),
                        _story("Quake Strikes Port Calder", now=t1, url="https://wire-one.test/b"),
                        _story("Hawks Win Final", now=t1, url="https://wire-one.test/c", category="Sports")],
                       started=t1)
    new.changes = compare_editions(old, new)
    page = render_edition_html(new)
    assert '<section class="brief" aria-label="In brief">' in page and 'href="#story-1"' in page
    assert page.count('<span class="tag new">new</span>') == 2
