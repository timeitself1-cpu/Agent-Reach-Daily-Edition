"""Accuracy pass: regressions taken from a real edition (October 5, 2026).

Every case below was wrong in that edition: unrelated reports joined a story through chained
generic words, filler sentences, cut-off headlines, ads and highlight clips, dropped accented
letters and site boilerplate in excerpts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from agent_reach.config import Settings
from agent_reach.models import CleanedTrendItem, RawTrendItem, SourceName
from agent_reach.pipeline.clusterer import DraftCluster, LinkIndex, SemanticClusterer

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)

#: (source, title, context) from the real edition; the first block forms the clusters under test.
REAL = [
    # FBI arrest (4 reports) glued to an Okinawa murder, a Japan protest, Treasury yields and bombers
    ("news_rss", "FBI arrests woman accused of spying on Taiwan leader's family for China",
     "Wanying Zhang surveilled Taiwanese president's son and family for China while in US, according to FBI"),
    ("news_rss", "FBI arrests a woman accused of spying on Taiwan leader's family for China", ""),
    ("news_rss", "FBI says California woman spied for China on Taiwanese president's son",
     "The 34-year-old woman was arrested as she sought to board a flight to Shanghai from Los Angeles."),
    ("google_news", "FBI Arrests Alleged Chinese Agent Accused of Spying on Son of Taiwan Leader", ""),
    ("news_rss", "US marine, 20, accused of murdering and robbing Japanese woman at hotel in Okinawa",
     "Japan says it has lodged strong protests with the US and seeks tighter discipline of troops stationed in the country"),
    ("google_news", "Japan summons US envoy as Marine arrested over killing in Okinawa", ""),
    ("news_rss", "Treasury yields hold near multiyear highs as traders await data, Fed minutes this week",
     "U.S. Treasury yields inched lower on Monday after a sharp selloff the week prior."),
    ("news_rss", "U.S. Air Force removes all bombers from British air base targeted by a suspected terror attack", ""),
    # Germany warning glued to an AI czar appointment
    ("google_news", "Germany at risk of violent conflict with Russia, intelligence chief says", ""),
    ("news_rss", "Ukraine-Russia war latest: Germany at risk of violent conflict with Putin as war enters new phase",
     "Germany's spy chief says no other country currently poses such a direct threat to Berlin"),
    ("news_rss", "Trump names national intelligence chief Jay Clayton as new AI czar",
     "Trump said Clayton will lead the White House's new Super Intelligence Force."),
    # plane crash glued to a developer API; bug bounty glued to an unrelated open-source release
    ("news_rss", "Six presumed dead as Coast Guard suspends search for missing medical plane near Nantucket",
     "Medical transport plane flying from Bermuda to Boston crashed off coast of Massachusetts"),
    ("youtube", "Urgent search for 6 missing people after a medical aircraft went down",
     "ABC's Morgan Norwood with the latest news after a medical aircraft went missing off the coast of Nantucket."),
    ("hackernews", "Web Search API", "Search the web from your AI agents and applications through AI Gateway."),
    ("news_rss", "Google freezes open-source bug bounty program amid flood of invalid AI slop submissions", ""),
    ("news_rss", "Google froze its open source bug bounty program due to a significant rise in AI submissions", ""),
    ("news_rss", "Flirt is now Open-Source", "Flirt is a review tool that optimizes for the patch series workflow."),
    # the rest of the run: ordinary sentence-case headlines (they teach which words are names)
    ("news_rss", "Spanish PM Sanchez calls early election after housing protests", ""),
    ("news_rss", "Spain's Pedro Sanchez, main critic of Trump in Europe, calls snap elections", ""),
    ("news_rss", "Nobel prize in medicine awarded for research into mysteries of brain", ""),
    ("news_rss", "Method for controlling brain cells with light wins Nobel", ""),
    ("news_rss", "Woman accused of fraud after charity collapse", ""),
    ("news_rss", "Police say a woman was accused of stealing from her employer", ""),
    ("news_rss", "Man accused of arson at a warehouse appears in court", ""),
    ("news_rss", "Two people were arrested and a woman injured after a search of the area", ""),
    ("news_rss", "Brazil vote set for runoff as Flavio Bolsonaro sees surprise lead", ""),
    ("news_rss", "Students blast off to US for Nasa robotics competition", ""),
    ("news_rss", "Amazon ends secret data center pacts and pledges $1 billion to host towns", ""),
    ("news_rss", "Microsoft: Windows update crashes some games and apps", ""),
]


def _items() -> list[CleanedTrendItem]:
    out = []
    for i, (source, title, ctx) in enumerate(REAL, start=1):
        raw = RawTrendItem(title=title, source=SourceName(source), timestamp=NOW)
        out.append(CleanedTrendItem(**raw.model_dump(), item_id=i, normalized_title=title, heuristic_score=0.6,
                                    context=ctx or None))
    return out


def _gate(ids: list[int]) -> list[list[int]]:
    items = _items()
    index = LinkIndex(items, items)
    clusterer = SemanticClusterer(Settings())
    drafts = clusterer._key_name_gate([DraftCluster(item_ids=ids, headline="x", category_raw="News")], index)
    return sorted((sorted(d.item_ids) for d in drafts), key=lambda g: (-len(g), g))


def test_names_are_learned_from_the_run_not_from_title_case():
    index = LinkIndex(_items())
    assert {"fbi", "taiwan", "okinawa", "germany", "nantucket", "google"} <= index.name_words
    assert not {"accused", "woman", "search", "intelligence", "chief"} & index.name_words


def test_spy_arrest_keeps_only_its_own_reports():
    groups = _gate([1, 2, 3, 4, 5, 6, 7, 8])
    assert groups[0] == [1, 2, 3, 4]  # the four FBI / Taiwan reports stay together
    assert [5, 6] in groups  # the Okinawa killing becomes its own story
    assert [7] in groups and [8] in groups  # yields and bombers stand alone (singleton rules decide)


def test_germany_warning_drops_the_ai_czar():
    assert _gate([9, 10, 11]) == [[9, 10], [11]]


def test_short_article_titles_no_longer_attach_through_one_word():
    items = _items()
    index = LinkIndex(items, items)
    assert not index.linked(13, 14)  # 'Web Search API' (Hacker News) is not the plane crash
    assert not index.linked(15, 17)  # 'Flirt is now Open-Source' is not Google's bug bounty
    assert index.linked(15, 16)  # the two bug-bounty reports still link
    assert _gate([12, 13]) == [[12, 13]]  # the two crash reports share 'Nantucket'


def test_a_story_without_shared_names_is_left_to_the_coherence_check():
    assert _gate([20, 21]) == [[20, 21]]  # 'Nobel' is shared: kept
    assert _gate([22, 23]) == [[22, 23]]  # no names at all: unchanged (lexical checks already ran)


# ---------------------------------------------------------------------- sentences and "why it matters"
def test_filler_and_repeated_sentences_are_dropped():
    from agent_reach.daily.edition import body_sentences

    summary = ("Spanish Prime Minister Pedro Sanchez called an early election for November 29. "
               "The election is drawing attention due to the potential defeat of his party. "
               "The election is scheduled for November 29.")
    assert body_sentences(summary) == ["Spanish Prime Minister Pedro Sanchez called an early election for November 29."]
    assert body_sentences("A user built a Mac app with Claude. This showcases the capabilities of the tool.") == \
        ["A user built a Mac app with Claude."]
    assert body_sentences("Three scientists won the Nobel prize. Their research has been published in various "
                          "scientific journals.") == ["Three scientists won the Nobel prize."]


def test_why_it_matters_must_name_a_concrete_effect():
    from agent_reach.daily.brief import concrete_effect

    assert not concrete_effect("The arrest highlights concerns about Chinese espionage in the US.")
    assert not concrete_effect("The transfer market would be significantly impacted.")
    assert not concrete_effect("This showcases the potential of technology in education.")
    assert concrete_effect("Island residents lose their ferry link while the 48-hour strike lasts.")
    assert concrete_effect("Communities will be able to see how much electricity and water data centers use.")
    assert concrete_effect("A defeat for Sanchez's party could bring down a long-serving European leader.")


# ---------------------------------------------------------------------- headlines
def test_headlines_keep_up_to_14_words_and_never_end_mid_phrase():
    from agent_reach.pipeline.cleaner import sanitize_headline

    assert sanitize_headline("How a mass Man City player exodus would warp the transfer market") == \
        "How a Mass Man City Player Exodus Would Warp the Transfer Market"
    long = "Internet Watch Foundation reports huge rise in AI child sexual abuse material found online this year so far"
    out = sanitize_headline(long)
    assert len(out.split()) <= 14 and out.split()[-1].lower() not in {"in", "this", "so", "would", "how"}
    assert sanitize_headline("Apple TV doc All of Us shows how iPads enable inclusive learning in a unique "
                             "school") == "Apple TV Doc All of Us Shows How iPads Enable Inclusive Learning"  # 16 words


def test_topic_labels_are_recognised_and_replaced_by_a_real_title():
    from agent_reach.pipeline.cleaner import is_label_headline

    for label in ("Cornell University Rape Allegations", "Lanterns Finale and Sequel",
                  "Big Tech's Military-Industrial Complex", "Default Hard Budget Caps",
                  "Germany at Risk of Violent Conflict"):
        assert is_label_headline(label), label
    for headline in ("Ransomware Attack Disrupts Halden Hospital Network", "Spanish PM Sanchez Calls Early Election",
                     "Braves Even NLDS Series Against Dodgers", "Nimbus Phone 5 Adds Satellite Messaging",
                     "Astronomers Detect Water Vapour on Exoplanet Tessa-9b"):
        assert not is_label_headline(headline), headline

    items = _items()
    clusterer = SemanticClusterer(Settings())
    draft = DraftCluster(item_ids=[9, 10], headline="Germany at Risk of Violent Conflict", category_raw="News",
                         summary="Germany's spy chief warned of a risk of violent conflict with Russia. The warning "
                                 "came as the war in Ukraine entered a new phase.", relevance=8)
    clusters, _ = clusterer._finalize([draft], {it.item_id: it for it in items})
    assert clusters[0].headline == "Germany at Risk of Violent Conflict with Russia, Intelligence Chief Says"


# ---------------------------------------------------------------------- ranking
def test_strong_news_may_exceed_the_category_cap_and_columns_stay_out_of_top_stories():
    from agent_reach.daily import edition as E
    from agent_reach.daily.prefs import DailyPrefs
    from tests.daily_fakes import make_story

    heads = ["Spain Calls Snap Election", "Nobel Prize Honours Optogenetics", "FBI Arrests Alleged Spy",
             "Brazil Vote Heads to Runoff", "Georgia Shooting Leaves Two Dead", "Germany Warns of Conflict"]
    news = [make_story(headline=h, category="News", relevance=9, now=NOW) for h in heads]
    weak_tech = [make_story(headline=h, category="Tech", relevance=5, now=NOW)
                 for h in ("Phone Update Ships", "Laptop Chip Unveiled", "Browser Adds Tabs", "Router Recall Begins")]
    column = make_story(headline="How I Made a Paid Mac App in 11 Days", category="Tech", relevance=9, now=NOW)
    sel = E.select_stories([column, *news, *weak_tech], DailyPrefs(max_per_category=4), now=NOW)
    top_cats = [s.category.value for s in sel.top]
    assert top_cats.count("News") == 6  # 4 + 2 strong extras
    assert column not in sel.top and sel.stories[-1] is column and sel.secondary == 1
    tech = [s for s in sel.stories if s.category.value == "Tech"]
    assert tech[-1] is column  # listed after the news in its own section


# ---------------------------------------------------------------------- ads, clips, text
def _clean(source: str, title: str, description: str | None = None):
    from agent_reach.pipeline.cleaner import TrendCleaner

    raw = RawTrendItem(title=title, source=SourceName(source), description=description, raw_score=1.0)
    return TrendCleaner(Settings()).clean([raw])


def test_ads_and_highlight_clips_are_filtered_with_a_named_reason():
    kept, stats = _clean("news_rss", "You're not using Claude to its full potential - this $15 E-Degree can help",
                         "TL;DR: on sale now for just $14.97 (MSRP $159) until October 11.")
    assert not kept and stats["promotional"] == 1
    kept, stats = _clean("youtube", "WARRIORS at CLIPPERS | NBA PRESEASON FULL GAME HIGHLIGHTS | October 4")
    assert not kept and stats["video_clip"] == 1
    kept, _ = _clean("youtube", "Brazil vote set for runoff as Flavio Bolsonaro sees surprise lead")
    assert len(kept) == 1
    kept, _ = _clean("news_rss", "Retailers report record Black Friday sales as shoppers return")
    assert len(kept) == 1  # news about sales is not an ad


def test_accented_letters_are_spelled_out_and_boilerplate_is_removed():
    from agent_reach.ingestion.video import video_description
    from agent_reach.pipeline.cleaner import normalize_text
    from agent_reach.pipeline.enricher import extract_page_context

    assert normalize_text("Det Centrale Personregister har konstateret en alvorlig sikkerhedshændelse") == \
        "Det Centrale Personregister har konstateret en alvorlig sikkerhedshaendelse"
    assert normalize_text("Straße in Łódź, Sánchez") == "Strasse in Lodz, Sanchez"
    page = ("<html><head><title>Nobel</title></head><body><article>"
            "<p>Thank you for visiting nature.com. You are using a browser version with limited support for CSS.</p>"
            "<p>Karl Deisseroth, Peter Hegemann and Georg Nagel win the Nobel Prize for their work on optogenetics.</p>"
            "<p>Want to bookmark your favourite articles? Start your Independent Membership today.</p>"
            "</article></body></html>")
    _, _, paragraphs = extract_page_context(page, None, 600)
    assert paragraphs == ["Karl Deisseroth, Peter Hegemann and Georg Nagel win the Nobel Prize for their work on optogenetics."]
    assert video_description("ABC's Morgan Norwood reports on the missing medical aircraft near Nantucket. ABC News "
                             "Digital is your daily source of breaking national and world news.") == \
        "ABC's Morgan Norwood reports on the missing medical aircraft near Nantucket."


# ---------------------------------------------------------------------- sources and the feed doctor
def test_version_4_settings_turn_tiktok_off_and_fix_dead_feeds(daily_paths):
    import json

    from agent_reach.daily.prefs import PREFS_VERSION, DailyPrefs, load_prefs

    old = DailyPrefs().model_dump(mode="json")
    old.update(prefs_version=4, enabled_sources=["google_news", "news_rss", "tiktok", "youtube"])
    old["feeds"] = [
        {"name": "VentureBeat - AI", "url": "https://venturebeat.com/category/ai/feed/", "category": "Science & AI"},
        {"name": "MIT News - Artificial Intelligence", "url": "https://news.mit.edu/rss/topic/artificial-intelligence2",
         "category": "Science & AI", "enabled": False},
        {"name": "Space.com", "url": "https://www.space.com/feeds/all", "category": "Science & AI"},
        {"name": "My Paper", "url": "https://paper.test/rss", "category": "News"},
    ]
    daily_paths.settings.write_text(json.dumps(old))
    prefs, warning = load_prefs(daily_paths)
    assert warning is None and prefs.prefs_version == PREFS_VERSION == 6
    assert "tiktok" not in prefs.enabled_sources and "youtube" in prefs.enabled_sources
    by_name = {f.name: f for f in prefs.feeds}
    assert "VentureBeat - AI" not in by_name and "Space.com" not in by_name
    assert by_name["SpaceNews"].url == "https://spacenews.com/feed/" and by_name["My Paper"].enabled
    assert "MIT News - Artificial Intelligence" not in by_name  # fixed in version 5, removed in version 6
    assert "tiktok" not in DailyPrefs().enabled_sources


def test_feed_doctor_flags_feeds_failing_for_days_but_not_outages(daily_paths):
    from datetime import timedelta

    from agent_reach.daily.feedhealth import failing_feeds, load_feed_health, record_run
    from agent_reach.models import FeedStat, SourceStat

    def run(day: int, broken_ok: bool, all_down: bool = False):
        feeds = [FeedStat(name="Good", url="https://good.test/rss", ok=not all_down, item_count=5),
                 FeedStat(name="Broken", url="https://broken.test/rss", ok=broken_ok and not all_down, error="HTTP 404")]
        record_run(daily_paths, [SourceStat(source="news_rss", ok=True, item_count=5, latency_ms=1, feeds=feeds)],
                   NOW + timedelta(days=day))

    run(0, False)
    run(1, False)
    assert failing_feeds(load_feed_health(daily_paths), NOW + timedelta(days=1)) == []  # not three days yet
    run(2, False, all_down=True)  # offline day: skipped, not counted against either feed
    run(3, False)
    flagged = failing_feeds(load_feed_health(daily_paths), NOW + timedelta(days=3))
    assert [r.name for r in flagged] == ["Broken"] and flagged[0].failures_in_row == 3
    run(4, True)  # it works again: no longer flagged
    assert failing_feeds(load_feed_health(daily_paths), NOW + timedelta(days=4)) == []
