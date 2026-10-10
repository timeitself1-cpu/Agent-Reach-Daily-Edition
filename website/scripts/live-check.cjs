const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const HEADERS = ['Content-Security-Policy', 'X-Content-Type-Options', 'X-Frame-Options', 'Referrer-Policy', 'Permissions-Policy', 'Strict-Transport-Security'];
const PRIVATE_PATHS = ['/docs/roadmap.md', '/tests/frontend.cjs', '/wrangler.jsonc', '/package.json'];
async function liveCheck(index, {fetchImpl = fetch, now = Date.now, wait = ms => new Promise(r => setTimeout(r, ms)), timeout = 600000, base = 'https://getagentreach.dev'} = {}) {
  const entry = index.editions.find(e => e.date === index.latest);
  if (!entry) throw new Error('Repository index has no latest edition');
  const deadline = now() + timeout;
  let matched = false, last = 'live revision unavailable';
  const get = (path, limit = 15000) => fetchImpl(base + path, {cache: 'no-store', signal: AbortSignal.timeout(limit)});
  do {
    try {
      const response = await get('/editions/index.json', Math.max(1, Math.min(15000, deadline - now())));
      if (!response.ok) throw new Error(`index HTTP ${response.status}`);
      const live = await response.json();
      const latest = live.editions.find(e => e.date === entry.date);
      matched = live.latest === index.latest && latest?.revision === entry.revision;
      last = `expected ${entry.date} revision ${entry.revision}, received ${live.latest} revision ${latest?.revision ?? 'missing'}`;
    } catch (error) { last = error.message; }
    if (matched) break;
    if (now() >= deadline) throw new Error('Live edition did not match within 10 minutes: ' + last);
    await wait(Math.min(15000, Math.max(0, deadline - now())));
  } while (now() < deadline);
  if (!matched) throw new Error('Live edition did not match within 10 minutes: ' + last);
  const home = await get('/');
  if (!home.ok) throw new Error(`Home HTTP ${home.status}`);
  for (const name of HEADERS) if (!home.headers.get(name)) throw new Error('Missing security header: ' + name);
  for (const path of PRIVATE_PATHS) {
    const response = await get(path);
    if (response.status !== 404) throw new Error(`Exposed path: ${path} (HTTP ${response.status}; expected 404)`);
  }
  console.log(`Live check passed: ${entry.date} revision ${entry.revision}; all security headers and private-path 404s.`);
}
module.exports = {liveCheck, HEADERS, PRIVATE_PATHS};
if (require.main === module) liveCheck(JSON.parse(readFileSync(resolve(__dirname, '../editions/index.json'), 'utf8')))
  .catch(error => {console.error(error.message); process.exitCode = 1;});
