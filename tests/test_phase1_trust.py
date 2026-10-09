from agent_reach.daily.edition import primary_url
from agent_reach.daily.publish import public_edition, search_entries, edition_page
from agent_reach.daily.strength import assess, reporting_groups, strength_of
from agent_reach.daily.render_html import render_edition_html
from agent_reach.outlets import outlet_key
from tests.daily_fakes import make_story, make_edition


def reports(names, titles=None):
    story = make_story(headline='Collin County trains poll workers for the election')
    seed = story.evidence[0]
    story.evidence = [seed.model_copy(update={
        'publisher': name, 'title': titles[i] if titles else story.headline,
        'url': f'https://publisher-{i}.test/story', 'source': 'news_rss', 'source_name': 'News feeds',
    }) for i, name in enumerate(names)]
    story.evidence_strength = None
    return story


def test_reviewed_newsroom_aliases_recalculate_strength_and_preserve_distinct_teams():
    assert outlet_key('NBC DFW') == outlet_key('NBC 5 Dallas-Fort Worth')
    assert outlet_key('NBC News') != outlet_key('NBC DFW')
    for names in [('NBC DFW', 'NBC 5 Dallas-Fort Worth'), ('Al Jazeera', 'Al Jazeera English')]:
        s = reports(names, ['The Lincoln returns to San Diego', 'USS Lincoln returns after deployment'])
        ed = make_edition([s])
        strength = assess(s.evidence, ed.generation_completed_utc)
        assert strength.independent_reports == 1 and strength.level == 'limited'
        assert strength.duplicates_collapsed == 1
        identities = reporting_groups(s.evidence)
        assert len({x['outlet_id'] for x in identities}) == 1
        assert len({x['reporting_origin'] for x in identities}) == 1
        # Cached editions retain the original all-report scope but lose the duplicate alias's points.
        s.evidence_strength = strength.model_copy(update={
            'publishers': list(names), 'independent_reports': 2, 'points': 4,
            'level': 'moderate', 'duplicates_collapsed': 0,
        })
        corrected = strength_of(s, ed.generation_completed_utc)
        assert corrected.independent_reports == 1 and corrected.level == 'limited'


def test_syndication_preserves_link_newsroom_and_reporting_origin_totals():
    s = reports(['Wire One', 'Local Daily'])
    ed = make_edition([s])
    pub = public_edition(ed)
    story = pub['stories'][0]
    c = story['coverage']
    assert c['source_links'] == 2
    assert c['linked_outlets'] == 2
    assert c['linked_reporting_origins'] == c['independent_reports'] == 1
    assert c['level'] == 'limited'
    assert story['sources'][0]['outlet_id'] != story['sources'][1]['outlet_id']
    assert story['sources'][0]['reporting_origin'] == story['sources'][1]['reporting_origin']
    entry = search_entries(pub)[0]
    assert entry['coverage'] == c and entry['l'] == c['level']


def test_later_syndication_match_connects_earlier_copies():
    s = reports(['Wire One', 'Local Daily', 'Local Daily'], ['Wire report', 'Local follow-up', 'Wire report'])
    strength = assess(s.evidence, make_edition([s]).generation_completed_utc)
    assert strength.independent_reports == 1 and strength.duplicates_collapsed == 2
    assert len({x['reporting_origin'] for x in reporting_groups(s.evidence)}) == 1


def test_high_title_overlap_does_not_hide_different_numbers_or_negation():
    headline = 'Council approves transport plan with 5 votes'
    s = reports(['Local'], ['Council approves transport plan with 4 votes'])
    assert primary_url(s, headline) is None
    s.evidence[0].title = 'Council does not approve transport plan with 5 votes'
    assert primary_url(s, headline) is None
    s.evidence[0].title = 'Council approves transport plan with 5 votes today'
    assert primary_url(s, headline) == s.evidence[0].url


def test_headline_never_uses_background_or_an_unrelated_report_when_matching_link_is_unresolved():
    headline = 'Princeton celebrates Anne Carson after denying her tenure'
    s = reports(['Wikipedia', 'The New York Times', 'BBC News'],
                ['Anne Carson', headline, 'Anne Carson wins Nobel Literature Prize'])
    s.headline = headline
    s.evidence[0] = s.evidence[0].model_copy(update={'source': 'wikipedia', 'url': 'https://en.wikipedia.org/wiki/Anne_Carson'})
    s.evidence[1] = s.evidence[1].model_copy(update={'source': 'google_news', 'url': 'https://news.google.com/rss/articles/unresolved'})
    assert primary_url(s, headline) is None
    pub = public_edition(make_edition([s]))
    assert 'Google News redirect' in edition_page(pub).decode()
    assert 'Google News redirect' in render_edition_html(make_edition([s]))
    s.evidence[1] = s.evidence[1].model_copy(update={'url': 'https://nytimes.com/anne-carson-princeton'})
    assert primary_url(s, headline) == 'https://nytimes.com/anne-carson-princeton'
    s.evidence[1] = s.evidence[1].model_copy(update={'url': 'javascript:alert(1)'})
    assert primary_url(s, headline) is None
