// Agent Reach Daily website. Every page is rendered from the editions the app publishes:
//   /editions/index.json        the archive list (newest first, "latest" = newest date)
//   /editions/YYYY-MM-DD.json   one public edition (written by agent_reach/daily/publish.py)
//   /search/YYYY-MM.json        the search data of one month (headline, short summary, outlets per story)
// All text from an edition goes into the page as text (textContent), never as HTML; only absolute
// http(s) links become links.
(() => {
  'use strict';
  const REPO = 'https://github.com/timeitself1-cpu/Agent-Reach-Daily-Edition';
  const MAIL = 'hello@getagentreach.dev';
  const NAV = [['Home', '/', 'home'], ['Latest News', '/latest/', 'latest'], ['Technology', '/technology/', 'Tech'],
    ['Science & AI', '/science/', 'Science & AI'], ['World', '/world/', 'News'], ['Archive', '/archive/', 'archive'],
    ['About', '/about/', 'about']];
  const SECTION = {
    'News': {label: 'World & Nation', path: '/world/', title: 'World', blurb: 'World and national news: politics, courts, conflict, the economy and public safety.'},
    'Tech': {label: 'Technology', path: '/technology/', title: 'Technology', blurb: 'Companies, products, security and the business of technology.'},
    'Science & AI': {label: 'Science & AI', path: '/science/', title: 'Science & AI', blurb: 'Research, space, health, climate and artificial intelligence.'},
    'Sports': {label: 'Sports'}, 'Entertainment': {label: 'Entertainment'}, 'Internet Culture': {label: 'Internet Culture'},
  };
  const body = document.body;
  const page = body.dataset.page || 'home';

  // ------------------------------------------------------------------ helpers
  function webUrl(u) {
    try { const x = new URL(u, location.origin); return (x.protocol === 'https:' || x.protocol === 'http:') ? x.href : null; }
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
        else { const u = webUrl(v); if (u) n.setAttribute('href', v.startsWith('/') ? v : u); }
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
  const clock = iso => new Date(iso).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit', timeZoneName: 'short'});
  const stamp = iso => new Date(iso).toLocaleString('en-US', {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
  function ago(iso) {
    if (!iso) return null;
    const min = (Date.now() - Date.parse(iso)) / 60000;
    if (!(min >= 0)) return stamp(iso);
    if (min < 60) return `${Math.max(1, Math.round(min))} min ago`;
    if (min < 60 * 24) return `${Math.round(min / 60)} h ago`;
    return stamp(iso);
  }
  const storyUrl = (ed, s) => `/daily/${ed.edition_date}/#story-${s.id}`;
  const editionUrl = d => `/daily/${d}/`;
  const catLabel = c => (SECTION[c] && SECTION[c].label) || c;
  const pageStatus = h('p', {class: 'sr', id: 'page-status', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true'});
  body.append(pageStatus); // Keep load status mounted while the page content changes.

  async function getJson(url) {
    const r = await fetch(url, {cache: 'no-cache'});
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }
  let indexPromise = null;
  const loadIndex = () => (indexPromise = indexPromise || getJson('/editions/index.json'));
  async function loadEdition(d) {
    const ed = await getJson(`/editions/${d}.json`);
    if (!ed || !Array.isArray(ed.stories) || !ed.stories.length) throw new Error('empty edition');
    ed.byId = Object.fromEntries(ed.stories.map(s => [s.id, s]));
    ed.ordered = ed.stories.slice().sort((a, b) => a.rank - b.rank);
    ed.topStories = (ed.top || []).map(id => ed.byId[id]).filter(Boolean);
    if (!ed.topStories.length) ed.topStories = ed.ordered.slice(0, 8);
    return ed;
  }

  // ------------------------------------------------------------------ story atoms
  function coverage(c) {
    if (c.level === 'strong') return 'Strong coverage';
    if (c.level === 'moderate') return 'Moderate coverage';
    return c.independent_reports <= 1 ? 'Single source' : 'Limited coverage';
  }
  function covMeter(s, big) {
    const c = s.coverage || {level: 'limited', independent_reports: 0};
    const n = c.independent_reports || 0;
    return h('span', {class: `cov ${c.level}`, title: `${plural(n, 'independent outlet')} reported this. Coverage is not a fact check.`},
      h('span', {class: 'bars', 'aria-hidden': 'true'}, h('i'), h('i'), h('i')), big ? null : coverage(c));
  }
  function outlets(s) {
    const names = [];
    for (const src of s.sources) if (src.kind === 'report' && !names.includes(src.outlet)) names.push(src.outlet);
    if (!names.length) for (const src of s.sources) if (!names.includes(src.outlet)) names.push(src.outlet);
    return names.length > 2 ? `${names.slice(0, 2).join(', ')} +${names.length - 2}` : names.join(', ');
  }
  function badges(s) {
    const out = [];
    if (s.change === 'new') out.push(h('span', {class: 'badge new', text: 'New'}));
    else if (s.change === 'updated') out.push(h('span', {class: 'badge updated', text: 'Updated'}));
    for (const l of s.labels || []) out.push(h('span', {class: 'badge trend', text: l}));
    return out;
  }
  const kicker = s => h('span', {class: 'kicker', 'data-cat': s.category}, catLabel(s.category), badges(s));
  function meta(s, opts = {}) {
    const when = ago(s.newest_published_utc);
    return h('div', {class: 'meta'},
      when ? h('time', {datetime: s.newest_published_utc, title: 'Newest report: ' + stamp(s.newest_published_utc), text: when}) : null,
      opts.noOutlets ? null : h('span', {class: 'outlets', text: outlets(s)}), covMeter(s));
  }
  function sourceList(s) {
    const n = s.sources.length;
    return h('details', {class: 'src'}, h('summary', {text: `View ${plural(n, 'source')}`}),
      h('ul', null, s.sources.map(src => {
        const url = webUrl(src.url);
        const when = src.published_utc ? stamp(src.published_utc) : 'time not stated';
        const kind = src.kind === 'signal' ? ' · social/search signal' : src.kind === 'repeat' ? ' · repeat or syndicated copy' : '';
        return h('li', null, url ? h('a', {href: url, rel: 'noopener noreferrer', target: '_blank', text: src.title}) : h('span', {text: src.title}),
          h('small', {text: `${src.outlet} · ${when}${kind}`}));
      })));
  }
  function card(ed, s, variant) {
    const cls = 'card' + (variant === 'feature' ? ' feature' : '');
    return h('article', {class: cls, 'data-cat': s.category}, kicker(s),
      h('h3', {class: 'hl'}, h('a', {href: storyUrl(ed, s), text: s.headline})),
      h('p', {class: 'dek', text: s.summary.join(' ')}), meta(s), sourceList(s));
  }

  // ------------------------------------------------------------------ chrome
  function masthead(current, ed) {
    const today = ed ? longDate(ed.edition_date) : new Date().toLocaleDateString('en-US', {weekday: 'long', month: 'long', day: 'numeric', year: 'numeric'});
    return h('header', {class: 'masthead'}, h('div', {class: 'wrap'},
      h('div', {class: 'mast-top'},
        h('div', {class: 'mast-date'}, h('strong', {text: ed ? 'Edition of ' : 'Today, '}), today),
        h('a', {class: 'brand', href: '/', 'aria-label': 'Agent Reach Daily, home'}, h('span', {class: 'brand-mark', 'aria-hidden': 'true'}),
          h('span', {class: 'brand-name', text: 'Agent Reach'}), h('span', {class: 'brand-daily', text: 'Daily'})),
        h('div', {class: 'mast-actions'}, h('a', {class: 'pill search', href: '/search/', 'aria-current': current === 'search' ? 'page' : null},
          h('span', {class: 'glass', 'aria-hidden': 'true'}), 'Search'),
          h('a', {class: 'pill solid', href: '/about/#app', text: 'Get the app'}))),
      h('nav', {class: 'nav', 'aria-label': 'Sections'}, NAV.map(([label, href, key]) =>
        h('a', {href, text: label, 'aria-current': key === current ? 'page' : null})))));
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
        h('span', {text: 'No cookies, no tracking, no ads.'}))));
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
    const nodes = [skipLink(), masthead(current, ed), main, footer()];
    if (app) app.replaceChildren(...nodes); else body.replaceChildren(...nodes, pageStatus);
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
    body.prepend(skipLink(), masthead(current, null));
    if (main) main.after(footer()); else body.append(footer());
  }
  function failed(current, what) {
    const message = what || 'The news could not be loaded.';
    mount(current, null, h('div', {class: 'wrap state'}, h('h1', {text: message}),
      h('p', null, 'Please reload the page. If it keeps happening, the newest edition may still be on its way: ', h('a', {href: '/archive/', text: 'see the archive'}), '.')));
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
  function strip(ed, idx) {
    const latest = idx && idx.latest === ed.edition_date;
    const ageH = (Date.now() - Date.parse(ed.generated_utc)) / 3.6e6;
    return h('div', {class: 'strip', 'aria-label': 'Edition details'},
      h('div', {class: 'edition-meta'},
        h('span', {class: 'live' + (latest && ageH < 30 ? '' : ' old')}, h('b', {text: latest ? 'Latest edition' : 'Archived edition'})),
        h('time', {datetime: ed.edition_date, text: longDate(ed.edition_date)}),
        ed.revision > 1 ? h('span', {text: `Update ${ed.revision}`}) : null,
        h('time', {datetime: ed.generated_utc, title: stamp(ed.generated_utc), text: `Generated ${clock(ed.generated_utc)}`})),
      h('span', {class: 'edition-stats'}, `${plural(ed.stories.length, 'story', 'stories')} from ${plural(ed.reports_read || 0, 'report')} · ${ed.sources_answered || 0} of ${ed.sources_tried || 0} source types responded · AI-generated summaries`));
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
    return h('article', {class: 'lead', 'data-cat': s.category},
      h('span', {class: 'rank-label', text: 'Top story'}), kicker(s),
      h('h1', {class: 'hl'}, h('a', {href: storyUrl(ed, s), text: s.headline})),
      h('p', {class: 'dek', text: s.summary.join(' ')}),
      s.why_it_matters ? h('p', {class: 'why'}, h('b', {text: 'Why it matters: '}), s.why_it_matters) : null,
      h('div', {class: 'lead-foot'}, meta(s), h('a', {class: 'readmore', href: storyUrl(ed, s), text: 'Read the story and its sources'})));
  }
  function rail(ed, stories) {
    return h('aside', {class: 'rail', 'aria-label': 'More top stories'}, h('h2', {class: 'rail-title'}, h('span', {text: 'Top stories'})),
      stories.map((s, i) => h('article', {class: 'rail-item', 'data-cat': s.category}, h('span', {class: 'rail-num', text: String(i + 2)}),
        kicker(s), h('h3', {class: 'hl'}, h('a', {href: storyUrl(ed, s), text: s.headline})),
        h('p', {class: 'dek', text: s.summary.join(' ')}), meta(s, {noOutlets: true}))));
  }
  function sectionBand(ed, cat, stories, title) {
    const sec = SECTION[cat] || {};
    return h('section', {class: 'band', 'data-cat': cat, 'aria-label': title || catLabel(cat)}, h('div', {class: 'wrap'},
      h('div', {class: 'band-head'}, h('h2', {class: 'band-title', text: title || catLabel(cat)}),
        sec.path ? h('a', {class: 'band-link', href: sec.path, text: `All ${sec.title}`}) : null),
      h('div', {class: 'grid'}, stories.map((s, i) => card(ed, s, i === 0 && stories.length >= 5 ? 'feature' : '')))));
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
  function renderFront(ed, idx, current) {
    const top = ed.topStories;
    const used = new Set(top.map(s => s.id));
    const content = [h('div', {class: 'wrap'}, strip(ed, idx), notices(ed, idx),
      h('div', {class: 'front'}, lead(ed, top[0]), rail(ed, top.slice(1, 4))))];
    if (top.length > 4) content.push(sectionBand(ed, null, top.slice(4, 8), 'More top stories'));
    for (const sec of ed.sections || []) {
      const stories = sec.ids.map(id => ed.byId[id]).filter(s => s && !used.has(s.id)).slice(0, 5);
      if (stories.length) content.push(sectionBand(ed, sec.category, stories));
    }
    if (idx) content.push(archiveBand(idx, ed.edition_date));
    content.push(aboutBand());
    mount(current, ed, content);
    document.title = current === 'home' ? 'Agent Reach Daily: today’s news, from public reporting'
      : `Agent Reach Daily: ${longDate(ed.edition_date)}`;
  }

  // ------------------------------------------------------------------ story page
  function sourcesBlock(s) {
    const groups = [
      ['report', 'Independent reports', 'Each from a different outlet.'],
      ['repeat', 'Repeats and syndicated copies', 'The same outlet again, or the same headline carried by another outlet (a wire story). Counted once.'],
      ['signal', 'Social and search signals', 'Trending searches and posts show attention, not reporting. They never count as a source.'],
    ];
    return h('section', {class: 'sources', id: 'sources', tabindex: '-1', 'aria-labelledby': 'sources-title'},
      h('h2', {id: 'sources-title', text: 'Sources'}), groups.map(([kind, title, hint]) => {
      const list = s.sources.filter(x => x.kind === kind);
      if (!list.length) return null;
      return h('div', null, h('h3', {text: `${title} (${list.length})`}), h('p', {class: 'hint', text: hint}),
        list.map(src => {
          const url = webUrl(src.url);
          return h('div', {class: 'source'}, h('span', {class: 'outlet', text: src.outlet}),
            h('span', {class: 'when', text: src.published_utc ? stamp(src.published_utc) : 'time not stated'}),
            url ? h('a', {class: 'title', href: url, rel: 'noopener noreferrer', target: '_blank', text: src.title}) : h('span', {class: 'title', text: src.title}),
            src.via && src.via !== src.outlet ? h('span', {class: 'via', text: 'Found via ' + src.via}) : null);
        }));
    }));
  }
  function coveragePanel(s) {
    const c = s.coverage;
    const facts = [h('li', {text: `${plural(c.independent_reports, 'independent outlet')}${c.publishers.length ? ': ' + c.publishers.join(', ') : ''}`})];
    if (c.repeats) facts.push(h('li', {text: `${plural(c.repeats, 'repeat or syndicated copy', 'repeats or syndicated copies')}, counted once`}));
    if (c.signals) facts.push(h('li', {text: `${plural(c.signals, 'social or search signal')} (attention, not reporting)`}));
    facts.push(h('li', {text: `Found through ${plural(c.channels, 'channel')}`}));
    if (c.independent_reports < 2) facts.push(h('li', {text: 'Not yet confirmed by a second independent outlet'}));
    return h('section', {class: 'panel', 'aria-label': 'Coverage'}, h('h2', {text: 'Coverage'}),
      h('div', {class: `cov-big cov ${c.level}`}, h('span', {class: 'bars', 'aria-hidden': 'true'}, h('i'), h('i'), h('i')), coverage(c)),
      h('ul', {class: 'facts'}, facts),
      h('p', {class: 'fine'}, 'Coverage counts independent outlets that reported this story. It is not a fact check: several outlets can repeat the same claim. ', h('a', {href: '/about/#coverage', text: 'More'})));
  }
  function renderStory(ed, idx, s) {
    const order = ed.ordered;
    const i = order.indexOf(s);
    const prev = order[i - 1], next = order[i + 1];
    const same = order.filter(x => x.category === s.category && x !== s).slice(0, 4);
    const when = s.newest_published_utc;
    const main = mount('edition', ed, h('div', {class: 'wrap'}, notices(ed, idx), h('article', {class: 'story', 'data-cat': s.category},
      h('nav', {class: 'crumbs', 'aria-label': 'Breadcrumb'}, h('a', {href: editionUrl(ed.edition_date), text: `Edition of ${shortDate(ed.edition_date)}`}),
        h('span', {'aria-hidden': 'true', text: '/'}), SECTION[s.category] && SECTION[s.category].path ? h('a', {href: SECTION[s.category].path, text: catLabel(s.category)}) : h('span', {text: catLabel(s.category)}),
        s.top_rank ? h('span', {text: `· Top story ${s.top_rank} of ${ed.topStories.length}`}) : null),
      h('div', {class: 'story-main'}, kicker(s), h('h1', {class: 'hl', tabindex: '-1', text: s.headline}),
        h('div', {class: 'meta'}, when ? h('span', {text: `Newest report ${stamp(when)}`}) : h('span', {text: 'Publication time not stated'}),
          h('span', {class: 'outlets', text: outlets(s)}), covMeter(s)),
        h('button', {class: 'source-jump', type: 'button', text: `Read ${plural(s.sources.length, 'source')} ↓`}),
        h('div', {class: 'story-body'}, s.summary.map(t => h('p', {text: t}))),
        s.why_it_matters ? h('div', {class: 'why-box'}, h('h2', {text: 'Why it matters'}), h('p', {text: s.why_it_matters})) : null,
        h('p', {class: 'ai-note'}, h('b', {text: 'How this was written. '}),
          `This summary was written automatically by a local AI model (${(ed.models && ed.models.summaries) || 'a local model'}) from the reports below, and each sentence was checked against them before publication. Nobody edited it. It can still be wrong or out of date: read the sources for the full story.`),
        sourcesBlock(s)),
      h('aside', {class: 'aside'}, coveragePanel(s),
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
    window.scrollTo(0, 0);
    return main;
  }

  // ------------------------------------------------------------------ other pages
  function renderLatest(ed, idx) {
    const known = ed.stories.filter(s => s.newest_published_utc).sort((a, b) => Date.parse(b.newest_published_utc) - Date.parse(a.newest_published_utc));
    const rest = ed.ordered.filter(s => !s.newest_published_utc);
    mount('latest', ed, h('div', {class: 'wrap'},
      h('header', {class: 'page-head'}, h('h1', {text: 'Latest News'}),
        h('p', {text: `Every story of the ${longDate(ed.edition_date)} edition, newest report first. Times are when the newest source says it was published, in your time zone.`})),
      notices(ed, idx),
      h('div', {class: 'river'}, known.concat(rest).map(s => h('article', {class: 'river-item', 'data-cat': s.category},
        h('div', {class: 'river-time'}, s.newest_published_utc ? [h('b', {text: new Date(s.newest_published_utc).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'})}),
          new Date(s.newest_published_utc).toLocaleDateString('en-US', {month: 'short', day: 'numeric'})] : h('b', {text: 'Time not stated'})),
        h('div', null, kicker(s), h('h2', {class: 'hl'}, h('a', {href: storyUrl(ed, s), text: s.headline})),
          h('p', {class: 'dek', text: s.summary.join(' ')}), meta(s, {}), sourceList(s)))))));
    document.title = 'Latest News | Agent Reach Daily';
  }
  function renderSection(ed, idx, cat) {
    const sec = SECTION[cat];
    const ids = ((ed.sections || []).find(x => x.category === cat) || {ids: []}).ids;
    const stories = ids.map(id => ed.byId[id]).filter(Boolean);
    mount(cat, ed, h('div', {class: 'wrap'},
      h('header', {class: 'page-head', 'data-cat': cat}, h('h1', {text: sec.title}), h('p', {text: `${sec.blurb} From the ${longDate(ed.edition_date)} edition.`})),
      notices(ed, idx)),
      stories.length ? h('section', {class: 'band', 'data-cat': cat, 'aria-label': sec.title}, h('div', {class: 'wrap'},
        h('div', {class: 'grid'}, stories.map((s, i) => card(ed, s, i === 0 && stories.length >= 3 ? 'feature' : '')))))
        : h('div', {class: 'wrap state'}, h('p', {text: 'No stories in this section in the latest edition.'})));
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
        h('p', {text: 'Every edition published here, newest first. Each date keeps its own permanent page; when an edition was updated during the day, the page shows the last update.'}),
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
        const list = doc.stories;
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
    function hit(x, terms) {
      return h('article', {class: 'hit', 'data-cat': x.c},
        h('div', {class: 'hit-meta'}, h('time', {datetime: x.d, text: shortDate(x.d)}), h('span', {class: 'kicker', 'data-cat': x.c, text: catLabel(x.c)}),
          x.t ? h('span', {class: 'badge trend', text: `Top story ${x.t}`}) : null),
        h('h2', {class: 'hl'}, h('a', {href: `/daily/${x.d}/#story-${x.id}`}, marked(x.h, terms))),
        x.s ? h('p', {class: 'dek'}, marked(x.s, terms)) : null,
        h('div', {class: 'meta'}, (x.o || []).length ? h('span', {class: 'outlets'}, marked((x.o || []).join(', '), terms)) : null,
          h('span', {class: `cov ${x.l || 'limited'}`}, h('span', {class: 'bars', 'aria-hidden': 'true'}, h('i'), h('i'), h('i')), COVER[x.l] || COVER.limited)));
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
      mount(null, null, h('div', {class: 'wrap state'}, h('h1', {text: 'Page not found'}),
        h('p', null, 'That page does not exist. ', h('a', {href: '/', text: 'Go to today’s news'}), ' or ', h('a', {href: '/archive/', text: 'browse the archive'}), '.')));
      return;
    }
    const current = page === 'section' ? body.dataset.section : page;
    loading(current);
    let idx;
    try { idx = await loadIndex(); } catch (e) { failed(current); return; }
    if (page === 'archive') { renderArchive(idx); pageStatus.textContent = `Archive loaded. ${plural((idx.editions || []).length, 'edition')}.`; return; }
    if (page === 'search') { renderSearch(idx); pageStatus.textContent = 'Archive search ready.'; return; }
    const date = body.dataset.date || idx.latest;
    if (!date) { failed(current, 'No edition has been published yet.'); return; }
    let ed;
    try { ed = await loadEdition(date); } catch (e) {
      failed(current, body.dataset.date ? `The edition of ${longDate(date)} is not available.` : null);
      return;
    }
    let renderedView = null;
    const route = () => {
      const m = /^#story-([0-9a-f]{6,40})$/.exec(location.hash);
      const s = m && ed.byId[m[1]];
      const view = s ? s.id : page;
      if (view === renderedView) return false;
      renderedView = view;
      if (s) return renderStory(ed, idx, s);
      if (page === 'latest') return renderLatest(ed, idx);
      if (page === 'section') return renderSection(ed, idx, body.dataset.section);
      return renderFront(ed, idx, page === 'home' ? 'home' : 'edition');
    };
    route();
    pageStatus.textContent = `Edition loaded. ${plural(ed.stories.length, 'story', 'stories')}.`;
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
