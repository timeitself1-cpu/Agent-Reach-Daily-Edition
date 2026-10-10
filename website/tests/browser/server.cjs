// Frozen editions exercise the production static renderer without depending on today's publication.
const {createServer} = require('node:http');
const {readFileSync, existsSync} = require('node:fs');
const {resolve, sep, extname} = require('node:path');
const {renderShell, addPreview} = require('../../scripts/build.cjs');
const root = resolve(__dirname, '../..'), fixtures = resolve(root, 'tests/fixtures');
const index = JSON.parse(readFileSync(resolve(fixtures, 'editions/index.json')));
const edition = JSON.parse(readFileSync(resolve(fixtures, 'editions/2026-10-07.json')));
const pages = new Map();
for (const path of ['/', '/daily/', '/daily/2026-10-07/', '/technology/', '/latest/', '/archive/']) {
  const base = path.includes('2026-10-07') ? fixtures : root;
  pages.set(path, addPreview(renderShell(readFileSync(resolve(base, '.' + path + 'index.html'), 'utf8'), path, index, edition)));
}
createServer((req, res) => {
  const path = new URL(req.url, 'http://localhost').pathname;
  if (pages.has(path)) { res.setHeader('Content-Type', 'text/html'); res.end(pages.get(path)); return; }
  if (!/^\/(?:assets|editions|search|events)\//.test(path)) { res.writeHead(404).end(); return; }
  const base = (path.startsWith('/assets/') || !existsSync(resolve(fixtures, '.' + decodeURIComponent(path)))) ? root : fixtures;
  const file = resolve(base, '.' + decodeURIComponent(path));
  if (!file.startsWith(base + sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader('Content-Type', {'.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json'}[extname(file)] || 'application/octet-stream');
    res.end(readFileSync(file));
  } catch (_) { res.writeHead(404).end(); }
}).listen(8874, '127.0.0.1');
