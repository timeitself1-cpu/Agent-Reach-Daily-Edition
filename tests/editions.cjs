const test = require('node:test');
const assert = require('node:assert/strict');
const {mkdtempSync, cpSync, readFileSync, writeFileSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {resolve, join} = require('node:path');
const {checkEditions} = require('../scripts/check-editions.cjs');
const {editionWarnings, headlineSimilarity} = require('../scripts/check-editions.cjs');
const {normOutlet, dedupeOutlets} = require('../assets/site.js');
const fixtures = resolve(__dirname, 'fixtures');
function mutate(file, change) {
  const dir = mkdtempSync(join(tmpdir(), 'agent-reach-test-'));
  try {
    cpSync(fixtures, dir, {recursive: true});
    const path = resolve(dir, file);
    const data = JSON.parse(readFileSync(path, 'utf8'));
    change(data);
    writeFileSync(path, JSON.stringify(data));
    checkEditions(dir);
  } finally { rmSync(dir, {recursive: true, force: true}); }
}
test('published-file validator accepts a complete frozen publication', () => {
  assert.equal(checkEditions(fixtures).editions.size, 1);
});
test('published-file validator rejects stale index counts and revisions', () => {
  assert.throws(() => mutate('editions/index.json', data => {data.editions[0].stories++;}), /story count/);
  assert.throws(() => mutate('editions/index.json', data => {data.editions[0].revision++;}), /revision matches/);
});
test('published-file validator rejects unreachable IDs and duplicate section membership', () => {
  assert.throws(() => mutate('editions/2026-10-07.json', data => {data.top[0] = 'abcdef123456';}), /top IDs resolve/);
  assert.throws(() => mutate('editions/2026-10-07.json', data => {data.sections[0].ids.push(data.sections[0].ids[0]);}), /section membership/);
});
test('published-file validator rejects old or incomplete monthly search data', () => {
  assert.throws(() => mutate('search/2026-10.json', data => {data.stories[0].h = 'Stale headline';}), /search headline/);
  assert.throws(() => mutate('search/2026-10.json', data => {data.stories.pop();}), /exact search membership/);
});
test('published-file validator tolerates optional empty values and unknown fields', () => {
  mutate('editions/2026-10-07.json', data => {
    data.future_field = {anything: true};
    data.compared_with = null;
    data.stories[0].why_it_matters = '';
    data.stories[0].summary = [];
    data.stories[0].sources[0].url = null;
    data.stories[0].sources[0].published_utc = null;
  });
});

test('outlet aliases share keys and prefer readable names', () => {
  for (const [a, b] of [['AP News', 'www.apnews.com'], ['NASA', 'NASA (.gov)'], ['Reuters', 'reuters.com'], ['CNBC', 'cnbc.com'], ['X', 'twitter.com'], ['The New York Times', 'nytimes.com']]) assert.equal(normOutlet(a), normOutlet(b));
  assert.deepEqual(dedupeOutlets(['apnews.com', 'AP News', 'NASA (.gov)', 'NASA']), ['AP News', 'NASA']);
});

test('recorded revision 6 warns for lead, Crew-12, Iran pair and all 21 redirects', () => {
  const ed = JSON.parse(readFileSync(resolve(fixtures, 'roadmap-2026-10-08.json')));
  const warnings = editionWarnings(ed);
  assert.ok(warnings.some(w => w.includes('0317f2df6bc9') && w.includes('duplicate')));
  const crew = ed.stories.find(s => /Crew-12/i.test(s.headline));
  assert.ok(warnings.some(w => w.includes(crew.id) && w.includes('duplicate')));
  assert.equal(warnings.filter(w => w.includes('Google News URL')).length, 21);
  const matching = warnings.filter(w => w.includes('matching headlines'));
  assert.equal(matching.length, 1); assert.match(matching[0], /\(0\.50\).*Iran/);
  assert.equal(headlineSimilarity('The new ships arrive before dusk', 'Ships arrived after dawn'), 0.2);
});

test('data warnings are exported, prefixed WARN, and never fail validation', () => {
  const messages = [], original = console.warn;
  console.warn = line => messages.push(line);
  try {
    const result = checkEditions(fixtures);
    assert.ok(result.warnings.length);
    assert.deepEqual(messages, result.warnings.map(w => 'WARN ' + w));
  } finally {console.warn = original;}
});

test('live check polls revisions and names missing headers and exposed paths without network', async () => {
  const {liveCheck, HEADERS} = require('../scripts/live-check.cjs');
  const index = {latest: '2026-10-08', editions: [{date: '2026-10-08', revision: 6}]};
  let polls = 0, time = 0, missing, exposed;
  const options = {now: () => time, wait: async ms => {time += ms;}, fetchImpl: async url => {
    if (url.endsWith('/editions/index.json')) return {ok: true, json: async () => ({latest: index.latest, editions: [{...index.editions[0], revision: ++polls < 2 ? 5 : 6}]})};
    if (url.endsWith('/')) return {ok: true, headers: new Headers(HEADERS.filter(h => h !== missing).map(h => [h, 'present']))};
    return {status: url.endsWith(exposed || '!') ? 200 : 404};
  }};
  await liveCheck(index, options); assert.equal(polls, 2);
  missing = 'X-Frame-Options'; await assert.rejects(liveCheck(index, options), /Missing security header: X-Frame-Options/);
  missing = null; exposed = '/package.json'; await assert.rejects(liveCheck(index, options), /Exposed path: \/package.json/);
  const stale = {...options, timeout: 30000, fetchImpl: async () => ({ok: true, json: async () => ({...index, latest: '2026-10-07'})})};
  await assert.rejects(liveCheck(index, stale), /did not match/);
});
