"""Second accuracy pass: regressions from a real evening edition (October 5, 2026, revision 2).

That edition grouped stories that only shared one phrase ('Supreme Court', 'iPhone 18 Pro',
'dies aged', 'Iranian drone', 'data centres') or a surname from a trend list ('Williams').
"""

from __future__ import annotations

import random

from agent_reach.models import CleanedTrendItem, RawTrendItem, SourceName
from agent_reach.pipeline.clusterer import LinkIndex
from tests.test_accuracy import NOW, REAL

#: (source, title, context) as they appeared in the edition
EVENING = [
    # 1-6: three different Supreme Court stories in one
    ("google_news", "New Supreme Court term begins with justices stumped by climate change case", ""),
    ("news_rss", "Supreme Court hears case on holding energy companies liable for climate change",
     "Supreme Court justices heard arguments in a major climate change case."),
    ("news_rss", "Supreme Court hears arguments in climate change case seeking to hold companies liable",
     "The Supreme Court began its new term by hearing arguments in a case seeking to hold energy companies liable."),
    ("google_news", "Longshot Bid to Block Paramount-Warner Bros. Discovery Merger Filed to Supreme Court", ""),
    ("news_rss", "Supreme Court Justice Denies Last-Minute Effort To Halt Paramount-Warner Bros. Discovery Merger",
     "The petition is a Hail Mary pass to stave off the deal, scheduled to close on Tuesday."),
    ("news_rss", "SIR row: Will annul EC orders not in keeping with law, says Supreme Court",
     "Supreme Court on Monday asked the Election Commission to clarify"),
    # 7-11: five different Apple stories in one
    ("news_rss", "tvOS 27.2 Code Hints at Apple Intelligence for New Apple TV",
     "Apple's latest tvOS 27.2 beta adds weight to rumors that the next Apple TV will have Siri AI support."),
    ("google_news", "Apple releases third iOS 27.2 developer beta for iPhone", ""),
    ("news_rss", "Apple iPhone 18 Pro review: big changes for small differences",
     "Longer battery life, better screen, upgraded Siri and new variable aperture camera"),
    ("news_rss", "iPhone 18 Pro Max can't call or text on AT&T? Apple will replace it for free",
     "Some iPhone 18 Pro Max phones on AT&T are stuck in SOS mode."),
    ("google_news", "Apple MacBook Pro Release Schedule: What To Expect When", ""),
    # 12-13: two obituaries
    ("news_rss", "Author and former politician Jeffrey Archer dies aged 86",
     "Bestselling author and former politician Jeffrey Archer has died at the age of 86."),
    ("news_rss", "Blue Planet and Gandhi composer George Fenton dies aged 76",
     "Composer George Fenton, whose work included music for films such as Gandhi"),
    # 14-16: bombers, plus an unrelated drone-strike story
    ("news_rss", "U.S. B-1 bombers evacuated from UK base because of threat of Iranian drone attack",
     "The U.S. military evacuated a dozen B-1 bombers from the RAF Fairford airbase in the UK"),
    ("google_news", "Exclusive: Soldiers and Gold Star families press Army leadership after deadly Iranian drone strike", ""),
    ("news_rss", "'We had a threat': Trump explains U.S. moving long-range bombers from UK",
     "The U.S. Air Force B-1 bombers removed from England have been used in strikes on Iran."),
    # 17-18: two data-centre stories
    ("news_rss", "Why are data centres such a big deal in Scotland?", "At least 23 huge data centres are planned in Scotland"),
    ("news_rss", "Nokia CEO says data centres would go up twice as fast if supply allowed",
     "Justin Hotard says customers would build data centres twice as fast"),
    # 19-20: a trend about another Williams
    ("news_rss", "Hayley Williams Responds to DHS' Suggestion to Thank Officers After ICE Comments",
     "Hayley Williams has drawn the ire of President Donald Trump's Department of Homeland Security."),
    ("x_trends24", "Gavin Williams", ""),
    # 21-32: stories that are right and must stay together
    ("news_rss", "Nobel prize in medicine 2026 awarded for research into mysteries of brain", ""),
    ("hackernews", "2026 Nobel Prize in Physiology or Medicine: Deisseroth, Hegemann, Nagel", ""),
    ("news_rss", "Nearly 200 people under observation after Irkutsk lab worker dies from plague", ""),
    ("hackernews", "US closely monitoring case of lab worker who possibly died of plague in Siberia", ""),
    ("news_rss", "Trump approval ratings plummet to new low, polls show", ""),
    ("news_rss", "Trump's approval hits new low among Hispanic voters ahead of midterms", ""),
    ("news_rss", "Trump's gains among Latino voters slip ahead of midterms", ""),
    ("news_rss", "Command-line tool quickly removes Apple Intelligence from macOS 27", "The tool can free up over 12GB of storage."),
    ("news_rss", "Get rid of Apple's AI bloatware and reclaim 12 GB of storage with this open source tool", ""),
    ("news_rss", "This tool frees up Apple Intelligence storage on macOS, but think twice before using it", ""),
    ("google_news", "'The Batman Part II' Production Paused As Matt Reeves Steps Away For Personal Reasons", ""),
    ("news_rss", "'The Batman II' Production Paused as Director Matt Reeves 'Focuses on a Family Matter'", ""),
    # 33-34: a trend fragment that does name the article's subject
    ("x_trends24", "Bijan", ""),
    ("news_rss", "Is the Falcons' Bijan Robinson the NFL's best running back? He is when he's in primetime", ""),
]


def _index() -> LinkIndex:
    """The evening stories inside a run of realistic size (a word in 30 of 1,000 items is not rare)."""
    rng = random.Random(1)
    words = ["".join(rng.choice("bcdfghklmnprstvz") + rng.choice("aeiou") for _ in range(4)) for _ in range(3000)]
    padding = [("news_rss", " ".join(rng.sample(words, 6)), "") for _ in range(1000)]
    items = []
    for i, (source, title, ctx) in enumerate(EVENING + REAL + padding, start=1):
        raw = RawTrendItem(title=title, source=SourceName(source), timestamp=NOW)
        items.append(CleanedTrendItem(**raw.model_dump(), item_id=i, normalized_title=title, heuristic_score=0.6,
                                      context=ctx or None))
    return LinkIndex(items, items)


INDEX = _index()


def _groups(ids: list[int]) -> list[list[int]]:
    return sorted((sorted(g) for g in INDEX.components(ids, [])), key=lambda g: (-len(g), g))


def test_one_shared_institution_does_not_make_one_story():
    assert _groups([1, 2, 3, 4, 5, 6]) == [[1, 2, 3], [4, 5], [6]]


def test_one_company_and_its_products_do_not_make_one_story():
    assert _groups([7, 8, 9, 10, 11]) == [[7], [8], [9], [10], [11]]
    assert {"iphone", "tvos"} <= INDEX.name_words  # capitals inside a word mark a name


def test_a_shared_phrase_counts_once():
    assert _groups([12, 13]) == [[12], [13]]  # 'dies aged'
    assert _groups([14, 15, 16]) == [[14, 16], [15]]  # 'Iranian drone'
    assert _groups([17, 18]) == [[17], [18]]  # 'data centres'


def test_a_trend_fragment_must_not_name_someone_else():
    assert _groups([19, 20]) == [[19], [20]]
    assert _groups([33, 34]) == [[33, 34]]


def test_real_stories_stay_together():
    for ids in ([21, 22], [23, 24], [26, 27], [28, 29, 30], [31, 32]):
        assert _groups(ids) == [ids]
    # rc12: 'Trump approval ratings plummet to new low' shares 'approval ... new low' with the Hispanic-voters
    # poll but nothing with 'Trump's gains among Latino voters slip': a report linked to one member of a story
    # only is not chained in (no single-link bridges); it stands alone.
    assert _groups([25, 26, 27]) == [[26, 27], [25]]


# ---------------------------------------------------------------- story text
def test_model_padding_the_sources_do_not_support_is_dropped():
    from agent_reach.daily.edition import body_sentences

    source = ("Neon Sets 'Artificial' Oscar Campaign With Andrew Garfield in Supporting Actor, Yura Borisov in Lead. "
              "Neon has set its Oscar campaign for Luca Guadagnino's \"Artificial,\" with Andrew Garfield in supporting "
              "actor and Yura Borisov in lead actor.")
    summary = ("Neon has set its Oscar campaign for Luca Guadagnino's 'Artificial,' with Andrew Garfield in supporting "
               "actor and Yura Borisov in lead actor. The film is a unique and artistic take on the human experience, "
               "with a focus on the complexities of human relationships.")
    assert body_sentences(summary, source) == [summary.split(" The film")[0]]
    etched = ("Sources: AI inference-chip startup Etched is in early talks to raise funding at a $40B-$50B valuation, "
              "up from $21B in August (Marina Temkin/TechCrunch)")
    got = body_sentences("Sources: AI inference-chip startup Etched is in early talks to raise funding at a $40B-$50B "
                         "valuation, up from $21B in August. The startup is working on developing AI inference chips "
                         "for various industries, including healthcare and finance.", etched)
    assert got == ["AI inference-chip startup Etched is in early talks to raise funding at a $40B-$50B valuation, "
                   "up from $21B in August."]


def test_other_languages_are_not_shown_as_the_summary():
    from agent_reach.daily.edition import body_sentences, looks_english

    danish = ("Omfattende uautoriseret adgang til borgeres CPR-oplysninger. Det Centrale Personregister (CPR) har "
              "konstateret en alvorlig sikkerhedshaendelse.")
    assert body_sentences(danish, danish) == []
    assert looks_english("Families near Port Calder face school closures until inspections finish.")
    assert looks_english("Charles de Gaulle airport closed runways on Monday.")


def test_titles_like_st_do_not_end_a_sentence():
    from agent_reach.daily.edition import SENTENCE_SPLIT_RX

    text = ("Interviews with Justine Wilson and Ashley St. Clair paint him as cruel. "
            "'If we don't adapt, there's no more math.' The field is changing.")
    assert SENTENCE_SPLIT_RX.split(text) == [
        "Interviews with Justine Wilson and Ashley St. Clair paint him as cruel.",
        "'If we don't adapt, there's no more math.'", "The field is changing."]


def test_why_it_matters_that_restates_the_summary_is_left_out():
    from agent_reach.daily.brief import apply_brief
    from tests.daily_fakes import make_story

    story = make_story(headline="Gauff Receives Racist Abuse Online After China Open Incident",
                       sentences=["Coco Gauff has received online racist abuse after her victory at the China Open."])
    story.evidence[0].title = "Gauff receives racist abuse online after China Open incident"
    story.evidence[0].excerpt = ("Coco Gauff has had to endure online racial abuse after her latest victory at the "
                                 "China Open; the American star beat 16-year-old Sun Xinran in straight sets.")
    assert apply_brief(story, "", "Coco Gauff has had to endure online racial abuse after her latest victory at "
                                  "the China Open.") == (0, 0)
    story.evidence[0].excerpt = "The Wilkes Subglacial Basin could raise global mean sea level by 10 to 13 feet."
    assert apply_brief(story, "", "A dramatic rise in global sea levels could have severe consequences for "
                                  "coastal communities.") == (0, 0)


# ---------------------------------------------------------------- headlines
def test_headline_amounts_must_come_from_the_reports():
    from agent_reach.pipeline.clusterer import quantities_grounded

    members = [i for i in INDEX.items.values() if i.item_id in (23, 24)]
    assert not quantities_grounded("Russian Lab Worker Dies of Suspected Plague, Thousands in Quarantine", members)
    assert quantities_grounded("Nearly 200 Under Observation After Lab Worker Dies of Plague", members)
    assert quantities_grounded("Lab Worker Dies of Plague in Siberia", members)


def test_long_titles_keep_their_first_sentence_and_their_quotes():
    from agent_reach.pipeline.cleaner import sanitize_headline

    assert sanitize_headline("Is the Falcons' Bijan Robinson the NFL's best running back? He is when he's in "
                             "primetime") == "Is the Falcons' Bijan Robinson the NFL's Best Running Back?"
    assert sanitize_headline("Hayley Williams Responds to DHS' Suggestion to Thank Officers After ICE Comments: "
                             "'Nazi Bitches'").endswith(": 'Nazi Bitches'")
    assert sanitize_headline("'We had a threat': Trump explains U.S. moving long-range bombers from UK") == \
        "'We Had a Threat': Trump Explains U.S. Moving Long-range Bombers from UK"


# ---------------------------------------------------------------- ranking and presentation
def _strength(level: str):
    from agent_reach.daily.strength import EvidenceStrength

    return EvidenceStrength(level=level, points=1 if level == "limited" else 5)


def test_top_stories_take_corroborated_news_before_single_outlet_features():
    from datetime import datetime, timezone

    from agent_reach.daily.edition import select_stories
    from agent_reach.daily.prefs import DailyPrefs
    from tests.daily_fakes import make_story

    now = datetime.now(timezone.utc)
    cats = ["News", "Tech", "Science & AI", "Sports", "Entertainment"]
    words = ["Harbor strike", "Chip launch", "Comet sighting", "Cup final", "Film premiere", "Senate vote",
             "Phone recall", "Glacier study", "Marathon record", "Album release", "Port fire", "Cloud outage",
             "Vaccine trial", "Derby win"]
    stories = []
    for i, w in enumerate(words):
        s = make_story(i + 1, headline=f"{w} in Town{chr(65 + i)}", category=cats[i % 5], now=now, relevance=8)
        s.evidence_strength = _strength("limited" if i in (3, 9) else "moderate")
        stories.append(s)
    stories[5].evidence_strength = _strength("limited")
    stories[5].relevance_score = 9  # rc10: rated 9, but still a single outlet
    sel = select_stories(stories, DailyPrefs(max_stories=10, max_per_category=4), now=now)
    top = {s.rank for s in sel.top}
    assert 4 not in top and 10 not in top  # limited, relevance 8: below the corroborated news
    # rc10: a single-outlet story waits for corroborated news even when the model rated it 9
    # (October 6: a 1-report story rated 9 took a place while a 5-report story waited)
    assert 6 not in top and {11, 12, 13} <= top
    assert [s.rank for s in sel.top] == [1, 2, 3, 5, 7, 8, 9, 11, 12, 13]
    # with places left after the corroborated news, the single-outlet story rated 9 comes first
    sel = select_stories(stories[:9], DailyPrefs(max_stories=8, max_per_category=4), now=now)
    assert {s.rank for s in sel.top} == {1, 2, 3, 5, 7, 8, 9, 6}


def test_html_sections_number_their_own_stories_consecutively():
    from agent_reach.daily.render_html import _section
    from tests.daily_fakes import make_edition, make_story

    stories = [make_story(i, headline=f"Separate story {i} about Town{i}") for i in range(1, 6)]
    edition = make_edition(stories)
    html = _section("News", stories, edition, shown={2, 4})
    assert "Also in Top Stories" in html
    assert "<h3>3. " in html and "<h3>4. " not in html


def test_feed_failure_notes_keep_the_http_status():
    from agent_reach.ingestion.news import _URL_PREFIX_RX

    err = "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml: HTTPStatusError: HTTP 404 Not Found"
    assert _URL_PREFIX_RX.sub("", err) == "HTTPStatusError: HTTP 404 Not Found"
