const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {JSDOM} = require('jsdom');
const {normalizeStory, primaryLink, normOutlet, correctedCoverage} = require('../assets/site.js');
const {renderShell} = require('../scripts/build.cjs');
const edition = require('./fixtures/trust-2026-10-08-r8.json');
const source = (outlet, title, url, kind = 'report') => ({outlet, title, url, kind, via: 'News feeds', published_utc: null});
const story = sources => ({headline: 'Collin County trains election workers', sources,
  coverage: {independent_reports: 2, publishers: sources.map(s => s.outlet), repeats: 0, level: 'moderate', points: 4}});

test('reviewed aliases adjust counts and scoring once, without grouping corporate siblings', () => {
  for (const names of [['NBC DFW', 'NBC 5 Dallas-Fort Worth'], ['Al Jazeera', 'Al Jazeera English']]) {
    const s = normalizeStory(story(names.map((name, i) => source(name, 'Different report ' + i, 'https://example.test/' + i))));
    assert.equal(s.coverage.independent_reports, 1);
    assert.equal(s.coverage.level, 'limited');
    assert.equal(s.coverage.points, 2);
    assert.equal(s.coverage.source_links, 2);
    assert.equal(s.coverage.linked_outlets, 1);
    assert.equal(s.coverage.linked_reporting_origins, 1);
    assert.deepEqual(s.sources.map(x => x.kind), ['report', 'repeat']);
    const before = structuredClone(s);
    normalizeStory(s);
    assert.deepEqual(s, before);
  }
  assert.notEqual(normOutlet('NBC News'), normOutlet('NBC DFW'));
  assert.notEqual(normOutlet('CNBC'), normOutlet('NBC News'));
  assert.equal(correctedCoverage({publishers: ['One', 'Two', 'Two'], independent_reports: 3, level: 'limited'}).level, 'limited');
});

test('syndicated evidence retains separate link and newsroom totals', () => {
  const s = story(['Wire One', 'Local Daily'].map((name, i) => source(name, 'Identical wire headline', 'https://example.test/' + i)));
  s.coverage = {independent_reports: 1, publishers: ['Wire One'], repeats: 1, level: 'limited'};
  normalizeStory(s);
  assert.equal(s.coverage.source_links, 2);
  assert.equal(s.coverage.linked_outlets, 2);
  assert.equal(s.coverage.linked_reporting_origins, 1);
  assert.equal(s.sources[0].reporting_origin, s.sources[1].reporting_origin);
  s.sources[1].title = 'The identical wire headline!';
  s.sources.forEach(src => { delete src.reporting_origin; });
  normalizeStory(s);
  assert.equal(s.coverage.linked_reporting_origins, 1);
});

test('primary destinations support the headline; unresolved exact reports keep the evidence fallback', () => {
  const headline = 'Princeton celebrates Anne Carson after denying her tenure';
  const s = {headline, url: 'https://en.wikipedia.org/wiki/Anne_Carson', sources: [
    source('Wikipedia', headline, 'https://en.wikipedia.org/wiki/Anne_Carson', 'signal'),
    source('NYT', headline, 'https://news.google.com/rss/articles/123'),
    source('BBC News', 'Anne Carson wins Nobel Literature Prize', 'https://bbc.com/news/other'),
  ]};
  assert.equal(primaryLink(s), null);
  s.sources[1].url = 'https://nytimes.com/anne-carson-princeton';
  assert.equal(primaryLink(s), s.sources[1].url);
  for (const url of ['javascript:alert(1)', 'https://en.wikipedia.org/wiki/Anne_Carson', 'https://news.google.com/rss/articles/123']) {
    s.sources[1].url = url; assert.equal(primaryLink(s), null);
  }
});

test('later syndication links join earlier copies and explicit origin IDs drive source grouping', () => {
  const s = story([
    source('Wire One', 'Wire report', 'https://one.test/a'),
    source('Local Daily', 'Local follow-up', 'https://two.test/b'),
    source('Local Daily', 'Wire report', 'https://two.test/a'),
  ]);
  normalizeStory(s);
  assert.equal(s.coverage.linked_reporting_origins, 1);
  assert.deepEqual(s.sources.map(x => x.kind), ['report', 'repeat', 'repeat']);
  const explicit = story(['One', 'Two'].map((name, i) => ({...source(name, 'Different ' + i, 'https://example.test/' + i), reporting_origin: 'wire:known'})));
  normalizeStory(explicit);
  assert.equal(explicit.coverage.linked_outlets, 2);
  assert.deepEqual(explicit.sources.map(x => x.kind), ['report', 'repeat']);
});

test('high title overlap cannot hide a different number or a negated claim', () => {
  const s = {headline: 'Council approves transport plan with 5 votes', sources: [
    source('Local', 'Council approves transport plan with 4 votes', 'https://local.test/a'),
  ]};
  assert.equal(primaryLink(s), null);
  s.sources[0].title = 'Council does not approve transport plan with 5 votes';
  assert.equal(primaryLink(s), null);
  s.sources[0].title = 'Council approves transport plan with 5 votes today';
  assert.equal(primaryLink(s), s.sources[0].url);
});

test('real October 8 stories correct duplicate aliases and background headline destinations', () => {
  const ed = structuredClone(edition);
  ed.stories.forEach(normalizeStory);
  const nbc = ed.stories.find(s => /Collin County/.test(s.headline));
  assert.ok(nbc);
  assert.equal(nbc.coverage.independent_reports, 1);
  assert.equal(nbc.coverage.linked_reporting_origins, 1);
  assert.equal(nbc.coverage.level, 'limited');
  const carson = ed.stories.find(s => /Princeton/.test(s.headline));
  assert.ok(carson);
  assert.equal(carson.url, null);
  for (const s of ed.stories) {
    assert.equal(new Set(s.coverage.publishers.map(normOutlet)).size, s.coverage.publishers.length);
    if (s.url) assert.ok(s.sources.some(src => src.url === s.url && src.kind !== 'signal'));
  }
});

test('static sources visibly label every unresolved Google redirect and retain its link', () => {
  const index = {latest: edition.edition_date, editions: [{date: edition.edition_date, revision: edition.revision, stories: edition.stories.length}]};
  const html = renderShell(readFileSync(require.resolve('../daily/index.html'), 'utf8'), '/daily/', index, edition);
  const dom = new JSDOM(html);
  const links = [...dom.window.document.querySelectorAll('details.src a')].filter(a => a.hostname === 'news.google.com');
  assert.ok(links.length > 0);
  for (const a of links) assert.match(a.parentElement.textContent, /Google News redirect/);
  for (const a of dom.window.document.querySelectorAll('a[href^="#"]')) assert.ok(dom.window.document.getElementById(a.hash.slice(1)));
  dom.window.close();
});

