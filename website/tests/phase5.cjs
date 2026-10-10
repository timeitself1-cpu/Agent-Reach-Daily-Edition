// Phase 4/5: one taxonomy (editions/sections.json) and one timestamp policy (reader's zone, UTC toggle).
const {JSDOM, VirtualConsole} = require('jsdom');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const assert = require('node:assert/strict');
const test = require('node:test');
const root = resolve(__dirname, '..');
const fixtures = resolve(__dirname, 'fixtures');
const script = readFileSync(resolve(root, 'assets/site.js'), 'utf8');
const sections = JSON.parse(readFileSync(resolve(root, 'editions/sections.json'), 'utf8'));
const settle = () => new Promise(r => setTimeout(r, 40));

async function open(path, {storage, sectionsFile, now = '2026-10-08T16:00:00Z'} = {}) {
  const errors = [], vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(e.message));
  const file = path.startsWith('/daily/2026') ? resolve(fixtures, '.' + path, 'index.html') : resolve(root, '.' + path, 'index.html');
  const dom = new JSDOM(readFileSync(file, 'utf8'), {url: 'https://example.test' + path, runScripts: 'outside-only', virtualConsole: vc});
  const w = dom.window, d = w.document;
  w.scrollTo = () => {}; w.HTMLElement.prototype.scrollIntoView = () => {};
  w.Date.now = () => Date.parse(now);
  if (storage === 'blocked') Object.defineProperty(w, 'localStorage', {get() { throw new Error('blocked'); }});
  else if (storage) for (const [k, v] of Object.entries(storage)) w.localStorage.setItem(k, v);
  w.fetch = async url => {
    if (url === '/editions/sections.json') return sectionsFile ? {ok: true, json: async () => sectionsFile} : {ok: false, status: 503};
    return {ok: true, json: async () => JSON.parse(readFileSync(resolve(fixtures, '.' + url)))};
  };
  w.eval(script);
  await settle();
  return {w, d, errors, close: () => w.close()};
}
const navLabels = d => [...d.querySelectorAll('.nav a')].map(a => a.textContent.trim());

test('the built-in section table is identical to editions/sections.json (it is only the fallback)', async () => {
  const p = await open('/world/');
  const expected = sections.sections.filter(s => !s.retired).map(s => s.label);
  const nav = navLabels(p.d);
  for (const label of expected) assert.ok(nav.includes(label), label);
  assert.deepEqual(expected.filter(l => nav.includes(l)), expected, 'same order');
  p.close();
});

test('sections.json drives labels and order when it can be read', async () => {
  const renamed = structuredClone(sections);
  renamed.sections.find(s => s.id === 'News').label = 'The World';
  const p = await open('/world/', {sectionsFile: renamed});
  assert.ok(navLabels(p.d).includes('The World'));
  assert.ok(!navLabels(p.d).includes('World & Nation'));
  p.close();
});

test('times follow the reader zone and a UTC toggle that is remembered', async () => {
  process.env.TZ = 'America/Chicago';
  const p = await open('/daily/2026-10-07/');
  const generated = p.d.querySelector('time[data-prefix="Generated "]');
  assert.ok(generated, 'generation time present');
  assert.match(generated.textContent, /Generated .* (CDT|CST)$/);
  const utc = [...p.d.querySelectorAll('.tz-control .seg')].find(b => b.dataset.tz === 'utc');
  utc.click();
  assert.equal(p.w.localStorage.getItem('tz'), 'utc');
  assert.match(generated.textContent, /UTC$/);
  assert.match(p.d.querySelector('.tz-name').textContent, /UTC/);
  p.close();
  const again = await open('/daily/2026-10-07/', {storage: {tz: 'utc'}});
  assert.match(again.d.querySelector('time[data-prefix="Generated "]').textContent, /UTC$/);
  again.close();
});

test('the page works when storage is blocked', async () => {
  const p = await open('/daily/2026-10-07/', {storage: 'blocked'});
  assert.deepEqual(p.errors, []);
  assert.ok(p.d.querySelector('main h1'));
  [...p.d.querySelectorAll('.tz-control .seg')].find(b => b.dataset.tz === 'utc').click();
  assert.match(p.d.querySelector('time[data-prefix="Generated "]').textContent, /UTC$/);
  p.close();
});

test('only source-stated publication times are shown (none invented for missing ones)', async () => {
  const p = await open('/daily/2026-10-07/');
  const ed = JSON.parse(readFileSync(resolve(fixtures, 'editions/2026-10-07.json'), 'utf8'));
  const stated = ed.stories.flatMap(s => s.sources).filter(s => s.published_utc).length;
  const shown = p.d.querySelectorAll('.source time.when').length;
  assert.ok(shown <= stated, `${shown} shown, ${stated} stated`);
  p.close();
});
