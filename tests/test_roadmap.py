"""Phases 1/2 acceptance, replaying the October 8 revision 6 saved evidence offline."""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from agent_reach.config import Settings
from agent_reach.daily.changes import compare_editions
from agent_reach.daily.edition import Story, adds_to_headline, qualifies, select_stories, evaluate_publication
from agent_reach.daily.prefs import DailyPrefs
from agent_reach.daily.publish import public_edition
from agent_reach.daily.render_html import render_edition_html
from agent_reach.daily.revisions import retain_listed
from agent_reach.daily.strength import assess, origin, strength_of
from agent_reach.ingestion.google_urls import GoogleNewsResolver
from agent_reach.models import CleanedTrendItem, SourceName
from agent_reach.outlets import outlet_name, registrable_domain
from agent_reach.pipeline.clusterer import LinkIndex, SemanticClusterer, DraftCluster
from agent_reach.pipeline.summary_checks import (clean_title, repair_text, useful_summary, validate_summary,
                                                verified_story)
from tests.daily_fakes import make_edition, make_story, RealAsyncClient

RECORD = json.loads((Path(__file__).parent / 'fixtures/real/2026-10-08-roadmap.json').read_text(encoding='utf-8'))
NOW = datetime.fromisoformat(RECORD['generated_utc'])


def recorded():
    return [Story.model_validate(s) for s in RECORD['stories']]


def test_lead_and_all_recorded_outlets_are_normalised_before_counting():
    stories = recorded()
    lead = strength_of(stories[0], NOW)
    assert lead.independent_reports == 7 and len(lead.publishers) == 7
    assert 'AP News' in lead.publishers and 'apnews.com' not in lead.publishers
    assert 'Reuters' in lead.publishers and 'reuters.com' not in lead.publishers
    cached = stories[0].model_copy(deep=True)
    cached.evidence_strength = cached.evidence_strength.model_copy(update={
        'publishers':['www.localpaper.com','Local Paper'], 'independent_reports':2})
    generic = strength_of(cached, NOW)
    assert generic.independent_reports == 1 and generic.publishers == ['Local Paper'] and generic.level == 'limited'
    for s in stories:
        strength = strength_of(s, NOW)
        assert len({origin(name, None) for name in strength.publishers}) == len(strength.publishers)
        assert strength.independent_reports <= len(strength.publishers)
    assert outlet_name('NASA (.gov)') == 'NASA'
    assert registrable_domain('https://feeds.bbc.co.uk/news') == 'bbc.co.uk'
    assert origin('AP News', None) == origin('apnews.com', None)
    evidence = [stories[0].evidence[0].model_copy(update={'publisher': p, 'title': f'Microsoft visa news {i}', 'url': u})
                for i, (p, u) in enumerate([('AP News', 'https://apnews.com/a'), ('apnews.com', 'https://www.apnews.com/b'),
                                            ('Reuters', 'https://reuters.com/a'), ('reuters.com', 'https://uk.reuters.com/b')])]
    assert assess(evidence, NOW).independent_reports == 2


def test_every_unresolved_google_link_is_labelled_in_publication():
    ed = make_edition(recorded(), started=NOW - timedelta(minutes=15))
    data = public_edition(ed)
    links = [e for s in data['stories'] for e in s['sources'] if e['url'] and 'news.google.com' in e['url']]
    assert len(links) == 21 and all(e['via'] == 'Google News' for e in links)
    assert data['stories'][0]['coverage']['independent_reports'] == 7


def test_resolver_follows_redirects_caches_successes_and_failures_and_bounds_requests(tmp_path, monkeypatch):
    async def dns(host, port):
        return '93.184.216.34'
    monkeypatch.setattr('agent_reach.pipeline.enricher._resolve_public', dns)
    calls = []
    def handler(req):
        calls.append((req.headers['host'], req.url.path))
        if req.headers['host'] == 'news.google.com':
            return httpx.Response(302, headers={'location': 'https://apnews.com/article/test'})
        return httpx.Response(200, text='<html><title>Publisher</title></html>')
    resolver = GoogleNewsResolver(Settings(db_path=tmp_path / 'history.db'))
    async def run():
        async with RealAsyncClient(transport=httpx.MockTransport(handler)) as client:
            sem = asyncio.Semaphore(2)
            url = 'https://news.google.com/rss/articles/recorded'
            assert await resolver.resolve(url, client, sem) == 'https://apnews.com/article/test'
            assert await resolver.resolve(url, client, sem) == 'https://apnews.com/article/test'
            cached = GoogleNewsResolver(Settings(db_path=tmp_path / 'history.db'))
            assert await cached.resolve(url, client, sem) == 'https://apnews.com/article/test'
            assert len(calls) == 2
            async def timeout(*args):
                raise asyncio.TimeoutError()
            monkeypatch.setattr(resolver.enricher, '_get', timeout)
            bad = 'https://news.google.com/rss/articles/unresolved'
            assert await resolver.resolve(bad, client, sem) is None
            assert await resolver.resolve(bad, client, sem) is None
    asyncio.run(run())


def test_windows_defaults_remove_unavailable_model_and_diagnostics_are_collapsed():
    prefs = DailyPrefs.model_validate({'prefs_version': 9, 'embed_model': 'embeddinggemma-2:270m',
                                      'embed_fallback_models': ['nomic-embed-text', 'embeddinggemma-2:270m']})
    assert prefs.embed_model == 'nomic-embed-text' and prefs.embed_fallback_models == []
    ed = make_edition()
    error = 'ResponseError: model "embeddinggemma-2:270m" not found'
    ed.model.grouping = {'fallback': error}
    ed.source_health[0].error = error
    soup = BeautifulSoup(render_edition_html(ed), 'html.parser')
    details = soup.select_one('details.run-details')
    assert details and not details.has_attr('open') and details.find('summary').text == 'Run details'
    assert error in details.text
    details.decompose()
    assert error not in soup.text


@pytest.mark.parametrize('rank', [8, 10, 29, 33])
def test_recorded_factual_context_subject_and_headline_errors_are_rejected(rank):
    story = recorded()[rank - 1]
    errors = validate_summary(' '.join(story.sentences), story.headline, [(e.title, e.excerpt) for e in story.evidence])
    assert errors, (rank, story.headline)
    headline, summary = verified_story(story)
    assert headline in [clean_title(e.title) for e in story.evidence]
    # the reports' own sentences replace the model's text, never the headline said again (October 10)
    assert summary and not summary[0].startswith(headline.rstrip('.!?')) or summary == [headline.rstrip('.!?') + '.']
    assert all(adds_to_headline(s, headline) for s in useful_summary(headline, summary))


def test_quotes_and_abbreviation_case_are_repaired_without_losing_subject():
    assert repair_text('Math 1.0" placed a premium on solving a problem.').count('"') % 2 == 0
    assert repair_text('P.T. Has been ported to PC.') == 'P.T. has been ported to PC.'
    story = recorded()[48]
    _, body = verified_story(story)
    assert 'P.T. has' in repair_text(' '.join(story.sentences))
    assert not any(line.startswith('Has ') for line in body)


def test_numbers_and_entities_cannot_be_borrowed_from_different_source_sentences():
    sources = [('Crew returns', 'Four people returned. Three astronauts and one cosmonaut returned.')]
    assert validate_summary('Four astronauts returned.', 'Crew returns', sources)
    assert not validate_summary('Three astronauts and one cosmonaut returned.', 'Crew returns', sources)
    assert validate_summary('NASA arrested 6,059 people in Paris.', 'NASA arrests people',
                            [('NASA speaks', 'NASA discussed the mission. Police made 6,059 arrests across France.')])
    assert 'headline key entity missing from summary' in validate_summary(
        'Engineers tested the new rocket.', 'NASA tests new rocket',
        [('NASA tests new rocket', None), ('Engineers tested the new rocket', None)])


def test_failed_summary_regenerates_once_then_extracts_source_text(tmp_path, monkeypatch):
    item = CleanedTrendItem(item_id=1, source=SourceName.NEWS_RSS, title='NASA crew returns', normalized_title='NASA crew returns',
                            heuristic_score=.9, timestamp=NOW, context='Three astronauts and one cosmonaut returned to Earth.')
    clusterer = SemanticClusterer(Settings(db_path=tmp_path / 'test.db'))
    calls = []
    async def chat(*args, **kwargs):
        calls.append(args)
        return {'groups': [{'group_id':1,'headline':'NASA crew returns','category':'News','primary_entities':['NASA'],
                            'summary':'Four astronauts returned to Earth.','relevance_score':8}]}
    monkeypatch.setattr(clusterer, '_chat_json', chat)
    draft = DraftCluster(item_ids=[1], headline='NASA crew returns', category_raw='News', summary='Four astronauts returned to Earth.')
    asyncio.run(clusterer._verify_summaries([draft], {1:item}, regenerate=True))
    assert len(calls) == 1
    assert draft.headline == item.title and 'Three astronauts' in draft.summary and 'Four astronauts' not in draft.summary


def test_invalid_regeneration_json_is_not_retried(tmp_path, monkeypatch):
    item = CleanedTrendItem(item_id=1, source=SourceName.NEWS_RSS, title='NASA crew returns',
                            normalized_title='NASA crew returns', heuristic_score=.9, timestamp=NOW,
                            context='Three astronauts and one cosmonaut returned to Earth.')
    clusterer = SemanticClusterer(Settings(db_path=tmp_path / 'test.db', llm_max_retries=5))
    calls = []
    class BadModel:
        async def chat(self, **kwargs):
            calls.append(kwargs)
            return {'message': {'content': 'not JSON'}}
    monkeypatch.setattr(clusterer, '_get_client', lambda: BadModel())
    draft = DraftCluster(item_ids=[1], headline=item.title, category_raw='News', summary='Four astronauts returned.')
    asyncio.run(clusterer._verify_summaries([draft], {1:item}, regenerate=True))
    assert len(calls) == 1 and 'Three astronauts' in draft.summary


@pytest.mark.parametrize('headline', ['Warhammer official trailer', 'The Heathens trailer', 'NFL mock draft',
                                      'First Take debate', 'Dak Prescott breaks down a play', 'Wired podcast', 'Video explainer'])
def test_single_source_fillers_require_a_second_independent_outlet(headline):
    story = make_story(headline=headline, now=NOW)
    assert not qualifies(story, NOW)
    story.evidence.append(story.evidence[0].model_copy(update={'publisher':'Wire Two','url':'https://wire-two.test/a',
                                                           'title':headline + ' reported independently'}))
    assert qualifies(story, NOW)


def test_sections_can_be_short_and_single_source_stories_need_news_or_strong_signal():
    news = make_story(now=NOW)
    attention = make_story(headline='Example project release', now=NOW, platforms=['hackernews'], relevance=6, items=1)
    assert qualifies(news, NOW) and not qualifies(attention, NOW)
    attention.relevance_score = 9; attention.raw_item_count = 3
    assert qualifies(attention, NOW)
    chosen = select_stories([news], DailyPrefs(), now=NOW)
    assert len(chosen.stories) == 1


def test_recorded_selection_reaches_single_source_target_and_retains_eligible_incumbents():
    chosen = select_stories(recorded(), DailyPrefs(), now=NOW).stories
    singles = sum(strength_of(s, NOW).independent_reports < 2 for s in chosen)
    assert (len(chosen), singles) == (31, 15)
    assert singles / len(chosen) < .5
    previous = make_edition(chosen, started=NOW - timedelta(minutes=75))
    # Losing feeds alone does not drop already listed, still-eligible coverage.
    kept = retain_listed([], previous, DailyPrefs(), NOW)
    assert len(kept) == len(chosen)
    assert len(compare_editions(previous, make_edition(kept, started=NOW)).gone) == 0


def _title_item(i, story):
    stated = max(e.published_at_utc for e in story.evidence if e.published_at_utc)
    return CleanedTrendItem(item_id=i, title=story.headline, normalized_title=story.headline, source=SourceName.NEWS_RSS,
                            heuristic_score=.9, timestamp=stated, metadata={'published_at': stated.isoformat()})


def test_recorded_iran_pair_merges_and_roundups_other_days_or_opposite_claims_do_not(tmp_path):
    stories = recorded()
    a, b = _title_item(1, stories[3]), _title_item(2, stories[21])
    index = LinkIndex([a,b])
    assert index.gate.accepts(1,2)
    clusterer = SemanticClusterer(Settings(db_path=tmp_path / 'test.db'))
    result = clusterer._deterministic_merge([DraftCluster(item_ids=[1], headline=a.title, category_raw='News'), DraftCluster(item_ids=[2], headline=b.title, category_raw='News')], index)
    assert len(result) == 1 and set(result[0].item_ids) == {1,2}
    for title in ['Trump Orders Iran Strikes Before Midterms',
                  'Trump Says US Will Not Strike Iran Before Midterms | Microsoft loses access to green card program']:
        other = b.model_copy(update={'normalized_title':title, 'title':title})
        assert not LinkIndex([a,other]).gate.accepts(1,2)
    later = b.model_copy(update={'timestamp':b.timestamp + timedelta(days=3),
                                  'metadata':{'published_at':(b.timestamp+timedelta(days=3)).isoformat()}})
    assert not LinkIndex([a,later]).gate.accepts(1,2)


def test_revisions_wait_an_hour_except_new_strong_top_three():
    prefs = DailyPrefs(min_ok_sources=1)
    previous = make_edition(started=NOW - timedelta(minutes=45))
    current = make_edition(started=NOW - timedelta(minutes=15))
    assert not evaluate_publication(current,prefs,same_day=previous).publishable
    current.generation_completed_utc = previous.generation_completed_utc + timedelta(hours=1)
    assert evaluate_publication(current,prefs,same_day=previous).publishable
    current.generation_completed_utc = NOW
    story = make_story(headline='Orbital station emergency evacuation', now=NOW)
    story.story_id = 'abcdef123456'
    story.evidence = [story.evidence[0].model_copy(update={'publisher':p,'title':f'{p} reports orbital evacuation',
                                                         'url':f'https://wire-{i}.test/a','source':src})
                      for i,(p,src) in enumerate([('Wire A','news_rss'),('Wire B','google_news'),('Wire C','news_rss')])]
    current.stories[0] = story
    assert strength_of(story,NOW).level == 'strong'
    assert evaluate_publication(current,prefs,same_day=previous).publishable


def test_actual_iran_feed_inputs_merge_despite_us_abbreviation_and_background_clause(tmp_path):
    data = json.loads((Path(__file__).parent / 'fixtures/real/2026-10-08-iran-inputs.json').read_text(encoding='utf-8'))
    items = [CleanedTrendItem.model_validate(row) for row in data]
    core = [item for item in items if item.item_id in {41, 304, 411}]
    index = LinkIndex(core)
    assert index.gate.accepts(41, 304) and index.gate.accepts(411, 304)
    clusterer = SemanticClusterer(Settings(db_path=tmp_path / 'test.db'))
    drafts = [DraftCluster(item_ids=[i.item_id], headline=i.title, category_raw='News') for i in core]
    result = clusterer._deterministic_merge(drafts, index)
    assert len(result) == 1 and set(result[0].item_ids) == {41, 304, 411}
    after = core[-1].model_copy(update={'normalized_title': 'Trump promises not to resume Iran strikes after midterm elections'})
    assert not LinkIndex([core[0], after]).gate.accepts(core[0].item_id, after.item_id)
    other_actor = core[-1].model_copy(update={'normalized_title': 'Biden promises not to resume Iran strikes before midterm elections'})
    assert not LinkIndex([core[0], other_actor]).gate.accepts(core[0].item_id, other_actor.item_id)


def test_incumbents_need_twenty_percent_better_replacements_and_changes_export_drops():
    old = make_story(now=NOW); old.story_id = 'abcdef123456'; old.combined_score = 100
    others = [make_story(headline=h, now=NOW) for h in ['Railway extension approved', 'School funding bill passes']]
    for i, s in enumerate(others):
        s.story_id=f'cccccc12345{i}'; s.combined_score=100
    previous = make_edition([old, *others],started=NOW-timedelta(minutes=75))
    weak = make_story(headline='New tax rate takes effect',now=NOW); weak.story_id='bbbbbb123456'; weak.combined_score=119
    prefs = DailyPrefs(max_stories=3)
    assert retain_listed([weak],previous,prefs,NOW)[0].story_id == old.story_id
    weak.combined_score=120
    kept=retain_listed([weak],previous,prefs,NOW)
    assert kept[0].story_id==weak.story_id
    current=make_edition(kept,started=NOW-timedelta(minutes=15));current.changes=compare_editions(previous,current)
    public=public_edition(current)
    assert public['changes']['compared_with']==public['compared_with']
    assert public['changes']['new']==['bbbbbb123456']
    assert public['changes']['dropped']==[{'headline':old.headline,'category':'News'}]
    assert public['schema_version']==1
