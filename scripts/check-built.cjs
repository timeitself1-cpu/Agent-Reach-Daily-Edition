// Inspect the actual deployment output: all local fragment destinations and search/story parity.
const {readFileSync, readdirSync} = require('node:fs');
const {resolve, relative} = require('node:path');
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const root = resolve(__dirname, '../dist'), origin = 'https://getagentreach.dev';
const documents = new Map();
function walk(dir) {
  for (const file of readdirSync(dir, {withFileTypes: true})) {
    const full = resolve(dir, file.name);
    if (file.isDirectory()) walk(full);
    else if (file.name.endsWith('.html')) {
      const route = '/' + relative(root, full).replaceAll('\\', '/').replace(/index\.html$/, '');
      documents.set(route, new JSDOM(readFileSync(full, 'utf8'), {url: origin + route}));
    }
  }
}
walk(root);
let anchors = 0, stories = 0;
try {
  for (const [route, dom] of documents) for (const a of dom.window.document.querySelectorAll('a[href]')) {
    const url = new URL(a.href);
    if (url.origin !== origin || !url.hash) continue;
    const target = documents.get(url.pathname.replace(/index\.html$/, ''));
    assert.ok(target?.window.document.getElementById(decodeURIComponent(url.hash.slice(1))), `Missing target: ${route} -> ${a.href}`);
    if (a.matches('.skip, .section-shortcuts a')) assert.equal(url.pathname, route, `In-page link leaves ${route}`);
    anchors++;
  }
  const index = JSON.parse(readFileSync(resolve(root, 'editions/index.json')));
  const search = new Map();
  for (const {date} of index.editions) {
    const month = date.slice(0, 7);
    if (!search.has(month)) search.set(month, JSON.parse(readFileSync(resolve(root, `search/${month}.json`))).stories);
    const edition = JSON.parse(readFileSync(resolve(root, `editions/${date}.json`)));
    const embedded = JSON.parse(documents.get(`/daily/${date}/`).window.document.getElementById('edition-data').textContent).edition;
    for (const s of edition.stories) {
      const entry = search.get(month).find(x => x.d === date && x.id === s.id);
      assert.deepEqual(entry.coverage, s.coverage, `Search coverage: ${date}/${s.id}`);
      assert.equal(entry.l, s.coverage.level);
      assert.equal(entry.u || null, s.url);
      assert.deepEqual(embedded.stories.find(x => x.id === s.id), s, `Embedded story: ${date}/${s.id}`);
      stories++;
    }
  }
  // Every RSS item links to a story fragment that exists on its dated page.
  let items = 0;
  for (const file of ['feed.xml', ...readdirSync(resolve(root, 'feeds')).map(f => 'feeds/' + f)]) {
    const feed = new JSDOM(readFileSync(resolve(root, file), 'utf8'), {contentType: 'text/xml'}).window.document;
    for (const link of feed.querySelectorAll('item > link')) {
      const url = new URL(link.textContent);
      assert.ok(documents.get(url.pathname)?.window.document.getElementById(url.hash.slice(1)), `Feed link: ${file} -> ${url}`);
      items++;
    }
  }
  assert.ok(items > 0, 'The RSS feeds have no items');
  console.log(`Verified ${items} RSS story links.`);
  console.log(`Verified ${anchors} local fragment links and HTML/JSON/search parity for ${stories} stories.`);
} finally { for (const dom of documents.values()) dom.window.close(); }
