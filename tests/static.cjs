const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {JSDOM} = require('jsdom');
const {renderShell} = require('../scripts/build.cjs');
const {shownSummary} = require('../assets/site.js');
const root = resolve(__dirname, '..');
const edition = JSON.parse(readFileSync(resolve(__dirname, 'fixtures/editions/2026-10-07.json')));
const index = JSON.parse(readFileSync(resolve(__dirname, 'fixtures/editions/index.json')));

test('ordinary HTML contains every summary, evidence link and fragment on complete news routes', () => {
  for (const route of ['/', '/daily/', '/daily/2026-10-07/', '/latest/', '/technology/', '/sports/']) {
    const shellRoot = route.includes('2026-10-07') ? resolve(__dirname, 'fixtures') : root;
    const html = renderShell(readFileSync(resolve(shellRoot, '.' + route + 'index.html'), 'utf8'), route, index, structuredClone(edition));
    const dom = new JSDOM(html); // No scripts, fetch, or browser renderer.
    try {
      const d = dom.window.document;
      assert.equal(d.body.dataset.rendered, 'static');
      assert.ok(d.querySelector('details.static-edition-details > summary'));
      assert.equal(d.querySelector('.edition-full').hidden, false);
      const category = d.body.dataset.section;
      const expected = edition.stories.filter(s => !category || s.category === category);
      assert.equal(d.querySelectorAll('main article[id^="story-"]').length, expected.length, route);
      for (const story of expected) {
        const article = d.getElementById('story-' + story.id);
        assert.ok(article, route + ': ' + story.id);
        assert.equal(article.querySelector('.hl').textContent, story.headline);
        const summary = shownSummary(story).join(' '); // sentences that only restate the headline are left out
        if (summary) assert.equal(article.querySelector('.dek').textContent, summary);
        else assert.equal(article.querySelector('.dek'), null, 'a headline can stand alone');
        assert.equal(article.querySelectorAll('details li').length, story.sources.length);
        assert.deepEqual([...article.querySelectorAll('details a')].map(a => a.href), story.sources.filter(s => s.url).map(s => s.url));
        if (story.why_it_matters) assert.ok(article.textContent.includes(story.why_it_matters));
        assert.equal(article.querySelector('.story-link'), null, 'native disclosure replaces script-only source navigation');
      }
      for (const time of d.querySelectorAll('time[data-relative]')) {
        assert.match(time.textContent, /UTC/);
        assert.doesNotMatch(time.textContent, /ago/);
      }
      assert.equal(new Set([...d.querySelectorAll('[id]')].map(n => n.id)).size, d.querySelectorAll('[id]').length);
    } finally { dom.window.close(); }
  }
});

test('the RSS feeds have one item per story, newest edition only, with escaped text and story links', () => {
  const {feedFiles} = require('../scripts/build.cjs');
  const ed = structuredClone(edition);
  ed.stories[0].headline = 'Q&A: <Rates> "rise"';
  const files = feedFiles(ed);
  assert.deepEqual(Object.keys(files).sort(), ['feed.xml', 'feeds/entertainment.xml', 'feeds/internet-culture.xml', 'feeds/science.xml', 'feeds/sports.xml', 'feeds/technology.xml', 'feeds/world.xml']);
  const read = text => new JSDOM(text, {contentType: 'text/xml'}).window.document;
  const all = read(files['feed.xml']);
  assert.equal(all.querySelectorAll('item').length, ed.stories.length);
  assert.equal(all.querySelector('item title').textContent, 'Q&A: <Rates> "rise"');
  for (const item of all.querySelectorAll('item')) {
    assert.match(item.querySelector('link').textContent, /^https:\/\/getagentreach\.dev\/daily\/2026-10-07\/#story-[0-9a-f]+$/);
    assert.equal(item.querySelector('guid').textContent, item.querySelector('link').textContent);
    assert.ok(!Number.isNaN(Date.parse(item.querySelector('pubDate').textContent)));
    assert.match(item.querySelector('description').textContent, /(?:: \d+ independent newsrooms? reported this|: no independent newsroom report yet)\. Summary written by a local AI model/);
    assert.doesNotMatch(item.querySelector('description').textContent, /outlets?|not stated/);
  }
  const tech = read(files['feeds/technology.xml']);
  assert.equal(tech.querySelectorAll('item').length, ed.stories.filter(s => s.category === 'Tech').length);
  assert.equal(tech.querySelector('channel > title').textContent, 'Agent Reach Daily: Technology');
});

test('static story articles carry share links and a prefilled Report an issue email', () => {
  const html = renderShell(readFileSync(resolve(root, 'index.html'), 'utf8'), '/', index, structuredClone(edition));
  const dom = new JSDOM(html);
  try {
    const d = dom.window.document;
    for (const story of edition.stories) {
      const article = d.getElementById('story-' + story.id);
      const report = new URL(article.querySelector('.static-share .report-issue').href);
      assert.equal(report.searchParams.get('subject'), `Report: ${story.headline} (edition of 2026-10-07)`);
      assert.deepEqual([...article.querySelectorAll('.static-share a:not(.report-issue)')].map(a => a.textContent), ['X', 'Facebook', 'Reddit']);
    }
  } finally { dom.window.close(); }
});
