const test = require('node:test');
const assert = require('node:assert/strict');
const {mkdtempSync, cpSync, readFileSync, writeFileSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {resolve, join} = require('node:path');
const {checkEditions} = require('../scripts/check-editions.cjs');
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
