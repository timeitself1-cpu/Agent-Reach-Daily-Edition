const {readFileSync, writeFileSync, mkdirSync, rmSync, cpSync, readdirSync, lstatSync} = require('node:fs');
const {resolve, dirname, sep} = require('node:path');
const {JSDOM, VirtualConsole} = require('jsdom');
const {checkEditions} = require('./check-editions.cjs');
const root = resolve(__dirname, '..');
const out = resolve(root, 'dist');
function renderShell(html, path, index, edition) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', error => errors.push(error));
  const dom = new JSDOM(html, {url: 'https://getagentreach.dev' + path, runScripts: 'outside-only', virtualConsole: vc});
  try {
    const w = dom.window, d = w.document;
    const embedded = d.createElement('script');
    embedded.id = 'edition-data'; embedded.type = 'application/json';
    // HTML parsers recognize </script> even in JSON. Escape every '<' before embedding.
    embedded.textContent = JSON.stringify({index, edition}).replace(/</g, '\\u003c');
    d.body.append(embedded);
    w.scrollTo = () => {};
    w.fetch = () => { throw new Error('Static rendering must use embedded edition data'); };
    w.eval(readFileSync(resolve(root, 'assets/site.js'), 'utf8'));
    if (errors.length) throw errors[0];
    if (!d.querySelector('main h1') || d.querySelector('main[aria-busy="true"]')) throw new Error('Unable to render ' + path);
    // The interactive lead/rail link to a detail view. Static readers need their evidence here.
    for (const story of edition.stories) {
      const article = d.getElementById('story-' + story.id);
      if (!article || article.querySelector('details.src')) continue;
      const details = d.createElement('details'); details.className = 'src';
      const summary = d.createElement('summary'); summary.textContent = `View ${story.sources.length} sources`;
      const list = d.createElement('ul');
      for (const source of story.sources) {
        const item = d.createElement('li');
        const title = d.createElement(source.url ? 'a' : 'span');
        title.textContent = source.title;
        if (source.url) { title.href = source.url; title.rel = 'noopener noreferrer'; }
        const meta = d.createElement('small');
        meta.textContent = `${source.outlet} · ${source.published_utc || 'time not stated'} · ${source.kind}`;
        item.append(title, meta); list.append(item);
      }
      details.append(summary, list); article.append(details);
    }
    d.querySelector('#page-status')?.remove(); // Client creates its own persistent live region.
    const noscript = d.createElement('noscript');
    const fallbackStyles = d.createElement('link');
    fallbackStyles.rel = 'stylesheet'; fallbackStyles.href = '/assets/no-script.css';
    noscript.append(fallbackStyles);
    d.head.append(noscript);
    return dom.serialize();
  } finally { dom.window.close(); }
}
function addPreview(html) {
  const dom = new JSDOM(html);
  try {
    const d = dom.window.document;
    for (const [name, content] of [['og:image', 'https://getagentreach.dev/assets/social-card.png'], ['og:image:alt', 'Agent Reach Daily: today’s news, from public reporting. Read the summaries. Check the sources.'], ['og:image:width', '1200'], ['og:image:height', '630'], ['og:image:type', 'image/png'], ['twitter:card', 'summary_large_image'], ['twitter:image', 'https://getagentreach.dev/assets/social-card.png']]) {
      const attr = name.startsWith('og:') ? 'property' : 'name';
      let meta = d.querySelector(`meta[${attr}="${name}"]`);
      if (!meta) { meta = d.createElement('meta'); meta.setAttribute(attr, name); d.head.append(meta); }
      meta.setAttribute('content', content);
    }
    return dom.serialize();
  } finally { dom.window.close(); }
}
function build() {
  const {index, editions} = checkEditions(root);
  // Clean only children of this fixed output target, never a caller-provided path.
  if (dirname(out) !== root) throw new Error('Invalid output directory');
  mkdirSync(out, {recursive: true});
  if (lstatSync(out).isSymbolicLink()) throw new Error('Output directory must not be a symbolic link');
  // Keep the directory itself so a Windows preview server can hold it open.
  for (const name of readdirSync(out)) {
    const target = resolve(out, name);
    if (!target.startsWith(out + sep)) throw new Error('Invalid cleanup target');
    rmSync(target, {recursive: true, force: true, maxRetries: 3});
  }
  for (const path of ['assets', 'editions', 'search', 'feed.xml', 'sitemap.xml', 'robots.txt', 'app-top-stories.webp', 'app-window.webp', '_headers']) cpSync(resolve(root, path), resolve(out, path), {recursive: true});
  const shells = ['index.html', 'daily/index.html', 'latest/index.html', 'technology/index.html', 'science/index.html', 'world/index.html', 'archive/index.html', 'search/index.html', 'about/index.html', '404.html', ...[...editions.keys()].map(date => `daily/${date}/index.html`)];
  for (const file of shells) {
    let html = readFileSync(resolve(root, file), 'utf8');
    const match = /data-page="([^"]+)"/.exec(html);
    const date = /data-date="([^"]+)"/.exec(html)?.[1] || index.latest;
    if (['home', 'edition', 'latest', 'section', 'archive'].includes(match?.[1]) && editions.has(date)) {
      const path = '/' + file.replace(/index\.html$/, '');
      html = renderShell(html, path, index, editions.get(date));
    }
    html = addPreview(html);
    mkdirSync(dirname(resolve(out, file)), {recursive: true});
    writeFileSync(resolve(out, file), html);
  }
  console.log(`Built public website in dist/ with ${editions.size} embedded editions.`);
}
module.exports = {renderShell, addPreview};
if (require.main === module) build();
