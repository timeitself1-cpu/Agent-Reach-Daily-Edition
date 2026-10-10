const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync, writeFileSync, mkdirSync, rmSync, existsSync} = require('node:fs');
const {resolve} = require('node:path');
const {build} = require('../scripts/build.cjs');

const root = resolve(__dirname, '..');
const dist = resolve(root, 'dist');
const eventsDir = resolve(root, 'events');

test('build copies events directory, index.json, and individual event records to dist/events', () => {
  mkdirSync(eventsDir, {recursive: true});
  const sampleIndex = [
    {
      event_id: 'evt_sample123',
      status: 'developing',
      category: 'News',
      first_seen: '2026-10-10',
      last_updated: '2026-10-10',
      headline: 'Sample Developing Event Headline',
      timeline_entries: 1
    }
  ];
  const sampleRecord = {
    event_id: 'evt_sample123',
    status: 'developing',
    category: 'News',
    first_seen: '2026-10-10',
    last_updated: '2026-10-10',
    current_headline: 'Sample Developing Event Headline',
    current_summary: 'Sample summary for event tracking.',
    timeline: [
      {
        date: '2026-10-10',
        edition: '2026-10-10',
        revision: 1,
        change: 'new',
        headline: 'Sample Developing Event Headline',
        summary: 'Sample summary for event tracking.',
        sources: ['BBC News'],
        source_count: 1,
        what_changed: '',
        story_url: 'https://example.com'
      }
    ]
  };

  const indexPath = resolve(eventsDir, 'index.json');
  const recordPath = resolve(eventsDir, 'evt_sample123.json');
  writeFileSync(indexPath, JSON.stringify(sampleIndex, null, 2), 'utf8');
  writeFileSync(recordPath, JSON.stringify(sampleRecord, null, 2), 'utf8');

  try {
    build();

    // Verify dist/events directory exists
    const distEventsDir = resolve(dist, 'events');
    assert.ok(existsSync(distEventsDir), 'dist/events directory must exist after build');

    // Verify dist/events/index.json
    const distIndexPath = resolve(distEventsDir, 'index.json');
    assert.ok(existsSync(distIndexPath), 'dist/events/index.json must exist after build');
    const builtIndex = JSON.parse(readFileSync(distIndexPath, 'utf8'));
    assert.deepEqual(builtIndex, sampleIndex, 'dist/events/index.json must match source index');

    // Verify individual event record in dist/events/evt_sample123.json
    const distRecordPath = resolve(distEventsDir, 'evt_sample123.json');
    assert.ok(existsSync(distRecordPath), 'Individual event record must exist in dist/events/');
    const builtRecord = JSON.parse(readFileSync(distRecordPath, 'utf8'));
    assert.deepEqual(builtRecord, sampleRecord, 'Built event record must match source event record');
    assert.equal(builtRecord.event_id, 'evt_sample123');
    assert.equal(builtRecord.timeline.length, 1);
  } finally {
    if (existsSync(recordPath)) rmSync(recordPath, {force: true});
    writeFileSync(indexPath, '[]\n', 'utf8');
  }
});
