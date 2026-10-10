const assert = require('node:assert/strict');
const {readFileSync, readdirSync} = require('node:fs');
const {resolve} = require('node:path');
const {JSDOM} = require('jsdom');
const {normOutlet, plural} = require('../assets/site.js');
const STOP_WORDS = new Set('a an the of to in on for and or with at by from as is are was be not before after says said us new'.split(' '));
function headlineWords(headline) {
  return new Set((headline.toLowerCase().match(/[a-z0-9]+/g) || []).filter(w => !STOP_WORDS.has(w)).map(w => w.replace(/s$/, '')));
}
function headlineSimilarity(a, b) {
  const x = headlineWords(a), y = headlineWords(b);
  return [...x].filter(w => y.has(w)).length / Math.max(1, new Set([...x, ...y]).size);
}
// ISO 8601 with a time zone, as the publisher writes it (2026-10-09T12:49:00Z or +00:00).
const isoStamp = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/;
// A real calendar day in YYYY-MM-DD form (rejects 2026-02-31 as well as 2026-2-3).
const realDate = d => /^\d{4}-\d{2}-\d{2}$/.test(d) && !Number.isNaN(Date.parse(d + 'T00:00:00Z')) && new Date(d + 'T00:00:00Z').toISOString().slice(0, 10) === d;
// Editorial warnings: published data stays valid, but a reader would see something odd. They never fail the build,
// because an edition already on the site must keep building (the publisher, not the website, fixes its data).
function editionWarnings(ed) {
  const warnings = [];
  for (const story of ed.stories) {
    const names = story.coverage.publishers;
    if (new Set(names.map(normOutlet)).size < names.length) warnings.push(`${ed.edition_date} story ${story.id}: duplicate normalised outlets`);
    const urls = story.sources.map(src => src.url).filter(Boolean);
    for (const url of new Set(urls.filter((u, i) => urls.indexOf(u) !== i))) warnings.push(`${ed.edition_date} story ${story.id}: duplicate source URL ${url}`);
    // The independent count cannot exceed the distinct newsrooms the edition names (publishers or reporting sources).
    const outlets = new Set([...names, ...story.sources.filter(src => src.kind !== 'signal').map(src => src.outlet)].map(normOutlet).filter(Boolean));
    const reported = story.coverage.independent_reports || 0;
    if (reported > outlets.size) warnings.push(`${ed.edition_date} story ${story.id}: ${plural(reported, 'independent report')} but only ${plural(outlets.size, 'distinct newsroom')} named`);
    for (const stamp of [story.newest_published_utc, ...story.sources.map(src => src.published_utc)]) {
      if (stamp && !isoStamp.test(stamp)) warnings.push(`${ed.edition_date} story ${story.id}: timestamp not in ISO 8601 form: ${stamp}`);
    }
    for (const source of story.sources) {
      try {
        if (new URL(source.url).hostname.toLowerCase() === 'news.google.com') warnings.push(`${ed.edition_date} story ${story.id}: Google News URL ${source.url}`);
      } catch (_) { /* Null/invalid URLs are handled by contract validation. */ }
    }
  }
  for (let i = 0; i < ed.stories.length; i++) for (let j = i + 1; j < ed.stories.length; j++) {
    const a = ed.stories[i], b = ed.stories[j], overlap = headlineSimilarity(a.headline, b.headline);
    if (overlap >= 0.4) warnings.push(`${ed.edition_date}: matching headlines ${a.id} / ${b.id} (${overlap.toFixed(2)}): ${a.headline} / ${b.headline}`);
  }
  return warnings;
}
const readJson = (root, file) => JSON.parse(readFileSync(resolve(root, file), 'utf8'));
const sameSet = (actual, expected, message) => assert.deepEqual([...actual].sort(), [...expected].sort(), message);
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
function checkEditions(root) {
  const index = readJson(root, 'editions/index.json');
  assert.equal(index.schema_version, 1, 'supported index schema');
  assert.ok(Array.isArray(index.editions), 'archive list');
  const dates = index.editions.map(e => e.date);
  assert.equal(new Set(dates).size, dates.length, 'unique archive dates');
  assert.ok(dates.every(d => datePattern.test(d)), 'valid edition filenames');
  for (const d of dates) assert.ok(realDate(d), `${d}: a real calendar date`);
  assert.deepEqual(dates, dates.slice().sort().reverse(), 'newest edition first');
  assert.equal(index.latest, dates[0] || null, 'latest matches archive');
  sameSet(readdirSync(resolve(root, 'editions')).filter(f => datePattern.test(f.slice(0, -5)) && f.endsWith('.json')).map(f => f.slice(0, -5)), dates, 'no withdrawn/orphan edition JSON');
  sameSet(readdirSync(resolve(root, 'daily')).filter(f => datePattern.test(f)), dates, 'no withdrawn/orphan dated pages');
  const editions = new Map();
  for (const entry of index.editions) {
    const ed = readJson(root, `editions/${entry.date}.json`);
    const context = entry.date;
    assert.equal(ed.schema_version, 1, context + ': supported edition schema');
    assert.equal(ed.edition_date, entry.date, context + ': filename/date');
    assert.equal(ed.revision, entry.revision, context + ': revision matches index');
    assert.ok(Number.isInteger(ed.revision) && ed.revision > 0, context + ': positive revision');
    assert.equal(ed.generated_utc, entry.generated_utc, context + ': generation matches index');
    assert.ok(Number.isFinite(Date.parse(ed.generated_utc)), context + ': generation timestamp');
    assert.ok(Array.isArray(ed.stories) && ed.stories.length, context + ': nonempty stories');
    assert.equal(ed.stories.length, entry.stories, context + ': story count matches index');
    const byId = new Map();
    for (const s of ed.stories) {
      assert.match(s.id, /^[0-9a-f]{6,40}$/, context + ': routable story ID');
      assert.ok(!byId.has(s.id), context + ': unique story ID');
      byId.set(s.id, s);
      assert.ok(typeof s.headline === 'string' && s.headline.trim(), context + `: empty headline (story ${s.id})`);
      if (s.newest_published_utc != null) assert.ok(Number.isFinite(Date.parse(s.newest_published_utc)), context + `: malformed newest report time (story ${s.id})`);
      assert.ok(typeof s.category === 'string' && s.category, context + ': category');
      assert.ok(Array.isArray(s.summary) && s.summary.every(t => typeof t === 'string'), context + ': plain summary sentences');
      assert.ok(Array.isArray(s.sources), context + ': source list');
      assert.ok(s.coverage && Array.isArray(s.coverage.publishers), context + ': coverage publishers');
      assert.ok(['strong', 'moderate', 'limited'].includes(s.coverage.level), context + ': coverage level');
      for (const src of s.sources) {
        assert.ok(typeof src.title === 'string' && typeof src.outlet === 'string', context + ': source text');
        assert.ok(['report', 'repeat', 'signal'].includes(src.kind), context + ': source kind');
        if (src.url != null) assert.match(src.url, /^https?:\/\//, context + ': absolute source URL');
        if (src.published_utc) assert.ok(Number.isFinite(Date.parse(src.published_utc)), context + `: malformed source time (story ${s.id})`);
      }
      if (s.url != null) { // optional: the article the headline opens, always one of the story's own sources
        assert.match(s.url, /^https?:\/\//, context + ': absolute headline link');
        assert.ok(s.sources.some(src => src.url === s.url), context + ': headline link is a story source');
      }
    }
    sameSet(ed.stories.map(s => s.rank), Array.from({length: ed.stories.length}, (_, i) => i + 1), context + ': contiguous unique ranks');
    assert.equal(new Set(ed.top).size, ed.top.length, context + ': unique top IDs');
    assert.ok(ed.top.every(id => byId.has(id)), context + ': top IDs resolve');
    const sections = new Map();
    for (const section of ed.sections) {
      assert.ok(!sections.has(section.category), context + ': unique sections');
      sections.set(section.category, section.ids.length);
      sameSet(section.ids, ed.stories.filter(s => s.category === section.category).map(s => s.id), context + ': section membership ' + section.category);
    }
    sameSet(ed.sections.flatMap(s => s.ids), byId.keys(), context + ': every story belongs to a section');
    assert.deepEqual(Object.fromEntries(sections), entry.sections, context + ': index section counts');
    const dom = new JSDOM(readFileSync(resolve(root, `daily/${entry.date}/index.html`), 'utf8'));
    try {
      assert.equal(dom.window.document.body.dataset.date, entry.date, context + ': shell date');
      assert.equal(dom.window.document.body.dataset.page, 'edition', context + ': shell route');
      assert.ok(dom.window.document.querySelector('#app'), context + ': mount target');
      assert.equal(dom.window.document.querySelector('link[rel="canonical"]').href, `https://getagentreach.dev/daily/${entry.date}/`, context + ': canonical URL');
    } finally { dom.window.close(); }
    editions.set(entry.date, ed);
  }
  const months = [...new Set(dates.map(d => d.slice(0, 7)))];
  sameSet(readdirSync(resolve(root, 'search')).filter(f => /^\d{4}-\d{2}\.json$/.test(f)).map(f => f.slice(0, -5)), months, 'search months match archive');
  for (const month of months) {
    const doc = readJson(root, `search/${month}.json`);
    assert.equal(doc.schema_version, 1, month + ': supported search schema');
    assert.equal(doc.month, month, month + ': filename/month');
    assert.ok(Array.isArray(doc.stories), month + ': search stories');
    sameSet(doc.stories.map(s => `${s.d}/${s.id}`), [...editions.values()].filter(e => e.edition_date.startsWith(month)).flatMap(e => e.stories.map(s => `${e.edition_date}/${s.id}`)), month + ': exact search membership');
    for (const hit of doc.stories) {
      const story = editions.get(hit.d).stories.find(s => s.id === hit.id);
      assert.equal(hit.h, story.headline, month + ': search headline');
      assert.equal(hit.c, story.category, month + ': search category');
      assert.equal(hit.r, story.rank, month + ': search rank');
      assert.equal(hit.l, story.coverage.level, month + ': search coverage');
      assert.ok(typeof hit.s === 'string' && Array.isArray(hit.o), month + ': searchable summary/outlets');
      if (hit.u != null) assert.equal(hit.u, story.url, month + ': search headline link');
    }
  }
  for (const [file, selector] of [['feed.xml', 'item > link'], ['sitemap.xml', 'url > loc']]) {
    const dom = new JSDOM(readFileSync(resolve(root, file), 'utf8'), {contentType: 'text/xml'});
    try {
      const listedDates = [...dom.window.document.querySelectorAll(selector)].map(n => /^https:\/\/getagentreach\.dev\/daily\/(\d{4}-\d{2}-\d{2})\/$/.exec(n.textContent)?.[1]).filter(Boolean);
      // RSS may eventually be capped; every linked date must remain available.
      if (file === 'sitemap.xml') sameSet(listedDates, dates, 'sitemap edition membership');
      else {
        assert.ok(listedDates.every(d => editions.has(d)), 'RSS contains no withdrawn dates');
        if (dates.length) assert.equal(listedDates[0], index.latest, 'RSS newest edition');
      }
    } finally { dom.window.close(); }
  }
  const warnings = [...editions.values()].flatMap(editionWarnings);
  for (const warning of warnings) console.warn('WARN ' + warning);
  return {index, editions, warnings};
}
module.exports = {checkEditions, editionWarnings, headlineSimilarity, realDate};
if (require.main === module) {
  try {
    const {editions} = checkEditions(resolve(process.argv[2] || resolve(__dirname, '..')));
    console.log(`Validated ${editions.size} published editions and their search, HTML, RSS and sitemap files.`);
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
