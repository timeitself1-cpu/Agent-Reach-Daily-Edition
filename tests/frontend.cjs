const {JSDOM, VirtualConsole} = require('jsdom');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const assert = require('node:assert/strict');
const test = require('node:test');
const root = resolve(__dirname, '..');
const fixtures = resolve(__dirname, 'fixtures');
const script = readFileSync(resolve(root, 'assets/site.js'), 'utf8');
const {normOutlet, normalizeStory} = require('../assets/site.js');
const roadmapEdition = JSON.parse(readFileSync(resolve(fixtures, 'roadmap-2026-10-08.json')));
const edition = JSON.parse(readFileSync(resolve(fixtures, 'editions/2026-10-07.json')));
const index = JSON.parse(readFileSync(resolve(fixtures, 'editions/index.json')));
const monthly = JSON.parse(readFileSync(resolve(fixtures, 'search/2026-10.json')));
const trustEdition = require('./fixtures/trust-2026-10-08-r8.json');
const settle = () => new Promise(r => setTimeout(r, 25));
async function open(path = '/', opts = {}) {
  const pathname = new URL(path, 'https://example.test').pathname;
  const file = opts.shell || (pathname.endsWith('/') ? pathname + 'index.html' : pathname);
  const shellRoot = !opts.shell && /^\/daily\/\d{4}-\d{2}-\d{2}\//.test(file) ? fixtures : root;
  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(e.message));
  const dom = new JSDOM(opts.html || readFileSync(resolve(shellRoot, '.' + file), 'utf8'), {
    url: 'https://example.test' + path, runScripts: 'outside-only', virtualConsole: vc,
  });
  const w = dom.window, d = w.document, requests = [];
  w.scrollTo = () => {};
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.Date.now = () => Date.parse(opts.now || '2026-10-08T16:00:00Z');
  if (opts.setup) opts.setup(w, d);
  if (opts.clipboard) Object.defineProperty(w.navigator, 'clipboard', {value: opts.clipboard});
  if (opts.share) Object.defineProperty(w.navigator, 'share', {value: opts.share});
  w.fetch = async url => {
    requests.push(url);
    const override = opts.fetch && await opts.fetch(url, requests);
    if (override !== undefined) {
      if (override === false) return {ok:false,status:503};
      if (override && override.ok === false) return override;
      return {ok:true,json:async()=>structuredClone(override)};
    }
    return {ok:true,json:async()=>JSON.parse(readFileSync(resolve(fixtures, '.' + url)))};
  };
  w.eval(script);
  await settle();
  return {w,d,requests,errors,close:()=>dom.window.close()};
}

test('all public route shells render and keep RSS discovery', async () => {
  for (const path of ['/', '/daily/', '/daily/2026-10-07/', '/latest/', '/technology/', '/science/', '/world/', '/local/', '/sports/', '/entertainment/', '/internet-culture/', '/archive/', '/search/', '/about/', '/404.html']) {
    const p = await open(path);
    assert.ok(p.d.querySelector('main h1'), path);
    assert.ok(p.d.querySelector('link[rel="alternate"][href="/feed.xml"]'), path);
    assert.ok(p.d.querySelector('footer a[href="/feed.xml"]'), path);
    assert.equal(p.d.querySelectorAll('.nav a').length, 11);
    assert.equal(p.d.querySelectorAll('#ext-note').length, 1, path);
    assert.deepEqual(p.errors, [], path);
    p.close();
  }
});

test('Home bands show up to five stories and link every section to a page that lists all of it', async () => {
  const p = await open('/');
  for (const sec of edition.sections) {
    const band = p.d.querySelector(`.band[data-cat="${sec.category}"]`);
    if (!band) continue; // every story of the section is already among the top stories
    assert.ok(band.querySelectorAll('.card').length <= 5, sec.category);
    const link = band.querySelector('.band-link');
    assert.match(link.textContent, new RegExp(`^All ${sec.ids.length} in `));
    const q = await open(link.getAttribute('href'));
    assert.equal(q.d.querySelectorAll('.card').length, sec.ids.length, sec.category);
    assert.equal(q.d.querySelector('.nav [aria-current="page"]').getAttribute('href'), link.getAttribute('href'));
    q.close();
  }
  p.close();
});

const NOT_ARTICLE = /^(?:[^/]+\.)?(?:news\.google\.com|google\.com|reddit\.com|x\.com|twitter\.com|bsky\.app|trends24\.in|news\.ycombinator\.com|tiktok\.com)$/;
test('one click on a headline opens the publisher article in a new tab; a second link opens the story page', async () => {
  for (const path of ['/', '/latest/', '/technology/', '/sports/']) {
    const p = await open(path);
    const items = [...p.d.querySelectorAll('main article[data-cat]')].filter(a => a.querySelector('.hl'));
    assert.ok(items.length > 2, path);
    for (const item of items) {
      const story = edition.stories.find(s => s.headline === item.querySelector('.hl').textContent);
      const a = item.querySelector('.hl a');
      if (a.target === '_blank') {
        assert.ok(story.sources.some(src => src.url === a.href && src.kind !== 'signal'));
        assert.ok(!NOT_ARTICLE.test(new URL(a.href).hostname.replace(/^www\./, '')));
        assert.match(a.rel, /noopener/); assert.equal(a.getAttribute('aria-describedby'), 'ext-note');
      } else assert.equal(a.getAttribute('href'), `/daily/2026-10-07/#story-${story.id}`);
      const more = item.querySelector('.story-link');
      assert.equal(more.getAttribute('href'), `/daily/2026-10-07/#story-${story.id}`);
      assert.match(more.textContent, new RegExp(`^${story.sources.filter(x => x.url).length} sources? and coverage: `));
    }
    assert.equal(p.d.getElementById('ext-note').textContent, 'Opens the publisher’s article in a new tab.');
    p.close();
  }
  // Google News redirects and social pages are passed over while the story has a publisher's article.
  const ed = structuredClone(edition), story = ed.stories[0];
  story.sources[0].title = story.headline;
  story.sources.unshift({outlet: 'Google News', via: 'Google News', title: 'x', url: 'https://news.google.com/rss/articles/abc', published_utc: null, kind: 'report'},
    {outlet: 'Reddit', via: 'Reddit', title: 'y', url: 'https://www.reddit.com/r/news/1', published_utc: null, kind: 'signal'});
  let p = await open('/', {fetch: u => u.endsWith('2026-10-07.json') ? ed : undefined});
  assert.equal(p.d.querySelector('.lead .hl a').getAttribute('href'), edition.stories[0].sources.find(x => x.url).url); p.close();
  // A matching report wins; a story without a resolved matching link opens its evidence page.
  story.sources[2].title = 'Unrelated story';
  story.url = 'https://example.org/chosen'; story.sources.push({outlet: 'Example', via: 'Example', title: 'z', url: story.url, published_utc: null, kind: 'report'});
  story.sources.at(-1).title = story.headline;
  ed.stories[1].sources.forEach(x => { x.url = null; }); ed.stories[1].url = null;
  p = await open('/latest/', {fetch: u => u.endsWith('2026-10-07.json') ? ed : undefined});
  assert.equal(p.d.querySelector(`#story-${story.id}, .river-item`) && [...p.d.querySelectorAll('.river-item .hl a')].find(a => a.textContent === story.headline).getAttribute('href'), story.url);
  const bare = [...p.d.querySelectorAll('.river-item .hl a')].find(a => a.textContent === ed.stories[1].headline);
  assert.equal(bare.getAttribute('href'), `/daily/2026-10-07/#story-${ed.stories[1].id}`); assert.equal(bare.target, '');
  p.close();
  // The story page's headline opens the article too, with a named button beside the source list.
  p = await open('/daily/2026-10-07/#story-' + story.id, {fetch: u => u.endsWith('2026-10-07.json') ? ed : undefined});
  assert.equal(p.d.querySelector('h1').textContent, story.headline);
  assert.equal(p.d.querySelector('h1 a').getAttribute('href'), story.url);
  assert.equal(p.d.querySelector('.read-source').textContent, 'Read at Example');
  p.close();
});

test('search results open the article when the search data names it', async () => {
  const doc = structuredClone(monthly); doc.stories[0].u = 'https://example.org/article';
  const p = await open('/search/?q=Hamilton', {fetch: u => u.startsWith('/search/') ? doc : undefined});
  const hit = p.d.querySelector('.hit');
  assert.equal(hit.querySelector('h2 a').getAttribute('href'), 'https://example.org/article');
  assert.equal(hit.querySelector('h2 a').target, '_blank');
  assert.match(hit.querySelector('.story-link').getAttribute('href'), /^\/daily\/2026-10-07\/\?headline=.*#story-/);
  p.close();
});

test('cards, search and source panels agree on corrected NBC coverage and redirect labelling', async () => {
  const ed = structuredClone(trustEdition);
  ed.stories.forEach(normalizeStory);
  const story = ed.stories.find(s => /Collin County/.test(s.headline));
  const idx = {...index, latest: ed.edition_date, editions: [{...index.editions[0], date: ed.edition_date}]};
  const doc = {stories: [{id: story.id, d: ed.edition_date, r: story.rank, c: story.category,
    h: story.headline, s: story.summary.join(' '), o: story.coverage.publishers, l: story.coverage.level, coverage: story.coverage}]};
  const fetch = url => url === '/editions/index.json' ? idx : url.startsWith('/editions/') ? ed : url.startsWith('/search/') ? doc : undefined;
  let p = await open('/local/', {fetch});
  assert.match(p.d.querySelector('.card .cov').textContent, /Single source/);
  assert.match(p.d.querySelector('.card .cov').title, /1 independent outlet/);
  p.close();
  p = await open('/search/?q=Collin', {fetch});
  assert.match(p.d.querySelector('.hit .cov').textContent, /Single source/);
  assert.match(p.d.querySelector('.hit').textContent, /NBC DFW/);
  assert.doesNotMatch(p.d.querySelector('.hit').textContent, /NBC 5 Dallas/);
  p.close();
  p = await open(`/daily/2026-10-08/#story-${story.id}`, {fetch, shell: '/daily/index.html',
    setup(w, d) { d.body.dataset.date = ed.edition_date; }});
  assert.match(p.d.querySelector('[aria-label="Coverage"]').textContent, /1 independent outlet: NBC DFW/);
  assert.match(p.d.querySelector('.sources').textContent, /Independent reports shown \(1\)/);
  for (const a of p.d.querySelectorAll('.source a')) if (new URL(a.href).hostname === 'news.google.com') {
    assert.match(a.parentElement.textContent, /Google News redirect/);
  }
  p.close();
});

test('the theme control saves a choice, Auto follows the system, and every page loads the theme first', async () => {
  const store = new Map();
  const p = await open('/', {setup(w) { Object.defineProperty(w, 'localStorage', {value: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: k => store.delete(k)}}); }});
  const [auto, light, dark] = ['auto', 'light', 'dark'].map(k => p.d.querySelector(`.theme-control [data-theme="${k}"]`));
  assert.equal(auto.getAttribute('aria-pressed'), 'true');
  light.click();
  assert.equal(p.d.documentElement.dataset.theme, 'light'); assert.equal(store.get('theme'), 'light');
  assert.equal(light.getAttribute('aria-pressed'), 'true'); assert.equal(auto.getAttribute('aria-pressed'), 'false');
  dark.click(); assert.equal(p.d.documentElement.dataset.theme, 'dark');
  auto.click(); assert.equal(p.d.documentElement.dataset.theme, undefined); assert.equal(store.has('theme'), false);
  p.close();
  const blocked = await open('/', {setup(w) { Object.defineProperty(w, 'localStorage', {get() { throw new Error('denied'); }}); }});
  blocked.d.querySelector('.theme-control [data-theme="light"]').click();
  assert.equal(blocked.d.documentElement.dataset.theme, 'light'); assert.deepEqual(blocked.errors, []); blocked.close();
  const {addPreview} = require('../scripts/build.cjs');
  const dated = new JSDOM(addPreview(readFileSync(resolve(fixtures, 'daily/2026-10-07/index.html'), 'utf8'))).window.document;
  const theme = dated.querySelector('head script[src="/assets/theme.js"]');
  assert.ok(theme && theme.compareDocumentPosition(dated.querySelector('link[rel="stylesheet"]')) & 4, 'theme script precedes the stylesheet');
  assert.equal(dated.querySelectorAll('meta[name="theme-color"][media]').length, 2);
});

test('edition disclosure preserves all metadata with accessible state', async () => {
  const p = await open('/');
  const toggle = p.d.querySelector('.edition-toggle'), details = p.d.querySelector('.edition-full');
  assert.equal(details.hidden, true);
  // The edition's numbers stay visible in the ticker; Details holds the full record.
  const ticker = p.d.querySelector('.strip .ticker');
  assert.equal(ticker.getAttribute('aria-label'), 'Edition status');
  assert.match(ticker.textContent, /Latest edition.*Oct 7, 2026 · Update 2.*44 stories.*1,517 reports.*10\/10 source types up.*Generated/);
  assert.ok(ticker.querySelector('time[data-relative][datetime="'+edition.generated_utc+'"]'));
  assert.ok(details.querySelector('time[datetime="'+edition.generated_utc+'"]'));
  toggle.click();
  assert.equal(details.hidden, false);
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  toggle.click();
  assert.equal(details.hidden, true);
  p.close();
});

test('copy and native share use a dated link with its headline, preserving the reading URL', async () => {
  let copied, shared;
  const story = edition.stories[0];
  const p = await open('/daily/2026-10-07/#story-'+story.id, {clipboard: {writeText: async value => {copied = value;}}, share: async value => {shared = value;}});
  const before = p.w.location.href;
  p.d.querySelector('.copy-story').click(); await settle();
  assert.equal(new URL(copied).searchParams.get('headline'), story.headline);
  assert.equal(new URL(copied).pathname, '/daily/2026-10-07/');
  assert.equal(new URL(copied).hash, '#story-'+story.id);
  assert.match(p.d.querySelector('.share-status').textContent, /copied/);
  assert.equal(p.w.location.href, before);
  p.d.querySelector('.share-story').click(); await settle();
  assert.equal(shared.title, story.headline);
  assert.equal(shared.url, copied);
  p.close();
});

test('unavailable clipboard exposes a selected link; cancelled sharing keeps reading focus', async () => {
  const p = await open('/daily/2026-10-07/#story-'+edition.top[0], {share: async () => {throw new p.w.DOMException('Cancelled', 'AbortError');}});
  const share = p.d.querySelector('.share-story'); share.focus(); share.click(); await settle();
  assert.equal(p.d.activeElement, share);
  assert.equal(p.d.querySelector('.share-fallback').hidden, true);
  p.d.querySelector('.copy-story').click(); await settle();
  const input = p.d.querySelector('.share-fallback input');
  assert.equal(p.d.querySelector('.share-fallback').hidden, false);
  assert.equal(p.d.activeElement, input);
  assert.equal(new URL(input.value).searchParams.get('headline'), edition.stories[0].headline);
  p.close();
});

test('dated edition request starts before the archive index finishes', async () => {
  let release; const deferred = new Promise(r => release = r);
  const p = await open('/daily/2026-10-07/', {fetch: u => u === '/editions/index.json' ? deferred : undefined});
  assert.deepEqual(p.requests.slice().sort(), ['/editions/2026-10-07.json', '/editions/index.json']);
  assert.ok(p.d.querySelector('main[aria-busy="true"]'));
  release(index); await settle();
  assert.equal(p.d.querySelector('h1').textContent, edition.stories[0].headline);
  p.close();
});

test('embedded edition renders without a loading skeleton or data requests; bad embed falls back', async () => {
  const {renderShell} = require('../scripts/build.cjs');
  const html = renderShell(readFileSync(resolve(root, 'index.html'), 'utf8'), '/', index, edition);
  const staticPage = new JSDOM(html);
  const shown = [...staticPage.window.document.querySelectorAll('main [id^="story-"]')];
  assert.ok(shown.length >= 20);
  for (const node of shown) {
    const story = edition.stories.find(s => 'story-' + s.id === node.id);
    assert.equal(node.querySelectorAll('details.src.static-src li').length, story.sources.length);
  }
  staticPage.window.close();
  const p = await open('/', {html});
  assert.deepEqual(p.requests, []);
  assert.equal(p.d.querySelector('.skeleton'), null);
  assert.equal(p.d.querySelectorAll('#page-status').length, 1);
  assert.equal(p.d.querySelector('h1').textContent, edition.stories[0].headline);
  assert.equal(p.d.body.dataset.rendered, undefined);
  assert.equal(p.d.body.dataset.prerender, undefined);
  for (const band of p.d.querySelectorAll('.band[data-cat]')) assert.ok(band.querySelectorAll('.card').length <= 5);
  p.close();
  const malformed = html.replace(/(<script id="edition-data"[^>]*>)[\s\S]*?(<\/script>)/, '$1invalid$2');
  const fallback = await open('/', {html: malformed});
  assert.ok(fallback.requests.includes('/editions/index.json'));
  assert.equal(fallback.d.querySelector('h1').textContent, edition.stories[0].headline);
  fallback.close();
});

test('static rendering escapes news text and script terminators in embedded JSON', async () => {
  const {renderShell, addPreview} = require('../scripts/build.cjs');
  const ed = structuredClone(edition);
  ed.stories[0].headline = '</script><script>window.attacked=true</script><img src=x>';
  ed.stories[0].summary = ['<b>Plain text summary</b>'];
  const html = addPreview(renderShell(readFileSync(resolve(root, 'index.html'), 'utf8'), '/', index, ed));
  const staticDom = new JSDOM(html);
  assert.equal(staticDom.window.document.querySelector('h1').textContent, ed.stories[0].headline);
  assert.equal(staticDom.window.document.querySelector('h1 img'), null);
  assert.ok(staticDom.window.document.querySelector('head > link[href="/assets/no-script.css"]'));
  staticDom.window.close();
  const p = await open('/', {html});
  assert.equal(p.w.attacked, undefined);
  assert.equal(p.d.querySelector('h1').textContent, ed.stories[0].headline);
  assert.deepEqual(p.requests, []);
  p.close();
});

test('latest river and category pages retain every fixture story', async () => {
  const p = await open('/latest/');
  assert.equal(p.d.querySelectorAll('.river-item').length, edition.stories.length);
  p.close();
  for (const [path, cat] of [['technology','Tech'], ['science','Science & AI'], ['world','News']]) {
    const q = await open('/'+path+'/');
    assert.equal(q.d.querySelectorAll('.card').length, edition.sections.find(s=>s.category===cat).ids.length);
    assert.equal(q.d.querySelectorAll('.card h2').length,q.d.querySelectorAll('.card').length);
    assert.equal(q.d.querySelectorAll('.card h3').length,0);
    assert.equal(q.d.querySelector('.nav [aria-current="page"]').textContent, path === 'world' ? 'World & Nation' : path === 'science' ? 'Science & AI' : path[0].toUpperCase()+path.slice(1));
    q.close();
  }
});

test('roadmap lead deduplicates publishers and labels links separately', async () => {
  const ed = roadmapEdition, story = ed.stories[0];
  const p = await open('/daily/2026-10-07/#story-' + story.id, {fetch: u => u.includes('/editions/2026-10-07') ? ed : undefined});
  const tags = [...p.d.querySelectorAll('.story-main .outlet-tags .tag')].map(t => t.textContent);
  assert.deepEqual(tags.slice(0, 2), ['AP News', 'Reuters'], 'widely known newsrooms lead the tags');
  assert.equal(tags.length, 7); assert.equal(new Set(tags).size, 7);
  const tagged = p.d.querySelector('.story-main .outlet-tags');
  assert.equal(tagged.querySelector('.tally').textContent, '7 outlets');
  assert.equal(tagged.querySelector('.tally').getAttribute('aria-hidden'), 'true'); // the sentence below says it once
  const spoken = [...tagged.childNodes].filter(n => !(n.getAttribute && n.getAttribute('aria-hidden'))).map(n => n.textContent).join('');
  assert.match(spoken, /^Reported independently by 7 outlets: AP News, Reuters, /);
  assert.match(p.d.querySelector('.facts').textContent, /7 independent outlets/);
  assert.doesNotMatch(p.d.querySelector('.facts').textContent, /apnews\.com|reuters\.com/);
  assert.match(p.d.querySelector('.source-jump').textContent, /8 source links/);
  const group = [...p.d.querySelectorAll('.sources h3')].find(h => h.textContent.startsWith('Independent'));
  const outlets = [...group.parentElement.querySelectorAll('.outlet')].map(n => normOutlet(n.textContent));
  assert.equal(outlets.length, new Set(outlets).size);
  assert.notEqual(p.d.activeElement, p.d.querySelector('h1'), 'direct arrival does not focus headline');
  p.close();
});

test('World & Nation label is consistent in route metadata and search', async () => {
  const p = await open('/world/');
  assert.equal(p.d.querySelector('h1').textContent, 'World & Nation');
  assert.equal(p.d.title, 'World & Nation | Agent Reach Daily');
  assert.match(p.d.querySelector('meta[name="description"]').content, /World & Nation/);
  p.close();
  const q = await open('/search/');
  assert.equal(q.d.querySelector('option[value="News"]').textContent, 'World & Nation');
  q.close();
});

test('update details count changes and optionally link dropped headlines as plain text', async () => {
  const ed = structuredClone(edition);
  ed.compared_with = {edition_date: ed.edition_date, revision: 1};
  ed.stories[0].change = 'new'; ed.stories[1].change = 'updated';
  const p = await open('/', {fetch: u => u.endsWith('2026-10-07.json') ? ed : undefined});
  assert.match(p.d.querySelector('.edition-changes').textContent, new RegExp(`Compared with update 1: ${ed.stories.filter(s=>s.change==='new').length} new · ${ed.stories.filter(s=>s.change==='updated').length} updated`));
  assert.equal(p.d.querySelector('.dropped-stories'), null); p.close();
  ed.changes = {dropped: [{headline: '<b>Removed headline</b>', category: 'News'}]};
  const q = await open('/', {fetch: u => u.endsWith('2026-10-07.json') ? ed : undefined});
  const a = q.d.querySelector('.dropped-stories a');
  assert.equal(a.textContent, '<b>Removed headline</b>');
  assert.equal(a.querySelector('b'), null);
  assert.equal(new URL(a.href).searchParams.get('q'), '"<b>Removed headline</b>"');
  assert.match(q.d.querySelector('.edition-full').textContent, /1 no longer listed/); q.close();
});

test('Home and Daily shortcuts resolve every section, including static HTML', async () => {
  const {renderShell} = require('../scripts/build.cjs');
  for (const path of ['/', '/daily/']) {
    const p = await open(path);
    const links = [...p.d.querySelectorAll('.section-shortcuts a')];
    assert.equal(links.length, edition.sections.length);
    links.forEach((a, i) => {
      assert.ok(p.d.getElementById(a.hash.slice(1)));
      assert.ok(a.textContent.endsWith(' ' + edition.sections[i].ids.length));
      a.focus(); assert.equal(p.d.activeElement, a);
    }); p.close();
    const shell = readFileSync(resolve(root, path === '/' ? 'index.html' : 'daily/index.html'), 'utf8');
    const dom = new JSDOM(renderShell(shell, path, index, structuredClone(edition)));
    assert.equal(dom.window.document.querySelectorAll('.section-shortcuts a').length, edition.sections.length);
    dom.window.close();
  }
});

test('relative timestamps refresh at 60 seconds and pause when hidden', async () => {
  let tick, stopped = 0, visible = 'visible';
  const ed = structuredClone(edition); ed.stories[0].newest_published_utc = '2026-10-08T15:41:00Z';
  const p = await open('/', {fetch: u => u.endsWith('2026-10-07.json') ? ed : undefined, setup(w, d) {
    Object.defineProperty(d, 'visibilityState', {get: () => visible});
    w.setInterval = (fn, ms) => {assert.equal(ms, 60000); tick = fn; return 1;};
    w.clearInterval = () => {stopped++; tick = null;};
  }});
  const time = p.d.querySelector('.lead time[data-relative]');
  assert.equal(time.textContent, '19 min ago');
  p.w.Date.now = () => Date.parse('2026-10-08T16:01:00Z'); tick();
  assert.equal(time.textContent, '20 min ago');
  visible = 'hidden'; p.d.dispatchEvent(new p.w.Event('visibilitychange'));
  assert.equal(tick, null); assert.equal(stopped, 1);
  visible = 'visible'; p.d.dispatchEvent(new p.w.Event('visibilitychange'));
  assert.equal(typeof tick, 'function'); p.close();
});

test('story times include historical year and local timezone', async () => {
  const ed = structuredClone(edition);
  for (const story of ed.stories) story.newest_published_utc = '2025-10-08T12:00:00Z';
  const q = await open('/technology/', {fetch: u => u.endsWith('2026-10-07.json') ? ed : undefined});
  const time = q.d.querySelector('.card .meta time');
  assert.match(time.textContent, /2025/); assert.match(time.textContent, /(?:[A-Z]{2,5}|GMT[+-]\d+)$/);
  assert.match(time.title, /2025/); q.close();
});

test('axe 4.10 reports no region or nested complementary landmarks', async () => {
  const axe = require('axe-core');
  assert.match(axe.version, /^4\.10\./);
  for (const path of ['/', '/world/', '/latest/', '/search/', '/archive/', '/about/', '/daily/2026-10-07/#story-' + edition.top[0]]) {
    const p = await open(path); p.w.eval(axe.source);
    const results = await p.w.axe.run(p.d, {runOnly: {type: 'rule', values: ['region', 'landmark-complementary-is-top-level']}});
    assert.equal(results.violations.length, 0, path + ': ' + results.violations.map(v => v.id).join(', '));
    assert.ok(p.d.querySelector('header .skip')); p.close();
  }
});

test('fresh, stale, and archived edition information survives', async () => {
  const p = await open('/');
  assert.match(p.d.querySelector('.strip').textContent, /Latest edition.*Update 2.*44 stories.*1,517 reports.*10 of 10/s);
  assert.equal(p.d.querySelector('.edition-full time[datetime="2026-10-07T23:42:20Z"]').textContent.startsWith('Generated'),true);
  assert.equal(p.d.querySelector('.live.old'),null);
  p.close();
  const stale = await open('/', {now:'2026-10-10T16:00:00Z'});
  assert.ok(stale.d.querySelector('.live.old'));
  assert.match(stale.d.querySelector('.notice').textContent,/most recent edition/);
  stale.close();
  const old = await open('/daily/2026-10-07/',{fetch:u=>u==='/editions/index.json'?{...index,latest:'2026-10-08'}:undefined});
  assert.match(old.d.querySelector('.strip').textContent,/Archived edition/);
  assert.equal(old.d.querySelector('.notice a').getAttribute('href'),'/daily/');
  old.close();
});

test('story sources and source groups match fixture, jump preserves URL', async () => {
  for (const story of edition.stories) {
    const p = await open('/daily/2026-10-07/#story-'+story.id);
    assert.equal(p.d.querySelector('h1').textContent,story.headline);
    assert.equal(p.d.querySelectorAll('.sources .source').length,story.sources.length);
    assert.deepEqual([...p.d.querySelectorAll('.sources a.title')].map(a=>a.href).sort(), story.sources.map(s=>s.url).sort());
    const grouped = normalizeStory(structuredClone(story)).sources;
    for (const [kind, title] of [['report','Independent reports shown'],['repeat','Repeats and syndicated copies'],['signal','Social and search signals']]) {
      const count=grouped.filter(s=>s.kind===kind).length;
      const heading=[...p.d.querySelectorAll('.sources h3')].find(h=>h.textContent===`${title} (${count})`);
      if(count) {
        assert.ok(heading,`${story.id}: ${kind}`);
        assert.deepEqual([...heading.parentElement.querySelectorAll('a.title')].map(a=>a.href).sort(),grouped.filter(s=>s.kind===kind).map(s=>s.url).sort());
      } else assert.equal([...p.d.querySelectorAll('.sources h3')].some(h=>h.textContent.startsWith(title)),false);
    }
    const hash = p.w.location.hash;
    p.d.querySelector('.source-jump').click();
    assert.equal(p.w.location.hash,hash);
    assert.equal(p.d.activeElement.id,'sources');
    assert.deepEqual(p.errors,[]);
    p.close();
  }
});

test('skip and regular anchors never remount a story; next/back focus title', async () => {
  const p = await open('/daily/2026-10-07/#story-'+edition.top[0]);
  const main = p.d.querySelector('main'), headline = p.d.querySelector('h1').textContent;
  p.d.querySelector('.skip').click();
  await settle();
  assert.equal(p.d.querySelector('main'),main);
  assert.equal(p.d.activeElement,main);
  assert.equal(p.w.location.hash,'#story-'+edition.top[0]);
  p.w.location.hash='#sources'; await settle();
  assert.equal(p.d.querySelector('main'),main);
  p.w.location.hash='#story-'+edition.top[0]; await settle();
  assert.equal(p.d.querySelector('main'),main);
  p.w.location.hash='#story-'+edition.top[1]; await settle();
  assert.notEqual(p.d.querySelector('h1').textContent,headline);
  assert.equal(p.d.activeElement,p.d.querySelector('h1'));
  p.w.location.hash='#story-'+edition.top[0]; await settle();
  assert.equal(p.d.querySelector('h1').textContent,headline);
  assert.equal(p.d.activeElement,p.d.querySelector('h1'));
  assert.deepEqual(p.errors,[]);
  p.close();
});

test('delayed page loading retains keyboard focus and a persistent status region',async()=>{
  for(const selector of ['.brand','.nav a[href="/"]','.skip','main']) {
    let release; const deferred=new Promise(r=>release=r);
    const p=await open('/',{fetch:u=>u==='/editions/index.json'?deferred:undefined});
    const status=p.d.querySelector('#page-status');
    assert.match(status.textContent,/Loading the edition/);
    assert.equal(p.d.querySelector('main').getAttribute('aria-busy'),'true');
    p.d.querySelector(selector).focus(); release(index); await settle();
    assert.equal(p.d.activeElement,p.d.querySelector(selector),selector);
    assert.equal(p.d.querySelector('#page-status'),status);
    assert.match(status.textContent,/Edition loaded.*44 stories/);
    assert.equal(p.d.querySelector('main').getAttribute('aria-busy'),'false');
    p.close();
  }
  const p=await open('/latest/');
  const main=p.d.querySelector('main');
  p.w.location.hash='#main'; await settle();
  p.w.location.hash=''; await settle();
  assert.equal(p.d.querySelector('main'),main);
  assert.notEqual(p.d.activeElement,p.d.querySelector('main h1'));
  p.close();
});

test('search recovery has a stable pending focus target without stealing later focus',async()=>{
  let release,attempts=0; const deferred=new Promise(r=>release=r);
  const p=await open('/search/?q=Hamilton',{fetch:u=>u.startsWith('/search/')?(++attempts===1?false:deferred):undefined});
  const status=p.d.querySelector('#search-status'),input=p.d.querySelector('input');
  p.d.querySelector('[data-act="retry"]').click();
  assert.equal(p.d.activeElement,status);
  assert.equal(p.d.querySelector('#search-results').getAttribute('aria-busy'),'true');
  assert.equal(p.d.querySelector('#search-results').getAttribute('aria-describedby'),'search-status');
  assert.equal(p.d.querySelector('#search-results').getAttribute('aria-label'),'Search results');
  input.focus(); release(monthly); await settle();
  assert.equal(p.d.activeElement,input);
  assert.equal(p.d.querySelector('#search-results').getAttribute('aria-busy'),'false');
  assert.match(status.textContent,/1 story found/);
  p.close();
});

test('Show more continues keyboard reading at the first newly revealed result',async()=>{
  const p=await open('/search/?q=the',{fetch:u=>u==='/editions/index.json'?{...index,editions:[index.editions[0],{...index.editions[0],date:'2026-09-07'}]}:u.includes('/search/2026-09')?{...monthly,stories:monthly.stories.map(s=>({...s,d:'2026-09-07'}))}:undefined});
  assert.equal(p.d.querySelectorAll('.hit').length,40);
  p.d.querySelector('[data-act="more"]').click(); await settle();
  assert.equal(p.d.activeElement,p.d.querySelectorAll('.hit h2 a')[40]);
  p.close();
});

test('search prefix, phrase, outlet, empty results and URL state', async () => {
  for (const [q, text] of [['Hamilt','Hamilton'], ['"Margaret Hamilton"','Hamilton'], ['Reuters','Reuters']]) {
    const p = await open('/search/?q='+encodeURIComponent(q));
    assert.ok(p.d.querySelectorAll('.hit').length > 0,q);
    assert.match(p.d.querySelector('.hits').textContent,new RegExp(text));
    assert.ok(p.d.querySelector('mark'));
    assert.equal(p.d.querySelector('.hits').getAttribute('aria-busy'),'false');
    assert.deepEqual(p.errors,[]);
    p.close();
  }
  const p = await open('/search/?q=zzzznoresults');
  assert.equal(p.d.querySelectorAll('.hit').length,0);
  assert.match(p.d.querySelector('.search-empty').textContent,/No matching stories/);
  assert.equal(p.d.querySelector('.search-empty a').getAttribute('href'),'/archive/');
  p.close();
});

test('search live query, section, sort, submit focus and clear', async () => {
  const p = await open('/search/');
  const input = p.d.querySelector('input'), cat = p.d.querySelector('select');
  assert.notEqual(p.d.activeElement,input);
  input.focus(); input.value='AI'; input.dispatchEvent(new p.w.Event('input'));
  await new Promise(r=>setTimeout(r,180));
  assert.ok(p.d.querySelectorAll('.hit').length>0);
  cat.value='Science & AI'; cat.dispatchEvent(new p.w.Event('change')); await settle();
  assert.ok([...p.d.querySelectorAll('.hit')].every(n=>n.dataset.cat==='Science & AI'));
  p.d.querySelector('[data-sort="best"]').click(); await settle();
  assert.match(p.w.location.search,/sort=best/);
  assert.match(p.w.location.search,/cat=Science/);
  input.focus(); p.d.querySelector('form').dispatchEvent(new p.w.Event('submit',{cancelable:true})); await settle();
  assert.equal(p.d.activeElement,input);
  input.value=''; input.dispatchEvent(new p.w.Event('input')); await new Promise(r=>setTimeout(r,180));
  assert.equal(p.d.querySelectorAll('.hit').length,0);
  assert.match(p.d.querySelector('[role="status"]').textContent,/Type to search/);
  p.close();
});

test('unavailable search month can be retried without reloading', async () => {
  let attempts=0;
  const p=await open('/search/?q=Hamilton',{fetch:u=>u.startsWith('/search/') && ++attempts===1 ? false : undefined});
  assert.match(p.d.querySelector('[role="status"]').textContent,/unavailable.*No editions could be searched/);
  assert.match(p.d.querySelector('.search-recovery').textContent,/October 2026/);
  assert.ok(p.d.querySelector('.search-recovery a[href="/archive/"]'));
  assert.doesNotMatch(p.d.querySelector('.hits').textContent,/No matching stories/);
  p.d.querySelector('[data-act="retry"]').click(); await settle();
  assert.equal(attempts,2);
  assert.ok(p.d.querySelectorAll('.hit').length>0);
  assert.equal(p.d.querySelector('[data-act="retry"]'),null);
  assert.equal(p.d.querySelector('.search-recovery').textContent,'');
  assert.equal(p.d.activeElement,p.d.querySelector('[role="status"]'));
  p.close();
});

test('a failed prefetched month stays retryable after repeated failures',async()=>{
  let attempts=0;
  const p=await open('/search/',{fetch:u=>u.startsWith('/search/') && ++attempts<=2 ? false : undefined});
  assert.equal(attempts,1);
  const input=p.d.querySelector('input'); input.value='Hamilton';
  const cat=p.d.querySelector('select'); cat.value='Tech'; cat.dispatchEvent(new p.w.Event('change'));
  p.d.querySelector('[data-sort="best"]').click(); await settle();
  assert.equal(attempts,1);
  assert.match(p.d.querySelector('[role="status"]').textContent,/unavailable/);
  p.d.querySelector('[data-act="retry"]').click(); await settle();
  assert.equal(attempts,2);
  assert.ok(p.d.querySelector('[data-act="retry"]'));
  assert.equal(p.d.activeElement,p.d.querySelector('[role="status"]'));
  p.d.querySelector('[data-act="retry"]').click(); await settle();
  assert.equal(attempts,3);
  assert.equal(p.d.querySelectorAll('.hit').length,1);
  assert.equal(new URLSearchParams(p.w.location.search).get('q'),'Hamilton');
  assert.equal(new URLSearchParams(p.w.location.search).get('cat'),'Tech');
  assert.equal(new URLSearchParams(p.w.location.search).get('sort'),'best');
  assert.equal(p.d.querySelector('[data-act="retry"]'),null);
  p.close();
});

test('monthly batching, partial failure, older search and pagination remain intact', async () => {
  const dates=Array.from({length:7},(_,i)=>`2026-${String(10-i).padStart(2,'0')}-07`);
  const idx={...index,editions:dates.map(date=>({...index.editions[0],date}))};
  let fail=true;
  const p=await open('/search/?q=the',{fetch:u=>{
    if(u==='/editions/index.json') return idx;
    if(u.startsWith('/search/')) {
      if(u.includes('2026-09') && fail) return false;
      return {...monthly,stories:monthly.stories.map(s=>({...s,d:u.slice(8,15)+'-07'}))};
    }
  }});
  assert.equal(p.requests.filter(u=>u.startsWith('/search/')).length,6);
  assert.equal(p.d.querySelectorAll('.hit').length,40);
  assert.match(p.d.querySelector('[role="status"]').textContent,/incomplete/);
  assert.match(p.d.querySelector('[role="status"]').textContent,/5 searched editions/);
  assert.match(p.d.querySelector('.search-recovery').textContent,/September 2026/);
  p.d.querySelector('[data-act="more"]').click(); await settle();
  assert.ok(p.d.querySelectorAll('.hit').length>40);
  fail=false; p.d.querySelector('[data-act="retry"]').click(); await settle();
  assert.doesNotMatch(p.d.querySelector('[role="status"]').textContent,/incomplete/);
  assert.match(p.d.querySelector('[role="status"]').textContent,/6 searched editions/);
  p.d.querySelector('[data-act="older"]').click(); await settle();
  assert.ok(p.requests.includes('/search/2026-04.json'));
  assert.equal(p.d.querySelector('[data-act="older"]'),null);
  p.close();
});

test('section and sort actions use the latest input before its debounce finishes', async()=>{
  for(const action of ['section','sort']) {
    const p=await open('/search/?q=zzzznoresults');
    const input=p.d.querySelector('input');
    input.value='Hamilton'; input.dispatchEvent(new p.w.Event('input'));
    if(action==='section') {
      const cat=p.d.querySelector('select'); cat.value='Tech'; cat.dispatchEvent(new p.w.Event('change'));
    } else p.d.querySelector('[data-sort="best"]').click();
    await settle();
    assert.equal(p.d.querySelectorAll('.hit').length,1);
    assert.equal(new URLSearchParams(p.w.location.search).get('q'),'Hamilton');
    assert.match(p.d.querySelector('.hit h2').textContent,/Hamilton/);
    p.close();
  }
});

test('invalid section links recover to all sections; filtered empty results can broaden',async()=>{
  for(const cat of ['bogus','toString','__proto__']) {
    const p=await open('/search/?q=Hamilton&cat='+cat+'&sort=best');
    assert.equal(p.d.querySelector('select').value,'');
    assert.equal(p.d.querySelectorAll('.hit').length,1);
    assert.equal(new URLSearchParams(p.w.location.search).has('cat'),false);
    assert.equal(new URLSearchParams(p.w.location.search).get('sort'),'best');
    p.close();
  }
  const p=await open('/search/?q=Hamilton&cat=Sports&sort=best');
  assert.equal(p.d.querySelectorAll('.hit').length,0);
  assert.match(p.d.querySelector('.search-empty').textContent,/No matching stories/);
  p.d.querySelector('[data-act="all-sections"]').click(); await settle();
  assert.equal(p.d.querySelectorAll('.hit').length,1);
  assert.equal(p.d.querySelector('select').value,'');
  assert.equal(new URLSearchParams(p.w.location.search).get('q'),'Hamilton');
  assert.equal(new URLSearchParams(p.w.location.search).get('sort'),'best');
  assert.equal(p.d.activeElement,p.d.querySelector('[role="status"]'));
  p.close();
});

test('invalid monthly data is retryable; valid empty data remains a true empty result',async()=>{
  const p=await open('/search/?q=Hamilton',{fetch:u=>u.startsWith('/search/')?{}:undefined});
  assert.match(p.d.querySelector('[role="status"]').textContent,/unavailable/);
  assert.ok(p.d.querySelector('[data-act="retry"]'));
  assert.equal(p.d.querySelector('.search-empty'),null);
  p.close();
  const empty=await open('/search/?q=Hamilton',{fetch:u=>u.startsWith('/search/')?{...monthly,stories:[]}:undefined});
  assert.match(empty.d.querySelector('[role="status"]').textContent,/0 stories found across 1 searched edition/);
  assert.match(empty.d.querySelector('.search-empty').textContent,/No matching stories/);
  assert.equal(empty.d.querySelector('[data-act="retry"]'),null);
  empty.close();
});

test('empty search scope and punctuation guidance stay distinct from unavailable data',async()=>{
  const p=await open('/search/?q=zzzznoresults',{fetch:u=>u==='/editions/index.json'?{...index,editions:Array.from({length:7},(_,i)=>({...index.editions[0],date:`2026-${String(10-i).padStart(2,'0')}-07`}))}:u.startsWith('/search/')?monthly:undefined});
  assert.match(p.d.querySelector('.search-empty').textContent,/No matches in the searched editions/);
  assert.ok(p.d.querySelector('[data-act="older"]'));
  p.close();
  const punctuation=await open('/search/?q=!!!');
  assert.match(punctuation.d.querySelector('[role="status"]').textContent,/Enter a word or phrase/);
  assert.equal(punctuation.d.querySelector('.search-empty'),null);
  punctuation.close();
});

test('a delayed earlier search cannot overwrite the current query', async()=>{
  let release;
  const deferred=new Promise(r=>release=r);
  const p=await open('/search/?q=Hamilton',{fetch:u=>u.startsWith('/search/')?deferred:undefined});
  const input=p.d.querySelector('input'); input.value='zzzznoresults';
  p.d.querySelector('form').dispatchEvent(new p.w.Event('submit',{cancelable:true}));
  release(monthly); await settle();
  assert.equal(p.d.querySelectorAll('.hit').length,0);
  assert.match(p.d.querySelector('.search-empty').textContent,/No matching stories/);
  assert.equal(p.d.querySelector('.hits').getAttribute('aria-busy'),'false');
  p.close();
});

test('failed edition load keeps archive recovery and safe text rendering', async()=>{
  const p=await open('/',{fetch:u=>u.includes('/editions/2026')?false:undefined});
  assert.match(p.d.querySelector('main').textContent,/could not be loaded/);
  assert.ok(p.d.querySelector('main a[href="/archive/"]'));
  p.close();
  const unsafe=structuredClone(edition); unsafe.stories[0].headline='<img src=x onerror=alert(1)>';
  const q=await open('/',{fetch:u=>u.includes('/editions/2026')?unsafe:undefined});
  assert.equal(q.d.querySelector('h1').textContent,unsafe.stories[0].headline);
  assert.equal(q.d.querySelector('h1 img'),null);
  q.close();
});

test('generation and source times remain explicit on every news-reading view',async()=>{
  for(const path of ['/', '/daily/2026-10-07/', '/latest/', '/technology/', '/science/', '/world/', '/daily/2026-10-07/#story-'+edition.top[0]]) {
    const p=await open(path);
    const generated=p.d.querySelector('.edition-full time[datetime="'+edition.generated_utc+'"]');
    assert.ok(generated,path);
    assert.match(generated.textContent,/Generated.*2026/);
    assert.match(p.d.querySelector('.strip').textContent,/Latest edition.*Update 2/);
    if(path.includes('#story')) {
      assert.ok(p.d.querySelector('.sources time[datetime]'));
      assert.equal(p.d.querySelector('.story-main .meta time').getAttribute('datetime'),edition.stories[0].newest_published_utc);
    }
    p.close();
  }
});

test('null source URLs and empty optional values remain readable plain text',async()=>{
  const ed=structuredClone(edition),story=ed.stories[0];
  story.sources[0].url=null; story.sources[0].published_utc=null;
  story.sources[0].title='<b>Source title is plain text</b>';
  story.why_it_matters=''; story.top_rank=null; story.summary=['A short summary.']; ed.compared_with=null;
  const p=await open('/daily/2026-10-07/#story-'+story.id,{fetch:u=>u.includes('/editions/2026')?ed:undefined});
  const source=p.d.querySelector('.source');
  assert.equal(source.querySelector('a'),null);
  assert.equal(source.querySelector('.title').textContent,story.sources[0].title);
  assert.equal(source.querySelector('b'),null);
  assert.equal(source.querySelector('time'),null);
  assert.match(source.textContent,/Time not stated/);
  assert.equal(p.d.querySelector('.why-box'),null);
  assert.equal(p.d.querySelectorAll('.story-body p').length,1);
  p.close();
  const card=await open('/technology/',{fetch:u=>u.includes('/editions/2026')?ed:undefined});
  assert.equal(card.d.querySelectorAll('.card').length,8);
  assert.equal(card.d.querySelector('a[href$="/null"]'),null);
  card.close();
});

test('search links recover changed IDs by exact or clearly shared headlines on the same date',async()=>{
  const original=edition.stories[0], ed=structuredClone(edition), replacement='abcdef123456';
  ed.stories[0].id=replacement; ed.revision=3;
  ed.top=ed.top.map(id=>id===original.id?replacement:id);
  ed.sections.forEach(sec=>sec.ids=sec.ids.map(id=>id===original.id?replacement:id));
  for(const hint of [original.headline.toUpperCase()+'!', 'Computing Pioneer Margaret Hamilton Dies Aged 90']) {
    const p=await open('/daily/2026-10-07/?headline='+encodeURIComponent(hint)+'#story-'+original.id,{fetch:u=>u.includes('/editions/2026')?ed:undefined});
    assert.equal(p.d.querySelector('h1').textContent,original.headline);
    assert.equal(p.w.location.hash,'#story-'+replacement);
    assert.equal(p.w.location.search,'');
    assert.match(p.d.querySelector('.story-recovery').textContent,/headline match/);
    assert.equal(p.d.querySelectorAll('.sources .source').length,original.sources.length);
    p.close();
  }
  const search=await open('/search/?q=Hamilton');
  const href=new URL(search.d.querySelector('.hit h2 a').href);
  assert.equal(href.searchParams.get('headline'),original.headline);
  assert.equal(href.hash,'#story-'+original.id);
  search.close();
});

test('missing story recovery never guesses on ties, weak matches, or absent headline hints',async()=>{
  const ed=structuredClone(edition);
  ed.stories[0].headline='Alpha beta gamma delta'; ed.stories[1].headline='Alpha beta gamma epsilon';
  for(const hint of ['Alpha beta gamma zeta', 'Alpha beta gamma delta', 'Alpha unknown unrelated', '']) {
    const doc=structuredClone(ed);
    if(hint==='Alpha beta gamma delta') doc.stories[1].headline=doc.stories[0].headline;
    const p=await open('/daily/2026-10-07/'+(hint?'?headline='+encodeURIComponent(hint):'')+'#story-abcdef123456',{fetch:u=>u.includes('/editions/2026')?doc:undefined});
    assert.ok(p.d.querySelector('.front'));
    assert.equal(p.d.querySelector('.story'),null);
    assert.match(p.d.querySelector('.story-recovery').textContent,/full edition/);
    p.close();
  }
  ed.stories[0].headline='What You Need To Know About Alpha';
  const boilerplate=await open('/daily/2026-10-07/?headline=What+You+Need+To+Know+About+Beta#story-abcdef123456',{fetch:u=>u.includes('/editions/2026')?ed:undefined});
  assert.equal(boilerplate.d.querySelector('.story'),null);
  assert.match(boilerplate.d.querySelector('.story-recovery').textContent,/full edition/);
  boilerplate.close();
});

test('withdrawn edition JSON and dated 404 shells provide archive recovery',async()=>{
  const removed=await open('/daily/2026-10-07/#story-'+edition.top[0],{fetch:u=>u.includes('/editions/2026')?{ok:false,status:404}:undefined});
  assert.match(removed.d.querySelector('h1').textContent,/This edition isn't available\. It may have been withdrawn\./);
  assert.ok(removed.d.querySelector('main a[href="/archive/"]'));
  removed.close();
  const p=await open('/daily/2026-10-07/#story-'+edition.top[0],{fetch:u=>u.includes('/editions/2026')?false:undefined});
  // A temporary server failure is not described as a withdrawal.
  assert.doesNotMatch(p.d.querySelector('h1').textContent,/taken off/);
  p.close();
  const withdrawn=await open('/daily/2026-10-06/',{shell:'/404.html'});
  assert.match(withdrawn.d.querySelector('h1').textContent,/This edition isn't available\. It may have been withdrawn\./);
  assert.ok(withdrawn.d.querySelector('main a[href="/archive/"]'));
  assert.equal(withdrawn.d.querySelector('#page-status').textContent,withdrawn.d.querySelector('h1').textContent);
  withdrawn.close();
});

test('the ticker shows what changed since the previous update and flags missing source types', async () => {
  const ed = structuredClone(edition);
  ed.compared_with = {edition_date: ed.edition_date, revision: 1};
  ed.stories[0].change = 'new'; ed.stories[1].change = 'new'; ed.stories[2].change = 'updated';
  ed.changes = {dropped: [{headline: 'Gone', category: 'News'}]};
  ed.sources_answered = 8;
  const p = await open('/latest/', {fetch: u => u.endsWith('2026-10-07.json') ? ed : undefined});
  const ticker = p.d.querySelector('.ticker');
  assert.match(ticker.textContent, new RegExp(`Since update 1: \\+${ed.stories.filter(s => s.change === 'new').length} new · ${ed.stories.filter(s => s.change === 'updated').length} updated · 1 dropped`));
  assert.ok(ticker.querySelector('.warn'));
  assert.match(ticker.querySelector('.warn').textContent, /^8\/10 source types up$/);
  assert.equal(p.d.querySelector('main .wrap').firstElementChild.className, 'strip', 'the ticker sits directly under the header');
  p.close();
});

test('outlet tags show one outlet once and only for stories with several independent outlets', async () => {
  const p = await open('/');
  for (const item of p.d.querySelectorAll('main article[data-cat]')) {
    const story = edition.stories.find(s => 'story-' + s.id === item.id);
    if (!story) continue;
    const tags = item.querySelector('.outlet-tags');
    const outlets = new Set(story.coverage.publishers.map(normOutlet));
    if (outlets.size < 2) { assert.equal(tags, null, story.headline); continue; }
    const names = [...tags.querySelectorAll('.tag:not(.more)')].map(t => normOutlet(t.textContent));
    assert.equal(new Set(names).size, names.length);
    const more = tags.querySelector('.tag.more');
    assert.equal(names.length + (more ? Number(more.textContent.slice(1)) : 0), outlets.size, story.headline);
  }
  p.close();
});

test('Local stories get a Frisco & North Texas band on Home and their own page', async () => {
  const ed = structuredClone(edition);
  const moved = ed.sections.find(s => s.category === 'News').ids.filter(id => !ed.top.includes(id)).slice(0, 2);
  for (const id of moved) ed.stories.find(s => s.id === id).category = 'Local';
  ed.sections.forEach(sec => { sec.ids = sec.ids.filter(id => !moved.includes(id)); });
  ed.sections.splice(1, 0, {category: 'Local', ids: moved});
  const fetch = u => u.endsWith('2026-10-07.json') ? ed : undefined;
  const home = await open('/', {fetch});
  const band = home.d.querySelector('.band[data-cat="Local"]');
  assert.equal(band.querySelector('.band-title').textContent, 'Frisco & North Texas');
  assert.equal(band.querySelectorAll('.card').length, 2);
  assert.equal(band.querySelector('.band-link').getAttribute('href'), '/local/');
  assert.match(band.querySelector('.card .kicker').textContent, /^Local/);
  assert.ok(home.d.querySelector('.section-shortcuts a[href$="#band-local"]'));
  home.close();
  const page = await open('/local/', {fetch});
  assert.equal(page.d.querySelector('h1').textContent, 'Frisco & North Texas');
  assert.equal(page.d.querySelectorAll('.card').length, 2);
  assert.equal(page.d.querySelector('.nav [aria-current="page"]').textContent, 'Local');
  page.close();
  const search = await open('/search/');
  assert.equal(search.d.querySelector('option[value="Local"]').textContent, 'Local');
  search.close();
});
