const {JSDOM, VirtualConsole} = require('jsdom');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const assert = require('node:assert/strict');
const test = require('node:test');
const root = resolve(__dirname, '..');
const script = readFileSync(resolve(root, 'assets/site.js'), 'utf8');
const edition = JSON.parse(readFileSync(resolve(root, 'editions/2026-10-07.json')));
const index = JSON.parse(readFileSync(resolve(root, 'editions/index.json')));
const monthly = JSON.parse(readFileSync(resolve(root, 'search/2026-10.json')));
const settle = () => new Promise(r => setTimeout(r, 25));
async function open(path = '/', opts = {}) {
  const pathname = new URL(path, 'https://example.test').pathname;
  const file = pathname.endsWith('/') ? pathname + 'index.html' : pathname;
  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(e.message));
  const dom = new JSDOM(readFileSync(resolve(root, '.' + file), 'utf8'), {
    url: 'https://example.test' + path, runScripts: 'outside-only', virtualConsole: vc,
  });
  const w = dom.window, d = w.document, requests = [];
  w.scrollTo = () => {};
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.Date.now = () => Date.parse(opts.now || '2026-10-08T16:00:00Z');
  w.fetch = async url => {
    requests.push(url);
    const override = opts.fetch && await opts.fetch(url, requests);
    if (override !== undefined) {
      if (override === false) return {ok:false,status:503};
      return {ok:true,json:async()=>structuredClone(override)};
    }
    return {ok:true,json:async()=>JSON.parse(readFileSync(resolve(root, '.' + url)))};
  };
  w.eval(script);
  await settle();
  return {w,d,requests,errors,close:()=>dom.window.close()};
}

test('all public route shells render and keep RSS discovery', async () => {
  for (const path of ['/', '/daily/', '/daily/2026-10-07/', '/latest/', '/technology/', '/science/', '/world/', '/archive/', '/search/', '/about/', '/404.html']) {
    const p = await open(path);
    assert.ok(p.d.querySelector('main h1'), path);
    assert.ok(p.d.querySelector('link[rel="alternate"][href="/feed.xml"]'), path);
    assert.ok(p.d.querySelector('footer a[href="/feed.xml"]'), path);
    assert.equal(p.d.querySelectorAll('.nav a').length, 7);
    assert.deepEqual(p.errors, [], path);
    p.close();
  }
});

test('latest river and category pages retain every fixture story', async () => {
  const p = await open('/latest/');
  assert.equal(p.d.querySelectorAll('.river-item').length, edition.stories.length);
  p.close();
  for (const [path, cat] of [['technology','Tech'], ['science','Science & AI'], ['world','News']]) {
    const q = await open('/'+path+'/');
    assert.equal(q.d.querySelectorAll('.card').length, edition.sections.find(s=>s.category===cat).ids.length);
    assert.equal(q.d.querySelector('.nav [aria-current="page"]').textContent, path === 'science' ? 'Science & AI' : path[0].toUpperCase()+path.slice(1));
    q.close();
  }
});

test('fresh, stale, and archived edition information survives', async () => {
  const p = await open('/');
  assert.match(p.d.querySelector('.strip').textContent, /Latest edition.*Update 2.*44 stories.*1,517 reports.*10 of 10/s);
  assert.equal(p.d.querySelector('.strip time[datetime="2026-10-07T23:42:20Z"]').textContent.startsWith('Published'),true);
  assert.equal(p.d.querySelector('.live.old'),null);
  p.close();
  const stale = await open('/', {now:'2026-10-10T16:00:00Z'});
  assert.ok(stale.d.querySelector('.live.old'));
  assert.match(stale.d.querySelector('.notice').textContent,/most recent edition/);
  stale.close();
  const old = await open('/daily/2026-10-07/',{fetch:u=>u==='/editions/index.json'?{...index,latest:'2026-10-08'}:undefined});
  assert.match(old.d.querySelector('.strip').textContent,/Archived edition/);
  assert.equal(old.d.querySelector('.notice a').getAttribute('href'),'/daily/');
  old.close();
});

test('story sources and source groups match fixture, jump preserves URL', async () => {
  for (const story of edition.stories) {
    const p = await open('/daily/2026-10-07/#story-'+story.id);
    assert.equal(p.d.querySelector('h1').textContent,story.headline);
    assert.equal(p.d.querySelectorAll('.sources .source').length,story.sources.length);
    assert.deepEqual([...p.d.querySelectorAll('.sources a.title')].map(a=>a.href).sort(), story.sources.map(s=>s.url).sort());
    for (const kind of ['report','repeat','signal']) {
      const count=story.sources.filter(s=>s.kind===kind).length;
      if(count) assert.ok([...p.d.querySelectorAll('.sources h3')].some(h=>h.textContent.endsWith(`(${count})`)));
    }
    const hash = p.w.location.hash;
    p.d.querySelector('.source-jump').click();
    assert.equal(p.w.location.hash,hash);
    assert.equal(p.d.activeElement.id,'sources');
    assert.deepEqual(p.errors,[]);
    p.close();
  }
});

test('skip and regular anchors never remount a story; next/back focus title', async () => {
  const p = await open('/daily/2026-10-07/#story-'+edition.top[0]);
  const main = p.d.querySelector('main'), headline = p.d.querySelector('h1').textContent;
  p.d.querySelector('.skip').click();
  await settle();
  assert.equal(p.d.querySelector('main'),main);
  assert.equal(p.d.activeElement,main);
  assert.equal(p.w.location.hash,'#story-'+edition.top[0]);
  p.w.location.hash='#sources'; await settle();
  assert.equal(p.d.querySelector('main'),main);
  p.w.location.hash='#story-'+edition.top[1]; await settle();
  assert.notEqual(p.d.querySelector('h1').textContent,headline);
  assert.equal(p.d.activeElement,p.d.querySelector('h1'));
  p.w.location.hash='#story-'+edition.top[0]; await settle();
  assert.equal(p.d.querySelector('h1').textContent,headline);
  assert.equal(p.d.activeElement,p.d.querySelector('h1'));
  assert.deepEqual(p.errors,[]);
  p.close();
});

test('search prefix, phrase, outlet, empty results and URL state', async () => {
  for (const [q, text] of [['Hamilt','Hamilton'], ['"Margaret Hamilton"','Hamilton'], ['Reuters','Reuters']]) {
    const p = await open('/search/?q='+encodeURIComponent(q));
    assert.ok(p.d.querySelectorAll('.hit').length > 0,q);
    assert.match(p.d.querySelector('.hits').textContent,new RegExp(text));
    assert.ok(p.d.querySelector('mark'));
    assert.equal(p.d.querySelector('.hits').getAttribute('aria-busy'),'false');
    assert.deepEqual(p.errors,[]);
    p.close();
  }
  const p = await open('/search/?q=zzzznoresults');
  assert.equal(p.d.querySelectorAll('.hit').length,0);
  assert.match(p.d.querySelector('.search-empty').textContent,/No matching stories/);
  assert.equal(p.d.querySelector('.search-empty a').getAttribute('href'),'/archive/');
  p.close();
});

test('search live query, section, sort, submit focus and clear', async () => {
  const p = await open('/search/');
  const input = p.d.querySelector('input'), cat = p.d.querySelector('select');
  assert.notEqual(p.d.activeElement,input);
  input.focus(); input.value='AI'; input.dispatchEvent(new p.w.Event('input'));
  await new Promise(r=>setTimeout(r,180));
  assert.ok(p.d.querySelectorAll('.hit').length>0);
  cat.value='Science & AI'; cat.dispatchEvent(new p.w.Event('change')); await settle();
  assert.ok([...p.d.querySelectorAll('.hit')].every(n=>n.dataset.cat==='Science & AI'));
  p.d.querySelector('[data-sort="best"]').click(); await settle();
  assert.match(p.w.location.search,/sort=best/);
  assert.match(p.w.location.search,/cat=Science/);
  input.focus(); p.d.querySelector('form').dispatchEvent(new p.w.Event('submit',{cancelable:true})); await settle();
  assert.equal(p.d.activeElement,input);
  input.value=''; input.dispatchEvent(new p.w.Event('input')); await new Promise(r=>setTimeout(r,180));
  assert.equal(p.d.querySelectorAll('.hit').length,0);
  assert.match(p.d.querySelector('[role="status"]').textContent,/Type to search/);
  p.close();
});

test('unavailable search month can be retried without reloading', async () => {
  let attempts=0;
  const p=await open('/search/?q=Hamilton',{fetch:u=>u.startsWith('/search/') && ++attempts===1 ? false : undefined});
  assert.match(p.d.querySelector('[role="status"]').textContent,/incomplete/);
  assert.doesNotMatch(p.d.querySelector('.hits').textContent,/No matching stories/);
  p.d.querySelector('[data-act="retry"]').click(); await settle();
  assert.equal(attempts,2);
  assert.ok(p.d.querySelectorAll('.hit').length>0);
  assert.equal(p.d.querySelector('[data-act="retry"]'),null);
  assert.equal(p.d.activeElement,p.d.querySelector('[role="status"]'));
  p.close();
});

test('monthly batching, partial failure, older search and pagination remain intact', async () => {
  const dates=Array.from({length:7},(_,i)=>`2026-${String(10-i).padStart(2,'0')}-07`);
  const idx={...index,editions:dates.map(date=>({...index.editions[0],date}))};
  let fail=true;
  const p=await open('/search/?q=the',{fetch:u=>{
    if(u==='/editions/index.json') return idx;
    if(u.startsWith('/search/')) {
      if(u.includes('2026-09') && fail) return false;
      return {...monthly,stories:monthly.stories.map(s=>({...s,d:u.slice(8,15)+'-07'}))};
    }
  }});
  assert.equal(p.requests.filter(u=>u.startsWith('/search/')).length,6);
  assert.equal(p.d.querySelectorAll('.hit').length,40);
  assert.match(p.d.querySelector('[role="status"]').textContent,/incomplete/);
  p.d.querySelector('[data-act="more"]').click(); await settle();
  assert.ok(p.d.querySelectorAll('.hit').length>40);
  fail=false; p.d.querySelector('[data-act="retry"]').click(); await settle();
  assert.doesNotMatch(p.d.querySelector('[role="status"]').textContent,/incomplete/);
  p.d.querySelector('[data-act="older"]').click(); await settle();
  assert.ok(p.requests.includes('/search/2026-04.json'));
  assert.equal(p.d.querySelector('[data-act="older"]'),null);
  p.close();
});

test('a delayed earlier search cannot overwrite the current query', async()=>{
  let release;
  const deferred=new Promise(r=>release=r);
  const p=await open('/search/?q=Hamilton',{fetch:u=>u.startsWith('/search/')?deferred:undefined});
  const input=p.d.querySelector('input'); input.value='zzzznoresults';
  p.d.querySelector('form').dispatchEvent(new p.w.Event('submit',{cancelable:true}));
  release(monthly); await settle();
  assert.equal(p.d.querySelectorAll('.hit').length,0);
  assert.match(p.d.querySelector('.search-empty').textContent,/No matching stories/);
  assert.equal(p.d.querySelector('.hits').getAttribute('aria-busy'),'false');
  p.close();
});

test('failed edition load keeps archive recovery and safe text rendering', async()=>{
  const p=await open('/',{fetch:u=>u.includes('/editions/2026')?false:undefined});
  assert.match(p.d.querySelector('main').textContent,/could not be loaded/);
  assert.ok(p.d.querySelector('main a[href="/archive/"]'));
  p.close();
  const unsafe=structuredClone(edition); unsafe.stories[0].headline='<img src=x onerror=alert(1)>';
  const q=await open('/',{fetch:u=>u.includes('/editions/2026')?unsafe:undefined});
  assert.equal(q.d.querySelector('h1').textContent,unsafe.stories[0].headline);
  assert.equal(q.d.querySelector('h1 img'),null);
  q.close();
});
