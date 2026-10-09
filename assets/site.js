// Shared by the browser and the publication validator (no browser runtime dependency).
const OUTLET_ALIASES = {
  ap: 'AP News', apnews: 'AP News', associatedpress: 'AP News', reuters: 'Reuters',
  cnbc: 'CNBC', twitter: 'X', x: 'X', nytimes: 'The New York Times',
  newyorktimes: 'The New York Times', thenewyorktimes: 'The New York Times',
  bbc: 'BBC News', bbcnews: 'BBC News', nasa: 'NASA', dw: 'DW',
  pbs: 'PBS NewsHour', pbsnewshour: 'PBS NewsHour', wired: 'Wired',
  tomshardware: "Tom's Hardware", github: 'GitHub', guardian: 'The Guardian',
  theguardian: 'The Guardian', washingtonpost: 'The Washington Post',
  thewashingtonpost: 'The Washington Post',
  nbcdfw: 'NBC DFW', nbc5dallasfortworth: 'NBC DFW',
  aljazeera: 'Al Jazeera', aljazeeraenglish: 'Al Jazeera'
};
function normOutlet(name) {
  let key = String(name || '').toLowerCase().trim().replace(/^www\./, '')
    .replace(/\s*\([^)]*\)$/, '').replace(/\.(?:co|com|org|net)\.[a-z]{2}$/, '')
    .replace(/\.[a-z]{2,}$/, '').replace(/[^a-z0-9]/g, '');
  return (OUTLET_ALIASES[key] || key).toLowerCase().replace(/[^a-z0-9]/g, '');
}
function dedupeOutlets(names) {
  const out = new Map();
  for (const name of names || []) {
    const key = normOutlet(name);
    if (!key) continue;
    const alias = Object.values(OUTLET_ALIASES).find(n => normOutlet(n) === key);
    const readable = alias || String(name).replace(/\s*\([^)]*\)$/, '').trim();
    if (!out.has(key) || (/\.[a-z]{2,}$/i.test(out.get(key)) && !/\.[a-z]{2,}$/i.test(readable))) out.set(key, readable);
  }
  return [...out.values()];
}
function correctedCoverage(c) {
  const publishers = dedupeOutlets(c.publishers || []);
  const count = Math.min(c.independent_reports || 0, publishers.length);
  const removed = (c.independent_reports || 0) - count;
  // Old exports lack the full scoring evidence. Never retain a strong label based on a removed alias.
  const corroboration = n => n < 2 ? 0 : Math.min(n, 4);
  const points = Number.isFinite(c.points) ? c.points - corroboration(c.independent_reports) + corroboration(count) : null;
  const level = count < 2 ? 'limited' : points !== null ? (points >= 5 ? 'strong' : 'moderate')
    : removed && count < 4 && c.level === 'strong' ? 'moderate' : c.level;
  return {...c, ...(points !== null ? {points} : {}), publishers, independent_reports: count, repeats: (c.repeats || 0) + removed, level};
}
const LINK_STOP = new Set('a an the of to in on for and or with at by from as is are was be before after says said'.split(' '));
const linkWords = text => new Set((String(text).toLowerCase().match(/[a-z0-9]+/g) || []).filter(w => !LINK_STOP.has(w)));
const titleKey = text => String(text).normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}_]/gu, '');
// Same syndication key as the publisher's cleaner.dedupe_key.
const reportTitleKey = text => String(text).toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim().replace(/^the /, '');
function articleUrl(value) {
  try {
    const u = new URL(value);
    const blocked = ['google.com', 'wikipedia.org', 'bsky.app', 'x.com', 'twitter.com', 'reddit.com', 'tiktok.com', 'trends24.in', 'news.ycombinator.com'];
    return /^https?:$/.test(u.protocol) && !blocked.some(h => u.hostname === h || u.hostname.endsWith('.' + h)) ? u.href : null;
  } catch (_) { return null; }
}
function primaryLink(s) {
  const reports = (s.sources || []).filter(src => src.kind !== 'signal');
  const exact = reports.filter(src => titleKey(src.title) === titleKey(s.headline));
  const words = linkWords(s.headline);
  const negation = text => [...new Set(String(text).toLowerCase().match(/\b(?:no|not|never)\b/g) || [])].sort().join(',');
  const numbers = text => String(text).match(/\b\d+(?:[.,]\d+)*\b/g) || [];
  const candidates = (exact.length ? exact : reports).map((src, order) => {
    const other = linkWords(src.title), common = [...words].filter(w => other.has(w)).length;
    const compatible = negation(s.headline) === negation(src.title) && numbers(s.headline).every(n => numbers(src.title).includes(n));
    return {url: compatible ? articleUrl(src.url) : null, score: common / Math.max(1, words.size), common, order};
  }).filter(x => x.url && (exact.length || (x.common >= Math.min(3, words.size) && x.score >= .7)));
  return candidates.sort((a, b) => b.score - a.score || a.order - b.order)[0]?.url || null;
}
function normalizeStory(s) {
  s.coverage = correctedCoverage(s.coverage);
  const keys = s.sources.map(src => src.outlet_id || normOutlet(src.outlet));
  const parents = s.sources.map((_, i) => i), seen = new Map();
  const root = i => { while (parents[i] !== i) { parents[i] = parents[parents[i]]; i = parents[i]; } return i; };
  s.sources.forEach((src, i) => {
    if (src.kind === 'signal' || !keys[i]) return;
    for (const [type, value] of [['outlet', keys[i]], ['title', reportTitleKey(src.title)], ['origin', src.reporting_origin]]) {
      if (!value) continue;
      const token = type + ':' + value;
      if (seen.has(token)) {
        const a = root(i), b = root(seen.get(token)); parents[Math.max(a, b)] = Math.min(a, b);
      }
      seen.set(token, i);
    }
  });
  const counted = new Set();
  s.sources = s.sources.map((src, i) => {
    const first = s.sources[root(i)];
    const report = src.kind === 'signal' || !keys[i] ? null : first.reporting_origin || 'outlet:' + keys[root(i)];
    const kind = src.kind === 'signal' ? 'signal' : counted.has(report) ? 'repeat' : 'report';
    if (report) counted.add(report);
    return {...src, outlet: dedupeOutlets([src.outlet])[0] || src.outlet, outlet_id: keys[i], reporting_origin: report, kind};
  });
  s.coverage.source_links = s.sources.filter(src => src.url).length;
  s.coverage.linked_outlets = new Set(s.sources.filter(src => src.kind !== 'signal' && src.outlet_id).map(src => src.outlet_id)).size;
  s.coverage.linked_reporting_origins = new Set(s.sources.map(src => src.reporting_origin).filter(Boolean)).size;
  s.url = primaryLink(s);
  return s;
}
if (typeof module !== 'undefined') module.exports = {normOutlet, dedupeOutlets, correctedCoverage, primaryLink, normalizeStory};
// Agent Reach Daily website. Every page is rendered from the editions the app publishes:
//   /editions/index.json        the archive list (newest first, "latest" = newest date)
//   /editions/YYYY-MM-DD.json   one public edition (written by agent_reach/daily/publish.py)
//   /search/YYYY-MM.json        the search data of one month (headline, short summary, outlets per story)
// All text from an edition goes into the page as text (textContent), never as HTML; only absolute
// http(s) links become links.
(() => {
  'use strict';
  if (typeof document === 'undefined') return;
  const REPO = 'https://github.com/timeitself1-cpu/Agent-Reach-Daily-Edition';
  const MAIL = 'hello@getagentreach.dev';
  const SECTION = {
    'News': {label: 'World & Nation', path: '/world/', title: 'World & Nation', blurb: 'World and national news: politics, courts, conflict, the economy and public safety.'},
    'Local': {label: 'Local', path: '/local/', title: 'Frisco & North Texas', blurb: 'Local news from Frisco, Collin and Denton counties and the rest of North Texas.'},
    'Tech': {label: 'Technology', path: '/technology/', title: 'Technology', blurb: 'Companies, products, security and the business of technology.'},
    'Science & AI': {label: 'Science & AI', path: '/science/', title: 'Science & AI', blurb: 'Research, space, health, climate and artificial intelligence.'},
    'Sports': {label: 'Sports', path: '/sports/', title: 'Sports', blurb: 'Games, results, trades and the business of sport.'},
    'Entertainment': {label: 'Entertainment', path: '/entertainment/', title: 'Entertainment', blurb: 'Film, television, music, games and the people who make them.'},
    'Internet Culture': {label: 'Internet Culture', path: '/internet-culture/', title: 'Internet Culture', blurb: 'What people are talking about online: platforms, creators and viral moments.'},
  };
  const NAV = [['Home', '/', 'home'], ['Latest', '/latest/', 'latest'],
    ...['News', 'Local', 'Tech', 'Science & AI', 'Sports', 'Entertainment', 'Internet Culture'].map(c => [SECTION[c].label, SECTION[c].path, c]),
    ['Archive', '/archive/', 'archive'], ['About', '/about/', 'about']];
  const body = document.body;
  const page = body.dataset.page || 'home';

  // ------------------------------------------------------------------ helpers
  function webUrl(u) {
    if (typeof u !== 'string' || !u.trim()) return null;
    try { const x = new URL(u, location.href); return (x.protocol === 'https:' || x.protocol === 'http:') ? x.href : null; }
    catch (e) { return null; }
  }
  function h(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k === 'href') {
        if (/^mailto:[^\s<>"]+$/.test(v)) n.setAttribute('href', v);
        else { const u = webUrl(v); if (u) n.setAttribute('href', v.startsWith('/') || v.startsWith('#') ? v : u); }
      }
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return n;
  }
  const plural = (n, one, many) => `${n.toLocaleString('en-US')} ${n === 1 ? one : (many || one + 's')}`;
  const dayOf = d => new Date(d + 'T12:00:00Z');
  const longDate = d => dayOf(d).toLocaleDateString('en-US', {weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC'});
  const shortDate = d => dayOf(d).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'});
  const stamp = iso => new Date(iso).toLocaleString('en-US', {year: new Date(iso).getFullYear() !== new Date(Date.now()).getFullYear() ? 'numeric' : undefined, month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short'});
  const fullStamp = iso => new Date(iso).toLocaleString('en-US', {year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short'});
  function ago(iso) {
    if (!iso) return null;
    const min = (Date.now() - Date.parse(iso)) / 60000;
    if (!(min >= 0)) return stamp(iso);
    if (min < 60) return `${Math.max(1, Math.round(min))} min ago`;
    if (min < 60 * 24) return `${Math.round(min / 60)} h ago`;
    return stamp(iso);
  }
  let relativeTimer = null;
  function refreshTimes() {
    for (const time of document.querySelectorAll('time[data-relative]')) time.textContent = ago(time.getAttribute('datetime'));
  }
  function scheduleTimes() {
    if (relativeTimer !== null) clearInterval(relativeTimer);
    relativeTimer = null;
    if (document.visibilityState === 'visible') { refreshTimes(); relativeTimer = setInterval(refreshTimes, 60000); }
  }
  document.addEventListener('visibilitychange', scheduleTimes);
  scheduleTimes();
  const storyUrl = (ed, s) => `/daily/${ed.edition_date}/#story-${s.id}`;
  const editionUrl = d => `/daily/${d}/`;
  const catLabel = c => (SECTION[c] && SECTION[c].label) || c;
  const pageStatus = h('p', {class: 'sr', id: 'page-status', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true'});
  body.append(pageStatus); // Keep load status mounted while the page content changes.
  const extNote = document.getElementById('ext-note') || h('p', {id: 'ext-note', hidden: true, text: 'Opens the publisher’s article in a new tab.'});
  body.append(extNote);

  async function getJson(url) {
    const r = await fetch(url, {cache: 'no-cache'});
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }
  let indexPromise = null;
  const loadIndex = () => (indexPromise = indexPromise || getJson('/editions/index.json'));
  function prepareEdition(ed) {
    if (!ed || !Array.isArray(ed.stories) || !ed.stories.length) throw new Error('empty edition');
    ed.stories.forEach(normalizeStory);
    ed.byId = Object.fromEntries(ed.stories.map(s => [s.id, s]));
    ed.ordered = ed.stories.slice().sort((a, b) => a.rank - b.rank);
    ed.topStories = (ed.top || []).map(id => ed.byId[id]).filter(Boolean);
    if (!ed.topStories.length) ed.topStories = ed.ordered.slice(0, 8);
    return ed;
  }
  async function loadEdition(d) {
    return prepareEdition(await getJson(`/editions/${d}.json`));
  }
  // The website build embeds the existing public JSON; no publisher field is required.
  function embeddedData() {
    try {
      const data = JSON.parse(document.getElementById('edition-data').textContent);
      const date = body.dataset.date || data.index.latest;
      if (data.edition.edition_date !== date) return null;
      return {idx: data.index, ed: prepareEdition(data.edition)};
    } catch (_) { return null; }
  }

  // ------------------------------------------------------------------ story atoms
  function coverage(c) {
    if (c.level === 'strong') return 'Strong coverage';
    if (c.level === 'moderate') return 'Moderate coverage';
    return c.independent_reports <= 1 ? 'Single source' : 'Limited coverage';
  }
  function covMeter(s, big) {
    const c = s.coverage || {level: 'limited', independent_reports: 0};
    const n = independentCount(s);
    return h('span', {class: `cov ${c.level}`, title: `${plural(n, 'independent outlet')} reported this. Coverage is not a fact check.`},
      h('span', {class: 'bars', 'aria-hidden': 'true'}, h('i'), h('i'), h('i')), big ? null : coverage(c));
  }
  function publisherList(s) {
    return dedupeOutlets(s.coverage?.publishers?.length ? s.coverage.publishers : s.sources.filter(x => x.kind === 'report').map(x => x.outlet));
  }
  const independentCount = s => Math.min(s.coverage?.independent_reports || 0, publisherList(s).length);
  const sourceLinks = s => s.sources.filter(x => webUrl(x.url)).length;
  // Independent outlets as tags, widely known national and international newsrooms first, so a story carried
  // by AP, Reuters and the BBC shows it at a glance. Every outlet is listed on the story page.
  const MAJOR_OUTLETS = ['AP News', 'Reuters', 'AFP', 'BBC News', 'The New York Times', 'The Washington Post',
    'The Wall Street Journal', 'Bloomberg', 'Financial Times', 'The Guardian', 'NPR', 'PBS NewsHour', 'CNN',
    'ABC News', 'CBS News', 'NBC News', 'Al Jazeera', 'DW', 'The Economist', 'Politico', 'Axios', 'CNBC'];
  function orderedOutlets(s) {
    const rank = n => { const i = MAJOR_OUTLETS.indexOf(n); return i < 0 ? MAJOR_OUTLETS.length : i; };
    return publisherList(s).map((n, i) => [n, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(x => x[0]);
  }
  function outletTags(s, max = 3) {
    const names = orderedOutlets(s);
    if (names.length < 2) return names.length ? h('span', {class: 'outlets', text: names[0]}) : null;
    const shown = names.slice(0, max), rest = names.length - shown.length;
    return h('span', {class: 'outlets outlet-tags', title: 'Reported independently by ' + names.join(', ')},
      h('span', {class: 'sr', text: `Reported independently by ${plural(names.length, 'outlet')}: `}),
      h('span', {class: 'tally', 'aria-hidden': 'true', text: plural(names.length, 'outlet')}),
      shown.map((n, i) => [i ? h('span', {class: 'sr', text: ', '}) : null, h('span', {class: 'tag', text: n})]),
      rest ? [h('span', {class: 'sr', text: ' and '}), h('span', {class: 'tag more', text: `+${rest}`}), h('span', {class: 'sr', text: ' more'})] : null);
  }
  function badges(s) {
    const out = [];
    if (s.change === 'new') out.push(h('span', {class: 'badge new', text: 'New'}));
    else if (s.change === 'updated') out.push(h('span', {class: 'badge updated', text: 'Updated'}));
    for (const l of s.labels || []) out.push(h('span', {class: 'badge trend', text: l}));
    return out;
  }
  const kicker = s => h('span', {class: 'kicker', 'data-cat': s.category}, catLabel(s.category), badges(s));
  // A supporting report, or the internal evidence view when no resolved title is a safe match.
  const hostOf = u => { try { return new URL(u).hostname.toLowerCase().replace(/^www\./, ''); } catch (_) { return ''; } };
  function mainLink(s) {
    return primaryLink(s);
  }
  function mainOutlet(s, url) {
    const src = (s.sources || []).find(x => webUrl(x.url) === url);
    return src ? (dedupeOutlets([src.outlet])[0] || src.outlet) : hostOf(url);
  }
  // A headline: one click opens the publisher's article in a new tab. A story without any link opens its page.
  function headline(ed, s, tag, cls = 'hl') {
    const url = mainLink(s);
    const link = url
      ? h('a', {class: 'out', href: url, rel: 'noopener noreferrer', target: '_blank', 'aria-describedby': 'ext-note', 'data-outlet': mainOutlet(s, url), text: s.headline})
      : h('a', {href: storyUrl(ed, s), text: s.headline});
    return h(tag, {class: cls}, link);
  }
  // The way to the story's own page: full summary, every source, coverage.
  function storyLink(ed, s) {
    const n = sourceLinks(s);
    return h('a', {class: 'story-link', href: storyUrl(ed, s)}, n ? plural(n, 'source') : 'Details',
      h('span', {class: 'sr', text: ` and coverage: ${s.headline}`}));
  }
  // Story footer: the outlet pills on their own row when several outlets reported it, then time, coverage
  // and the link to the story page.
  function meta(s, opts = {}) {
    const when = ago(s.newest_published_utc);
    const tags = opts.noOutlets ? null : outletTags(s, opts.tags || 3);
    const several = tags && tags.classList.contains('outlet-tags');
    return [several ? h('div', {class: 'outlet-row'}, tags) : null, h('div', {class: 'meta'},
      when && !opts.noTime ? h('time', {datetime: s.newest_published_utc, 'data-relative': 'true', title: 'Newest report: ' + stamp(s.newest_published_utc), text: when}) : null,
      several ? null : tags, covMeter(s),
      opts.ed ? storyLink(opts.ed, s) : null)];
  }
  function card(ed, s, variant, tag = 'h3') {
    const cls = 'card' + (variant === 'feature' ? ' feature' : '');
    return h('article', {class: cls, id: 'story-' + s.id, 'data-cat': s.category}, kicker(s),
      headline(ed, s, tag), h('p', {class: 'dek', text: s.summary.join(' ')}), meta(s, {ed}));
  }

  // ------------------------------------------------------------------ chrome
  function masthead(current, ed) {
    const today = ed ? longDate(ed.edition_date) : new Date().toLocaleDateString('en-US', {weekday: 'long', month: 'long', day: 'numeric', year: 'numeric'});
    return h('header', {class: 'masthead'}, skipLink(), h('div', {class: 'wrap'},
      h('div', {class: 'mast-top'},
        h('div', {class: 'mast-date'}, h('strong', {text: ed ? 'Edition of ' : 'Today, '}), today),
        h('a', {class: 'brand', href: '/', 'aria-label': 'Agent Reach Daily, home'}, h('span', {class: 'brand-mark', 'aria-hidden': 'true'}),
          h('span', {class: 'brand-name', text: 'Agent Reach'}), h('span', {class: 'brand-daily', text: 'Daily'})),
        h('div', {class: 'mast-actions'}, h('a', {class: 'pill search', href: '/search/', 'aria-current': current === 'search' ? 'page' : null},
          h('span', {class: 'glass', 'aria-hidden': 'true'}), 'Search'),
          h('a', {class: 'pill solid', href: '/about/#app', text: 'Get the app'}))),
      h('nav', {class: 'nav', 'aria-label': 'Sections'}, h('div', {class: 'nav-row'}, NAV.map(([label, href, key]) =>
        h('a', {href, text: label, 'aria-current': key === current ? 'page' : null}))))));
  }
  // Keep the current section in view when the navigation row scrolls sideways (phones).
  function revealCurrentNav() {
    const row = document.querySelector('.nav-row'), here = row && row.querySelector('[aria-current="page"]');
    if (!row || !here || row.scrollWidth <= row.clientWidth) return;
    row.scrollLeft = Math.max(0, here.offsetLeft - (row.clientWidth - here.offsetWidth) / 2);
  }
  // A ticker that scrolls sideways (phones) can be scrolled from the keyboard too.
  function scrollableTicker() {
    const t = document.querySelector('.ticker');
    if (!t) return;
    if (t.scrollWidth > t.clientWidth + 1) t.setAttribute('tabindex', '0'); else t.removeAttribute('tabindex');
  }
  window.addEventListener('resize', scrollableTicker);
  // Reader-chosen theme: Auto follows the system; assets/theme.js applies a saved choice before the first paint.
  const THEMES = [['auto', 'Auto'], ['light', 'Light'], ['dark', 'Dark']];
  function savedTheme() {
    try { const t = localStorage.getItem('theme'); return t === 'light' || t === 'dark' ? t : 'auto'; } catch (_) { return 'auto'; }
  }
  function themeControl() {
    const buttons = THEMES.map(([key, label]) => h('button', {type: 'button', class: 'seg', 'data-theme': key, 'aria-pressed': String(savedTheme() === key), text: label}));
    for (const b of buttons) b.addEventListener('click', () => {
      const key = b.dataset.theme;
      if (key === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = key;
      try { if (key === 'auto') localStorage.removeItem('theme'); else localStorage.setItem('theme', key); } catch (_) { /* private mode: this page only */ }
      for (const x of buttons) x.setAttribute('aria-pressed', String(x === b));
    });
    return h('div', {class: 'theme-control', role: 'group', 'aria-label': 'Colour theme'}, h('span', {text: 'Theme'}), buttons);
  }
  function footer() {
    return h('footer', {class: 'footer'}, h('div', {class: 'wrap'},
      h('div', {class: 'foot-grid'},
        h('div', null, h('h3', {text: 'About Agent Reach Daily'}),
          h('p', {text: 'A daily news edition made by software: it reads public reporting from news outlets and feeds, groups the reports of one event into one story, and writes a short summary with a local AI model. It is published automatically, without an editor.'}),
          h('p', {text: 'Summaries can contain mistakes. Always check the linked sources. Headlines and articles belong to their publishers; Agent Reach is not affiliated with the outlets it links to.'})),
        h('div', null, h('h3', {text: 'Read'}), h('ul', null,
          h('li', null, h('a', {href: '/daily/', text: 'Latest edition'})), h('li', null, h('a', {href: '/latest/', text: 'Latest News'})),
          h('li', null, h('a', {href: '/archive/', text: 'Archive'})), h('li', null, h('a', {href: '/search/', text: 'Search the archive'})),
          h('li', null, h('a', {href: '/about/#method', text: 'How it works'})),
          h('li', null, h('a', {href: '/about/#coverage', text: 'Reading coverage strength'})),
          h('li', null, h('a', {href: '/feed.xml', text: 'RSS feed'})))),
        h('div', null, h('h3', {text: 'Project'}), h('ul', null,
          h('li', null, h('a', {href: '/about/#app', text: 'The Windows app'})), h('li', null, h('a', {href: REPO, text: 'Source code on GitHub'})),
          h('li', null, h('a', {href: '/about/#corrections', text: 'Corrections'})), h('li', null, h('a', {href: 'mailto:' + MAIL, text: MAIL}))))),
      h('div', {class: 'foot-base'}, h('span', {text: '© 2026 Michael Brown · Open source under the MIT License'}),
        themeControl(), h('span', {text: 'No cookies, no tracking, no ads.'}))));
  }
  function mount(current, ed, ...content) {
    const active = document.activeElement;
    const scope = active.closest && active.closest('.masthead, .footer');
    const focusedLink = scope && active.closest('a[href]');
    const linkIndex = focusedLink ? [...scope.querySelectorAll('a[href]')].filter(a => a.getAttribute('href') === focusedLink.getAttribute('href')).indexOf(focusedLink) : -1;
    const wasSkip = active.matches && active.matches('.skip');
    const wasInMain = active.closest && active.closest('main');
    const main = h('main', {id: 'main', tabindex: '-1', 'aria-busy': 'false'}, content);
    const app = document.getElementById('app');
    const nodes = [masthead(current, ed), main, footer()];
    if (app) app.replaceChildren(...nodes); else body.replaceChildren(...nodes, pageStatus, extNote);
    delete body.dataset.rendered;
    revealCurrentNav(); scrollableTicker();
    if (!active.isConnected) {
      const newScope = scope && document.querySelector(scope.classList.contains('masthead') ? '.masthead' : '.footer');
      const target = wasSkip ? document.querySelector('.skip') : focusedLink && newScope
        ? [...newScope.querySelectorAll('a[href]')].filter(a => a.getAttribute('href') === focusedLink.getAttribute('href'))[linkIndex]
        : wasInMain ? main : null;
      if (target) target.focus({preventScroll: true});
    }
    return main;
  }
  function skipLink() {
    const link = h('a', {class: 'skip', href: '#main', text: 'Skip to content'});
    link.addEventListener('click', e => {
      const main = document.getElementById('main');
      if (!main) return;
      e.preventDefault(); // Keep the story hash and the mounted content intact.
      main.focus({preventScroll: true});
      main.scrollIntoView({block: 'start'});
    });
    return link;
  }
  function chrome(current) { // static pages (About): header and footer around the page's own content
    const main = document.getElementById('main');
    if (main) main.setAttribute('tabindex', '-1');
    body.prepend(masthead(current, null));
    if (main) main.after(footer()); else body.append(footer());
    revealCurrentNav();
  }
  function failed(current, what, withdrawn = false) {
    const message = what || 'The news could not be loaded.';
    mount(current, null, h('div', {class: 'wrap state'}, h('h1', {text: message}),
      h('p', null, withdrawn ? 'This dated edition is no longer available. ' : 'Please reload the page. If it keeps happening, the newest edition may still be on its way: ', h('a', {href: '/archive/', text: 'see the archive'}), '.')));
    document.title = message + ' | Agent Reach Daily';
    pageStatus.textContent = message;
  }
  function loading(current) {
    pageStatus.textContent = current === 'search' ? 'Loading archive search…' : current === 'archive' ? 'Loading the archive…' : 'Loading the edition…';
    const main = mount(current, null, h('div', {class: 'wrap'},
      h('div', {class: 'skeleton', 'aria-hidden': 'true'}, h('div', {style: 'height:440px'}), h('div', {style: 'height:440px'}))));
    main.setAttribute('aria-busy', 'true');
  }

  // ------------------------------------------------------------------ front page / edition
  function strip(ed, idx, crumbs) {
    const latest = idx && idx.latest === ed.edition_date;
    const ageH = (Date.now() - Date.parse(ed.generated_utc)) / 3.6e6;
    const details = h('div', {class: 'edition-full', id: 'edition-details'},
      h('div', {class: 'edition-meta'},
        h('span', {class: 'live' + (latest && ageH < 30 ? '' : ' old')}, h('b', {text: latest ? 'Latest edition' : 'Archived edition'})),
        h('time', {datetime: ed.edition_date, text: longDate(ed.edition_date)}),
        ed.revision > 1 ? h('span', {text: `Update ${ed.revision}`}) : null,
        h('time', {datetime: ed.generated_utc, title: ed.generated_utc, text: `Generated ${fullStamp(ed.generated_utc)}`})),
      h('span', {class: 'edition-stats'}, `${plural(ed.stories.length, 'story', 'stories')} from ${plural(ed.reports_read || 0, 'report')} · ${ed.sources_answered || 0} of ${ed.sources_tried || 0} source types responded · AI-generated summaries`));
    if (ed.compared_with) {
      const count = kind => ed.stories.filter(s => s.change === kind).length;
      details.append(h('p', {class: 'edition-changes', text: `Compared with update ${ed.compared_with.revision}: ${count('new')} new · ${count('updated')} updated`}));
    }
    if (ed.changes) {
      const dropped = ed.changes.dropped || [];
      details.append(h('p', {text: `${dropped.length} no longer listed`}), h('ul', {class: 'dropped-stories'}, dropped.map(s =>
        h('li', null, h('a', {href: '/search/?q=' + encodeURIComponent('"' + s.headline + '"'), text: s.headline})))));
    }
    details.hidden = true;
    const toggle = h('button', {type: 'button', class: 'edition-toggle', 'aria-expanded': 'false', 'aria-controls': 'edition-details', 'aria-label': 'Show full edition details'},
      crumbs ? h('span', {class: 'edition-toggle-text', text: `${latest ? 'Latest' : 'Archived'}${ed.revision > 1 ? ` · Update ${ed.revision}` : ''}`}) : null,
      h('span', {class: 'edition-toggle-label', text: 'Details'}));
    toggle.addEventListener('click', () => {
      details.hidden = !details.hidden;
      toggle.setAttribute('aria-expanded', String(!details.hidden));
      toggle.setAttribute('aria-label', `${details.hidden ? 'Show' : 'Hide'} full edition details`);
    });
    return h('div', {class: 'strip' + (crumbs ? ' with-crumbs' : '')}, h('div', {class: 'strip-row'}, crumbs || ticker(ed, latest, ageH), toggle), details);
  }
  // The edition at a glance, always visible under the header: freshness, size, how many source types answered
  // and what changed since the previous update. One line; it scrolls sideways on phones.
  function ticker(ed, latest, ageH) {
    const n = x => h('b', {text: Number(x || 0).toLocaleString('en-US')});
    const answered = ed.sources_answered || 0, tried = ed.sources_tried || 0;
    const count = kind => ed.stories.filter(s => s.change === kind).length;
    const dropped = ed.changes && Array.isArray(ed.changes.dropped) ? ed.changes.dropped.length : null;
    return h('ul', {class: 'ticker', 'aria-label': 'Edition status'},
      h('li', {class: 'live' + (latest && ageH < 30 ? '' : ' old')}, h('b', {text: latest ? 'Latest edition' : 'Archived edition'})),
      h('li', null, h('time', {datetime: ed.edition_date, text: shortDate(ed.edition_date)}), ed.revision > 1 ? ` · Update ${ed.revision}` : ''),
      h('li', null, n(ed.stories.length), ed.stories.length === 1 ? ' story' : ' stories'),
      h('li', null, n(ed.reports_read), ed.reports_read === 1 ? ' report' : ' reports'),
      h('li', {class: tried && answered < tried ? 'warn' : null, title: `${answered} of ${tried} kinds of source answered during this run`}, h('b', {text: `${answered}/${tried}`}), ' source types up'),
      ed.compared_with ? h('li', {class: 'diff'}, `Since update ${ed.compared_with.revision}: `, h('b', {class: 'up', text: `+${count('new')}`}), ' new · ',
        n(count('updated')), ' updated', dropped != null ? [' · ', n(dropped), ' dropped'] : null) : null,
      h('li', null, 'Generated ', h('time', {datetime: ed.generated_utc, 'data-relative': 'true', title: fullStamp(ed.generated_utc), text: ago(ed.generated_utc)})));
  }
  function notices(ed, idx) {
    const out = [];
    if (idx && idx.latest && idx.latest !== ed.edition_date)
      out.push(h('p', {class: 'notice'}, `You are reading the edition of ${longDate(ed.edition_date)}. `, h('a', {href: '/daily/', text: 'Read the latest edition →'})));
    else if ((Date.now() - Date.parse(ed.generated_utc)) / 3.6e6 > 36)
      out.push(h('p', {class: 'notice', text: `This is the most recent edition (${shortDate(ed.edition_date)}). A new one appears here after the next daily run.`}));
    return out;
  }
  function lead(ed, s) {
    return h('article', {class: 'lead', id: 'story-' + s.id, 'data-cat': s.category},
      h('span', {class: 'rank-label', text: 'Top story'}), kicker(s),
      headline(ed, s, 'h1'),
      h('p', {class: 'dek', text: s.summary.join(' ')}),
      s.why_it_matters ? h('p', {class: 'why'}, h('b', {text: 'Why it matters: '}), s.why_it_matters) : null,
      meta(s, {ed, tags: 4}));
  }
  function rail(ed, stories) {
    return h('section', {class: 'rail', 'aria-labelledby': 'rail-title'}, h('h2', {class: 'rail-title', id: 'rail-title'}, h('span', {text: 'Top stories'})),
      stories.map((s, i) => h('article', {class: 'rail-item', id: 'story-' + s.id, 'data-cat': s.category}, h('span', {class: 'rail-num', 'aria-hidden': 'true', text: String(i + 2)}),
        kicker(s), headline(ed, s, 'h3'),
        h('p', {class: 'dek', text: s.summary.join(' ')}), meta(s, {ed, tags: 2}))));
  }
  const BAND_STORIES = 5;
  function sectionBand(ed, cat, stories, title, complete = false) {
    const sec = SECTION[cat] || {};
    const shown = complete ? stories : stories.slice(0, BAND_STORIES);
    const all = cat ? ((ed.sections || []).find(x => x.category === cat) || {ids: []}).ids.length : 0;
    const grid = h('div', {class: 'grid'}, shown.map((s, i) => card(ed, s, i === 0 && shown.length >= 4 ? 'feature' : '')));
    return h('section', {class: 'band', id: cat ? sectionId(cat) : 'band-top', 'data-cat': cat, 'aria-labelledby': (cat ? sectionId(cat) : 'band-top') + '-title'}, h('div', {class: 'wrap'},
      h('div', {class: 'band-head'}, h('h2', {class: 'band-title', id: (cat ? sectionId(cat) : 'band-top') + '-title', text: title || sec.title || catLabel(cat)}),
        sec.path ? h('a', {class: 'band-link', href: sec.path}, `All ${all} in ${sec.title}`) : null), grid));
  }
  function archiveBand(idx, current) {
    const others = (idx.editions || []).filter(e => e.date !== current).slice(0, 4);
    if (!others.length) return null;
    return h('section', {class: 'band', 'aria-label': 'Previous editions'}, h('div', {class: 'wrap'},
      h('div', {class: 'band-head'}, h('h2', {class: 'band-title', text: 'Previous editions'}), h('a', {class: 'band-link', href: '/archive/', text: 'Archive'})),
      h('div', {class: 'grid'}, others.map(e => h('article', {class: 'card'}, h('span', {class: 'kicker', text: shortDate(e.date)}),
        h('h3', {class: 'hl'}, h('a', {href: editionUrl(e.date), text: e.lead})), h('p', {class: 'dek', text: (e.headlines || []).join(' · ')}),
        h('div', {class: 'meta', text: plural(e.stories, 'story', 'stories')}))))));
  }
  function aboutBand() {
    return h('section', {class: 'wrap about-band', 'aria-label': 'About Agent Reach Daily'},
      h('div', null, h('h2', {text: 'The day’s news, from public reporting, summarized by a local AI.'}),
        h('p', {text: 'Agent Reach Daily reads around 1,500 reports a day from 112 publisher feeds, 22 YouTube news channels and eight other kinds of source, keeps each event as one story, and checks every summary sentence against the story’s own sources. It runs on one Windows PC and publishes here automatically. Coverage strength shows how many independent outlets reported a story; it is not a fact check.'}),
        h('div', {class: 'links'}, h('a', {class: 'pill', href: '/about/#method', text: 'How it works'}), h('a', {class: 'pill', href: '/about/#app', text: 'Make your own edition'}))),
      h('ol', {class: 'howlist'},
        h('li', null, h('b', {text: 'Collect'}), 'News feeds, Google News, Hacker News, Wikipedia, YouTube, Bluesky, Mastodon and trend lists.'),
        h('li', null, h('b', {text: 'Group'}), 'Reports of one event become one story. When unsure, they stay apart.'),
        h('li', null, h('b', {text: 'Write'}), 'A local model (no cloud AI) writes the summary; unsupported sentences are removed.'),
        h('li', null, h('b', {text: 'Publish'}), 'A failed run never replaces the last good edition.')));
  }
  const sectionId = cat => 'band-' + cat.toLowerCase().replace(/[^a-z]+/g, '-');
  function sectionShortcuts(ed) {
    return h('nav', {class: 'section-shortcuts', 'aria-label': 'Jump to a section'}, (ed.sections || []).map(sec =>
      h('a', {class: 'pill', href: '#' + sectionId(sec.category), text: `${catLabel(sec.category)} ${sec.ids.length}`})));
  }
  function renderFront(ed, idx, current, storyNotice) {
    const top = ed.topStories;
    const used = new Set(top.slice(0, 8).map(s => s.id));
    const content = [h('div', {class: 'wrap'}, strip(ed, idx), sectionShortcuts(ed), notices(ed, idx),
      storyNotice ? h('p', {class: 'notice story-recovery', text: storyNotice}) : null,
      h('div', {class: 'front'}, lead(ed, top[0]), rail(ed, top.slice(1, 4))))];
    if (top.length > 4) content.push(sectionBand(ed, null, top.slice(4, 8), 'More top stories'));
    for (const sec of ed.sections || []) {
      const stories = sec.ids.map(id => ed.byId[id]).filter(s => s && !used.has(s.id));
      content.push(sectionBand(ed, sec.category, stories, null, current === 'edition' || body.dataset.prerender === 'true'));
    }
    if (idx) content.push(archiveBand(idx, ed.edition_date));
    content.push(aboutBand());
    mount(current, ed, content);
    document.title = current === 'home' ? 'Agent Reach Daily: today’s news, from public reporting'
      : `Agent Reach Daily: ${longDate(ed.edition_date)}`;
  }

  // ------------------------------------------------------------------ story page
  function sourcesBlock(s) {
    const sources = s.sources;
    const groups = [
      ['report', 'Independent reports shown', 'One entry per reporting origin in the displayed sources.'],
      ['repeat', 'Repeats and syndicated copies', 'The same outlet again, or the same headline carried by another outlet (a wire story). Counted once.'],
      ['signal', 'Social and search signals', 'Trending searches and posts show attention, not reporting. They never count as a source.'],
    ];
    return h('section', {class: 'sources', id: 'sources', tabindex: '-1', 'aria-labelledby': 'sources-title'},
      h('h2', {id: 'sources-title', text: 'Sources'}), groups.map(([kind, title, hint]) => {
      const list = sources.filter(x => x.kind === kind);
      if (!list.length) return null;
      return h('div', null, h('h3', {text: `${title} (${list.length})`}), h('p', {class: 'hint', text: hint}),
        list.map(src => {
          const url = webUrl(src.url);
          return h('div', {class: 'source'}, h('span', {class: 'outlet', text: dedupeOutlets([src.outlet])[0] || src.outlet}),
            src.published_utc ? h('time', {class: 'when', datetime: src.published_utc, text: fullStamp(src.published_utc)}) : h('span', {class: 'when', text: 'Time not stated'}),
            url ? h('a', {class: 'title', href: url, rel: 'noopener noreferrer', target: '_blank', text: src.title}) : h('span', {class: 'title', text: src.title}),
            hostOf(src.url) === 'news.google.com' ? h('span', {class: 'via', text: 'Google News redirect · opens through Google News'})
              : src.via && src.via !== src.outlet ? h('span', {class: 'via', text: 'Found via ' + src.via}) : null);
        }));
    }));
  }
  function coveragePanel(s) {
    const c = {...s.coverage, independent_reports: independentCount(s), publishers: publisherList(s)};
    const facts = [h('li', {text: `${plural(c.independent_reports, 'independent outlet')}${c.publishers.length ? ': ' + c.publishers.join(', ') : ''}`})];
    facts.push(h('li', {text: `Displayed evidence: ${plural(c.source_links || 0, 'source link')} · ${plural(c.linked_outlets || 0, 'newsroom')} · ${plural(c.linked_reporting_origins || 0, 'reporting origin')}`}));
    if (c.repeats) facts.push(h('li', {text: `${plural(c.repeats, 'repeat or syndicated copy', 'repeats or syndicated copies')}, counted once`}));
    if (c.signals) facts.push(h('li', {text: `${plural(c.signals, 'social or search signal')} (attention, not reporting)`}));
    facts.push(h('li', {text: `Found through ${plural(c.channels, 'channel')}`}));
    if (c.independent_reports < 2) facts.push(h('li', {text: 'Not yet confirmed by a second independent outlet'}));
    return h('section', {class: 'panel', 'aria-label': 'Coverage'}, h('h2', {text: 'Coverage'}),
      h('div', {class: `cov-big cov ${c.level}`}, h('span', {class: 'bars', 'aria-hidden': 'true'}, h('i'), h('i'), h('i')), coverage(c)),
      h('ul', {class: 'facts'}, facts),
      h('p', {class: 'fine'}, 'Coverage counts independent outlets that reported this story. It is not a fact check: several outlets can repeat the same claim. ', h('a', {href: '/about/#coverage', text: 'How coverage is measured'})));
  }
  function renderStory(ed, idx, s, storyNotice) {
    const order = ed.ordered;
    const i = order.indexOf(s);
    const prev = order[i - 1], next = order[i + 1];
    const same = order.filter(x => x.category === s.category && x !== s).slice(0, 4);
    const when = s.newest_published_utc;
    const crumbs = h('nav', {class: 'crumbs', 'aria-label': 'Breadcrumb'}, h('a', {href: editionUrl(ed.edition_date)}, h('span', {class: 'crumb-pre', text: 'Edition of '}), shortDate(ed.edition_date)),
      h('span', {'aria-hidden': 'true', text: '/'}), SECTION[s.category] && SECTION[s.category].path ? h('a', {href: SECTION[s.category].path, text: catLabel(s.category)}) : h('span', {text: catLabel(s.category)}),
      s.top_rank ? h('span', {class: 'crumb-rank', text: `· Top story ${s.top_rank} of ${ed.topStories.length}`}) : null);
    const url = mainLink(s);
    const main = mount('edition', ed, h('div', {class: 'wrap'}, strip(ed, idx, crumbs), notices(ed, idx),
      storyNotice ? h('p', {class: 'notice story-recovery', text: storyNotice}) : null,
      h('article', {class: 'story', 'data-cat': s.category},
      h('div', {class: 'story-main'}, kicker(s), url
        ? h('h1', {class: 'hl', tabindex: '-1'}, h('a', {class: 'out', href: url, rel: 'noopener noreferrer', target: '_blank', 'aria-describedby': 'ext-note', 'data-outlet': mainOutlet(s, url), text: s.headline}))
        : h('h1', {class: 'hl', tabindex: '-1', text: s.headline}),
        h('div', {class: 'meta'}, when ? h('time', {datetime: when, text: `Newest report ${fullStamp(when)}`}) : h('span', {text: 'Publication time not stated'}),
          outletTags(s, 8), covMeter(s)),
        h('div', {class: 'story-actions'},
          url ? h('a', {class: 'pill solid read-source', href: url, rel: 'noopener noreferrer', target: '_blank', 'aria-describedby': 'ext-note'}, `Read at ${mainOutlet(s, url)}`) : null,
          h('button', {class: 'source-jump', type: 'button', text: `${plural(sourceLinks(s), 'source link')} ↓`}),
          h('button', {class: 'pill share-story', type: 'button', text: 'Share'}),
          h('button', {class: 'pill copy-story', type: 'button', text: 'Copy link'})),
        h('p', {class: 'share-status sr', role: 'status', 'aria-live': 'polite'}),
        h('label', {class: 'share-fallback', hidden: true}, 'Copy this story link', h('input', {type: 'url', readonly: true})),
        h('div', {class: 'story-body'}, s.summary.map(t => h('p', {text: t}))),
        s.why_it_matters ? h('div', {class: 'why-box'}, h('h2', {text: 'Why it matters'}), h('p', {text: s.why_it_matters})) : null,
        h('p', {class: 'ai-note'}, h('b', {text: 'How this was written. '}),
          `This summary was written automatically by a local AI model (${(ed.models && ed.models.summaries) || 'a local model'}) from the reports below, and each sentence was checked against them before publication. Nobody edited it. It can still be wrong or out of date: read the sources for the full story.`),
        sourcesBlock(s)),
      h('section', {class: 'aside', 'aria-labelledby': 'story-context-title'}, h('h2', {id: 'story-context-title', class: 'sr', text: 'Story context'}), coveragePanel(s),
        same.length ? h('section', {class: 'panel', 'aria-label': 'More in this section'}, h('h2', {text: `More in ${catLabel(s.category)}`}),
          h('div', {class: 'compact'}, same.map(x => h('div', {class: 'item'}, h('h3', {class: 'hl'}, h('a', {href: storyUrl(ed, x), text: x.headline})), meta(x, {noOutlets: true}))))) : null),
      h('nav', {class: 'story-nav', 'aria-label': 'Previous and next story'},
        prev ? h('a', {href: storyUrl(ed, prev)}, h('small', {text: '← Previous story'}), h('span', {text: prev.headline})) : h('span'),
        next ? h('a', {class: 'next', href: storyUrl(ed, next)}, h('small', {text: 'Next story →'}), h('span', {text: next.headline})) : h('span')))));
    document.title = `${s.headline} | Agent Reach Daily`;
    main.querySelector('.source-jump').addEventListener('click', () => {
      const sources = main.querySelector('#sources');
      sources.focus({preventScroll: true});
      sources.scrollIntoView({block: 'start'});
    });
    const shareUrl = new URL(storyUrl(ed, s), location.origin);
    shareUrl.searchParams.set('headline', s.headline);
    const status = main.querySelector('.share-status');
    const copy = async () => {
      try {
        await navigator.clipboard.writeText(shareUrl.href);
        status.textContent = 'Story link copied.';
      } catch (_) {
        const fallback = main.querySelector('.share-fallback');
        fallback.hidden = false;
        const input = fallback.querySelector('input');
        input.value = shareUrl.href;
        input.focus(); input.select();
        status.textContent = 'Select and copy the story link below.';
      }
    };
    main.querySelector('.copy-story').addEventListener('click', copy);
    main.querySelector('.share-story').addEventListener('click', async () => {
      if (!navigator.share) { await copy(); return; }
      try { await navigator.share({title: s.headline, url: shareUrl.href}); }
      catch (error) { if (error.name !== 'AbortError') await copy(); }
    });
    window.scrollTo(0, 0);
    return main;
  }

  // ------------------------------------------------------------------ other pages
  function renderLatest(ed, idx) {
    const known = ed.stories.filter(s => s.newest_published_utc).sort((a, b) => Date.parse(b.newest_published_utc) - Date.parse(a.newest_published_utc));
    const rest = ed.ordered.filter(s => !s.newest_published_utc);
    mount('latest', ed, h('div', {class: 'wrap'}, strip(ed, idx),
      h('header', {class: 'page-head'}, h('h1', {text: 'Latest News'}),
        h('p', {text: `Every story of the ${longDate(ed.edition_date)} edition, newest report first. Times are when the newest source says it was published, in your time zone.`})),
      notices(ed, idx),
      h('div', {class: 'river'}, known.concat(rest).map(s => h('article', {class: 'river-item', id: 'story-' + s.id, 'data-cat': s.category},
        h('div', {class: 'river-time'}, s.newest_published_utc ? [h('b', {text: new Date(s.newest_published_utc).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'})}),
          new Date(s.newest_published_utc).toLocaleDateString('en-US', {month: 'short', day: 'numeric'})] : h('b', {text: 'Time not stated'})),
        h('div', {class: 'river-body'}, kicker(s), headline(ed, s, 'h2'),
          h('p', {class: 'dek', text: s.summary.join(' ')}), meta(s, {ed, noTime: true})))))));
    document.title = 'Latest News | Agent Reach Daily';
  }
  function renderSection(ed, idx, cat) {
    const sec = SECTION[cat];
    const ids = ((ed.sections || []).find(x => x.category === cat) || {ids: []}).ids;
    const stories = ids.map(id => ed.byId[id]).filter(Boolean);
    mount(cat, ed, h('div', {class: 'wrap'}, strip(ed, idx),
      h('header', {class: 'page-head', 'data-cat': cat}, h('h1', {text: sec.title}), h('p', {text: `${sec.blurb} From the ${longDate(ed.edition_date)} edition.`})),
      notices(ed, idx)),
      stories.length ? h('section', {class: 'band', 'data-cat': cat, 'aria-label': sec.title}, h('div', {class: 'wrap'},
        h('div', {class: 'grid'}, stories.map((s, i) => card(ed, s, i === 0 && stories.length >= 3 ? 'feature' : '', 'h2')))))
        : h('div', {class: 'wrap state'}, h('h2', {text: `No ${sec.title} stories in this edition`}),
          h('p', null, cat === 'Local' ? 'Local stories appear here when an edition has them. ' : 'Other sections may have more today. ',
            h('a', {href: '/', text: 'Read the full edition'}), '.')));
    document.title = `${sec.title} | Agent Reach Daily`;
  }
  function renderArchive(idx) {
    const months = new Map();
    for (const e of idx.editions || []) {
      const key = dayOf(e.date).toLocaleDateString('en-US', {month: 'long', year: 'numeric', timeZone: 'UTC'});
      if (!months.has(key)) months.set(key, []);
      months.get(key).push(e);
    }
    mount('archive', null, h('div', {class: 'wrap'},
      h('header', {class: 'page-head'}, h('h1', {text: 'Archive'}),
        h('p', {text: 'Available editions, newest first. Each has its own dated page; when an edition was updated during the day, the page shows the last update. Withdrawn editions are removed from the archive.'}),
        searchForm('')),
      h('div', {class: 'archive'}, months.size ? [...months].map(([m, list]) => h('section', {class: 'month'}, h('h2', {text: m}),
        list.map(e => h('a', {class: 'ed-row', href: editionUrl(e.date)},
          h('div', {class: 'ed-day'}, String(dayOf(e.date).getUTCDate()), h('small', {text: dayOf(e.date).toLocaleDateString('en-US', {weekday: 'long', timeZone: 'UTC'})})),
          h('div', null, h('p', {class: 'ed-lead', text: e.lead}), h('ul', {class: 'ed-more'}, (e.headlines || []).map(t => h('li', {text: t}))),
            h('div', {class: 'chips'}, Object.entries(e.sections || {}).map(([c, n]) => h('span', {class: 'chip', text: `${catLabel(c)} ${n}`})))),
          h('div', {class: 'ed-count', text: plural(e.stories, 'story', 'stories')}))))) : h('p', {class: 'state', text: 'No editions have been published yet.'}))));
    document.title = 'Archive | Agent Reach Daily';
  }

  // ------------------------------------------------------------------ search
  // The archive is searched in the browser: one small file per month, newest months first. Only the months the
  // reader reaches are downloaded, so a search stays fast however long the archive gets.
  const SEARCH_BATCH = 6;     // months searched before asking to go further back
  const SEARCH_PAGE = 40;     // results shown before "Show more"
  const COVER = {strong: 'Strong coverage', moderate: 'Moderate coverage', limited: 'Limited coverage'};
  const fold = t => String(t || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const norm = t => ' ' + fold(t).replace(/[^\p{L}\p{N}]+/gu, ' ').trim() + ' ';
  const commonHeadlineWords = new Set('a about an and are as at be by for from has have how in is it of on or that the this to was were what will with you your'.split(' '));
  function recoverHeadline(ed, hint) {
    if (!hint) return null;
    const key = norm(hint).trim();
    if (!key) return null;
    const exact = ed.stories.filter(s => norm(s.headline).trim() === key);
    if (exact.length) return exact.length === 1 ? exact[0] : null;
    const words = new Set(key.split(' ').filter(w => !commonHeadlineWords.has(w)));
    if (words.size < 3) return null;
    const candidates = ed.stories.map(story => {
      const own = new Set(norm(story.headline).trim().split(' ').filter(w => !commonHeadlineWords.has(w)));
      const shared = [...words].filter(w => own.has(w)).length;
      return {story, shared, size: own.size};
    }).sort((a, b) => b.shared - a.shared);
    const best = candidates[0], runnerUp = candidates[1];
    // Require substantial overlap on both headlines and a clear margin; never guess on a tie.
    return best && best.shared >= 3 && best.shared / words.size >= 0.6 && best.shared / best.size >= 0.6 &&
      (!runnerUp || best.shared - runnerUp.shared >= 2) ? best.story : null;
  }
  const monthOf = d => d.slice(0, 7);
  const monthName = m => dayOf(m + '-15').toLocaleDateString('en-US', {month: 'long', year: 'numeric', timeZone: 'UTC'});
  function searchForm(q) {
    return h('form', {class: 'search-form', role: 'search', action: '/search/', method: 'get'},
      h('span', {class: 'glass', 'aria-hidden': 'true'}),
      h('input', {type: 'search', name: 'q', value: q, placeholder: 'Search every edition: a name, place or topic', 'aria-label': 'Search the archive', autocomplete: 'off', enterkeyhint: 'search'}),
      h('button', {class: 'pill solid', type: 'submit', text: 'Search'}));
  }
  function parseQuery(q) { // words match the start of a word; "quoted words" match as a phrase
    const terms = [];
    String(q).replace(/"([^"]+)"|(\S+)/g, (m, phrase, word) => { const t = norm(phrase || word).trim(); if (t) terms.push(t); return ''; });
    return [...new Set(terms)].slice(0, 8);
  }
  function marked(text, terms) {
    if (!terms.length) return text;
    const esc = terms.map(t => t.split(' ').map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[^\\p{L}\\p{N}]+'));
    const rx = new RegExp(`(^|[^\\p{L}\\p{N}])(${esc.join('|')})`, 'giu');
    const out = []; let last = 0;
    String(text).replace(rx, (m, pre, hit, at) => {
      const start = at + pre.length;
      out.push(text.slice(last, start), h('mark', {text: hit})); last = start + hit.length; return m;
    });
    out.push(text.slice(last));
    return out;
  }
  function renderSearch(idx) {
    const params = new URLSearchParams(location.search);
    let timer = null;
    const months = [...new Set((idx.editions || []).map(e => monthOf(e.date)))].sort().reverse();
    const editionsIn = new Map(); for (const e of idx.editions || []) editionsIn.set(monthOf(e.date), (editionsIn.get(monthOf(e.date)) || 0) + 1);
    const data = new Map();   // month -> entries with folded text, or null when it could not be loaded
    const pending = new Map();
    const requestedCat = params.get('cat') || '';
    const st = {q: params.get('q') || '', cat: Object.hasOwn(SECTION, requestedCat) ? requestedCat : '', sort: params.get('sort') === 'best' ? 'best' : 'new',
      horizon: Math.min(SEARCH_BATCH, months.length), shown: SEARCH_PAGE, run: 0};
    function load(m) {
      if (!pending.has(m)) pending.set(m, getJson(`/search/${m}.json`).then(doc => {
        if (!Array.isArray(doc && doc.stories)) throw new Error('unavailable search data');
        const list = doc.stories.map(x => {
          const c = x.coverage ? correctedCoverage(x.coverage) : null;
          return {...x, o: dedupeOutlets(x.o || []), l: c ? c.level : x.l, coverage: c,
            u: articleUrl(x.u) || undefined};
        });
        data.set(m, list.filter(x => x && x.d && x.id && x.h).map(x => Object.assign(x, {
          _h: norm(x.h), _all: norm([x.h, x.s, (x.o || []).join(' '), catLabel(x.c)].join(' | '))})));
      }).catch(() => data.set(m, null)));
      return pending.get(m);
    }
    const input = h('input', {id: 'archive-query', type: 'search', value: st.q, placeholder: 'A name, place or topic', 'aria-label': 'Search the archive', 'aria-describedby': 'search-help', autocomplete: 'off', enterkeyhint: 'search'});
    const cat = h('select', {'aria-label': 'Section'}, h('option', {value: '', text: 'All sections'}),
      Object.keys(SECTION).map(c => h('option', {value: c, text: catLabel(c), selected: c === st.cat})));
    const sortBtns = [['new', 'Newest first'], ['best', 'Best match']].map(([k, label]) =>
      h('button', {type: 'button', class: 'seg', 'data-sort': k, 'aria-pressed': String(st.sort === k), text: label}));
    const form = h('form', {class: 'search-form search-tools', role: 'search'},
      h('label', {class: 'search-field'}, h('span', {text: 'Search the archive'}), input),
      h('label', {class: 'search-field'}, h('span', {text: 'Section'}), cat),
      h('button', {class: 'pill solid', type: 'submit', text: 'Search'}));
    form.addEventListener('submit', e => { e.preventDefault(); st.shown = SEARCH_PAGE; syncQuery(); run(); });
    const status = h('p', {class: 'search-status', id: 'search-status', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true', tabindex: '-1'});
    const recovery = h('div', {class: 'search-recovery'});
    const results = h('div', {class: 'hits', id: 'search-results', role: 'region', 'aria-label': 'Search results', 'aria-describedby': 'search-status', 'aria-busy': 'false'});
    const more = h('div', {class: 'search-more'});
    const first = (idx.editions || []).length ? idx.editions[idx.editions.length - 1].date : null;
    mount('search', null, h('div', {class: 'wrap'},
      h('header', {class: 'page-head'}, h('h1', {text: 'Search'}),
        h('p', {text: first ? `Search headlines, summaries and outlets across ${plural((idx.editions || []).length, 'edition')}, since ${longDate(first)}.` : 'No editions have been published yet.'}),
        form,
        h('p', {class: 'search-help', id: 'search-help', text: 'Results appear as you type. Words match the start of a word; use "quotes" to match a phrase.'}),
        h('div', {class: 'segs', role: 'group', 'aria-label': 'Order'}, sortBtns)),
      status, recovery, results, more));
    document.title = (st.q ? `${st.q}: search` : 'Search') + ' | Agent Reach Daily';

    function remember() {
      const p = new URLSearchParams();
      if (st.q) p.set('q', st.q); if (st.cat) p.set('cat', st.cat); if (st.sort === 'best') p.set('sort', 'best');
      history.replaceState(null, '', '/search/' + (p.toString() ? '?' + p : ''));
      document.title = (st.q ? `${st.q}: search` : 'Search') + ' | Agent Reach Daily';
    }
    function syncQuery() {
      clearTimeout(timer);
      const q = input.value.trim();
      if (q !== st.q) st.shown = SEARCH_PAGE;
      st.q = q;
      remember();
    }
    async function run(focusAfter, firstNewResult) {
      const ticket = ++st.run;
      const terms = parseQuery(st.q);
      const reach = months.slice(0, st.horizon);
      results.replaceChildren(); more.replaceChildren(); recovery.replaceChildren();
      results.setAttribute('aria-busy', 'false');
      if (!terms.length) {
        status.textContent = months.length ? (st.q ? 'Enter a word or phrase to search.' : 'Type to search. Results appear as you type.') : '';
        if (months.length) load(months[0]);
        if (focusAfter) status.focus({preventScroll: true});
        return;
      }
      if (reach.some(m => !data.has(m))) status.textContent = 'Searching…';
      results.setAttribute('aria-busy', 'true');
      // Give a removed recovery button a stable successor while the request runs.
      if (focusAfter) status.focus({preventScroll: true});
      await Promise.all(reach.map(load));
      if (ticket !== st.run) return;
      const hits = [];
      const missing = [];
      for (const m of reach) {
        const list = data.get(m);
        if (!list) { missing.push(m); continue; }
        for (const x of list) {
          if (st.cat && x.c !== st.cat) continue;
          let score = 0, ok = true;
          for (const t of terms) {
            if (!x._all.includes(' ' + t)) { ok = false; break; }
            score += x._h.includes(' ' + t) ? 3 : 1;
          }
          if (ok) hits.push([score + (x.t ? 0.5 : 0), x]);
        }
      }
      hits.sort((a, b) => st.sort === 'best' ? (b[0] - a[0]) || b[1].d.localeCompare(a[1].d) || a[1].r - b[1].r
        : b[1].d.localeCompare(a[1].d) || a[1].r - b[1].r);
      const searched = reach.reduce((n, m) => n + (data.get(m) ? editionsIn.get(m) || 0 : 0), 0);
      const span = reach.length ? (reach.length === 1 ? monthName(reach[0]) : `${monthName(reach[reach.length - 1])} to ${monthName(reach[0])}`) : '';
      status.textContent = missing.length === reach.length && missing.length
        ? 'Search is unavailable. No editions could be searched.'
        : `${plural(hits.length, 'story', 'stories')} found across ${plural(searched, 'searched edition')}${span ? ` (${span})` : ''}.` +
          (missing.length ? ` Results are incomplete: ${plural(missing.length, 'month')} could not be loaded.` : '');
      results.replaceChildren(...hits.slice(0, st.shown).map(([, x]) => hit(x, terms)));
      results.setAttribute('aria-busy', 'false');
      if (missing.length) recovery.append(
        h('h2', {text: missing.length === reach.length ? 'Search temporarily unavailable' : 'Some editions could not be searched'}),
        h('p', {text: `Unavailable: ${missing.map(monthName).join(', ')}. Retry to search these editions; your query and filters are kept.`}),
        h('div', {class: 'search-recovery-actions'},
          h('button', {class: 'pill', type: 'button', 'data-act': 'retry', text: 'Retry unavailable months'}),
          h('a', {class: 'pill', href: '/archive/', text: 'Browse editions by date'})));
      if (hits.length > st.shown) more.append(h('button', {class: 'pill', type: 'button', text: `Show more results (${(hits.length - st.shown).toLocaleString('en-US')} more)`, 'data-act': 'more'}));
      if (st.horizon < months.length) more.append(h('button', {class: 'pill', type: 'button', 'data-act': 'older',
        text: `Search older editions (before ${monthName(months[st.horizon - 1])})`}));
      if (!hits.length && !missing.length) results.append(h('div', {class: 'search-empty'},
        h('h2', {text: 'No matching stories'}),
        h('p', {text: st.horizon < months.length ? 'No matches in the searched editions. Try fewer or shorter words, or search older editions below.' : 'Try fewer or shorter words, or choose another section.'}),
        st.cat ? h('button', {class: 'pill', type: 'button', 'data-act': 'all-sections', text: 'Search all sections'}) : null,
        h('a', {href: '/archive/', text: 'Browse editions by date →'})));
      // A reader may have moved on while data loaded; never take their focus back.
      if (focusAfter && document.activeElement === status) {
        const target = firstNewResult == null ? status : results.querySelectorAll('.hit h2 a')[firstNewResult] || status;
        target.focus({preventScroll: true});
        target.scrollIntoView({block: 'nearest'});
      }
    }
    const storyHref = x => `/daily/${x.d}/?headline=${encodeURIComponent(x.h)}#story-${x.id}`;
    function hit(x, terms) {
      return h('article', {class: 'hit', 'data-cat': x.c},
        h('div', {class: 'hit-meta'}, h('time', {datetime: x.d, text: shortDate(x.d)}), h('span', {class: 'kicker', 'data-cat': x.c, text: catLabel(x.c)}),
          x.t ? h('span', {class: 'badge trend', text: `Top story ${x.t}`}) : null),
        h('h2', {class: 'hl'}, x.u && webUrl(x.u) && /^https?:/.test(x.u)
          ? h('a', {class: 'out', href: webUrl(x.u), rel: 'noopener noreferrer', target: '_blank', 'aria-describedby': 'ext-note'}, marked(x.h, terms))
          : h('a', {href: storyHref(x)}, marked(x.h, terms))),
        x.s ? h('p', {class: 'dek'}, marked(x.s, terms)) : null,
        h('div', {class: 'meta'}, (x.o || []).length ? h('span', {class: 'outlets'}, marked((x.o || []).join(', '), terms)) : null,
          x.coverage ? covMeter({coverage: x.coverage, sources: []})
            : h('span', {class: `cov ${x.l || 'limited'}`}, h('span', {class: 'bars', 'aria-hidden': 'true'}, h('i'), h('i'), h('i')), COVER[x.l] || COVER.limited),
          x.u ? h('a', {class: 'story-link', href: storyHref(x)}, 'Sources', h('span', {class: 'sr', text: ` and coverage: ${x.h}`})) : null));
    }
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { st.shown = SEARCH_PAGE; syncQuery(); run(); }, 140); });
    cat.addEventListener('change', () => { st.cat = cat.value; st.shown = SEARCH_PAGE; syncQuery(); run(); });
    for (const b of sortBtns) b.addEventListener('click', () => {
      st.sort = b.dataset.sort; for (const x of sortBtns) x.setAttribute('aria-pressed', String(x === b)); syncQuery(); run();
    });
    function recover(e) {
      const act = e.target.closest('button') && e.target.closest('button').dataset.act;
      if (!act) return;
      syncQuery();
      if (act === 'more') { const previousShown = st.shown; st.shown += SEARCH_PAGE; run(true, previousShown); }
      if (act === 'older') { st.horizon = Math.min(months.length, st.horizon + SEARCH_BATCH); run(true); }
      if (act === 'retry') {
        for (const m of months.slice(0, st.horizon)) if (data.get(m) === null) { data.delete(m); pending.delete(m); }
        run(true);
      }
      if (act === 'all-sections') { st.cat = ''; cat.value = ''; st.shown = SEARCH_PAGE; remember(); run(true); }
    }
    more.addEventListener('click', recover);
    recovery.addEventListener('click', recover);
    results.addEventListener('click', recover);
    if (requestedCat !== st.cat) remember();
    run();
  }

  // ------------------------------------------------------------------ routing
  async function start() {
    if (page === 'about') { chrome('about'); return; }
    if (page === 'notfound') {
      if (/^\/daily\/\d{4}-\d{2}-\d{2}\/$/.test(location.pathname)) {
        failed('edition', "This edition isn't available. It may have been withdrawn.", true);
        return;
      }
      mount(null, null, h('div', {class: 'wrap state'}, h('h1', {text: 'Page not found'}),
        h('p', null, 'That page does not exist. ', h('a', {href: '/', text: 'Go to today’s news'}), ' or ', h('a', {href: '/archive/', text: 'browse the archive'}), '.')));
      return;
    }
    const current = page === 'section' ? body.dataset.section : page;
    const embedded = embeddedData();
    if (!embedded) loading(current);
    // Start a known dated edition alongside its index, and handle its rejection immediately.
    const dated = !embedded && body.dataset.date ? loadEdition(body.dataset.date).then(ed => ({ed}), error => ({error})) : null;
    let idx;
    try { idx = embedded ? embedded.idx : await loadIndex(); } catch (e) { failed(current); return; }
    if (page === 'archive') { renderArchive(idx); pageStatus.textContent = `Archive loaded. ${plural((idx.editions || []).length, 'edition')}.`; return; }
    if (page === 'search') { renderSearch(idx); pageStatus.textContent = 'Archive search ready.'; return; }
    const date = body.dataset.date || idx.latest;
    if (!date) { failed(current, 'No edition has been published yet.'); return; }
    let ed;
    try {
      const result = dated && await dated;
      if (result && result.error) throw result.error;
      ed = embedded ? embedded.ed : result ? result.ed : await loadEdition(date);
    } catch (e) {
      if (body.dataset.date && e.message === '404') {
        failed(current, "This edition isn't available. It may have been withdrawn.", true);
        return;
      }
      failed(current, body.dataset.date ? `The edition of ${longDate(date)} is not available.` : null);
      return;
    }
    let renderedView = null;
    const route = () => {
      const m = /^#story-([0-9a-f]{6,40})$/.exec(location.hash);
      let s = m && ed.byId[m[1]];
      const hint = new URLSearchParams(location.search);
      let storyNotice = null;
      if (m && !s) {
        s = recoverHeadline(ed, hint.get('headline'));
        storyNotice = s ? 'The original story link no longer exists in this revision. Showing the closest clear headline match.'
          : 'This story was updated in a later edition of the day; here is the full edition.';
      }
      if (hint.has('headline')) {
        hint.delete('headline');
        history.replaceState(null, '', location.pathname + (hint.toString() ? '?' + hint : '') + (s ? '#story-' + s.id : location.hash));
      }
      const view = s ? s.id : page + (storyNotice ? ':missing-story' : '');
      if (view === renderedView) return false;
      renderedView = view;
      if (s) return renderStory(ed, idx, s, storyNotice);
      if (storyNotice) return renderFront(ed, idx, page === 'home' ? 'home' : 'edition', storyNotice);
      if (page === 'latest') return renderLatest(ed, idx);
      if (page === 'section') return renderSection(ed, idx, body.dataset.section);
      return renderFront(ed, idx, page === 'home' ? 'home' : 'edition');
    };
    route();
    pageStatus.textContent = document.querySelector('.story-recovery')?.textContent || `Edition loaded. ${plural(ed.stories.length, 'story', 'stories')}.`;
    window.addEventListener('hashchange', () => {
      // Ordinary page anchors must not remount the news or discard keyboard focus.
      if (location.hash && !/^#story-/.test(location.hash)) return;
      if (route() === false) return;
      const title = document.querySelector('main h1');
      if (title) { title.setAttribute('tabindex', '-1'); title.focus({preventScroll: true}); }
      window.scrollTo(0, 0);
    });
  }
  start();
})();
