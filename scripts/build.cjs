const {readFileSync, writeFileSync, mkdirSync, rmSync, cpSync, readdirSync, lstatSync} = require('node:fs');
const {resolve, dirname, sep} = require('node:path');
const {JSDOM, VirtualConsole} = require('jsdom');
const {checkEditions} = require('./check-editions.cjs');
const {dedupeOutlets, normalizeStory, plural, shownSummary, coverageLabel, sourceListNote, evidenceBreakdown, SOURCE_KIND} = require('../assets/site.js');
const root = resolve(__dirname, '..');
const out = resolve(root, 'dist');
const staticStamp = value => new Date(value).toLocaleString('en-US', {year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'UTC', timeZoneName: 'short'});
function renderShell(html, path, index, edition) {
  edition = structuredClone(edition);
  edition.stories.forEach(normalizeStory);
  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', error => errors.push(error));
  const dom = new JSDOM(html, {url: 'https://getagentreach.dev' + path, runScripts: 'outside-only', virtualConsole: vc});
  try {
    const w = dom.window, d = w.document;
    const embedded = d.createElement('script');
    embedded.id = 'edition-data'; embedded.type = 'application/json';
    // HTML parsers recognize </script> even in JSON. Escape every '<' before embedding.
    embedded.textContent = JSON.stringify({index, edition, sections: SECTIONS_DOC}).replace(/</g, '\\u003c');
    d.body.append(embedded);
    w.scrollTo = () => {};
    w.fetch = () => { throw new Error('Static rendering must use embedded edition data'); };
    d.body.dataset.prerender = 'true';
    w.eval(readFileSync(resolve(root, 'assets/site.js'), 'utf8'));
    if (errors.length) throw errors[0];
    if (!d.querySelector('main h1') || d.querySelector('main[aria-busy="true"]')) throw new Error('Unable to render ' + path);
    d.body.dataset.rendered = 'static';
    delete d.body.dataset.prerender;
    // Native details keeps lengthy revision history accessible without pushing the news below it.
    const editionDetails = d.querySelector('.edition-full');
    if (editionDetails) {
      const disclosure = d.createElement('details'); disclosure.className = 'static-edition-details';
      const summary = d.createElement('summary'); summary.textContent = 'Edition details and changes';
      editionDetails.before(disclosure); editionDetails.hidden = false;
      disclosure.append(summary, editionDetails);
    }
    // A durable timestamp remains accurate even long after this build. The browser restores relative times.
    for (const time of d.querySelectorAll('time[datetime]')) {
      if (time.dateTime.includes('T')) time.textContent = (time.textContent.startsWith('Generated ') ? 'Generated ' : '') + staticStamp(time.dateTime);
    }
    if (d.body.dataset.page === 'latest') d.querySelector('.page-head p').textContent = `Every story of the ${edition.edition_date} edition, newest report first. Source publication times are shown in UTC.`;
    // Story fragments must resolve with scripts disabled or unavailable, with evidence in place.
    for (const story of edition.stories) {
      const article = d.getElementById('story-' + story.id);
      if (!article || article.querySelector('details.src')) continue;
      const container = article.querySelector('.river-body') || article;
      const riverTime = article.querySelector('.river-time');
      if (riverTime && story.newest_published_utc) {
        const time = d.createElement('time'); time.dateTime = story.newest_published_utc;
        time.textContent = staticStamp(story.newest_published_utc); riverTime.replaceChildren(time);
      }
      if (story.why_it_matters && !article.querySelector('.why')) {
        const why = d.createElement('p'); why.className = 'why static-why';
        const label = d.createElement('b'); label.textContent = 'Why it matters: ';
        why.append(label, story.why_it_matters); container.append(why);
      }
      const details = d.createElement('details'); details.className = 'src static-src';
      const count = story.sources.filter(s => s.url).length;
      const summary = d.createElement('summary'); summary.textContent = count ? `View ${plural(count, 'source link')}` : 'View source details';
      const list = d.createElement('ul');
      for (const source of story.sources) {
        const item = d.createElement('li');
        const title = d.createElement(source.url ? 'a' : 'span');
        title.textContent = source.title;
        if (source.url) { title.href = source.url; title.rel = 'noopener noreferrer'; }
        const meta = d.createElement('small');
        // A source without a stated publication time shows no time at all (never a placeholder).
        meta.textContent = [dedupeOutlets([source.outlet])[0] || source.outlet, source.published_utc ? staticStamp(source.published_utc) : null,
          SOURCE_KIND[source.kind] || source.kind, source.url && new URL(source.url).hostname === 'news.google.com' ? 'Google News redirect' : null].filter(Boolean).join(' · ');
        item.append(title, meta); list.append(item);
      }
      const totals = d.createElement('p');
      const note = sourceListNote(story);
      totals.textContent = evidenceBreakdown(story) + (note ? `. ${note}: the others were counted in coverage but are not listed in this edition.` : '');
      details.append(summary, totals, list); container.append(details);
      const link = `${SITE}/daily/${edition.edition_date}/#story-${story.id}`;
      const actions = d.createElement('p'); actions.className = 'share-links static-share';
      const share = (text, href) => { const a = d.createElement('a'); a.href = href; a.textContent = text; a.rel = 'noopener noreferrer'; return a; };
      const label = d.createElement('span'); label.textContent = 'Share on';
      const u = encodeURIComponent(link), t = encodeURIComponent(story.headline);
      actions.append(label, share('X', `https://x.com/intent/post?text=${t}&url=${u}`), share('Facebook', `https://www.facebook.com/sharer/sharer.php?u=${u}`),
        share('Reddit', `https://www.reddit.com/submit?url=${u}&title=${t}`));
      const report = share('Report an issue', `mailto:hello@getagentreach.dev?subject=${encodeURIComponent(`Report: ${story.headline} (edition of ${edition.edition_date})`)}&body=${encodeURIComponent(`Story: ${link}\n\nWhat is wrong:\n`)}`);
      report.className = 'report-issue'; report.removeAttribute('rel'); actions.append(report);
      container.append(actions);
      // The native disclosure is the source control until the browser mounts the enhanced view.
      article.querySelector('.story-link')?.remove();
    }
    d.querySelector('#page-status')?.remove(); // Client creates its own persistent live region.
    const fallbackStyles = d.createElement('link');
    fallbackStyles.rel = 'stylesheet'; fallbackStyles.href = '/assets/no-script.css';
    d.head.append(fallbackStyles);
    return dom.serialize();
  } finally { dom.window.close(); }
}
// RSS: one item per story of the newest edition (the publisher's feed.xml has one item per edition), and one
// feed per section. Built from the same edition files as the pages, so every link resolves (check-built.cjs).
const SITE = 'https://getagentreach.dev';
// The one taxonomy: editions/sections.json (published by the app; same file the pages read).
const SECTIONS_DOC = JSON.parse(readFileSync(resolve(root, 'editions/sections.json'), 'utf8'));
const FEED_SECTIONS = Object.fromEntries(SECTIONS_DOC.sections.filter(s => s.path && !s.retired).map(s => [s.id, [s.path.replace(/\//g, ''), s.label]]));
const xml = text => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '');
const rfc822 = iso => new Date(iso).toUTCString().replace('GMT', '+0000');
function feedXml(edition, stories, {title, path, self}) {
  const items = stories.map(s => {
    const link = `${SITE}/daily/${edition.edition_date}/#story-${s.id}`;
    // A summary that only restates the headline is left out; a sentence without end punctuation gets a full stop.
    const parts = shownSummary(s).map(t => /[.!?…"'”’)]$/.test(t.trim()) ? t.trim() : t.trim() + '.');
    if (s.why_it_matters) parts.push('Why it matters: ' + s.why_it_matters);
    const c = s.coverage || {}, n = c.independent_reports || 0; // the same wording as the pages (site.js coverageLabel)
    parts.push(`${coverageLabel(c)}: ${n ? `${plural(n, 'independent newsroom')} reported this` : 'no independent newsroom report yet'}.`);
    parts.push('Summary written by a local AI model and checked against its sources; read the sources before relying on it.');
    return `<item><title>${xml(s.headline)}</title><link>${xml(link)}</link><guid isPermaLink="true">${xml(link)}</guid>` +
      `<pubDate>${rfc822(s.newest_published_utc || edition.generated_utc)}</pubDate>` +
      `<category>${xml((FEED_SECTIONS[s.category] || [null, s.category])[1])}</category><description>${xml(parts.join(' '))}</description></item>`;
  });
  return `<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>` +
    `<title>${xml(title)}</title><link>${SITE}${path}</link><atom:link href="${SITE}${self}" rel="self" type="application/rss+xml"/>` +
    `<description>${xml(`Every story of the latest Agent Reach Daily edition (${edition.edition_date}, update ${edition.revision}), summarized by a local AI model from public reporting.`)}</description>` +
    `<language>en-us</language><lastBuildDate>${rfc822(edition.generated_utc)}</lastBuildDate>${items.join('')}</channel></rss>\n`;
}
function feedFiles(edition) {
  const byId = new Map(edition.stories.map(s => [s.id, s]));
  const ordered = [...edition.top, ...edition.sections.flatMap(sec => sec.ids)].filter((id, i, all) => all.indexOf(id) === i && byId.has(id)).map(id => byId.get(id));
  const files = {'feed.xml': feedXml(edition, ordered, {title: 'Agent Reach Daily', path: '/', self: '/feed.xml'})};
  for (const [category, [slug, label]] of Object.entries(FEED_SECTIONS)) {
    files[`feeds/${slug}.xml`] = feedXml(edition, ordered.filter(s => s.category === category),
      {title: `Agent Reach Daily: ${label}`, path: `/${slug}/`, self: `/feeds/${slug}.xml`});
  }
  return files;
}
function addPreview(html) {
  const dom = new JSDOM(html);
  try {
    const d = dom.window.document;
    // Publisher-written dated shells predate the light theme: give every page the theme script and colours.
    if (!d.querySelector('script[src="/assets/theme.js"]')) {
      const theme = d.createElement('script'); theme.src = '/assets/theme.js';
      d.head.insertBefore(theme, d.head.querySelector('link[rel="stylesheet"]'));
    }
    const dark = d.querySelector('meta[name="theme-color"]:not([media])');
    if (dark) {
      dark.setAttribute('media', '(prefers-color-scheme: dark)');
      const light = d.createElement('meta'); light.name = 'theme-color'; light.content = '#f6f5f1';
      light.setAttribute('media', '(prefers-color-scheme: light)'); dark.after(light);
    }
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
  // Derive consistent legacy corrections for HTML, direct JSON readers and monthly search.
  // The publisher-owned repository files remain the input; only dist is rewritten.
  for (const [date, edition] of editions) {
    edition.stories.forEach(normalizeStory);
    writeFileSync(resolve(out, `editions/${date}.json`), JSON.stringify(edition));
  }
  for (const month of new Set([...editions.keys()].map(date => date.slice(0, 7)))) {
    const file = resolve(out, `search/${month}.json`), data = JSON.parse(readFileSync(file, 'utf8'));
    data.stories = data.stories.map(entry => {
      const story = editions.get(entry.d).stories.find(s => s.id === entry.id);
      const next = {...entry, o: dedupeOutlets(entry.o), l: story.coverage.level, coverage: story.coverage};
      delete next.u;
      if (story.url) next.u = story.url;
      return next;
    });
    writeFileSync(file, JSON.stringify(data));
  }
  mkdirSync(resolve(out, 'feeds'), {recursive: true});
  for (const [path, text] of Object.entries(feedFiles(editions.get(index.latest)))) writeFileSync(resolve(out, path), text);
  const shells = ['index.html', 'daily/index.html', 'latest/index.html', 'technology/index.html', 'science/index.html', 'world/index.html', 'sports/index.html', 'entertainment/index.html', 'internet-culture/index.html', 'archive/index.html', 'search/index.html', 'about/index.html', 'sources/index.html', 'corrections/index.html', '404.html', ...[...editions.keys()].map(date => `daily/${date}/index.html`)];
  for (const file of shells) {
    let html = readFileSync(resolve(root, file), 'utf8');
    const match = /data-page="([^"]+)"/.exec(html);
    const date = /data-date="([^"]+)"/.exec(html)?.[1] || index.latest;
    if (['home', 'edition', 'latest', 'section', 'archive', 'sources'].includes(match?.[1]) && editions.has(date)) {
      const path = '/' + file.replace(/index\.html$/, '');
      html = renderShell(html, path, index, editions.get(date));
    }
    const section = /data-section="([^"]+)"/.exec(html)?.[1];
    if (FEED_SECTIONS[section]) { // feed discovery for the section's own RSS feed
      const [slug, label] = FEED_SECTIONS[section];
      html = html.replace('</head>', `<link rel="alternate" type="application/rss+xml" title="Agent Reach Daily: ${label.replace(/&/g, '&amp;')}" href="/feeds/${slug}.xml">\n</head>`);
    }
    html = addPreview(html);
    mkdirSync(dirname(resolve(out, file)), {recursive: true});
    writeFileSync(resolve(out, file), html);
  }
  console.log(`Built public website in dist/ with ${editions.size} embedded editions.`);
}
module.exports = {renderShell, addPreview, feedFiles};
if (require.main === module) build();
