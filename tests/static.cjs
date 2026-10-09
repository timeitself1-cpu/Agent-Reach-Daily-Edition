const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {JSDOM} = require('jsdom');
const {renderShell} = require('../scripts/build.cjs');
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
        assert.equal(article.querySelector('.dek').textContent, story.summary.join(' '));
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
